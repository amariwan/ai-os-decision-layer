import json
import math
import subprocess
import sys
import time

import pytest

from ai_os_decision.models import DecisionQuestion, DecisionState
from ai_os_decision.system_one import (
    BoundedRequest, Capability, CapabilitySnapshot, DeterministicFallback,
    LiquidD1Backend, ExistingQwenBackend, FreeLLMBackend, QuotaTracker,
    SystemOneRuntime, cloud_eligible, privacy_screen, validate_native,
)


def request(text="Fix a bug", action="read", risk="low"):
    return BoundedRequest(
        DecisionState(text=text),
        (DecisionQuestion("tool", "choice", "Select a tool", {"terminal": "shell", "atlas": "repo"}),),
        {"tool": "terminal"},
        CapabilitySnapshot((Capability("terminal", "tool", "client-exposed"),
                            Capability("atlas", "tool", "client-exposed"))),
        {"tool": "tool"}, action=action, minimum_risk=risk,
    )


class Fake:
    name = "fake"

    def __init__(self, raw):
        self.raw = raw
        self.calls = 0

    def infer(self, req):
        self.calls += 1
        return self.raw


def native(choice="atlas", confidence=.8):
    return {"answers": {"tool": {"type": "choice", "choice": choice,
            "confidence": confidence, "probabilities": {"terminal": 1-confidence, "atlas": confidence}}},
            "usage": {"input_tokens": 10, "output_tokens": 0}}


def test_unknown_capability_is_rejected_before_backend():
    r = request()
    r.questions[0].options["invented"] = "bad"
    f = Fake(native())
    with pytest.raises(ValueError):
        SystemOneRuntime(f).decide(r)
    assert f.calls == 0


@pytest.mark.parametrize("bad", [native("invented"), native(confidence=math.nan),
                                  {"answers": {}}, native(confidence=2)])
def test_invalid_backend_falls_back(bad):
    out = SystemOneRuntime(Fake(bad)).decide(request())
    assert out.fallback_used and out.answers["tool"].value == "terminal"


def test_shadow_does_not_change_authority_or_log_text():
    runtime = SystemOneRuntime(Fake(native()))
    r = request("secret task text")
    out = runtime.shadow(r)
    assert out.authoritative.answers["tool"].value == "terminal"
    assert out.observation.answers["tool"].value == "atlas"
    assert "secret task text" not in json.dumps(out.metadata())
    assert "terminal" not in json.dumps(out.metadata())


@pytest.mark.parametrize("action", ["deploy", "delete", "publish", "install", "permissions", "unknown"])
def test_protected_actions_fail_closed_even_if_model_says_safe(action):
    out = SystemOneRuntime(Fake(native())).decide(request(action=action, risk="high"))
    assert out.requires_human_approval and out.risk == "high"


def test_required_answers_survive_model():
    r = request()
    r.required_answers["tool"] = "terminal"
    assert SystemOneRuntime(Fake(native())).decide(r).answers["tool"].value == "terminal"


def test_d1_disabled_never_spawns(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("spawned"))
    out = SystemOneRuntime(LiquidD1Backend()).decide(request())
    assert out.fallback_used


def test_timeout_kills_child(tmp_path):
    # Exercise the real process deadline, not an uninterruptible thread timeout.
    from ai_os_decision.system_one_backends import run_worker
    script = tmp_path / "blocked.py"
    script.write_text("import time; time.sleep(30)")
    t = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_worker(sys.executable, [str(script)], {}, .1)
    assert time.monotonic() - t < 3


def test_noul_and_score_native_semantics():
    r = BoundedRequest(DecisionState(text="test"), (
        DecisionQuestion("review", "boolean", "Review?"),
        DecisionQuestion("complexity_score", "score", "Complexity?", criteria=["low", "medium", "high"])),
        {"review": True, "complexity_score": 1.0}, CapabilitySnapshot(()))
    a, _ = validate_native(r, {"answers": {
        "review": {"type": "noul", "noul": .2},
        "complexity_score": {"type": "score", "score": 1.3, "confidence": .5,
                       "probabilities": {"0": .2, "1": .3, "2": .5},
                       "legend": {"0": "low", "1": "medium", "2": "high"}}},
        "usage": {"input_tokens": 22, "output_tokens": 0}})
    assert a["review"].value is False and a["review"].confidence == .8
    assert a["complexity_score"].value == 1.3


