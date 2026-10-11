"""Hardening regressions: policy/config, cloud egress, circuit breaker,
shadow worker lifecycle, authority contract. Synthetic data only."""
import json
import threading
import time

import pytest

from ai_os_decision.engine import DecisionEngine
from ai_os_decision.models import DecisionQuestion, DecisionState, load_config
from ai_os_decision.policy import PolicyEngine, validate_policy_config
from ai_os_decision.shadow import SHADOW_MAX_WORKERS, ShadowRuntime, _SHADOW_SLOTS
from ai_os_decision.system_one import (
    BoundedRequest, Capability, CapabilitySnapshot, QuotaTracker, SystemOneRuntime,
)
from ai_os_decision.system_one_backends import (
    FreeLLMBackend, _WORKER_SEMAPHORE, run_worker, sanitize_cloud_payload,
    validate_cloud_payload,
)

SECRET = "sk-SYNTHETIC-0000"
CONFIG_EXAMPLE = "config.example.yaml"


def tool_request(text="Fix a bug", action="read", risk="low", extra=None,
                 environment="dev"):
    state = DecisionState(text=text, environment=environment,
                          repository="acme/app", branch="main",
                          permissions=("exec",),
                          available_agents=("coding_agent",),
                          available_tools=("terminal",),
                          extra=extra or {})
    return BoundedRequest(
        state,
        (DecisionQuestion("tool", "choice", "Select a tool",
                          {"terminal": "shell", "atlas": "repo"}),),
        {"tool": "terminal"},
        CapabilitySnapshot((Capability("terminal", "tool", "client-exposed"),
                            Capability("atlas", "tool", "client-exposed"))),
        {"tool": "tool"}, action=action, minimum_risk=risk,
    )


# ---- Phase 1: policy & configuration ----

def test_example_config_nested_rules_require_production_approval():
    cfg = load_config(CONFIG_EXAMPLE)
    rule = cfg["policy"]["approval_required"][0]
    assert rule == {"env": "production",
                    "actions": ["deploy", "delete", "drop", "migrate"]}
    policy = PolicyEngine(cfg)
    for action in ("deploy", "delete", "drop", "migrate"):
        assert policy.check(f"please {action} now", "production",
                            action)["approval_required"] is True
        assert policy.check("do it now", "production",
                            action)["approval_required"] is True


@pytest.mark.parametrize("bad", [
    {"approval_required": [{"env": "production", "actions": []}]},
    {"approval_required": [{"env": "  ", "actions": ["deploy"]}]},
    {"approval_required": [{"env": "production", "actions": ["deploy"],
                             "scope": "all"}]},              # unknown key
    {"deny_patterns": ["ok", ""]},
    {"version": ""},
])
def test_incomplete_security_rules_rejected(bad):
    with pytest.raises(ValueError):
        validate_policy_config(bad)


@pytest.mark.parametrize("bad", [
    {"approval_required": "production"},
    {"approval_required": ["deploy"]},
    {"approval_required": [{"env": "production"}]},   # actions missing
    {"approval_required": [{"actions": ["deploy"]}]},  # env missing
    {"deny_patterns": "rm -rf /"},
    {"fail_closed": "yes"},
    {"version": 2},
])
def test_malformed_types_rejected(bad):
    with pytest.raises(TypeError):
        validate_policy_config(bad)


def test_fail_closed_default_true():
    assert PolicyEngine({}).fail_closed is True
    assert PolicyEngine({"policy": {}}).fail_closed is True


# ---- Phase 2: cloud egress boundary ----

def test_cloud_payload_allowlist_drops_context_and_secrets():
    req = tool_request(extra={"api_key": SECRET,
                              "nested": {"password": "SYNTHETIC-pw"}})
    payload = sanitize_cloud_payload(req)
    assert set(payload) == {"state", "questions"}
    assert set(payload["state"]) <= {"text", "intent", "environment"}
    assert SECRET not in json.dumps(payload)
    assert "SYNTHETIC-pw" not in json.dumps(payload)


