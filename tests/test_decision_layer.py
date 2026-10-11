"""Unit tests: mapping, gate, fallback, policy override, invalid, timeout. No model weights."""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_os_decision import engine as eng
from ai_os_decision.laya_engine import from_laya_answers, to_laya_questions, LayaUnavailable
from ai_os_decision.models import ConfidenceGate, DecisionQuestion, DecisionState, load_config
from ai_os_decision.policy import PolicyEngine


def q_choice():
    return DecisionQuestion("route", "choice", "Which agent?", {"coding_agent": "code", "devops_agent": "infra", "direct": "other"})


def q_bool(suffix="needs_human_approval"):
    return DecisionQuestion(suffix, "boolean", "Need approval?")


def test_choice_mapping():
    lq = to_laya_questions([q_choice()])
    assert lq["route"]["type"] == "choice"
    raw = {"answers": {"route": {"type": "choice", "choice": "devops_agent",
            "probabilities": {"coding_agent": 0.1, "devops_agent": 0.8, "direct": 0.1}, "confidence": 0.72}}}
    ans = from_laya_answers(raw)
    assert ans["route"].value == "devops_agent"
    assert ans["route"].confidence == 0.72


def test_boolean_mapping_noul():
    raw = {"answers": {"needs_human_approval": {"type": "noul", "noul": 0.91}}}
    ans = from_laya_answers(raw)
    assert ans["needs_human_approval"].value is True
    assert ans["needs_human_approval"].confidence == 0.91


def test_score_mapping():
    raw = {"answers": {"risk": {"type": "score", "score": 1.7, "confidence": 0.66,
            "probabilities": {"0": 0.1, "1": 0.3, "2": 0.6}}}}
    ans = from_laya_answers(raw)
    assert ans["risk"].value == 1.7


def test_invalid_question_kind():
    try:
        to_laya_questions([DecisionQuestion("x", "magic", "?")])
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_invalid_laya_answer_type():
    try:
        from_laya_answers({"answers": {"x": {"type": "telepathy"}}})
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_gate_thresholds():
    g = ConfidenceGate(0.90, 0.70)
    assert g.route(0.95) == "execute"
    assert g.route(0.75) == "verify"
    assert g.route(0.5) == "escalate"


def test_policy_deny_forces_approval():
    cfg = {"policy": {"version": "t", "deny_patterns": ["delete production database"], "approval_required": [], "fail_closed": True}}
    p = PolicyEngine(cfg)
    r = p.check("please delete production database now", "production")
    assert r["denied"] is True


def test_policy_never_overridden_by_laya():
    cfg = {"policy": {"version": "t", "deny_patterns": ["delete production database"],
                      "approval_required": [{"env": "production", "actions": ["deploy"]}], "fail_closed": True},
           "decision_engine": {"provider": "rule", "confidence": {"auto_execute": 0.9, "verify": 0.7}}}
    e = eng.DecisionEngine(cfg)
    st = DecisionState(text="delete production database", environment="production")
    qs = [q_bool(), DecisionQuestion("risk", "score", "Risk?", criteria=["low", "med", "high"])]
    res = e.decide(st, qs)
    assert res.policy_override is True
    assert res.answers["needs_human_approval"].value is True


def test_fallback_on_laya_unavailable():
    cfg = {"policy": {"version": "t"}, "decision_engine": {"provider": "laya"}}
    e = eng.DecisionEngine(cfg)
    e.laya.decide = lambda s, q: (_ for _ in ()).throw(LayaUnavailable("down"))
    st = DecisionState(text="route this ticket", environment="dev")
    res = e.decide(st, [q_choice()])
    assert res.fallback_used is True
    assert res.provider == "rule"


def test_config_loader():
    cfg = load_config(os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
    assert cfg["decision_engine"]["confidence"]["auto_execute"] == 0.90
    assert cfg["policy"]["fail_closed"] is True


class TestCase(unittest.TestCase):
    def test_all(self):
        for fn in [test_choice_mapping, test_boolean_mapping_noul, test_score_mapping,
                   test_invalid_question_kind, test_invalid_laya_answer_type,
                   test_gate_thresholds, test_policy_deny_forces_approval,
                   test_policy_never_overridden_by_laya, test_fallback_on_laya_unavailable,
                   test_config_loader]:
            with self.subTest(fn.__name__):
                fn()


if __name__ == "__main__":
    unittest.main()
