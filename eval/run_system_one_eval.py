"""Labeled DE/EN decision microbenchmark; never an end-to-end agent benchmark."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from ai_os_decision.system_one import DeterministicFallback, SystemOneRuntime, cloud_eligible, QuotaTracker
from ai_os_decision.system_one_backends import ExistingQwenBackend, FreeLLMBackend, LiquidD1Backend
from ai_os_decision.system_one_io import discover_freellm_models, read_request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["deterministic", "qwen", "d1", "freellm"], default="deterministic")
    parser.add_argument("--model", default="qwen3.5:9b-mlx")
    parser.add_argument("--snapshot")
    parser.add_argument("--python")
    parser.add_argument("--approve-d1", action="store_true")
    parser.add_argument("--approve-cloud", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / "system_one"
    fixtures = json.loads((root/"fixtures.json").read_text())
    rows = []
    for f in fixtures:
        req = read_request(root / Path(f["request_path"]).name)
        if args.backend == "d1" and not args.approve_d1:
            rows.append({"id": f["id"], "status": "BLOCKED", "reason": "resource approval required"})
            continue
        if args.backend == "freellm" and not args.approve_cloud:
            rows.append({"id": f["id"], "status": "BLOCKED", "reason": "cloud approval required"})
            continue
        if args.backend in ("qwen", "freellm") and f.get("visual"):
            rows.append({"id": f["id"], "status": "NOT_APPLICABLE", "reason": "text baseline"})
            continue
        try:
            if args.backend == "qwen":
                backend = ExistingQwenBackend(args.model, req.inventory)
            elif args.backend == "freellm":
                gate = cloud_eligible(req, {"freellm": {"enabled": True}}, None, args.model)
                if not gate["allowed"]:
                    rows.append({"id": f["id"], "status": "BLOCKED", "reason": gate["reason"]})
                    continue
                _, json_ok = discover_freellm_models()
                backend = FreeLLMBackend(args.model, req.inventory, json_mode=args.model in json_ok,
                                         quota=QuotaTracker(), enabled=True, approved=True)
            elif args.backend == "d1":
                backend = LiquidD1Backend(args.snapshot, args.python, enabled=True, approved=True)
            else:
                backend = DeterministicFallback()
        except (ValueError, RuntimeError) as exc:
            rows.append({"id": f["id"], "status": "BLOCKED", "reason": type(exc).__name__})
            continue
        out = SystemOneRuntime(backend, cache_size=0).decide(req)
        values = {k: a.value for k,a in out.answers.items()}
        row = {"id": f["id"], "use_case": f["use_case"], "language": f["language"],
               "status": "PASS" if not out.fallback_used else "BLOCKED",
               "answers": values, "expected": f["expected"], "correct": values == f["expected"],
               "source": out.decision_source, "fallback": out.fallback_used, "error": out.error,
               "latency_ms": out.latency_ms, "usage": out.usage, "measurement": out.measurement,
               "confidence_semantics": out.confidence_semantics,
               "distributions": {k:a.probabilities for k,a in out.answers.items()}}
        rows.append(row)
        print(json.dumps({k:row[k] for k in ("id","correct","fallback","latency_ms")}),flush=True)
    evaluated = [r for r in rows if "correct" in r]
    model_success = [r for r in evaluated if not r["fallback"]]
    lat = sorted(r["latency_ms"] for r in model_success)
    summary = {"backend":args.backend,"model":args.model if args.backend in ("qwen","freellm") else None,
               "fixtures":len(rows), "statuses":dict(Counter(r["status"] for r in rows)),
               "evaluated":len(evaluated),"successful_backend_calls":len(model_success),
               "accuracy_including_fallback":sum(r["correct"] for r in evaluated)/len(evaluated) if evaluated else None,
               "backend_accuracy":sum(r["correct"] for r in model_success)/len(model_success) if model_success else None,
               "p50_ms":statistics.median(lat) if lat else None,
               "p95_ms":lat[math.ceil(.95*len(lat))-1] if lat else None,
               "fallback_count":sum(r["fallback"] for r in evaluated),
               "tokens": {key:sum(r["usage"][key] for r in evaluated) for key in ("input_tokens","output_tokens")},
               "end_to_end_task_completion":"UNVERIFIED: decision microbenchmark only",
               "confidence_calibration":"UNVERIFIED: tiny synthetic set; Qwen encoding has no native likelihoods",
               "invalid_option_selection":"rejected by contract tests; raw rate not measured",
               "skill_precision_recall":"UNVERIFIED: no multilabel ground truth corpus",
               "critical_error_rate":"UNVERIFIED: inadequate protected-action corpus",
               "cpu_gpu_utilization":"UNVERIFIED: no system utilization sampler"}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({"summary":summary,"rows":rows},indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