def test_cloud_payload_rejects_images_and_foreign_fields():
    import dataclasses
    req = dataclasses.replace(tool_request(), images=("some.png",))
    with pytest.raises(ValueError):
        sanitize_cloud_payload(req)
    clean = tool_request()
    questions = sanitize_cloud_payload(clean)["questions"]
    with pytest.raises(ValueError):
        validate_cloud_payload({"state": {"text": "x", "extra": {}},
                                "questions": questions})
    with pytest.raises(ValueError):
        validate_cloud_payload({"state": {"text": "x"}, "questions": {},
                                "capabilities": []})


def freellm_backend(**kw):
    inv = CapabilitySnapshot((
        Capability("terminal", "tool", "c"), Capability("atlas", "tool", "c"),
        Capability("glm-synth", "model", "freellm:/v1/models:glm-synth",
                   completion=True)))
    state = DecisionState(text="Fix a bug")
    req = BoundedRequest(
        state,
        (DecisionQuestion("tool", "choice", "Select a tool",
                          {"terminal": "shell", "atlas": "repo"}),),
        {"tool": "terminal"}, inv, {"tool": "tool"})
    args = {"enabled": True, "approved": True}
    args.update(kw)
    return FreeLLMBackend("glm-synth", inv, **args), req


def test_rejected_cloud_payload_zero_transport_calls(monkeypatch):
    import dataclasses
    backend, helper_req = freellm_backend()
    calls = []
    monkeypatch.setattr("ai_os_decision.system_one_backends.run_worker",
                        lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(
                            AssertionError("transport must not be called")))
    bad = dataclasses.replace(
        helper_req,
        state=dataclasses.replace(helper_req.state,
                                  text=f"deploy with api_key={SECRET} in env"))
    with pytest.raises(ValueError):
        backend.infer(bad)
    assert calls == []


