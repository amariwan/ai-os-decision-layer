"""Observed audit failures; synthetic payloads, no cloud requests."""
import dataclasses
import threading

import pytest

from ai_os_decision.models import DecisionQuestion, DecisionState
from ai_os_decision.shadow import SHADOW_MAX_WORKERS, ShadowRuntime
from ai_os_decision.system_one import BoundedRequest, Capability, CapabilitySnapshot, QuotaTracker
from ai_os_decision.system_one_backends import FreeLLMBackend


def cloud_request(field):
    marker = "Bearer SYNTHETIC_AUDIT_ONLY"
    state = DecisionState(text="routine task")
    question = DecisionQuestion("tool", "choice", "Select", {"shell": "shell", "repo": "repo"})
    if field in {"intent", "environment", "text"}:
        state = dataclasses.replace(state, **{field: marker})
    elif field == "instructions":
        question = dataclasses.replace(question, instructions=marker)
    elif field == "options":
        question = dataclasses.replace(question, options={"shell": marker, "repo": "repo"})
    elif field == "criteria":
        question = DecisionQuestion("tool", "score", "Select", criteria=["safe", marker])
    inventory = CapabilitySnapshot((Capability("cloud-test", "model", "freellm:test", completion=True),))
    request = BoundedRequest(state, (question,), {"tool": 0.0 if field == "criteria" else "shell"}, inventory)
    request.validate()
    return request, FreeLLMBackend("cloud-test", inventory, enabled=True, approved=True)


@pytest.mark.parametrize("field", ["text", "intent", "environment", "instructions", "options", "criteria"])
def test_all_cloud_transfer_fields_reject_sensitive_content_before_transport(field, monkeypatch):
    request, backend = cloud_request(field)
    monkeypatch.setattr("ai_os_decision.system_one_backends.run_worker",
                        lambda *a: pytest.fail("rejected payload reached transport"))
    with pytest.raises(ValueError, match="sensitive-content"):
        backend.infer(request)


def test_worker_rechecks_sensitive_questions_before_transport(monkeypatch):
    from ai_os_decision.system_one_backends import sanitize_cloud_payload
    from ai_os_decision.system_one_worker import freellm
    request, _ = cloud_request("instructions")
    payload = sanitize_cloud_payload(request)
    payload.update(model="cloud-test", base_url="http://127.0.0.1:1", timeout=1)
    monkeypatch.setattr("ai_os_decision.system_one_worker.cloud_json",
                        lambda *a: pytest.fail("worker forwarded sensitive content"))
    with pytest.raises(ValueError, match="sensitive-content"):
        freellm(payload)


def test_model_identifier_is_screened_at_worker_boundary(monkeypatch):
    from ai_os_decision.system_one_backends import sanitize_cloud_payload
    from ai_os_decision.system_one_worker import freellm
    request, _ = cloud_request("ordinary")
    payload = sanitize_cloud_payload(request)
    payload.update(model="Bearer SYNTHETIC_AUDIT_ONLY", base_url="http://127.0.0.1:1", timeout=1)
    monkeypatch.setattr("ai_os_decision.system_one_worker.cloud_json",
                        lambda *a: pytest.fail("sensitive model ID reached transport"))
    with pytest.raises(ValueError, match="sensitive-content"):
        freellm(payload)


def test_backend_rejects_string_privacy_override():
    request, _ = cloud_request("ordinary")
    with pytest.raises(TypeError, match="allow_private"):
        FreeLLMBackend("cloud-test", request.inventory, allow_private="false")


@pytest.mark.parametrize("field", ["enabled", "allow_private"])
def test_quoted_boolean_config_never_authorizes_cloud(field):
    from ai_os_decision.system_one import cloud_eligible
    request, _ = cloud_request("ordinary")
    config = {"freellm": {"enabled": True, "allow_private": False}}
    config["freellm"][field] = "false"
    assert cloud_eligible(request, config) == {"allowed": False, "reason": "invalid-cloud-config"}


def test_status_reads_do_not_reserve_the_half_open_probe():
    clock = [100.0]
    quota = QuotaTracker(max_failures=1, cooldown=1, clock=lambda: clock[0])
    quota.record({"type": "provider"})
    clock[0] = 102.0
    for _ in range(3):
        quota.state()
    assert quota.allow() is True
    assert quota.allow() is False
    quota.record({"type": "ok"})
    assert quota.allow() is True


def test_shadow_timeouts_do_not_admit_more_work_while_workers_are_blocked():
    release = threading.Event()
    all_started = threading.Event()
    calls = []

    class BlockedLaya:
        def decide(self, *args):
            calls.append(1)
            if len(calls) == SHADOW_MAX_WORKERS:
                all_started.set()
            release.wait(5)
            raise RuntimeError("synthetic")

    runtime = ShadowRuntime(timeout_ms=20, config={})
    runtime.laya = BlockedLaya()
    try:
        for _ in range(SHADOW_MAX_WORKERS):
            runtime.handle("routine task")
        assert all_started.wait(1)
        outputs = [runtime.handle("routine task") for _ in range(6)]
        assert all(out["shadow"]["error"] == "RuntimeError" for out in outputs)
    finally:
        release.set()
