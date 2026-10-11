"""JSONL observability. No raw text, no secrets. stdlib only."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ai_os_decision.models import DecisionResult


def log_decision(result: DecisionResult, decision_type: str, log_path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    # primary answer = first answer, for traceability without logging text
    first = next(iter(result.answers.values()), None)
    selected = str(getattr(first, "value", "")) if first else ""
    conf = float(getattr(first, "confidence", 0.0)) if first else 0.0
    entry = {
        "decision_id": result.decision_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision_type": decision_type,
        "selected_option": selected,
        "confidence": conf,
        "provider": result.provider,
        "latency_ms": round(result.latency_ms, 2),
        "fallback_used": result.fallback_used,
        "policy_override": result.policy_override,
        "execution_result": "",
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return result.decision_id
