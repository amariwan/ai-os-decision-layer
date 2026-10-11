"""Unified task preparation. Policy and rules decide; Laya observes locally.

Returns a reviewable plan, never executes tools or writes Brain memory.
"""
from __future__ import annotations

from ai_os_decision.shadow import ShadowRuntime


def prepare_task(text: str, environment: str, runtime: ShadowRuntime, action: str = "") -> dict:
    out = {"schema": "ai-os-task/v1", "status": "invalid_request", "route": None,
           "policy": None, "execution_enabled": False,
           "laya": {"attempted": False, "status": "not_attempted", "fallback_used": False,
                    "observation": {}}}
    if (not isinstance(text, str) or not text.strip() or len(text) > 8192
            or not isinstance(environment, str) or not environment.strip() or len(environment) > 128
            or not isinstance(action, str) or len(action) > 64):
        return out
    policy = runtime.policy.check(text, environment, action)
    out["policy"] = policy
    if policy["denied"]:
        out["status"] = "denied"
        out["laya"]["status"] = "skipped_policy"
        return out
    result = runtime.handle(text, environment)
    baseline, shadow = result["baseline"], result["shadow"]
    out["status"] = "approval_required" if policy["approval_required"] else "ready"
    out["decision_id"] = baseline.decision_id
    out["route"] = {"intent": baseline.answers["intent"].value,
                    "agent": baseline.answers["agent_route"].value,
                    "needs_reasoning": baseline.answers["needs_reasoning"].value,
                    "source": "deterministic"}
    error = shadow["error"]
    status = "ok" if not shadow["fallback_used"] else (
        "timeout" if error in {"TimeoutError", "TimeoutExpired"} else "unavailable")
    out["laya"] = {"attempted": True, "status": status, "fallback_used": shadow["fallback_used"],
                   "error": error, "latency_ms": shadow["latency_ms"],
                   "observation": {k: value["laya"] for k, value in shadow["details"].items()
                                   if value["laya"] is not None}}
    return out
