"""Shadow mode: run deterministic baseline + Laya side by side."""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from ai_os_decision.laya_engine import LayaDecisionEngine
from ai_os_decision.models import DecisionAnswer, DecisionQuestion, DecisionResult, DecisionState
from ai_os_decision.policy import PolicyEngine


SHADOW_QUESTIONS = [
    DecisionQuestion(
        "intent",
        "choice",
        "Which intent best describes this request?",
        {
            "coding": "code repository refactor bug test",
            "research": "research web compare latest find",
            "automation": "workflow automation schedule n8n",
            "knowledge": "knowledge brain context remember",
            "system": "system health status configuration",
            "unknown": "everything else",
        },
    ),
    DecisionQuestion(
        "agent_route",
        "choice",
        "Which agent route should handle this request?",
        {
            "coding_agent": "code repository refactor bug test",
            "research_agent": "research web compare latest find",
            "workflow_agent": "workflow automation schedule n8n",
            "direct": "simple answer knowledge system unknown",
        },
    ),
    DecisionQuestion(
        "needs_reasoning",
        "boolean",
        "Does this request require substantial reasoning?",
    ),
]


class ShadowRuntime:
    """Run baseline as authority and Laya as an optional, isolated observer."""

    def __init__(self, model_dir: str | None = None, timeout_ms: int = 150, config: dict | None = None):
        self.laya = LayaDecisionEngine(model_dir, timeout_ms)
        self.timeout_ms = timeout_ms
        self.policy = PolicyEngine(config or {})

    def handle(self, text: str, environment: str = "dev", log_path: str | None = None) -> dict:
        state = DecisionState(text=text, environment=environment)
        policy = self.policy.check(text, environment)
        baseline_result = deterministic_baseline(state)
        started = time.perf_counter()
        shadow = {
            q.id: {
                "baseline": baseline_result.answers[q.id].value,
                "laya": None,
                "confidence": None,
                "agreement": None,
            }
            for q in SHADOW_QUESTIONS
        }
        error = None
        fallback_used = False
        provider = "laya"
        try:
            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(self.laya.decide, state, SHADOW_QUESTIONS)
            try:
                laya_result = future.result(timeout=self.timeout_ms / 1000)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            for q in SHADOW_QUESTIONS:
                answer = laya_result.answers[q.id]
                shadow[q.id].update(
                    laya=answer.value,
                    confidence=answer.confidence,
                    agreement=answer.value == baseline_result.answers[q.id].value,
                )
        except Exception as exc:  # shadow never changes the main path
            error = type(exc).__name__
            fallback_used = True
            provider = "baseline"
        entry = {
            "decision_id": f"shadow-{int(time.time_ns())}",
            "request_id": "shadow-runtime",
            "timestamp": datetime.now(UTC).isoformat(),
            "decision_type": "intent|agent_route|needs_reasoning",
            "baseline": {key: value["baseline"] for key, value in shadow.items()},
            "laya": {key: value["laya"] for key, value in shadow.items()},
            "details": shadow,
            "confidence": {key: value["confidence"] for key, value in shadow.items()},
            "agreement": {key: value["agreement"] for key, value in shadow.items()},
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "provider": provider,
            "fallback_used": fallback_used,
            "policy_override": bool(policy["denied"] or policy["approval_required"]),
            "policy_reasons": policy["reasons"],
            "error": error,
        }
        if log_path:
            log_shadow(entry, log_path)
        return {"baseline": baseline_result, "shadow": entry}


def deterministic_baseline(state: DecisionState) -> DecisionResult:
    """Small explainable baseline used only as the shadow comparison point."""
    text = state.text.lower()
    if any(word in text for word in ("python", "code", "repository", "refactor", "bug", "test", "debug")):
        intent, route = "coding", "coding_agent"
    elif any(word in text for word in ("research", "web", "compare", "latest", "find")):
        intent, route = "research", "research_agent"
    elif any(word in text for word in ("workflow", "automation", "schedule", "n8n", "pipeline")):
        intent, route = "automation", "workflow_agent"
    elif any(word in text for word in ("knowledge", "brain", "context", "remember")):
        intent, route = "knowledge", "direct"
    elif any(word in text for word in ("system", "health", "status", "config")):
        intent, route = "system", "direct"
    else:
        intent, route = "unknown", "direct"
    reasoning = intent in {"coding", "research", "automation"}
    answers = {
        "intent": DecisionAnswer("intent", "choice", intent, 1.0),
        "agent_route": DecisionAnswer("agent_route", "choice", route, 1.0),
        "needs_reasoning": DecisionAnswer("needs_reasoning", "boolean", reasoning, 1.0),
    }
    return DecisionResult(answers, "rule", 0.0, False, False, f"baseline-{int(time.time_ns())}")


def log_shadow(existing: dict, laya: str | None = None, match: bool | None = None,
               log_path: str | None = None, decision_id: str = "") -> None:
    """Write sanitized JSONL. The legacy scalar signature remains supported."""
    if log_path is None:
        log_path = str(laya)
        laya = None
        match = None
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    entry = existing if isinstance(existing, dict) else {
        "decision_id": decision_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "existing": existing,
        "laya": laya,
        "match": match,
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
