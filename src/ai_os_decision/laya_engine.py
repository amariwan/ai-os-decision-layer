"""Laya adapter. Thin mapping only; no business logic here.

Uses the local RLAgent checkpoint (rl_agent_api.py layout) when available,
else raises so the caller can fall back. Never fail open: caller decides.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

from ai_os_decision.models import DecisionAnswer, DecisionQuestion, DecisionResult, DecisionState

_LAYA_DIR = os.environ.get("LAYA_MODEL_DIR", "models/laya")


class LayaUnavailable(Exception):
    pass


def to_laya_questions(questions: list[DecisionQuestion]) -> dict:
    """DecisionQuestion -> Jev/Laya request shape (choice|score|noul)."""
    out: dict = {}
    for q in questions:
        q.validate()
        if q.kind == "choice":
            out[q.id] = {
                "type": "choice",
                "instructions": q.instructions,
                "criteria": {k: (v or "") for k, v in q.options.items()},
            }
        elif q.kind == "score":
            out[q.id] = {"type": "score", "instructions": q.instructions, "criteria": list(q.criteria)}
        else:  # boolean -> noul
            out[q.id] = {"type": "noul", "instructions": q.instructions}
    return out


def from_laya_answers(raw: dict) -> dict:
    """Laya response -> DecisionAnswer. Confidence kept as MODEL SCORE."""
    answers: dict = {}
    for qid, a in (raw.get("answers") or {}).items():
        t = a.get("type")
        if t == "choice":
            probs = {str(k): float(v) for k, v in (a.get("probabilities") or {}).items()}
            answers[qid] = DecisionAnswer(qid, "choice", a.get("choice"), float(a.get("confidence", 0.0)), probs)
        elif t == "score":
            probs = {str(k): float(v) for k, v in (a.get("probabilities") or {}).items()}
            answers[qid] = DecisionAnswer(qid, "score", float(a.get("score", 0.0)), float(a.get("confidence", 0.0)), probs)
        elif t == "noul":
            p = float(a.get("noul", 0.0))
            answers[qid] = DecisionAnswer(qid, "boolean", bool(p >= 0.5), round(max(p, 1 - p), 4), {"true": p, "false": round(1 - p, 4)})
        else:
            raise ValueError(f"unknown laya answer type for {qid}: {t}")
    return answers


class LayaDecisionEngine:
    name = "laya"

    def __init__(self, model_dir: str | None = None, timeout_ms: int = 2000):
        self.model_dir = model_dir or os.environ.get("LAYA_MODEL_DIR", _LAYA_DIR)
        self.timeout_ms = timeout_ms
        self._agent = None

    def _load(self):
        if self._agent is not None:
            return self._agent
        if self.model_dir not in sys.path:
            sys.path.insert(0, self.model_dir)
        try:
            from rl_agent_api import RLAgent  # type: ignore
        except Exception as e:  # pragma: no cover
            raise LayaUnavailable(f"rl_agent import failed: {e}")
        try:
            self._agent = RLAgent(self.model_dir)
        except Exception as e:
            raise LayaUnavailable(f"laya checkpoint load failed: {e}")
        return self._agent

    def decide(self, state: DecisionState, questions: list[DecisionQuestion]) -> DecisionResult:
        t0 = time.perf_counter()
        lq = to_laya_questions(questions)
        agent = self._load()
        try:
            raw = agent.system_one(state.to_laya_state(), lq)
        except Exception as e:
            raise LayaUnavailable(str(e))
        answers = from_laya_answers(raw)
        if set(answers) != {q.id for q in questions}:
            raise LayaUnavailable("incomplete laya answers")
        ms = (time.perf_counter() - t0) * 1000
        return DecisionResult(answers, self.name, ms, False, False, f"laya-{uuid.uuid4().hex[:8]}", {"model": raw.get("model", "")})

    def health(self) -> str:
        """Healthy only after a real minimal inference, never on file presence alone."""
        question = DecisionQuestion(
            "health", "choice", "Classify this health check.", {"system": "health check", "unknown": "other"}
        )
        try:
            self.decide(DecisionState(text="health check"), [question])
        except LayaUnavailable:
            return "unavailable"
        return "healthy"