def test_cache_and_input_changes():
    f = Fake(native()); runtime = SystemOneRuntime(f)
    runtime.decide(request()); runtime.decide(request())
    assert f.calls == 1
    runtime.decide(request("Different task"))
    assert f.calls == 2


def test_qwen_must_be_discovered_completion_model():
    with pytest.raises(ValueError):
        ExistingQwenBackend("invented", CapabilitySnapshot(()))


def test_deterministic_baseline_requires_no_model():
    assert DeterministicFallback().infer(request())["answers"]["tool"]["choice"] == "terminal"


def test_reserved_model_cannot_bypass_mapping():
    r = BoundedRequest(DecisionState(text="test"),
        (DecisionQuestion("selected_model", "choice", "model", {"invented": "x", "also-invented": "y"}),),
        {"selected_model": "invented"}, CapabilitySnapshot(()))
    with pytest.raises(ValueError, match="undiscovered"):
        SystemOneRuntime().decide(r)


def test_standard_ollama_capabilities_use_show(monkeypatch):
    from ai_os_decision import system_one_worker as w
    calls = []
    monkeypatch.setattr(w, "http_json", lambda path, payload: calls.append((path, payload)) or {"capabilities": ["completion"]})
    assert w.model_capabilities({"name": "qwen3.5:9b"}) == ["completion"]
    assert calls[0][0] == "/api/show"
    assert w.model_capabilities({"name": "qwen", "capabilities": ["completion"]}) == ["completion"]
    assert len(calls) == 1


def test_public_engine_reuses_cache():
    from ai_os_decision.engine import DecisionEngine
    f = Fake(native()); engine = DecisionEngine()
    engine.recommend(request(), f)
    out = engine.recommend(request(), f)
    assert f.calls == 1 and out.measurement["cache_hit"]
    assert out.usage == {"input_tokens": 0, "output_tokens": 0}


def test_measurements_preserved_and_qwen_confidence_labeled():
    raw = native(); raw["measurement"] = {"warm_ms": 30.0, "device": "mps", "rss_bytes": 1234}
    f = Fake(raw); f.name = "qwen"
    out = SystemOneRuntime(f).decide(request())
    assert out.measurement["warm_ms"] == 30
    assert out.confidence_semantics == "synthetic-encoding-not-model-confidence"
    assert out.uncertainty == ("tool",)


def test_request_is_bounded_and_skill_booleans_are_discovered():
    r = BoundedRequest(DecisionState(text="x"), (DecisionQuestion("skill:invented", "boolean", "use?"),),
                       {"skill:invented": False}, CapabilitySnapshot(()))
    with pytest.raises(ValueError):
        r.validate()


def test_snapshot_source_tampering_rejected_before_heavy_import(tmp_path):
    from ai_os_decision.system_one_worker import verify_snapshot
    (tmp_path / "api.py").write_text("raise RuntimeError('unreviewed')")
    with pytest.raises(ValueError, match="snapshot differs"):
        verify_snapshot(tmp_path)


def test_normalized_contract_candidates_and_mandatory_skill():
    skill = "/approved/SKILL.md"
    model = "qwen"
    inv = CapabilitySnapshot((Capability(skill, "skill", "approved configuration"),
        Capability(model, "model", "runtime", completion=True), Capability("other", "model", "runtime")))
    qs = (DecisionQuestion("selected_model", "choice", "model", {model: "known", "other": "known"}),
          DecisionQuestion("skill:"+skill, "boolean", "required skill"))
    r = BoundedRequest(DecisionState(text="test"), qs, {"selected_model": model, "skill:"+skill: False},
                       inv, required_answers={"skill:"+skill: True}, action="local-test", minimum_risk="low")
    out = SystemOneRuntime().decide(r).application_contract(inv)
    assert out["selected_model"] == model and out["selected_skills"] == [skill]


def test_existing_deny_policy_is_applied_to_shadow():
    from ai_os_decision.engine import DecisionEngine
    f = Fake(native())
    out = DecisionEngine({"policy": {"deny_patterns": ["forbidden"]}}).observe(request("forbidden"), f)
    assert out.authoritative.denied and out.observation.denied and f.calls == 0


