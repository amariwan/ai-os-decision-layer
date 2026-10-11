"""Short-lived local Laya worker; no remote discovery or execution."""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import asdict
import json
import sys

from ai_os_decision.laya_engine import ContextWindowExceeded, LayaDecisionEngine, ModelAnswerInvalid
from ai_os_decision.models import DecisionQuestion, DecisionState


def main():
    payload = json.load(sys.stdin)
    # Third-party initialization messages must not corrupt the JSON protocol.
    with redirect_stdout(sys.stderr):
        engine = LayaDecisionEngine(payload["model_dir"])
        try:
            result = engine.decide(DecisionState(**payload["state"]),
                                   [DecisionQuestion(**q) for q in payload["questions"]])
        except ContextWindowExceeded:
            print(json.dumps({'error': 'context_too_large'}), file=sys.__stdout__)
            return
        except ModelAnswerInvalid:
            print(json.dumps({'error': 'invalid_answer'}), file=sys.__stdout__)
            return
    print(json.dumps(asdict(result), allow_nan=False))


if __name__ == "__main__":
    main()
