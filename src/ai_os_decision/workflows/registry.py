"""One SQLite truth layer: sources -> occurrences -> variants -> structures."""
from __future__ import annotations

import json
import re
import sqlite3
from functools import wraps
from pathlib import Path

from .analysis import analyze, redact
from .discovery import parse
from .normalize import encoded, hashes, validate

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY, url TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('KEEP','DROP','UNAVAILABLE')), metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS variants(
 id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL REFERENCES workflows(id),
 metadata TEXT NOT NULL, payload TEXT NOT NULL, risk TEXT NOT NULL, status TEXT NOT NULL,
 local_capable INTEGER, requires_credentials INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS variant_group ON variants(workflow_id);
CREATE VIRTUAL TABLE IF NOT EXISTS workflow_fts USING fts5(variant_id UNINDEXED, text, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS occurrences(
 source_id TEXT NOT NULL REFERENCES sources(id), path TEXT NOT NULL, pointer TEXT NOT NULL,
 revision TEXT NOT NULL, variant_id TEXT NOT NULL REFERENCES variants(id),
 raw_hash TEXT NOT NULL, document_raw_hash TEXT NOT NULL, source_url TEXT NOT NULL,
 status TEXT NOT NULL, PRIMARY KEY(source_id,path,pointer,revision));
CREATE INDEX IF NOT EXISTS occurrence_variant ON occurrences(variant_id);
CREATE TABLE IF NOT EXISTS issues(
 source_id TEXT NOT NULL REFERENCES sources(id), path TEXT NOT NULL, pointer TEXT NOT NULL,
 revision TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'BROKEN',
 PRIMARY KEY(source_id,path,pointer,revision,reason));
CREATE TABLE IF NOT EXISTS scans(
 source_id TEXT PRIMARY KEY REFERENCES sources(id), details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS aliases(
 variant_id TEXT NOT NULL REFERENCES variants(id), source_id TEXT NOT NULL REFERENCES sources(id),
 path TEXT NOT NULL, pointer TEXT NOT NULL, revision TEXT NOT NULL, metadata TEXT NOT NULL,
 PRIMARY KEY(variant_id,source_id,path,pointer,revision));
"""


def snapshot(method):
    """Keep multi-query responses on one committed snapshot during sync."""
    @wraps(method)
    def read(self, *args, **kwargs):
        owns_transaction = not self.db.in_transaction
        if owns_transaction:
            self.db.execute("BEGIN")
        try:
            return method(self, *args, **kwargs)
        finally:
            if owns_transaction:
                self.db.rollback()  # Read-only transaction; no cache entries were written.
    return read


class Registry:
    def __init__(self, path: str | Path, readonly: bool = False):
        self.path = Path(path).resolve()
        if readonly:
            self.db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
            self.db.execute("PRAGMA query_only=ON")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
        self.db.row_factory = sqlite3.Row
        self._document_cache = {}

    def close(self):
        self.db.close()

    def rollback(self):
        self.db.rollback()
        self._document_cache.clear()

    def register(self, source: dict):
        source = dict(source)
        if source["url"].lower().startswith("https://github.com/"):
            source["url"] = source["url"].rstrip("/").lower()
        if source.get("status", "KEEP") not in {"KEEP", "DROP", "UNAVAILABLE"}:
            raise ValueError("invalid source status")
        existing = self.db.execute("SELECT id FROM sources WHERE url=?", (source["url"],)).fetchone()
        if existing and existing["id"] != source["id"]:
            raise ValueError("source URL already registered under another ID")
        self.db.execute("INSERT INTO sources VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET url=excluded.url,kind=excluded.kind,status=excluded.status,metadata=excluded.metadata",
                        (source["id"], source["url"], source["kind"], source.get("status", "KEEP"), encoded(source).decode()))
        self.db.commit()

    @snapshot
    def sources(self) -> list[dict]:
        result = []
        for row in self.db.execute("SELECT * FROM sources ORDER BY id"):
            item = json.loads(row["metadata"])
            item["status"] = row["status"]
            item["occurrences"] = self.db.execute("SELECT count(*) FROM occurrences WHERE source_id=?", (row["id"],)).fetchone()[0]
            scan = self.db.execute("SELECT details FROM scans WHERE source_id=?", (row["id"],)).fetchone()
            item["scan"] = json.loads(scan[0]) if scan else None
            result.append(item)
        return result

    def issue(self, source: str, path: str, revision: str, reason: str, pointer: str = "/"):
        self.db.execute("INSERT OR IGNORE INTO issues VALUES(?,?,?,?,?,'BROKEN')", (source, path, pointer, revision, reason))

    def ingest(self, source: str, path: str, revision: str, data: bytes, source_url: str, annotations: dict | None = None) -> int:
        import hashlib

        count = 0
        document_hash = hashlib.sha256(data).hexdigest()
        if not annotations and document_hash in self._document_cache:
            cached = self._document_cache[document_hash]
            for pointer, variant_id, raw_hash, alias_json in cached:
                self.db.execute("INSERT OR IGNORE INTO occurrences VALUES(?,?,?,?,?,?,?,?,?)", (source, path, pointer, revision, variant_id, raw_hash, document_hash, source_url, "DUPLICATE"))
                self.db.execute("INSERT OR IGNORE INTO aliases VALUES(?,?,?,?,?,?)", (variant_id, source, path, pointer, revision, alias_json))
            return len(cached)
        cached = []
        had_error = False
        for pointer, workflow in parse(path, data):
            if workflow is None:
                had_error = True
                self.issue(source, path, revision, "invalid_json", pointer)
                continue
            errors = validate(workflow)
            if errors:
                had_error = True
                self.issue(source, path, revision, ",".join(errors), pointer)
                continue
            try:
                hs = hashes(workflow, data if pointer == "/" else None)
                view = workflow
                if annotations:
                    view = dict(workflow)
                    for field in ["name", "description", "tags"]:
                        if not view.get(field) and annotations.get(field):
                            view[field] = annotations[field]
                metadata = analyze(view)
            except (TypeError, ValueError, AttributeError, KeyError, RecursionError):
                had_error = True
                self.issue(source, path, revision, "unsupported_workflow_shape", pointer)
                continue
            exists = self.db.execute("SELECT 1 FROM variants WHERE id=?", (hs["normalized_hash"],)).fetchone()
            self.db.execute("INSERT OR IGNORE INTO workflows VALUES(?)", (hs["structural_hash"],))
            if not exists:
                safe = redact(workflow)
                safe["active"] = False
                metadata.update(hs)
                self.db.execute("INSERT INTO variants VALUES(?,?,?,?,?,?,?,?)", (hs["normalized_hash"], hs["structural_hash"], encoded(metadata).decode(), encoded(safe).decode(), metadata["risk"], metadata["status"], metadata["local_capable"], metadata["requires_credentials"]))
                # Only analyzed metadata is indexed, never code/parameters/credentials.
                text = " ".join(str(v) for k, v in metadata.items() if k in {"name", "description", "nodes", "categories", "integrations", "ai_providers", "tags", "databases", "external_services", "local_services"})
                self.db.execute("INSERT INTO workflow_fts(rowid,variant_id,text) SELECT rowid,?,? FROM variants WHERE id=?", (hs["normalized_hash"], text, hs["normalized_hash"]))
            else:
                prior = json.loads(self.db.execute("SELECT metadata FROM variants WHERE id=?", (hs["normalized_hash"],)).fetchone()[0])
                prior["aliases"] = sorted(set(prior.get("aliases", [prior["name"]])) | {metadata["name"]})
                prior["descriptions"] = sorted(set(prior.get("descriptions", [prior["description"]])) | {metadata["description"]})
                for field in ["categories", "tags", "findings"]:
                    prior[field] = sorted(set(prior[field]) | set(metadata[field]))
                if prior["name"] == "Unnamed workflow" and metadata["name"] != "Unnamed workflow":
                    prior["name"] = metadata["name"]
                if not prior["description"]:
                    prior["description"] = metadata["description"]
                levels = {"LOW": 1, "MEDIUM": 2, "UNKNOWN": 3, "HIGH": 4}
                prior["risk"] = max([prior["risk"], metadata["risk"]], key=levels.get)
                if metadata["status"] == "UNSAFE":
                    prior["status"] = "UNSAFE"
                self.db.execute("UPDATE variants SET metadata=?,risk=?,status=? WHERE id=?", (encoded(prior).decode(), prior["risk"], prior["status"], hs["normalized_hash"]))
                self.db.execute("DELETE FROM workflow_fts WHERE rowid=(SELECT rowid FROM variants WHERE id=?)", (hs["normalized_hash"],))
                text = " ".join(str(v) for k, v in prior.items() if k in {"name", "aliases", "description", "descriptions", "nodes", "categories", "integrations", "ai_providers", "tags", "databases", "external_services", "local_services"})
                self.db.execute("INSERT INTO workflow_fts(rowid,variant_id,text) SELECT rowid,?,? FROM variants WHERE id=?", (hs["normalized_hash"], text, hs["normalized_hash"]))
            alias = {k: metadata[k] for k in ["name", "description", "categories", "tags"]}
            self.db.execute("INSERT OR IGNORE INTO aliases VALUES(?,?,?,?,?,?)", (hs["normalized_hash"], source, path, pointer, revision, encoded(alias).decode()))
            self.db.execute("INSERT OR IGNORE INTO occurrences VALUES(?,?,?,?,?,?,?,?,?)", (source, path, pointer, revision, hs["normalized_hash"], hs["raw_hash"], document_hash, source_url, "DUPLICATE" if exists else metadata["status"]))
            count += 1
            cached.append((pointer, hs["normalized_hash"], hs["raw_hash"], encoded(alias).decode()))
        if cached and not had_error and not annotations:
            self._document_cache[document_hash] = cached
        return count

    @snapshot
    def search(self, query: str = "", *, category: str | None = None, node: str | None = None,
               integration: str | None = None, source: str | None = None, local_capable: bool | None = None,
               risk: str | None = None, status: str | None = None, credentials: bool | None = None,
               external_service: str | None = None, exclude_integration: str | None = None,
               limit: int = 20, offset: int = 0) -> dict:
        if not 1 <= limit <= 100 or offset < 0 or len(query) > 500:
            raise ValueError("invalid pagination or query length")
        if risk and risk not in {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}:
            raise ValueError("invalid risk")
        if status and status not in {"VERIFIED", "CANDIDATE", "UNSAFE", "BROKEN", "DUPLICATE"}:
            raise ValueError("invalid status")
        if status == "BROKEN":
            if any(v is not None for v in [category, node, integration, local_capable, credentials, external_service, exclude_integration]) or risk not in {None, "UNKNOWN"}:
                return {"total": 0, "items": [], "limit": limit, "offset": offset}
            conditions, args = ["1"], []
            if source:
                conditions.append("source_id=?"); args.append(source)
            if query:
                conditions.append("path LIKE ?"); args.append("%" + query + "%")
            condition = " AND ".join(conditions)
            total = self.db.execute("SELECT count(*) FROM issues WHERE " + condition, args).fetchone()[0]
            issues = self.db.execute("SELECT * FROM issues WHERE " + condition + " ORDER BY source_id,path,pointer LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
            return {"total": total, "items": [dict(r) | {"risk": "UNKNOWN", "record_type": "broken_source_document"} for r in issues], "limit": limit, "offset": offset}
        tokens = re.findall(r"[\w-]+", query.lower())
        if "local" in tokens:
            tokens.remove("local")
            local_capable = True
        where, params = [], []
        join = ""
        rank = "(0+0)"
        if tokens:
            join = "JOIN workflow_fts f ON f.rowid=v.rowid"
            where.append("workflow_fts MATCH ?")
            params.append(" AND ".join('"' + token + '"' for token in tokens))
            rank = "f.rank"
        for key, value in {"risk": risk, "status": status, "local_capable": local_capable, "requires_credentials": credentials}.items():
            if value is not None and not (key == "status" and value in {"BROKEN", "DUPLICATE"}):
                where.append(f"v.{key}=?")
                params.append(value)
        if status in {"BROKEN", "DUPLICATE"}:
            where.append("EXISTS(SELECT 1 FROM occurrences os WHERE os.variant_id=v.id AND os.status=?)")
            params.append(status)
        for key, value in {"categories": category, "nodes": node, "integrations": integration, "external_services": external_service}.items():
            if value:
                where.append(f"EXISTS(SELECT 1 FROM json_each(v.metadata, '$.{key}') j WHERE lower(j.value) LIKE ? ESCAPE '\\')")
                params.append("%" + value.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if exclude_integration:
            where.append("NOT EXISTS(SELECT 1 FROM json_each(v.metadata,'$.nodes') j WHERE lower(j.value) LIKE ?) AND NOT EXISTS(SELECT 1 FROM json_each(v.metadata,'$.ai_providers') j WHERE lower(j.value) LIKE ?)")
            params.extend(["%" + exclude_integration.lower() + "%"] * 2)
        if source:
            where.append("EXISTS(SELECT 1 FROM occurrences os WHERE os.variant_id=v.id AND os.source_id=?)")
            params.append(source)
        condition = " AND ".join(where) or "1"
        base = f"FROM variants v {join} WHERE {condition}"
        total = self.db.execute(f"SELECT count(DISTINCT v.workflow_id) {base}", params).fetchone()[0]
        groups = self.db.execute(f"SELECT v.workflow_id,min({rank}) score {base} GROUP BY v.workflow_id ORDER BY score,v.workflow_id LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
        items = []
        for group in groups:
            matches = self.db.execute(f"SELECT v.id,v.metadata {base} AND v.workflow_id=? ORDER BY {rank},v.id", [*params, group["workflow_id"]]).fetchall()
            item = json.loads(matches[0]["metadata"])
            item["id"] = group["workflow_id"]
            item["matched_variant_ids"] = [m["id"] for m in matches]
            item["variant_count"] = self.db.execute("SELECT count(*) FROM variants WHERE workflow_id=?", (item["id"],)).fetchone()[0]
            item["sources"] = self.provenance(item["id"])
            item["duplicate_count"] = max(0, len(item["sources"]) - 1)
            item["evaluation_scope"] = "metadata describes first matching variant; other variants may differ"
            items.append(item)
        return {"total": total, "items": items, "limit": limit, "offset": offset}

    @snapshot
    def provenance(self, workflow_id: str) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT o.* FROM occurrences o JOIN variants v ON o.variant_id=v.id WHERE v.workflow_id=? ORDER BY source_id,path,pointer,revision", (workflow_id,))]

    @snapshot
    def get(self, workflow_id: str) -> dict:
        rows = self.db.execute("SELECT id,metadata FROM variants WHERE workflow_id=? ORDER BY id", (workflow_id,)).fetchall()
        if not rows:
            raise KeyError(workflow_id)
        sources = self.provenance(workflow_id)
        return {"id": workflow_id, "variants": [{"id": r["id"], **json.loads(r["metadata"])} for r in rows],
                "sources": sources, "duplicate_count": max(0, len(sources) - 1),
                "aliases": [dict(r) | {"metadata": json.loads(r["metadata"])} for r in self.db.execute("SELECT a.* FROM aliases a JOIN variants v ON a.variant_id=v.id WHERE v.workflow_id=?", (workflow_id,))]}

    @snapshot
    def facets(self, field: str) -> list[dict]:
        if field not in {"categories", "integrations", "ai_providers"}:
            raise ValueError("invalid facet")
        return [dict(r) for r in self.db.execute(f"SELECT j.value name,count(DISTINCT v.workflow_id) count FROM variants v,json_each(v.metadata,'$.{field}') j GROUP BY j.value ORDER BY count DESC,name")]

    def export(self, workflow_id: str, variant_id: str | None = None, acknowledge_risk: bool = False) -> dict:
        rows = self.db.execute("SELECT * FROM variants WHERE workflow_id=?", (workflow_id,)).fetchall()
        if not rows:
            raise KeyError(workflow_id)
        if len(rows) != 1 and variant_id is None:
            raise ValueError("select a variant explicitly")
        row = next((r for r in rows if variant_id is None or r["id"] == variant_id), None)
        if row is None:
            raise KeyError(variant_id)
        if not acknowledge_risk:
            raise ValueError("review dependencies/security and explicitly acknowledge risk before export")
        payload = json.loads(row["payload"])
        for key in ["id", "versionId", "meta", "pinData", "staticData", "tags", "createdAt", "updatedAt"]:
            payload.pop(key, None)
        payload["active"] = False
        for node in payload["nodes"]:
            node.pop("credentials", None)
            node.pop("webhookId", None)
            if node["type"].lower().endswith(("executeworkflow", "executeworkflowtrigger")):
                raise ValueError("subworkflow references must be reviewed and rewired before export")
        return {"workflow": payload, "review": json.loads(row["metadata"]), "sources": self.provenance(workflow_id),
                "warning": "Sanitized inactive template. Reconfigure all dependencies; static analysis is not approval to execute."}

    @snapshot
    def stats(self) -> dict:
        scalar = lambda sql: self.db.execute(sql).fetchone()[0]
        occurrences = scalar("SELECT count(*) FROM occurrences")
        unique = scalar("SELECT count(*) FROM workflows")
        return {"sources": scalar("SELECT count(*) FROM sources"), "occurrences": occurrences, "unique_workflows": unique,
                "variants": scalar("SELECT count(*) FROM variants"), "duplicates": max(0, occurrences - unique),
                "duplicate_ratio": (occurrences - unique) / occurrences if occurrences else 0,
                "issues": scalar("SELECT count(*) FROM issues"),
                "risk_variants": {r[0]: r[1] for r in self.db.execute("SELECT risk,count(*) FROM variants GROUP BY risk")},
                "status_variants": {r[0]: r[1] for r in self.db.execute("SELECT status,count(*) FROM variants GROUP BY status")},
                "local_capable_variants": scalar("SELECT count(*) FROM variants WHERE local_capable=1"),
                "categories": self.facets("categories"), "integrations": self.facets("integrations")}
