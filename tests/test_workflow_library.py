"""Synthetic-only tests: no credentials, workflow execution or remote writes."""
import copy
import io
import json
import sqlite3
import zipfile

import pytest

from ai_os_decision.workflows.analysis import analyze
from ai_os_decision.workflows.discovery import documents, parse
from ai_os_decision.workflows.normalize import hashes, validate
from ai_os_decision.workflows.registry import Registry


def workflow(provider="lmChatOllama", url="http://localhost:11434"):
    return {"name": "Local RAG Ollama Postgres", "nodes": [
        {"name": "Start", "type": "n8n-nodes-base.manualTrigger", "id": "a", "position": [1, 2], "parameters": {}},
        {"name": "Model", "type": "@n8n/n8n-nodes-langchain." + provider, "typeVersion": 1, "parameters": {"baseUrl": url}},
        {"name": "Postgres", "type": "n8n-nodes-base.postgres", "parameters": {"operation": "select"}},
    ], "connections": {"Start": {"main": [[{"node": "Model", "type": "main", "index": 0}]]},
                       "Model": {"main": [[{"node": "Postgres", "type": "main", "index": 0}]]}}}


@pytest.fixture
def registry(tmp_path):
    reg = Registry(tmp_path / "library.db")
    for name in ["one", "two"]:
        reg.register({"id": name, "url": "https://github.com/test/" + name, "kind": "github", "status": "KEEP"})
    yield reg
    reg.close()


def add(reg, w, source="one", path="workflow.json"):
    return reg.ingest(source, path, "commit", json.dumps(w).encode(), "https://example.test/source")


def test_discovery_wrappers_json_strings_and_invalid_json():
    w = workflow()
    values = list(parse("dataset.json", json.dumps({"items": [{"workflow": json.dumps(w)}]}).encode()))
    assert len(values) == 1 and values[0][1]["nodes"] == w["nodes"]
    assert list(parse("bad.json", b"{")) == [("/", None)]
    assert len(list(parse("lines.jsonl", json.dumps(w).encode() + b"\nnot json"))) == 2


def test_zip_discovery_rejects_traversal():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("../evil.json", "{}")
        z.writestr("folder/ok.json", json.dumps(workflow()))
    result = list(documents("workflows.zip", data.getvalue()))
    assert [name for name, _ in result] == ["workflows.zip!folder/ok.json"]


def test_hashes_ignore_ids_layout_names_order_and_keep_behavior():
    a = workflow()
    b = copy.deepcopy(a)
    b["id"] = "instance"; b["updatedAt"] = "later"
    b["nodes"][0].update(id="new", position=[50, 60], name="Renamed")
    b["connections"]["Renamed"] = b["connections"].pop("Start")
    b["nodes"].reverse()
    first, second = hashes(a), hashes(b)
    assert first["raw_hash"] != second["raw_hash"]
    assert first["normalized_hash"] == second["normalized_hash"]
    assert first["structural_hash"] == second["structural_hash"]
    b["nodes"][1]["parameters"]["baseUrl"] = "https://external.example"
    assert hashes(b)["normalized_hash"] != first["normalized_hash"]
    assert hashes(b)["structural_hash"] == first["structural_hash"]
    assert all(len(value) == 64 for value in first.values())


def test_topology_and_expressions():
    a = workflow(); a["nodes"][1]["parameters"]["prompt"] = "={{ $node['Start'].json.text }}"
    b = copy.deepcopy(a)
    b["nodes"][0]["name"] = "Begin"
    b["nodes"][1]["parameters"]["prompt"] = "={{ $node['Begin'].json.text }}"
    b["connections"]["Begin"] = b["connections"].pop("Start")
    assert hashes(a)["normalized_hash"] == hashes(b)["normalized_hash"]
    b["connections"]["Begin"]["main"][0][0]["node"] = "Postgres"
    assert hashes(a)["structural_hash"] != hashes(b)["structural_hash"]


