"""Evaluate the deterministic baseline and optional Laya shadow provider."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_os_decision.models import load_config
from ai_os_decision.shadow import ShadowRuntime


def main() -> None:
    base = os.path.dirname(__file__)
    with open(os.path.join(base, "shadow_decisions.jsonl")) as handle:
        rows = [json.loads(line) for line in handle]
    cfg = load_config(os.path.join(base, "..", "config.yaml"))
    runtime = ShadowRuntime(
        (cfg.get("laya", {}) or {}).get("model_dir"),
        int((cfg.get("decision_engine", {}) or {}).get("timeouts", {}).get("laya_ms", 150)),
        cfg,
    )
    baseline_correct = {"intent": [], "agent_route": [], "needs_reasoning": []}
    laya_available = 0
    failures = 0
    latencies = []
    agreements = []
    for row in rows:
        started = time.perf_counter()
        output = runtime.handle(row["input"])
        latencies.append((time.perf_counter() - started) * 1000)
        shadow = output["shadow"]
        if not shadow["fallback_used"]:
            laya_available += 1
            agreements.extend(v["agreement"] for v in shadow["baseline"].values() if v["agreement"] is not None)
        else:
            failures += 1
        baseline_correct["intent"].append(
            shadow["baseline"]["intent"] == row["expected_intent"]
        )
        baseline_correct["agent_route"].append(
            shadow["baseline"]["agent_route"] == row["expected_agent_route"]
        )
        baseline_correct["needs_reasoning"].append(
            shadow["baseline"]["needs_reasoning"] == row["expected_needs_reasoning"]
        )
    ordered = sorted(latencies)
    print(json.dumps({
        "cases": len(rows),
        "baseline_accuracy": {
            key: round(statistics.mean(values), 4) if values else None
            for key, values in baseline_correct.items()
        },
        "laya_available": laya_available,
        "laya_failures_or_timeouts": failures,
        "baseline_laya_agreement": round(statistics.mean(agreements), 4) if agreements else None,
        "latency_ms": {
            "p50": round(ordered[len(ordered) // 2], 2),
            "p95": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2),
        },
        "note": "Laya confidence is observed model score; no execution threshold is applied.",
    }, indent=2))


if __name__ == "__main__":
    main()