def test_model_capabilities_malformed_inline_falls_back_to_show(monkeypatch):
    from ai_os_decision import system_one_worker as w
    calls = []
    def fake_http(path, payload=None, timeout=5):
        calls.append((path, payload))
        return {"capabilities": ["completion"]}
    monkeypatch.setattr(w, "http_json", fake_http)
    assert w.model_capabilities({"name": "qwen3.5:9b-mlx", "capabilities": "completion"}) == ["completion"]
    assert calls and calls[0][0] == "/api/show"


def test_model_capabilities_show_unavailable_returns_empty(monkeypatch):
    from ai_os_decision import system_one_worker as w
    def boom(path, payload=None, timeout=5):
        raise ConnectionError("ollama down")
    monkeypatch.setattr(w, "http_json", boom)
    assert w.model_capabilities({"name": "qwen3.5:9b-mlx"}) == []
    assert w.model_capabilities({"name": "qwen3.5:9b-mlx", "capabilities": None}) == []
    assert w.model_capabilities({"no-name": True}) == []
    assert w.model_capabilities("not-a-dict") == []


@pytest.mark.parametrize("bad_resp", [{}, {"capabilities": "completion"},
                                       {"capabilities": [1, 2]}, ["completion"], None])
def test_model_capabilities_malformed_show_returns_empty(monkeypatch, bad_resp):
    from ai_os_decision import system_one_worker as w
    monkeypatch.setattr(w, "http_json", lambda path, payload=None, timeout=5: bad_resp)
    assert w.model_capabilities({"name": "qwen3.5:9b-mlx"}) == []


def test_discover_models_skips_malformed_rows(monkeypatch):
    from ai_os_decision import system_one_io as io
    tags = {"models": [
        {"name": "qwen3.5:9b-mlx", "digest": "abc123", "capabilities": ["completion"]},
        {"name": "embed-model", "digest": "def456", "capabilities": ["embedding"]},
        {"digest": "no-name"},
        {"name": "no-digest"},
        {"name": "", "digest": "empty-name"},
        {"name": "x" * 513, "digest": "too-long"},
        "not-a-dict",
    ]}
    monkeypatch.setattr(io, "http_json", lambda path, payload=None, timeout=5: tags)
    out = io.discover_models()
    by_id = {c.id: c for c in out}
    assert set(by_id) == {"qwen3.5:9b-mlx", "embed-model"}
    assert by_id["qwen3.5:9b-mlx"].completion is True
    assert by_id["embed-model"].completion is False
    assert by_id["qwen3.5:9b-mlx"].source == "ollama:/api/tags:abc123"


@pytest.mark.parametrize("bad", [{}, {"models": "nope"}, {"models": None}, ["models"], None])
def test_discover_models_malformed_envelope_raises(monkeypatch, bad):
    from ai_os_decision import system_one_io as io
    monkeypatch.setattr(io, "http_json", lambda path, payload=None, timeout=5: bad)
    with pytest.raises(TypeError, match="malformed Ollama inventory"):
        io.discover_models()


def test_qwen_rejects_when_show_reports_no_completion(monkeypatch):
    from ai_os_decision import system_one_worker as w
    def fake_http(path, payload=None, timeout=5):
        if path == "/api/tags":
            return {"models": [{"name": "qwen3.5:9b-mlx", "digest": "abc"}]}
        return {"capabilities": ["embedding"]}
    monkeypatch.setattr(w, "http_json", fake_http)
    with pytest.raises(ValueError, match="no longer available"):
        w.qwen({"model": "qwen3.5:9b-mlx", "state": {}, "questions": {}, "timeout": 5})


def test_qwen_backend_rejects_non_completion_model():
    inv = CapabilitySnapshot((Capability("embed", "model", "ollama:/api/tags:abc"),),)
    with pytest.raises(ValueError):
        ExistingQwenBackend("embed", inv)


def test_recommendation_telemetry_contract():
    out = SystemOneRuntime(Fake(native())).decide(request())
    assert out.decision_source == "fake"
    assert out.fallback_used is False and out.error is None
    assert isinstance(out.latency_ms, float) and out.latency_ms >= 0
    assert set(out.usage) == {"input_tokens", "output_tokens"}
    assert isinstance(out.measurement, dict)
    assert out.confidence_semantics == "deterministic-encoding-not-statistical-confidence"
    bad = SystemOneRuntime(Fake({"answers": {}})).decide(request())
    assert bad.fallback_used is True and bad.error is not None