def test_invalid_connections():
    w = workflow(); w["connections"]["Start"]["main"][0][0]["node"] = "Missing"
    assert "invalid_connection" in validate(w)


def test_classification_locality_and_cloud_dominance():
    a = analyze(workflow())
    assert {"RAG", "Ollama", "Postgres"} <= set(a["categories"])
    assert a["local_capable"] is True and a["requires_cloud"] is False
    w = workflow(); w["nodes"].append({"name": "Mail", "type": "n8n-nodes-base.gmail", "parameters": {}})
    a = analyze(w)
    assert a["local_capable"] is False and a["requires_cloud"] is True
    assert a["requires_paid_service"] is None


@pytest.mark.parametrize("node,params,finding", [
    ("executeCommand", {"command": "echo synthetic"}, "command_execution"),
    ("postgres", {"operation": "delete"}, "destructive_operation"),
    ("code", {"jsCode": "require('child_process')"}, "dangerous_code_pattern"),
])
def test_high_risks(node, params, finding):
    w = {"name": "Synthetic", "nodes": [{"name": "Only", "type": "n8n-nodes-base." + node, "parameters": params}], "connections": {}}
    meta = analyze(w)
    assert meta["risk"] == "HIGH" and meta["status"] == "UNSAFE"
    assert finding in meta["findings"]


def test_dynamic_destination_unknown():
    w = {"nodes": [{"name": "HTTP", "type": "n8n-nodes-base.httpRequest", "parameters": {"url": "={{ $json.url }}"}}], "connections": {}}
    assert analyze(w)["risk"] == "UNKNOWN"
    assert analyze(w)["local_capable"] is None


def test_provenance_merge_and_idempotency(registry):
    assert add(registry, workflow()) == 1
    assert add(registry, workflow(), "two") == 1
    add(registry, workflow(), "two")
    registry.db.commit()
    result = registry.search("RAG Ollama Postgres local")
    assert result["total"] == 1
    assert len(result["items"][0]["sources"]) == 2
    assert result["items"][0]["duplicate_count"] == 1
    assert registry.stats()["occurrences"] == 2


def test_variants_kept_and_search_filters_same_variant(registry):
    w = workflow(); add(registry, w)
    w = copy.deepcopy(w); w["name"] = "Cloud Secret Project"; w["nodes"][1]["parameters"]["baseUrl"] = "https://cloud.example"
    add(registry, w, "two")
    assert registry.stats()["unique_workflows"] == 1
    assert registry.stats()["variants"] == 2
    assert registry.search("Secret", local_capable=True)["total"] == 0
    assert registry.search("Secret", local_capable=False)["total"] == 1
    assert registry.search(source="two", local_capable=True)["total"] == 0


def test_filters_pagination_and_injection(registry):
    add(registry, workflow())
    for filters in [{"category": "Ollama"}, {"node": "lmChatOllama"}, {"integration": "postgres"},
                    {"credentials": False}, {"risk": "LOW"}, {"status": "CANDIDATE"}, {"source": "one"},
                    {"exclude_integration": "OpenAI"}]:
        assert registry.search(**filters)["total"] == 1
    assert registry.search(source="x' OR 1=1 --")["total"] == 0
    assert registry.search('"; DROP TABLE variants; --')["total"] == 0
    with pytest.raises(ValueError):
        registry.search(limit=10000)


def test_broken_retained_and_source_unique(registry):
    registry.ingest("one", "bad.json", "commit", b"{", "source")
    assert registry.stats()["issues"] == 1
    with pytest.raises(ValueError):
        registry.register({"id": "another", "url": "https://github.com/test/one", "kind": "github"})


def test_export_inactive_redacted_and_explicit(registry):
    w = workflow(); w["active"] = True; w["pinData"] = {"personal": "synthetic"}
    w["nodes"][1]["credentials"] = {"ollamaApi": {"id": "account", "name": "synthetic"}}
    add(registry, w)
    ident = registry.search()["items"][0]["id"]
    with pytest.raises(ValueError):
        registry.export(ident)
    result = registry.export(ident, acknowledge_risk=True)
    assert result["workflow"]["active"] is False
    assert "pinData" not in result["workflow"]
    assert "credentials" not in result["workflow"]["nodes"][1]
    assert "account" not in json.dumps(result)