def test_sanitized_payload_reaches_transport_without_secrets(monkeypatch):
    import dataclasses
    backend, helper_req = freellm_backend()
    seen = {}

    def fake_worker(python, arguments, payload, timeout):
        seen.update(payload)
        return {"answers": {"tool": {"type": "choice", "choice": "terminal",
                                     "confidence": 1.0,
                                     "probabilities": {"terminal": 1.0,
                                                       "atlas": 0.0}}},
                "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr("ai_os_decision.system_one_backends.run_worker", fake_worker)
    req = dataclasses.replace(
        helper_req,
        state=dataclasses.replace(helper_req.state,
                                  extra={"api_key": SECRET,
                                         "nested": {"password": "SYNTHETIC-pw"}}))
    out = backend.infer(req)
    assert out["answers"]["tool"]["choice"] == "terminal"
    assert set(seen) == {"state", "questions", "model", "base_url",
                         "json_mode", "timeout"}
    assert set(seen["state"]) <= {"text", "intent", "environment"}
    assert SECRET not in json.dumps(seen)


def test_worker_rejects_non_allowlisted_state():
    from ai_os_decision import system_one_worker as w
    with pytest.raises((TypeError, ValueError)):
        w.freellm({"model": "m", "base_url": "http://127.0.0.1:1", "timeout": 1,
                   "state": {"text": "x", "extra": {"api_key": SECRET}},
                   "questions": {}})


# ---- Phase 3: circuit breaker ----

class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_circuit_closed_open_half_open_single_probe():
    clock = FakeClock()
    q = QuotaTracker(max_failures=2, cooldown=60, clock=clock)
    assert q.allow() and q.state()["state"] == "closed"
    q.record({"type": "provider"})
    assert q.allow()
    q.record({"type": "provider"})
    assert not q.allow() and q.state()["state"] == "open"
    clock.now += 61  # cooldown elapsed -> exactly one probe
    assert q.allow() is True
    assert q.allow() is False  # second call waits for probe outcome
    q.record({"type": "provider"})  # failed probe re-opens
    assert not q.allow() and q.state()["state"] == "open"
    clock.now += 61
    assert q.allow() is True
    q.record({"type": "ok"})  # successful probe closes
    assert q.allow() and q.state()["state"] == "closed"
    assert q.state()["consecutive_failures"] == 0


def test_circuit_uses_monotonic_clock(monkeypatch):
    assert QuotaTracker()._clock is time.monotonic
    clock = FakeClock()
    q = QuotaTracker(max_failures=1, cooldown=60, clock=clock)
    q.record({"type": "provider"})
    assert not q.allow()
    monkeypatch.setattr(time, "time", lambda: clock.now + 10_000)
    assert not q.allow()  # wall-clock jump must not open/close/shorten


def test_circuit_rate_limited_honours_retry_after():
    clock = FakeClock()
    q = QuotaTracker(max_failures=5, cooldown=60, clock=clock)
    q.record({"type": "rate_limited", "retry_after": 120})
    assert not q.allow()
    clock.now += 61
    assert not q.allow()
    clock.now += 60
    assert q.allow() is True


def test_quotas_are_process_local_and_independent():
    a, b = QuotaTracker(), QuotaTracker()
    a.record({"type": "provider"})
    assert a.state()["consecutive_failures"] == 1
    assert b.state()["consecutive_failures"] == 0


# ---- Phase 3: shadow worker lifecycle ----

class SlowLaya:
    def __init__(self, delay=0.3):
        self.delay = delay
        self.calls = 0

    def decide(self, state, questions):
        self.calls += 1
        time.sleep(self.delay)
        raise AssertionError("must time out first")


def shadow_threads():
    return [t for t in threading.enumerate()
            if t.name.startswith("ai-os-shadow")]


def test_repeated_shadow_timeouts_stay_bounded():
    runtime = ShadowRuntime(model_dir=None, timeout_ms=50, config={})
    runtime.laya = SlowLaya()
    before = len(shadow_threads())
    for _ in range(6):
        out = runtime.handle("do work", "dev")
        assert out["shadow"]["fallback_used"] is True
        assert out["shadow"]["provider"] == "baseline"
        assert out["baseline"].provider == "rule"
    time.sleep(0.6)  # let timed-out observations drain
    assert len(shadow_threads()) - before <= SHADOW_MAX_WORKERS


def test_shadow_concurrency_limit_fails_closed_to_baseline():
    runtime = ShadowRuntime(model_dir=None, timeout_ms=50, config={})
    for _ in range(SHADOW_MAX_WORKERS):
        assert _SHADOW_SLOTS.acquire(blocking=False)
    try:
        out = runtime.handle("do work", "dev")
    finally:
        for _ in range(SHADOW_MAX_WORKERS):
            _SHADOW_SLOTS.release()
    assert out["shadow"]["fallback_used"] is True
    assert out["shadow"]["error"] == "RuntimeError"
    assert out["baseline"].provider == "rule"


def test_worker_overload_spawns_nothing(monkeypatch):
    monkeypatch.setattr("ai_os_decision.system_one_backends.subprocess.run",
                        lambda *a, **k: pytest.fail("must not spawn"))
    for _ in range(4):
        assert _WORKER_SEMAPHORE.acquire(blocking=False)
    try:
        with pytest.raises(RuntimeError, match="worker-overloaded"):
            run_worker("python", ["x"], {}, 5)
    finally:
        for _ in range(4):
            _WORKER_SEMAPHORE.release()


def test_worker_timeout_reaps_child_and_stays_usable(tmp_path):
    script = tmp_path / "blocked.py"
    script.write_text("import time; time.sleep(30)")
    import subprocess as sp
    import sys
    t0 = time.monotonic()
    with pytest.raises(sp.TimeoutExpired):
        run_worker(sys.executable, [str(script)], {}, 0.1)
    assert time.monotonic() - t0 < 5
    echo = tmp_path / "echo.py"
    echo.write_text("import json,sys; print(json.dumps({'ok': True}))")
    out = run_worker(sys.executable, [str(echo)], {}, 5)
    assert out == {"ok": True}


# ---- Phase 4: authority contract ----

class ContradictingModel:
    """Model says: other tool, low risk, no approval — all must lose."""
    name = "contradicting"

    def __init__(self, tool="atlas"):
        self.tool = tool

    def infer(self, req):
        return {"answers": {
                    "tool": {"type": "choice", "choice": self.tool,
                             "confidence": 1.0,
                             "probabilities": {"terminal": 0.0, "atlas": 1.0}},
                    "risk": {"type": "choice", "choice": "low",
                             "confidence": 1.0,
                             "probabilities": {"low": 1.0, "high": 0.0}},
                    "requires_human_approval": {"type": "noul", "noul": 0.0}},
                "usage": {"input_tokens": 1, "output_tokens": 1}}


def authority_request():
    inv = CapabilitySnapshot((Capability("terminal", "tool", "c"),
                              Capability("atlas", "tool", "c")))
    return BoundedRequest(
        DecisionState(text="routine cleanup", environment="dev"),
        (DecisionQuestion("tool", "choice", "Select a tool",
                          {"terminal": "shell", "atlas": "repo"}),
         DecisionQuestion("risk", "choice", "Risk?",
                          {"low": "low", "high": "high"}),
         DecisionQuestion("requires_human_approval", "boolean", "Approval?")),
        {"tool": "terminal", "risk": "high",
         "requires_human_approval": True},
        inv, {"tool": "tool"},
        required_answers={"tool": "terminal"},
        action="deploy", minimum_risk="high")


def test_contradicting_model_cannot_lower_authority():
    req = authority_request()
    runtime = SystemOneRuntime(ContradictingModel())
    rec = runtime.decide(req)
    assert rec.answers["tool"].value == "terminal"  # required wins
    assert rec.risk == "high"                        # floor wins
    assert rec.requires_human_approval is True       # latch wins
    auth = runtime.authoritative(req)
    assert auth.decision_source == "deterministic"
    assert auth.answers["tool"].value == "terminal"
    assert (auth.risk, auth.requires_human_approval) == ("high", True)


def test_shadow_authoritative_never_reflects_model():
    runtime = SystemOneRuntime(ContradictingModel())
    req = authority_request()
    obs = runtime.shadow(req)
    auth = runtime.authoritative(req)
    assert obs.authoritative.answers["tool"].value == "terminal"
    assert obs.authoritative.risk == "high"
    assert obs.authoritative.decision_source == "deterministic"
    assert {k: a.value for k, a in obs.authoritative.answers.items()} == \
           {k: a.value for k, a in auth.answers.items()}
    assert obs.observation.decision_source == "contradicting"
    assert "terminal" not in json.dumps(obs.metadata())


def test_engine_observe_keeps_authority_and_recommend_is_advisory():
    engine = DecisionEngine({})
    req = authority_request()
    observed = engine.observe(req, ContradictingModel())
    assert observed.authoritative.decision_source == "deterministic"
    assert observed.authoritative.answers["tool"].value == "terminal"
    rec = engine.recommend(req, ContradictingModel())
    assert rec.decision_source == "contradicting"
    assert rec.answers["tool"].value == "terminal"
    assert rec.risk == "high" and rec.requires_human_approval is True


def test_legacy_deny_path_still_enforced():
    cfg = {"policy": {"deny_patterns": ["delete production database"],
                      "approval_required": [], "fail_closed": True},
           "decision_engine": {"provider": "rule"}}
    engine = DecisionEngine(cfg)
    res = engine.decide(DecisionState(text="delete production database",
                                      environment="production"),
                        [DecisionQuestion("needs_human_approval", "boolean",
                                          "Need approval?")])
    assert res.policy_override is True
    assert res.answers["needs_human_approval"].value is True