def freellm_inv(model="glm-5.3-flash", completion=True):
    return CapabilitySnapshot((Capability(model, "model", "freellm:/v1/models:" + model,
                                          "GLM", completion=completion),))


def test_discover_freellm_only_available(monkeypatch):
    from ai_os_decision import system_one_io as io
    rows = {"data": [
        {"id": "glm-5.3-flash", "name": "GLM", "available": True,
         "supported_parameters": ["response_format", "tools"]},
        {"id": "gpt-5.6-luna", "name": "Luna", "available": False, "unavailable_reason": "no_key"},
        {"id": "embeddinggemma300m", "name": "emb", "available": True},
        {"name": "no-id", "available": True},
        "not-a-dict",
    ]}
    monkeypatch.setattr(io, "cloud_json", lambda base, path, payload=None, timeout=10: (rows, {}))
    caps, json_ok = io.discover_freellm_models()
    by_id = {c.id: c for c in caps}
    assert set(by_id) == {"glm-5.3-flash", "embeddinggemma300m"}
    assert by_id["glm-5.3-flash"].completion is True
    assert by_id["embeddinggemma300m"].completion is False
    assert json_ok == frozenset({"glm-5.3-flash"})
    assert by_id["glm-5.3-flash"].source == "freellm:/v1/models:glm-5.3-flash"
    assert "FREELLMAPI" not in repr(caps) and "freellmapi-" not in repr(caps)


@pytest.mark.parametrize("bad", [{}, {"data": "nope"}, {"models": None}, []])
def test_discover_freellm_malformed_envelope_raises(monkeypatch, bad):
    from ai_os_decision import system_one_io as io
    monkeypatch.setattr(io, "cloud_json", lambda base, path, payload=None, timeout=10: (bad, {}))
    with pytest.raises(TypeError, match="malformed cloud inventory"):
        io.discover_freellm_models()


def test_discover_freellm_transport_failure_raises_without_key_material(monkeypatch):
    from ai_os_decision import system_one_io as io
    monkeypatch.setattr(io, "cloud_json",
                        lambda base, path, payload=None, timeout=10: ({"transport_error": {"type": "unauthorized"}}, {}))
    with pytest.raises(RuntimeError, match="cloud discovery failed: unauthorized"):
        io.discover_freellm_models()


def test_discover_freellm_rejects_non_loopback():
    from ai_os_decision import system_one_io as io
    with pytest.raises(ValueError, match="loopback"):
        io.discover_freellm_models("https://example.com")


def test_freellm_worker_success_maps_usage_and_telemetry(monkeypatch):
    from ai_os_decision import system_one_worker as w
    seen = {}
    def fake_cloud(base, path, payload, timeout):
        seen.update(payload)
        assert path == "/v1/chat/completions"
        content = json.dumps({"tool": "atlas"})
        return ({"choices": [{"message": {"content": content}}],
                 "usage": {"prompt_tokens": 178, "completion_tokens": 15}},
                {"x-ratelimit-remaining": "112"})
    monkeypatch.setattr(w, "cloud_json", fake_cloud)
    out = w.freellm({"model": "glm-5.3-flash", "base_url": "http://127.0.0.1:31415",
                     "timeout": 5, "json_mode": True,
                     "state": {"text": "x"},
                     "questions": {"tool": {"type": "choice", "criteria": {"terminal": "s", "atlas": "r"}}}})
    assert out["answers"]["tool"]["choice"] == "atlas"
    assert out["usage"] == {"input_tokens": 178, "output_tokens": 15}
    assert out["measurement"]["rate_limit_remaining"] == 112.0
    assert out["confidence_semantics"] == "synthetic-encoding-not-model-confidence"
    assert seen["response_format"] == {"type": "json_object"}


