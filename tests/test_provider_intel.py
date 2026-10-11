"""Provider intelligence: inventory, evidence, ranking, runner helpers. No network/keys."""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_os_decision.provider_intel import (
    ModelEvidence, ModelRecord, TaskRequirements, build_inventory, evidence_is_fresh,
    filter_eligible, load_evidence_file, rank_candidates,
)
from ai_os_decision.system_one import Capability


def _runner():
    spec = importlib.util.spec_from_file_location(
        "run_provider_benchmark",
        os.path.join(os.path.dirname(__file__), "..", "eval", "run_provider_benchmark.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ollama_caps():
    return (Capability("qwen3.5:9b-mlx", "model", "ollama:/api/tags:abc", completion=True),
            Capability("embeddinggemma:300m", "model", "ollama:/api/tags:def", completion=False))


def freellm_rows():
    return [
        {"id": "glm-5.3-flash", "name": "GLM", "available": True, "context_window": 1000000,
         "supported_parameters": ["response_format", "tools"]},
        {"id": "gpt-5.6-luna", "available": False, "unavailable_reason": "no_key"},
        {"id": "embeddinggemma300m", "available": True},
        {"id": "", "available": True},
        "not-a-dict",
    ]


def test_build_inventory_normalizes_without_invention():
    recs = {r.model_id: r for r in build_inventory(ollama_caps(), freellm_rows(), observed_at="2026-10-11T00:00:00+00:00")}
    assert recs["qwen3.5:9b-mlx"].availability == "available"
    assert recs["qwen3.5:9b-mlx"].capabilities == frozenset({"completion"})
    assert recs["qwen3.5:9b-mlx"].pricing == "local-inference-no-per-token-fee"
    assert recs["gpt-5.6-luna"].availability == "advertised"
    assert recs["gpt-5.6-luna"].capabilities == frozenset()
    glm = recs["glm-5.3-flash"]
    assert glm.availability == "available" and glm.context == 1000000
    assert glm.capabilities == frozenset({"completion", "json", "tools"})
    assert glm.pricing is None  # unknown, never invented
    assert recs["embeddinggemma300m"].capabilities == frozenset()
    assert "" not in recs and len(recs) == 5
    assert "vision" not in glm.capabilities  # no discovery source proves vision


def test_record_rejects_invention():
    with pytest.raises(ValueError, match="invented capability"):
        ModelRecord("freellm", "m", "available", frozenset({"vision"}), None).validate()
    with pytest.raises(ValueError, match="unknown provider"):
        ModelRecord("nope", "m", "available", frozenset(), None).validate()


def test_filter_eligible_gates():
    recs = build_inventory(ollama_caps(), freellm_rows(), observed_at="t")
    base = TaskRequirements("engineering")
    assert {r.model_id for r in filter_eligible(recs, base, policy_allows_cloud=False)} == {"qwen3.5:9b-mlx"}
    cloud_ok = TaskRequirements("engineering", allow_cloud=True)
    got = {r.model_id for r in filter_eligible(recs, cloud_ok, policy_allows_cloud=True)}
    assert got == {"qwen3.5:9b-mlx", "glm-5.3-flash"}
    assert "gpt-5.6-luna" not in got  # advertised, never eligible
    assert "embeddinggemma300m" not in got  # no completion
    json_req = TaskRequirements("engineering", require_json=True, allow_cloud=True)
    assert [r.model_id for r in filter_eligible(recs, json_req, policy_allows_cloud=True)] == ["glm-5.3-flash"]
    ctx_req = TaskRequirements("engineering", min_context=2000000, allow_cloud=True)
    assert filter_eligible(recs, ctx_req, policy_allows_cloud=True) == []
    assert filter_eligible(recs, TaskRequirements("x", providers=("ollama",)), policy_allows_cloud=True)


def _ts(hour):
    from datetime import datetime, timezone
    return datetime(2026, 10, 11, hour, tzinfo=timezone.utc)


def ev(mid, provider="ollama", samples=4, accuracy=1.0, ts=None):
    stamp = ts if isinstance(ts, str) else (ts or _ts(8)).isoformat()
    return ModelEvidence(mid, provider, "provider-benchmark/v1", stamp, samples, accuracy,
                         100.0, 0.0, "hash", "test")


NOW = _ts(10).timestamp()


def test_rank_prefers_measured_and_local_ties():
    recs = build_inventory(ollama_caps(), freellm_rows(), observed_at="t")
    req = TaskRequirements("engineering", allow_cloud=True)
    evidence = {("ollama", "qwen3.5:9b-mlx"): ev("qwen3.5:9b-mlx", samples=4, accuracy=0.9),
                ("freellm", "glm-5.3-flash"): ev("glm-5.3-flash", "freellm", samples=4, accuracy=0.93)}
    ranked = rank_candidates(recs, evidence, req, now_ts=NOW, policy_allows_cloud=True)
    assert ranked[0][0].model_id == "qwen3.5:9b-mlx"  # within 0.05: local wins ties
    assert ranked[0][1] == 0.9 and "measured" in ranked[0][2]


def test_rank_insufficient_and_stale_evidence_never_wins():
    recs = build_inventory(ollama_caps(), freellm_rows(), observed_at="t")
    req = TaskRequirements("engineering", allow_cloud=True)
    evidence = {("freellm", "glm-5.3-flash"): ev("glm-5.3-flash", "freellm", samples=1, accuracy=1.0),
                ("ollama", "qwen3.5:9b-mlx"): ev("qwen3.5:9b-mlx", samples=4, accuracy=0.5,
                                                 ts=_ts(0).replace(year=2025))}
    ranked = rank_candidates(recs, evidence, req, min_samples=3, max_age_days=30,
                             now_ts=NOW, policy_allows_cloud=True)
    assert all(score is None for _, score, _ in ranked)
    assert {reason for _, _, reason in ranked} == {"insufficient-evidence", "stale-evidence"}


def test_rank_empty_when_nothing_qualifies():
    ranked = rank_candidates((), {}, TaskRequirements("x"), now_ts=0)
    assert ranked == []


def test_evidence_file_validation(tmp_path):
    good = {"evidence": [{"model_id": "m", "provider": "ollama", "benchmark_version": "v1",
                           "timestamp": "2026-10-11T00:00:00+00:00", "samples": 2,
                           "accuracy": 0.5, "p50_ms": 10.0, "fallback_rate": 0.0,
                           "config_hash": "h", "provenance": "t"}]}
    p = tmp_path / "ev.json"
    p.write_text(json.dumps(good))
    assert load_evidence_file(p)[("ollama", "m")].samples == 2
    p.write_text(json.dumps({"evidence": "nope"}))
    with pytest.raises(TypeError, match="malformed evidence file"):
        load_evidence_file(p)
    bad = json.loads(json.dumps(good))
    bad["evidence"][0]["accuracy"] = 1.5
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="outside"):
        load_evidence_file(p)


def test_evidence_freshness():
    fresh = ev("m", ts="2026-10-11T10:00:00+00:00")
    assert evidence_is_fresh(fresh, max_age_days=30, now_ts=NOW)
    assert not evidence_is_fresh(fresh, max_age_days=30, now_ts=1960176000)
    assert not evidence_is_fresh(ev("m", ts="not-a-time"), max_age_days=30, now_ts=NOW)


def test_runner_summarize_and_evidence():
    mod = _runner()
    rows = [
        {"pair_id": "a", "fixture": "F1", "provider": "ollama", "model": "q",
         "status": "PASS", "correct": True, "fallback": False, "error": None,
         "latency_ms": 100.0, "usage": {"input_tokens": 10, "output_tokens": 2},
         "measurement": {}, "confidence_semantics": "s"},
        {"pair_id": "b", "fixture": "F2", "provider": "ollama", "model": "q",
         "status": "FALLBACK", "correct": False, "fallback": True, "error": "RuntimeError",
         "latency_ms": 50.0, "usage": {"input_tokens": 0, "output_tokens": 0},
         "measurement": {}, "confidence_semantics": "s"},
        {"pair_id": "c", "fixture": "F1", "provider": "freellm", "model": "g",
         "status": "BLOCKED", "reason": "budget-exhausted"},
        {"pair_id": "d", "fixture": "F1", "provider": "deterministic", "model": None,
         "status": "PASS", "correct": True, "fallback": False, "error": None,
         "latency_ms": 0.05, "usage": {"input_tokens": 0, "output_tokens": 0},
         "measurement": {}, "confidence_semantics": "s"},
    ]
    summary = mod.summarize(rows, "hash")
    q = summary["models"]["ollama:q"]
    assert q["samples"] == 2 and q["accuracy"] == 0.5 and q["fallback_rate"] == 0.5
    assert q["errors"] == {"RuntimeError": 1} and q["p50_ms"] == 100.0
    assert "freellm:g" not in summary["models"]  # BLOCKED-only models excluded
    evidence = {e["model_id"]: e for e in mod.build_evidence(rows, summary, "hash")}
    assert set(evidence) == {"q"}  # deterministic excluded
    assert evidence["q"]["samples"] == 2 and evidence["q"]["provenance"] == "run_provider_benchmark"


def test_runner_checkpoint_resume_skips_malformed(tmp_path):
    mod = _runner()
    cp = tmp_path / "cp.jsonl"
    cp.write_text('{"pair_id": "F1|ollama:q"}\nnot json\n{"no-id": true}\n')
    assert mod.read_checkpoint(str(cp)) == {"F1|ollama:q": {"pair_id": "F1|ollama:q"}}
    assert mod.read_checkpoint(str(tmp_path / "missing")) == {}


def test_runner_load_pairs_rejects_unknown():
    mod = _runner()
    with pytest.raises(ValueError, match="unknown fixtures"):
        mod.load_pairs(Path("eval/provider_intel"), ["NOPE"])