def test_readonly_does_not_create_database(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        Registry(tmp_path / "absent.db", readonly=True)
    assert not (tmp_path / "absent.db").exists()


@pytest.mark.parametrize("integration", ["github", "asana", "unknown-community-node"])
def test_cloud_and_unknown_nodes_not_assumed_local(integration):
    w = {"nodes": [{"name": "External", "type": "n8n-nodes-base." + integration, "parameters": {}}], "connections": {}}
    meta = analyze(w)
    assert meta["local_capable"] is not True
    assert meta["requires_external_api"] is not False


@pytest.mark.parametrize("key", ["X-API-Key", "Authorization", "access_token"])
def test_named_header_secrets_are_not_persisted_or_exported(registry, key):
    w = {"nodes": [{"name": "HTTP", "type": "n8n-nodes-base.httpRequest", "parameters": {
        "url": "http://localhost:3000", "headerParameters": {"parameters": [{"name": key, "value": "SYNTHETIC_NON_SECRET_PLACEHOLDER"}]}}}], "connections": {}}
    add(registry, w)
    item = registry.search()["items"][0]
    assert item["risk"] == "HIGH"
    payload = registry.export(item["id"], acknowledge_risk=True)
    assert "SYNTHETIC_NON_SECRET_PLACEHOLDER" not in json.dumps(payload)
    assert "SYNTHETIC_NON_SECRET_PLACEHOLDER" not in registry.db.execute("SELECT payload FROM variants").fetchone()[0]


def test_http_delete_is_destructive():
    w = {"nodes": [{"name": "HTTP", "type": "n8n-nodes-base.httpRequest", "parameters": {"url": "http://localhost:3000/data", "method": "DELETE"}}], "connections": {}}
    assert analyze(w)["status"] == "UNSAFE"
    assert "destructive_operation" in analyze(w)["findings"]


def test_duplicate_aliases_remain_searchable(registry):
    w = workflow(); add(registry, w)
    w["name"] = "DistinctiveAlias"; w["description"] = "UniqueDescription"; w["tags"] = ["UniqueTag"]
    add(registry, w, "two")
    for text in ["DistinctiveAlias", "UniqueDescription", "UniqueTag"]:
        assert registry.search(text)["total"] == 1
    assert len(registry.get(registry.search()["items"][0]["id"])["aliases"]) == 2


def test_bad_zip_member_does_not_prevent_valid_member():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("bad.json", json.dumps(workflow()))
        z.writestr("good.json", json.dumps(workflow()))
    raw = bytearray(data.getvalue())
    import struct
    offset = 30 + struct.unpack_from("<H", raw, 26)[0] + struct.unpack_from("<H", raw, 28)[0]
    raw[offset] = 255
    result = list(documents("archive.zip", bytes(raw)))
    assert result[0][1] is None
    assert result[1][1] is not None


def test_http_api_is_readonly_and_filtered(registry):
    import threading
    import urllib.error
    import urllib.request
    from ai_os_decision.workflows.interfaces import http_server
    add(registry, workflow()); registry.db.commit()
    server = http_server(registry.path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(url + "/search?query=Ollama&local_capable=true") as r:
            assert json.load(r)["total"] == 1
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url + "/execute")
        assert error.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url + "/search?local_capable=maybe")
        assert error.value.code == 400
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_mcp_real_sdk_client_search_and_dependencies(registry):
    pytest.importorskip("mcp")
    import asyncio
    from mcp import Client
    from ai_os_decision.workflows.interfaces import mcp_server
    add(registry, workflow()); registry.db.commit()
    ident = registry.search()["items"][0]["id"]

    async def check():
        async with Client(mcp_server(registry.path)) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 6
            result = await client.call_tool("find_local_workflows", {"query": "RAG Ollama Postgres", "exclude_integration": "openai"})
            assert not result.is_error and json.loads(result.content[0].text)["total"] == 1
            result = await client.call_tool("get_workflow_dependencies", {"workflow_id": ident})
            assert not result.is_error and "postgres" in json.loads(result.content[0].text)["variants"][0]["databases"]
    asyncio.run(check())


