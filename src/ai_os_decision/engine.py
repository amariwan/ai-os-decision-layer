"""Orchestration: Policy pre-check > engine > confidence gate > safe fallback.

Order (never inverted):
  Hard Policy > Security/Permission > Laya decision > LLM recommendation.
"""
from __future__ import annotations

import time
import uuid

from ai_os_decision.laya_engine import LayaDecisionEngine, LayaUnavailable
from ai_os_decision.models import (
    ConfidenceGate,
    DecisionAnswer,
    DecisionQuestion,
    DecisionResult,
    DecisionState,
)
from ai_os_decision.policy import PolicyEngine
from ai_os_decision.rule_engine import RuleBasedDecisionEngine


class DecisionEngine:
    """Minimal DecisionEngine abstraction (Protocol-shaped, stdlib only)."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        de = self.config.get("decision_engine", {})
        to = de.get("timeouts", {})
        self.policy = PolicyEngine(self.config)
        conf = de.get("confidence", {}) or {}
        self.gate = ConfidenceGate(
            float(conf.get("auto_execute", 0.90)), float(conf.get("verify", 0.70))
        )
        self.laya = LayaDecisionEngine(
            ((self.config.get("laya", {}) or {}).get("model_dir")) or None,
            int(to.get("laya_ms", 2000)),
        )
        self.rules = RuleBasedDecisionEngine()
        self.provider = str(de.get("provider", "laya"))

    def decide(self, state: DecisionState, questions: list[DecisionQuestion]) -> DecisionResult:
        t0 = time.perf_counter()
        decision_id = f"dec-{uuid.uuid4().hex[:8]}"
        pol = self.policy.check(state.text, state.environment)
        # Hard deny: fail closed immediately, mark override.
        if pol["denied"]:
            answers = self._forced_answers(questions, high_risk=True)
            ms = (time.perf_counter() - t0) * 1000
            return DecisionResult(answers, "rule", ms, True, True, decision_id)

        try:
            res = self._primary(state, questions)
        except Exception:
            res = self.rules.decide(state, questions)
            res = DecisionResult(res.answers, res.provider, res.latency_ms, True, False, decision_id)
            answers = self._apply_policy_approval(res.answers, pol, questions, override=True)
            return DecisionResult(answers, res.provider, (time.perf_counter() - t0) * 1000, True, bool(pol["approval_required"]), decision_id)

        answers = self._apply_policy_approval(res.answers, pol, questions, override=False)
        override = bool(pol["approval_required"])
        ms = (time.perf_counter() - t0) * 1000
        return DecisionResult(answers, res.provider, ms, res.fallback_used, override, decision_id, res.raw_routing)

    def gate_action(self, confidence: float) -> str:
        return self.gate.route(confidence)

    def recommend(self, request, backend=None):
        """Explicit bounded System-One recommendation; never executes a route.

        Existing decide()/Laya behavior stays intact. Heavy dependencies are not
        imported unless an approved d1 worker is explicitly requested.
        """
        return self._system_one_runtime(backend).decide(request)

    def observe(self, request, backend=None):
        """Return the deterministic authority separately from a shadow observation."""
        return self._system_one_runtime(backend).shadow(request)

    def _system_one_runtime(self, backend):
        from ai_os_decision.system_one import SystemOneRuntime
        existing = getattr(self, "_system_one", None)
        if existing is None or getattr(self, "_system_one_backend", None) is not backend:
            self._system_one = SystemOneRuntime(backend, self.config)
            self._system_one_backend = backend
        return self._system_one

    def _primary(self, state: DecisionState, questions: list[DecisionQuestion]) -> DecisionResult:
        if self.provider == "rule":
            return self.rules.decide(state, questions)
        if self.provider == "llm-stub":
            raise LayaUnavailable("llm provider not configured")
        return self.laya.decide(state, questions)  # default: laya

    @staticmethod
    def _forced_answers(questions: list[DecisionQuestion], high_risk: bool) -> dict:
        out: dict = {}
        for q in questions:
            qid = q.id.lower()
            if q.kind == "boolean":
                if "approval" in qid or "human" in qid:
                    out[q.id] = DecisionAnswer(q.id, "boolean", True, 1.0)
                elif "escalat" in qid or "verif" in qid:
                    out[q.id] = DecisionAnswer(q.id, "boolean", True, 1.0)
                elif "reasoning" in qid:
                    out[q.id] = DecisionAnswer(q.id, "boolean", True, 1.0)
                else:
                    out[q.id] = DecisionAnswer(q.id, "boolean", False, 1.0)
            elif q.kind == "choice":
                key = _safest_choice(q)
                out[q.id] = DecisionAnswer(q.id, "choice", key, 1.0, {k: (1.0 if k == key else 0.0) for k in q.options})
            else:
                out[q.id] = DecisionAnswer(q.id, "score", float(len(q.criteria) - 1) if high_risk and "risk" in qid else 0.0, 1.0)
        return out

    @staticmethod
    def _apply_policy_approval(answers: dict, pol: dict, questions: list[DecisionQuestion], override: bool) -> dict:
        if not pol.get("approval_required"):
            return answers
        out = dict(answers)
        for q in questions:
            qid = q.id.lower()
            if q.kind == "boolean" and ("approval" in qid or "human" in qid):
                out[q.id] = DecisionAnswer(q.id, "boolean", True, 1.0)
        # policy override flag handled by caller; mark via override param
        return out


def _safest_choice(q: DecisionQuestion) -> str:
    keys = list(q.options.keys())
    kl = [k.lower() for k in keys]
    for pref in ("human", "escalat", "direct", "other", "manual"):
        for k, l in zip(keys, kl):
            if pref in l:
                return k
    return keys[0]