def test_freellm_worker_without_json_mode_omits_response_format(monkeypatch):
    from ai_os_decision import system_one_worker as w
    seen = {}
    def fake_cloud(base, path, payload, timeout):
        seen.update(payload)
        return ({"choices": [{"message": {"content": json.dumps({"tool": "terminal"})}}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 2}}, {})
    monkeypatch.setattr(w, "cloud_json", fake_cloud)
    w.freellm({"model": "m", "base_url": "http://127.0.0.1:31415", "timeout": 5,
               "state": {}, "questions": {"tool": {"type": "choice", "criteria": {"terminal": "s", "atlas": "r"}}}})
    assert "response_format" not in seen


@pytest.mark.parametrize("raw", [{"choices": []}, {"choices": [{"message": {}}]},
                                  {"choices": [{"message": {"content": "not json"}}]},
                                  {"choices": [{"message": {"content": json.dumps({"tool": "invented"})}}]}])
def test_freellm_worker_malformed_maps_to_transport_error(monkeypatch, raw):
    from ai_os_decision import system_one_worker as w
    monkeypatch.setattr(w, "cloud_json", lambda base, path, payload, timeout: (raw, {}))
    out = w.freellm({"model": "m", "base_url": "http://127.0.0.1:31415", "timeout": 5,
                     "state": {}, "questions": {"tool": {"type": "choice", "criteria": {"terminal": "s", "atlas": "r"}}}})
    assert out["transport_error"]["type"] in ("malformed", "rejected")


def test_freellm_worker_rejects_images():
    from ai_os_decision import system_one_worker as w
    with pytest.raises(ValueError):
        w.freellm({"images": ["x"], "model": "m", "base_url": "http://127.0.0.1:1", "timeout": 1,
                   "state": {}, "questions": {}})