def test_source_seed_keeps_previously_skipped_mirrors(tmp_path):
    from ai_os_decision.workflows.sources import seed_sources
    file = tmp_path / "catalog.json"
    file.write_text(json.dumps([{"category": "n8n Library", "requested_repo": "owner/mirror", "decision": "SKIP"}]))
    assert seed_sources(file)[0]["status"] == "KEEP"


def test_raw_hash_matches_actual_bytes():
    import hashlib
    w = workflow(); raw = json.dumps(w, indent=4).encode()
    assert hashes(w, raw)["raw_hash"] == hashlib.sha256(raw).hexdigest()


def test_cached_duplicate_preserves_alias_provenance(registry):
    w = workflow()
    add(registry, w)
    add(registry, w, source="two")
    result = registry.search("RAG")
    assert result["total"] == 1
    detail = registry.get(result["items"][0]["id"])
    assert {a["source_id"] for a in detail["aliases"]} == {"one", "two"}
    assert len(detail["sources"]) == 2


def test_broken_source_filter_and_case_insensitive_source_identity(registry):
    registry.ingest("one", "bad.json", "commit", b"{", "https://example.test")
    assert registry.search(status="BROKEN", source="one")["total"] == 1
    assert registry.search(status="BROKEN", source="two")["total"] == 0
    assert registry.search(status="BROKEN", category="RAG")["total"] == 0
    with pytest.raises(ValueError, match="already registered"):
        registry.register({"id": "other", "url": "https://GitHub.com/TEST/ONE/", "kind": "github"})


def test_unknown_namespace_cannot_impersonate_local_service():
    w = workflow()
    w["nodes"][1]["type"] = "untrusted-community.ollama"
    result = analyze(w)
    assert result["local_capable"] is None
    assert "unrecognized_integration" in result["findings"]


def test_json_encoded_http_headers_are_flagged_and_redacted(registry):
    w = workflow()
    w["nodes"].append({"name": "HTTP", "type": "n8n-nodes-base.httpRequest", "parameters": {
        "url": "http://localhost:8080", "specifyHeaders": "json",
        "jsonHeaders": json.dumps({"X-API-Key": "SYNTHETIC_KEY_12345", "Authorization": "Basic SYNTHETIC_AUTH_12345"})}})
    add(registry, w)
    item = registry.search()["items"][0]
    assert item["risk"] == "HIGH"
    assert "possible_embedded_secret" in item["findings"]
    payload = registry.export(item["id"], acknowledge_risk=True)["workflow"]
    assert "SYNTHETIC_" not in json.dumps(payload)
    assert "SYNTHETIC_" not in registry.db.execute("SELECT payload FROM variants").fetchone()[0]


def test_unknown_file_node_is_not_assumed_local():
    w = workflow()
    w["nodes"][1]["type"] = "n8n-nodes-unreviewed.fileAgent"
    result = analyze(w)
    assert result["local_capable"] is None
    assert result["risk"] == "UNKNOWN"


def test_source_rollback_invalidates_document_cache(registry):
    add(registry, workflow())
    registry.rollback()
    assert add(registry, workflow(), source="two") == 1
    assert registry.search()["total"] == 1


def test_official_source_recovers_from_unavailable(registry, monkeypatch, tmp_path):
    from ai_os_decision.workflows import sources
    registry.register({"id": "official", "url": "https://n8n.io/workflows/", "kind": "official",
                       "status": "UNAVAILABLE", "availability_reason": "old_error"})
    monkeypatch.setattr(sources, "github_snapshot", lambda *args: (_ for _ in ()).throw(ValueError()))
    monkeypatch.setattr(sources, "sync_official", lambda *args: {"status": "COMPLETE"})
    sources.sync(registry, tmp_path)
    official = next(s for s in registry.sources() if s["id"] == "official")
    assert official["status"] == "KEEP"
    assert "availability_reason" not in official


