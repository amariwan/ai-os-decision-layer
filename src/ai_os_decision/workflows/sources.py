"""Read-only upstream acquisition; never checkout or execute upstream code."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import tarfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .discovery import MAX_FILE, documents

MAX_DOWNLOAD = 512 * 1024 * 1024


def fetch(url: str, destination: Path, limit: int = MAX_DOWNLOAD):
    """Only fixed public upstream hosts. No workflow-declared URL is fetched."""
    from urllib.parse import urlsplit

    if urlsplit(url).hostname not in {"codeload.github.com", "api.n8n.io"}:
        raise ValueError("unsupported upstream host")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".partial")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "AI-OS-Static-Workflow-Library", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=45) as response, temp.open("wb") as stream:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > limit:
                    raise ValueError("upstream download limit exceeded")
                stream.write(block)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def seed_sources(catalog_path: Path) -> list[dict]:
    result = []
    for row in json.loads(catalog_path.read_text()):
        if not (row["category"].startswith("n8n") or row["category"] == "Self-hosted Stack"):
            continue
        repo = row["requested_repo"]
        official = repo == "Official n8n Workflows"
        result.append({"id": "n8n-official" if official else repo.lower(), "name": repo,
                       "url": "https://n8n.io/workflows/" if official else "https://github.com/" + repo,
                       "kind": "official" if official else "github", "repo": None if official else repo,
                       "revision": row.get("audited_commit"), "status": "KEEP",
                       "license": row.get("license_spdx", "UNKNOWN"), "license_scope": "metadata only; review individual content rights",
                       "previous_assessment": row.get("historical_capability_decision", row.get("decision"))})
    return result


def github_snapshot(source: dict, cache: Path):
    repo, revision = source["repo"], source.get("revision")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise ValueError("invalid GitHub repo")
    if not re.fullmatch(r"[0-9a-f]{40}", revision or ""):
        raise ValueError("missing pinned commit; source retained, not fetched")
    snapshot = cache / "upstream" / (source["id"].replace("/", "__") + "-" + revision + ".tar.gz")
    if not snapshot.exists():
        fetch(f"https://codeload.github.com/{repo}/tar.gz/{revision}", snapshot)
    return snapshot


def archive_documents(snapshot: Path):
    with tarfile.open(snapshot, "r:gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts[1:]
            if not member.isfile() or not parts or ".." in parts:
                continue
            path = "/".join(parts)
            if not path.lower().endswith((".json", ".jsonl", ".zip")):
                continue
            if member.size > MAX_FILE:
                yield path, None
                continue
            stream = archive.extractfile(member)
            if stream is not None:
                yield from documents(path, stream.read(MAX_FILE + 1))


def sync_github(registry, source: dict, snapshot: Path):
    counts = {"json_files": 0, "workflow_occurrences": 0, "oversize_or_archive_error": 0, "status": "COMPLETE", "revision": source["revision"]}
    for path, data in archive_documents(snapshot):
        counts["json_files"] += 1
        if data is None:
            counts["oversize_or_archive_error"] += 1
            registry.issue(source["id"], path, source["revision"], "oversize_or_archive_error")
            continue
        url = f"https://github.com/{source['repo']}/blob/{source['revision']}/{quote(path.split('!')[0], safe='/')}"
        counts["workflow_occurrences"] += registry.ingest(source["id"], path, source["revision"], data, url)
    if counts["oversize_or_archive_error"]:
        counts["status"] = "PARTIAL"
    registry.db.execute("INSERT OR REPLACE INTO scans VALUES(?,?)", (source["id"], json.dumps(counts)))
    registry.db.commit()
    return counts


def sync_official(registry, source: dict, cache: Path, limit: int = 0):
    """Paginate public catalog, then fetch full definitions; cache snapshots."""
    root = cache / "upstream" / "n8n-official"
    root.mkdir(parents=True, exist_ok=True)
    ids = []
    page = 1
    total = None
    while total is None or len(ids) < total:
        dest = root / f"catalog-{page}.json"
        if not dest.exists():
            fetch(f"https://api.n8n.io/templates/search?rows=250&page={page}", dest, MAX_FILE)
        listing = json.loads(dest.read_bytes())
        total = int(listing["totalWorkflows"])
        batch = listing.get("workflows", [])
        ids.extend(str(w["id"]) for w in batch)
        if not batch or (limit and len(ids) >= limit):
            break
        page += 1
        if page > 1000:
            raise ValueError("official pagination limit")
    ids = list(dict.fromkeys(ids))
    selected = ids[:limit] if limit else ids

    def download(template_id):
        destination = root / (template_id + ".json")
        try:
            if not destination.exists():
                fetch("https://api.n8n.io/templates/workflows/" + template_id, destination, MAX_FILE)
            return template_id, destination, None
        except urllib.error.HTTPError as exc:
            return template_id, None, f"HTTP_{exc.code}"
        except (OSError, ValueError, urllib.error.URLError) as exc:
            return template_id, None, type(exc).__name__

    counts = {"catalog_total": total, "discovered_ids": len(ids), "json_files": 0, "fetched_json_files": 0, "workflow_occurrences": 0, "errors": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for template_id, destination, error in pool.map(download, selected):
            counts["json_files"] += 1
            if error:
                counts["errors"] += 1
                registry.issue(source["id"], template_id + ".json", "public-api", error)
                continue
            counts["fetched_json_files"] += 1
            data = destination.read_bytes()
            revision = "sha256:" + hashlib.sha256(data).hexdigest()
            outer = json.loads(data).get("workflow", {})
            annotations = {k: outer.get(k) for k in ["name", "description"]}
            annotations["tags"] = outer.get("categories", [])
            counts["workflow_occurrences"] += registry.ingest(source["id"], template_id + ".json", revision, data, "https://api.n8n.io/templates/workflows/" + template_id, annotations)
            if counts["json_files"] % 250 == 0:
                registry.db.commit()
                print(json.dumps({"source": source["id"], "progress": counts}), flush=True)
    counts["status"] = "COMPLETE" if len(selected) == total and not counts["errors"] else "PARTIAL"
    registry.db.execute("INSERT OR REPLACE INTO scans VALUES(?,?)", (source["id"], json.dumps(counts)))
    registry.db.commit()
    return counts


def sync(registry, cache: Path, official_limit: int = 0, source_ids: list[str] | None = None):
    all_sources = registry.sources()
    if source_ids and set(source_ids) - {s["id"] for s in all_sources}:
        raise ValueError("unknown source ID")
    sources = [s for s in all_sources if s["status"] != "DROP" and (not source_ids or s["id"] in source_ids)]
    github = [s for s in sources if s["kind"] == "github"]

    def acquire(source):
        try:
            return source, github_snapshot(source, cache), None
        except (OSError, ValueError, urllib.error.URLError, tarfile.TarError) as exc:
            return source, None, type(exc).__name__

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for source, snapshot, error in pool.map(acquire, github):
            if error:
                source["status"] = "UNAVAILABLE"
                source["availability_reason"] = error
                registry.register(source)
                print(json.dumps({"source": source["id"], "status": "UNAVAILABLE", "reason": error}), flush=True)
                continue
            source["status"] = "KEEP"
            registry.register(source)
            try:
                counts = sync_github(registry, source, snapshot)
            except (OSError, ValueError, tarfile.TarError, EOFError) as exc:
                registry.rollback()
                registry.db.execute("INSERT OR REPLACE INTO scans VALUES(?,?)", (source["id"], json.dumps({"status": "PARTIAL", "error": type(exc).__name__})))
                registry.db.commit()
                counts = {"status": "PARTIAL", "error": type(exc).__name__}
            print(json.dumps({"source": source["id"], **counts}), flush=True)
    for source in sources:
        if source["kind"] == "official":
            try:
                counts = sync_official(registry, source, cache, official_limit)
                source["status"] = "KEEP"
                source.pop("availability_reason", None)
                registry.register(source)
                print(json.dumps({"source": source["id"], **counts}), flush=True)
            except (OSError, ValueError, urllib.error.URLError) as exc:
                registry.rollback()
                source["status"] = "UNAVAILABLE"
                source["availability_reason"] = type(exc).__name__
                registry.register(source)
    return registry.stats()
