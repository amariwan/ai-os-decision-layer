"""Bounded advisory model selection. Hard filters run before local Laya.

Only rows the gateway reports as executable (execution_status "ready") become
candidates: /v1/models also advertises router slots (auto/fusion/claude-*)
without that signal, and the gateway rejects those IDs at inference time
(model_not_found). Free-only enforcement is response-side (AUTO_FREE): rows
expose no pricing, so the caller verifies observed usage cost before accepting
a model.
"""
from __future__ import annotations

import json
import math

from ai_os_decision.models import DecisionQuestion, DecisionState
from ai_os_decision.policy import PolicyEngine
from ai_os_decision.system_one import SystemOneRuntime
from ai_os_decision.system_one_backends import sanitize_cloud_payload, validate_cloud_payload


def cloud_request_gate(request, config):
    request.validate()
    try:
        payload = sanitize_cloud_payload(request)
        wire = validate_cloud_payload(payload, allow_private=False)
    except (ValueError, TypeError):
        return "private_payload"
    policy = PolicyEngine(config)
    check = policy.check(wire.decode(), request.state.environment, request.action)
    baseline = SystemOneRuntime(config=config).authoritative(request)
    if (not policy.fail_closed or baseline.denied or baseline.requires_human_approval
            or check["denied"] or check["approval_required"]):
        return "policy_or_approval"
    return None


def select_model(request, config, rows, laya, *, free_only=False):
    mode = "auto_free" if free_only is True else "auto"
    result = {"model": None, "status": "blocked", "source": "policy",
              "fallback_used": False, "pricing": "unknown",
              "mode": mode, "candidates": []}
    reason = cloud_request_gate(request, config)
    cfg = config.get("freellm", {})
    if reason or any(cfg.get(k) is not True for k in ("enabled", "auto_enabled")):
        return {**result, "reason": reason or "auto_disabled"}
    allow = cfg.get("allowed_models", [])
    if allow == "[]":  # Existing minimal YAML loader's empty-list representation.
        allow = []
    if not isinstance(allow, list) or any(not isinstance(x, str) for x in allow):
        return {**result, "reason": "invalid_allowlist"}
    needed = len(json.dumps(sanitize_cloud_payload(request), ensure_ascii=True).encode()) + 2048
    eligible = {}
    for row in rows:
        mid = row.get("id")
        context = row.get("context_length", row.get("context_window"))
        if (row.get("available") is not True or row.get("execution_status") != "ready"
                or not isinstance(mid, str) or not 1 <= len(mid) <= 256
                or mid.lower() in {"auto", "fusion"} or "embed" in mid.lower()
                or (allow and mid not in allow) or type(context) is not int or context < needed):
            continue
        # Model IDs are external data too; credentials/policy patterns never enter Laya.
        try:
            validate_cloud_payload(sanitize_cloud_payload(request), model=mid)
        except (ValueError, TypeError):
            continue
        check = PolicyEngine(config).check(mid, request.state.environment, request.action)
        if check["denied"] or check["approval_required"]:
            continue
        eligible[mid] = f"context {context}; quality/price unknown"
    options = dict(sorted(eligible.items())[:4])
    result.update(candidate_count=len(eligible), shortlist_count=len(options))
    if not options:
        return {**result, "reason": "no_eligible_model"}
    selected = next(iter(options))
    if len(options) == 1:
        return {**result, "model": selected, "candidates": [selected],
                "status": "ready", "source": "single_eligible"}
    try:
        # No arbitrary truncation: the installed engine enforces its context window.
        if len(request.state.text) > 2000:
            raise ValueError("routing_context_too_large")
        answer = laya.decide(DecisionState(text=request.state.text, actor_type="",
                                           extra={"_require_full_context": True}),
                             [DecisionQuestion("model", "choice", "Choose a suitable model for this task.", options)])
        choice = answer.answers["model"]
        value = choice.value
        if (answer.provider != "laya" or set(answer.answers) != {"model"}
                or choice.question_id != "model" or choice.kind != "choice"
                or type(choice.confidence) not in (int, float) or not math.isfinite(choice.confidence)
                or not 0 <= choice.confidence <= 1
                or value not in options or answer.fallback_used):
            raise ValueError("invalid_laya_choice")
        ordered = [value] + [mid for mid in options if mid != value]
        return {**result, "model": value, "candidates": ordered,
                "status": "ready", "source": "laya"}
    except Exception as exc:
        return {**result, "model": selected, "candidates": list(options),
                "status": "ready", "source": "deterministic",
                "fallback_used": True, "error": type(exc).__name__}