def test_search_reads_committed_snapshot_during_source_update(registry):
    add(registry, workflow())
    registry.db.commit()
    reader = Registry(registry.path, readonly=True)
    try:
        w = workflow()
        w["nodes"][1]["parameters"]["baseUrl"] = "http://localhost:11435"
        add(registry, w, path="different.json")
        assert reader.search()["total"] == 1
        assert len(reader.get(reader.search()["items"][0]["id"])["variants"]) == 1
        registry.db.commit()
        assert len(reader.get(reader.search()["items"][0]["id"])["variants"]) == 2
    finally:
        reader.close()


def test_wrapper_annotations_preserve_raw_hash_and_workflow_identity(registry):
    from ai_os_decision.workflows.normalize import encoded
    w = workflow()
    w.pop("name")
    payload = json.dumps({"workflow": {"workflow": w, "description": "Research RAG documents"}}).encode()
    registry.ingest("one", "official.json", "sha256:example", payload, "https://example.test", {"name": "Official local RAG", "description": "Research RAG documents", "tags": [{"name": "Research"}]})
    item = registry.search("Research")["items"][0]
    import hashlib
    assert item["raw_hash"] == hashlib.sha256(encoded(w)).hexdigest()
    assert item["description"] == "Research RAG documents"
    assert item["name"] == "Official local RAG"
    assert item["normalized_hash"] == hashes(w)["normalized_hash"]


def test_report_measures_provenance_and_static_status(registry, tmp_path):
    from ai_os_decision.workflows.report import write_report
    for s in registry.sources():
        s["name"] = s["id"]
        registry.register(s)
    add(registry, workflow())
    add(registry, workflow(), source="two")
    registry.db.commit()
    report = tmp_path / "report.md"
    write_report(registry, report)
    text = report.read_text()
    assert "| Registrierte Sources | 2 |" in text
    assert "| Einzigartige Strukturgruppen (structural_hash) | 1 |" in text
    assert "50.00%" in text
    assert "| VERIFIED | 0 | 0 |" in text
    assert "Kein Workflow wurde ausgeführt" in text


def test_official_annotations_are_not_lost_to_mirror_document_cache(registry):
    w = workflow()
    w.pop("name")
    payload = json.dumps({"workflow": {"name": "OfficialAlias", "workflow": w}}).encode()
    registry.ingest("one", "mirror.json", "commit", payload, "https://example.test")
    registry.ingest("two", "official.json", "commit", payload, "https://example.test", {"name": "OfficialAlias", "description": "Gmail research"})
    result = registry.search("OfficialAlias")
    assert result["total"] == 1
    assert result["items"][0]["name"] == "OfficialAlias"
    assert "possible_personal_data" in result["items"][0]["findings"]
    assert len(registry.get(result["items"][0]["id"])["sources"]) == 2


def test_filter_and_detail_share_snapshot_during_risk_update(registry):
    w = {"name": "Simple", "nodes": [{"name": "Start", "type": "n8n-nodes-base.manualTrigger", "parameters": {}}], "connections": {}}
    add(registry, w)
    registry.db.commit()
    reader = Registry(registry.path, readonly=True)
    real = reader.db
    class InterleavedConnection:
        changed = False
        def __getattr__(self, name):
            return getattr(real, name)
        def execute(self, sql, params=()):
            if "SELECT v.id,v.metadata" in sql and not self.changed:
                self.changed = True
                registry.db.execute("UPDATE variants SET risk='MEDIUM'")
                registry.db.commit()
            return real.execute(sql, params)
    reader.db = InterleavedConnection()
    try:
        result = reader.search(risk="LOW")
        assert result["total"] == 1 and len(result["items"]) == 1
        assert reader.search(risk="LOW")["total"] == 0
    finally:
        reader.close()