def test_freellm_worker_missing_usage_flagged_not_fabricated(monkeypatch):
    from ai_os_decision import system_one_worker as w
    monkeypatch.setattr(w, "cloud_json", lambda base, path, payload, timeout: (
        {"choices": [{"message": {"content": json.dumps({"tool": "terminal"})}}]}, {}))
    out = w.freellm({"model": "m", "base_url": "http://127.0.0.1:31415", "timeout": 5,
                     "state": {}, "questions": {"tool": {"type": "choice", "criteria": {"terminal": "s", "atlas": "r"}}}})
    assert out["usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert out["measurement"]["usage_missing"] is True


def test_cloud_json_error_mapping(monkeypatch):
    import urllib.error
    from ai_os_decision import system_one_worker as w
    import os
    monkeypatch.setitem(os.environ, "FREELLMAPI_KEY", "test-key")
    def fail(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "slow", {"Retry-After": "74"}, None)
    monkeypatch.setattr(w.urllib.request, "urlopen", fail)
    parsed, _ = w.cloud_json("http://127.0.0.1:31415", "/v1/chat/completions", {}, 5)
    assert parsed == {"transport_error": {"type": "rate_limited", "retry_after": 74.0}}


def test_cloud_json_missing_key_never_raises_with_material(monkeypatch):
    from ai_os_decision import system_one_worker as w
    monkeypatch.delenv("FREELLMAPI_KEY", raising=False)
    parsed, _ = w.cloud_json("http://127.0.0.1:31415", "/v1/models", None, 5)
    assert parsed == {"transport_error": {"type": "missing_credentials"}}


def test_freellm_backend_disabled_by_default():
    from ai_os_decision.system_one_backends import FreeLLMBackend
    with pytest.raises(RuntimeError, match="explicit approval"):
        FreeLLMBackend("glm-5.3-flash", freellm_inv()).infer(request())
    with pytest.raises(RuntimeError, match="explicit approval"):
        FreeLLMBackend("glm-5.3-flash", freellm_inv(), enabled=True).infer(request())


def test_freellm_backend_rejects_undiscovered_and_non_loopback():
    from ai_os_decision.system_one_backends import FreeLLMBackend
    with pytest.raises(ValueError, match="discovered available"):
        FreeLLMBackend("invented-model", freellm_inv())
    with pytest.raises(ValueError, match="discovered available"):
        FreeLLMBackend("gpt-5.6-luna", freellm_inv("gpt-5.6-luna", completion=False))
    with pytest.raises(ValueError, match="loopback"):
        FreeLLMBackend("glm-5.3-flash", freellm_inv(), base_url="https://example.com")


def test_freellm_backend_records_quota_and_falls_back(monkeypatch):
    from ai_os_decision import system_one_backends as b
    quota = QuotaTracker(max_failures=5)
    backend = FreeLLMBackend("glm-5.3-flash", freellm_inv(), quota=quota, enabled=True, approved=True)
    monkeypatch.setattr(b, "run_worker", lambda *a, **k: {"transport_error": {"type": "rate_limited", "retry_after": 60}})
    r = BoundedRequest(DecisionState(text="Fix a bug"),
                       (DecisionQuestion("tool", "choice", "t", {"terminal": "s", "atlas": "r"}),),
                       {"tool": "terminal"},
                       CapabilitySnapshot((Capability("terminal", "tool", "c"), Capability("atlas", "tool", "c"),
                                           Capability("glm-5.3-flash", "model", "freellm:/v1/models:glm-5.3-flash", completion=True)),),
                       {"tool": "tool"}, action="read", minimum_risk="low")
    out = SystemOneRuntime(backend).decide(r)
    assert out.fallback_used and out.error == "RuntimeError"
    assert quota.state()["consecutive_failures"] == 1 and not quota.allow()


@pytest.mark.parametrize("text,blocked", [
    ("deploy with API_KEY=abc123 in env", True),
    ("here is the private key -----BEGIN RSA PRIVATE KEY-----", True),
    ("Authorization: Bearer tokens must rotate", True),
    ("my password is hunter2, please reset", True),
    ("Refactor this Python repository", False),
])
def test_privacy_screen_blocks_secrets(text, blocked):
    out = privacy_screen(text)
    assert (not out["allowed"]) == blocked
    assert "Refactor" not in out["reason"]


def test_privacy_screen_explicit_override():
    out = privacy_screen("API_KEY=abc", allow_private=True)
    assert out == {"allowed": True, "reason": "explicitly-authorized"}


def test_quota_tracker_circuit_and_recovery():
    q = QuotaTracker(max_failures=2, cooldown=60)
    assert q.allow()
    q.record({"type": "provider"})
    assert q.allow()
    q.record({"type": "rate_limited", "retry_after": 120})
    assert not q.allow()
    q.record({"type": "ok"})
    assert q.allow() and q.state()["consecutive_failures"] == 0


def test_cloud_eligible_gates():
    r = request()
    assert cloud_eligible(r, {}) == {"allowed": False, "reason": "cloud-disabled"}
    assert cloud_eligible(r, {"freellm": {"enabled": True}}, None, "other")["allowed"] is True
    assert cloud_eligible(r, {"freellm": {"enabled": True, "allowed_models": []}}, None, "other")["allowed"] is True
    assert cloud_eligible(r, {"freellm": {"enabled": True, "allowed_models": "[]"}}, None, "other")["allowed"] is True
    assert cloud_eligible(r, {"freellm": {"enabled": True, "allowed_models": ["glm"]}}, None, "other") == {
        "allowed": False, "reason": "model-not-allowlisted"}
    secret = request("set API_KEY=x then deploy")
    assert cloud_eligible(secret, {"freellm": {"enabled": True}})["reason"].startswith("sensitive-content")
    assert cloud_eligible(secret, {"freellm": {"enabled": True, "allow_private": True}})["allowed"] is True
    q = QuotaTracker()
    q.record({"type": "rate_limited", "retry_after": 300})
    assert cloud_eligible(r, {"freellm": {"enabled": True}}, q) == {"allowed": False, "reason": "quota-cooldown"}


def test_read_request_resolves_relative_images_without_weakening_validation(tmp_path):
    from ai_os_decision.system_one_io import read_request
    img = tmp_path / "tiny.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    payload = {"state": {"text": "Check the button", "environment": "dev"},
               "questions": [{"id": "UC15", "kind": "boolean", "instructions": "Is the button present?"}],
               "fallback_answers": {"UC15": True},
               "inventory": {"capabilities": []},
               "candidate_kinds": {}, "required_answers": {},
               "minimum_risk": "low", "action": "read",
               "approval_required": False, "denied": False,
               "images": ["tiny.png"]}
    req_path = tmp_path / "case.json"
    req_path.write_text(json.dumps(payload))
    req = read_request(req_path)
    assert list(req.images) == [str((tmp_path / "tiny.png").resolve())]
    bad = dict(payload, images=["missing.png"])
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="bounded local file"):
        read_request(bad_path)
