"""Rule-based fallback. Deterministic, no model. Fail closed on risk."""
from __future__ import annotations

import time
import uuid

from ai_os_decision.models import DecisionAnswer, DecisionQuestion, DecisionResult, DecisionState


class RuleBasedDecisionEngine:
    name = "rule"

    def decide(self, state: DecisionState, questions: list[DecisionQuestion]) -> DecisionResult:
        t0 = time.perf_counter()
        answers: dict = {}
        text = (state.text or "").lower()
        prod = (state.environment or "").lower() == "production"
        for q in questions:
            q.validate()
            if q.kind == "boolean":
                val = _bool_default(q.id, text, prod)
                answers[q.id] = DecisionAnswer(q.id, "boolean", val, 0.6 if val else 0.7)
            elif q.kind == "choice":
                key = _choice_default(q, text)
                answers[q.id] = DecisionAnswer(q.id, "choice", key, 0.55, {k: (0.55 if k == key else round(0.45 / max(1, len(q.options) - 1), 4)) for k in q.options})
            else:  # score
                n = max(2, len(q.criteria))
                s = _score_default(q.id, text, prod, n)
                answers[q.id] = DecisionAnswer(q.id, "score", s, 0.5)
        ms = (time.perf_counter() - t0) * 1000
        return DecisionResult(answers, self.name, ms, True, False, f"rule-{uuid.uuid4().hex[:8]}")


def _bool_default(qid: str, text: str, prod: bool) -> bool:
    q = qid.lower()
    if "human_approval" in q or "human" in q:
        return prod or any(w in text for w in ("production", "delete", "drop", "deploy", "migrate"))
    if "reasoning" in q:
        return any(w in text for w in ("why", "debug", "research", "complex", "analyze", "refactor"))
    if "verification" in q or "verify" in q:
        return prod or "deploy" in text
    if "escalat" in q:
        return prod
    return False


def _choice_default(q: DecisionQuestion, text: str) -> str:
    keys = list(q.options.keys())
    scored = []
    for k in keys:
        kl = k.lower()
        hit = kl in text
        desc = str(q.options[k] or "").lower()
        dhit = any(w in text for w in desc.split(",") if w.strip()) if desc else False
        scored.append((2 if hit else (1 if dhit else 0), k))
    scored.sort(reverse=True)
    return scored[0][1]


def _score_default(qid: str, text: str, prod: bool, n: int) -> float:
    q = qid.lower()
    base = 1.0 if prod else 0.0
    if "risk" in q:
        extra = sum(w in text for w in ("delete", "drop", "production", "database", "deploy")) * 0.5
        return round(min(n - 1, base + extra + 0.5), 2)
    if "priorit" in q or "urgent" in q:
        extra = sum(w in text for w in ("urgent", "asap", "blocking", "outage", "critical"))
        return round(min(n - 1, base + extra), 2)
    return round(base, 2)
