"""Eval: rule-engine baseline on synthetic set. Reports accuracy, FPR/FNR approval, latency."""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_os_decision.engine import DecisionEngine
from ai_os_decision.models import DecisionQuestion, DecisionState, load_config

AGENTS = {"coding_agent": "code tasks", "devops_agent": "deploy infra prod", "research_agent": "research compare", "workflow": "scheduled pipeline n8n", "direct": "simple answer"}
TOOLS = {"github": "pr repo code", "docker": "container image", "kubernetes": "k8s pods deploy infra"}
MODELS = {"laya": "classify route score simple", "reasoning": "why debug design prove complex architecture"}


def questions_for(case):
    cat = case["cat"]
    if cat in ("agent", "workflow"):
        return [DecisionQuestion("route", "choice", "Which route?", dict(AGENTS))]
    if cat == "tool":
        return [DecisionQuestion("tool", "choice", "Which tool?", dict(TOOLS))]
    if cat == "model":
        return [DecisionQuestion("model", "choice", "Which model?", dict(MODELS))]
    if cat == "risk":
        return [DecisionQuestion("risk", "score", "Risk level?", criteria=["low", "medium", "high"])]
    return [DecisionQuestion("needs_human_approval", "boolean", "Need human approval?")]


def main():
    base = os.path.dirname(__file__)
    data = os.path.join(base, "decisions.jsonl")
    if not os.path.exists(data):
        print("missing decisions.jsonl, run make_dataset.py first")
        sys.exit(2)
    cfg = load_config(os.path.join(base, "..", "config.yaml"))
    cfg = dict(cfg)
    cfg["decision_engine"] = dict(cfg.get("decision_engine", {}))
    cfg["decision_engine"]["provider"] = "rule"  # baseline; swap to laya for live eval
    eng = DecisionEngine(cfg)
    with open(data) as handle:
        rows = [json.loads(line) for line in handle]
    correct = total = 0
    tp = fp = tn = fn = 0
    lat = []
    conf_ok, conf_bad = [], []
    for c in rows:
        st = DecisionState(text=c["text"], environment=c.get("env", "dev"))
        qs = questions_for(c)
        t0 = time.perf_counter()
        res = eng.decide(st, qs)
        lat.append((time.perf_counter() - t0) * 1000)
        ans = res.answers[qs[0].id]
        total += 1
        if c["cat"] in ("agent", "workflow"):
            ok = ans.value == c.get("expect_route")
        elif c["cat"] == "tool":
            ok = ans.value == c.get("expect_tool")
        elif c["cat"] == "model":
            ok = ans.value == c.get("expect_model")
        elif c["cat"] == "risk":
            ok = abs(float(ans.value) - float(c.get("risk", 0))) < 0.6
        else:
            ok = bool(ans.value) == bool(c.get("approval"))
            if ans.value and c.get("approval"):
                tp += 1
            elif ans.value and not c.get("approval"):
                fp += 1
            elif not ans.value and not c.get("approval"):
                tn += 1
            else:
                fn += 1
        correct += bool(ok)
        (conf_ok if ok else conf_bad).append(float(ans.confidence))
    lat_sorted = sorted(lat)
    p50 = lat_sorted[len(lat_sorted) // 2]
    p95 = lat_sorted[int(len(lat_sorted) * 0.95) - 1]
    fpr = fp / max(1, fp + tn)
    fnr = fn / max(1, fn + tp)
    out = {
        "n": total,
        "accuracy": round(correct / total, 4),
        "approval_fpr": round(fpr, 4),
        "approval_fnr": round(fnr, 4),
        "mean_conf_correct": round(statistics.mean(conf_ok or [0]), 4),
        "mean_conf_wrong": round(statistics.mean(conf_bad or [0]), 4),
        "fallback_rate": 1.0,
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
