"""Provider intelligence benchmark: dry-run by default, live only with approval.

 Budgets, cooldowns, checkpoint/resume, sanitized artifacts. Sequential calls
 only (no concurrent provider load). Cloud pairs additionally require
 --approve-cloud, freellm.enabled, and per-fixture privacy clearance.
 """
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ai_os_decision.provider_intel import build_inventory
from ai_os_decision.system_one import (
    BoundedRequest, CapabilitySnapshot, DeterministicFallback,
    QuotaTracker, SystemOneRuntime, cloud_eligible,
)
from ai_os_decision.system_one_backends import ExistingQwenBackend, FreeLLMBackend
from ai_os_decision.system_one_io import (
    discover_freellm_models, discover_models, freellm_inventory_rows, read_request,
)

VERSION = "provider-benchmark/v1"


def load_pairs(root, wanted):
    fixtures = json.loads((root / "fixtures.json").read_text())
    if wanted != ["all"]:
        wanted = set(wanted)
        fixtures = [f for f in fixtures if f["id"] in wanted]
        missing = wanted - {f["id"] for f in fixtures}
        if missing:
            raise ValueError("unknown fixtures: " + ",".join(sorted(missing)))
    return fixtures


def read_checkpoint(path):
    """Load completed pair_ids; malformed lines are skipped, never fatal."""
    done = {}
    if not path or not Path(path).exists():
        return done
    for line in Path(path).read_text().splitlines():
        try:
            row = json.loads(line)
            done[row["pair_id"]] = row
        except (ValueError, KeyError):
            continue
    return done


def live_inventory():
    """Local discovery is free; cloud discovery needs FREELLMAPI_KEY (may fail)."""
    ollama = discover_models()
    try:
        freellm_caps, json_ok = discover_freellm_models()
        rows = freellm_inventory_rows()
    except Exception as exc:
        freellm_caps, json_ok, rows = (), frozenset(), None
        cloud_error = type(exc).__name__
    else:
        cloud_error = None
    observed = datetime.now(timezone.utc).isoformat()
    records = build_inventory(ollama, rows or (), observed_at=observed)
    return ollama, freellm_caps, json_ok, records, cloud_error


def inject_model(req, cap):
    caps = tuple(req.inventory.capabilities) + (cap,)
    data = {"state": req.state, "questions": req.questions, "fallback_answers": req.fallback_answers,
            "inventory": CapabilitySnapshot(caps), "candidate_kinds": dict(req.candidate_kinds),
            "required_answers": dict(req.required_answers), "minimum_risk": req.minimum_risk,
            "action": req.action, "approval_required": req.approval_required, "denied": req.denied}
    out = BoundedRequest(**data)
    out.validate()
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=["deterministic"],
                        help="'deterministic', 'ollama:<id>', 'freellm:<id>', 'd1:<id>'")
    parser.add_argument("--fixtures", nargs="*", default=["all"])
    parser.add_argument("--live", action="store_true", help="execute model backends (default: dry-run plan + deterministic only)")
    parser.add_argument("--approve-cloud", action="store_true")
    parser.add_argument("--budget", type=int, default=24)
    parser.add_argument("--per-model-budget", type=int, default=8)
    parser.add_argument("--cooldown-local", type=float, default=2.0)
    parser.add_argument("--cooldown-cloud", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--checkpoint", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-out", default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent / "provider_intel"
    fixtures = load_pairs(root, args.fixtures)
    ollama, freellm_caps, json_ok, records, cloud_error = live_inventory()
    by_model = {}
    for c in ollama:
        by_model[("ollama", c.id)] = c
    for c in freellm_caps:
        by_model[("freellm", c.id)] = c

    config_hash = hashlib.sha256(json.dumps(
        {"fixtures": [f["id"] for f in fixtures], "models": sorted(args.models),
         "version": VERSION}, sort_keys=True).encode()).hexdigest()[:16]

    plan = []
    for spec in args.models:
        if spec == "deterministic":
            plan.append(("deterministic", None, None))
            continue
        provider, _, mid = spec.partition(":")
        cap = by_model.get((provider, mid))
        if cap is None or not cap.completion:
            plan.append((provider, mid, "BLOCKED:not-discovered-or-incomplete"))
        else:
            plan.append((provider, mid, None))

    print(json.dumps({"version": VERSION, "config_hash": config_hash, "dry_run": not args.live,
                      "cloud_discovery": "ok" if cloud_error is None else cloud_error,
                      "plan": [{"provider": p, "model": m, "gate": g} for p, m, g in plan],
                      "fixtures": [f["id"] for f in fixtures]}, indent=1))
    if not args.live:
        print("dry-run: deterministic baseline only; pass --live to execute model backends")
        livemodels = [p for p in plan if p[0] != "deterministic" and p[2] is None]
        if livemodels:
            print("live pairs that WOULD run: " + str(len(livemodels) * len(fixtures)))

    done = read_checkpoint(args.checkpoint)

    from ai_os_decision.models import load_config
    config = load_config(str(Path(__file__).resolve().parents[1] / "config.yaml"))
    quotas = {"ollama": QuotaTracker(), "freellm": QuotaTracker()}
    spent, per_model, last_call, eliminated = 0, Counter(), {}, set()
    rows = list(done.values())

    def checkpoint(row):
        if args.checkpoint:
            with open(args.checkpoint, "a") as f:
                f.write(json.dumps(row, allow_nan=False) + "\n")

    for provider, mid, gate in plan:
        for f in fixtures:
            pair = f["id"] + "|" + provider + ":" + (mid or "-")
            if pair in done:
                continue
            if gate is not None:
                row = {"pair_id": pair, "fixture": f["id"], "provider": provider, "model": mid,
                       "status": "BLOCKED", "reason": gate}
                rows.append(row)
                checkpoint(row)
                continue
            if provider == "d1":
                row = {"pair_id": pair, "fixture": f["id"], "provider": provider, "model": mid,
                       "status": "BLOCKED", "reason": "native-inference-unavailable"}
                rows.append(row)
                checkpoint(row)
                continue
            if provider != "deterministic" and not args.live:
                continue
            if spent >= args.budget or per_model[provider + ":" + str(mid)] >= args.per_model_budget:
                row = {"pair_id": pair, "fixture": f["id"], "provider": provider, "model": mid,
                       "status": "BLOCKED", "reason": "budget-exhausted"}
                rows.append(row)
                checkpoint(row)
                continue
            if mid in eliminated:
                row = {"pair_id": pair, "fixture": f["id"], "provider": provider, "model": mid,
                       "status": "BLOCKED", "reason": "model-eliminated"}
                rows.append(row)
                checkpoint(row)
                continue
            req = read_request(root / f["request_path"])
            try:
                if provider == "deterministic":
                    backend = DeterministicFallback()
                elif provider == "ollama":
                    req = inject_model(req, by_model[(provider, mid)])
                    backend = ExistingQwenBackend(mid, req.inventory, timeout=args.timeout)
                else:
                    if not f.get("cloud_ok", True):
                        row = {"pair_id": pair, "fixture": f["id"], "provider": provider,
                               "model": mid, "status": "BLOCKED", "reason": "privacy-protected"}
                        rows.append(row)
                        checkpoint(row)
                        continue
                    gate_ok = cloud_eligible(req, config, quotas["freellm"], mid)
                    if not gate_ok["allowed"] or not args.approve_cloud:
                        row = {"pair_id": pair, "fixture": f["id"], "provider": provider,
                               "model": mid, "status": "BLOCKED",
                               "reason": gate_ok["reason"] if not gate_ok["allowed"] else "cloud-approval-required"}
                        rows.append(row)
                        checkpoint(row)
                        continue
                    req = inject_model(req, by_model[(provider, mid)])
                    backend = FreeLLMBackend(mid, req.inventory, json_mode=mid in json_ok,
                                             quota=quotas["freellm"], enabled=True, approved=True,
                                             timeout=args.timeout)
            except (ValueError, RuntimeError) as exc:
                row = {"pair_id": pair, "fixture": f["id"], "provider": provider, "model": mid,
                       "status": "BLOCKED", "reason": type(exc).__name__}
                rows.append(row)
                checkpoint(row)
                continue
            cool = args.cooldown_cloud if provider == "freellm" else args.cooldown_local
            wait = last_call.get(mid, 0) + cool - time.monotonic()
            if provider != "deterministic" and wait > 0:
                time.sleep(wait)
            out = SystemOneRuntime(backend, cache_size=0).decide(req)
            last_call[mid or "deterministic"] = time.monotonic()
            spent += 1
            per_model[provider + ":" + str(mid)] += 1
            values = {k: a.value for k, a in out.answers.items()}
            # Fallback answers matching expected count as correct-by-fallback;
            # they are never counted as successful model inferences (see status).
            row = {"pair_id": pair, "fixture": f["id"], "category": f.get("category"),
                   "language": f.get("language"), "provider": provider, "model": mid,
                   "status": "PASS" if not out.fallback_used else "FALLBACK",
                   "correct": values == f["expected"], "source": out.decision_source,
                   "fallback": out.fallback_used, "error": out.error,
                   "latency_ms": round(out.latency_ms, 2), "usage": out.usage,
                   "measurement": out.measurement, "confidence_semantics": out.confidence_semantics}
            rows.append(row)
            checkpoint(row)
            print(json.dumps({k: row[k] for k in ("pair_id", "status", "correct", "error", "latency_ms")}), flush=True)
            if out.fallback_used:
                fails = sum(1 for r in rows if r.get("model") == mid and r.get("fallback"))
                if fails >= 3 and provider != "deterministic":
                    eliminated.add(mid)

    summary = summarize(rows, config_hash)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(
        {"summary": summary, "rows": rows, "inventory": [r.to_json() for r in records]}, indent=1) + "\n")
    if args.evidence_out:
        Path(args.evidence_out).write_text(json.dumps(
            {"evidence": build_evidence(rows, summary, config_hash)}, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


def summarize(rows, config_hash):
    by_model = {}
    for r in rows:
        if r.get("status") not in ("PASS", "FALLBACK"):
            continue
        by_model.setdefault((r["provider"], r["model"]), []).append(r)
    models = {}
    for (provider, mid), rs in by_model.items():
        ok = [r for r in rs if r["status"] == "PASS"]
        lat = sorted(r["latency_ms"] for r in ok)
        models[f"{provider}:{mid}"] = {
            "samples": len(rs), "accuracy": sum(r["correct"] for r in rs) / len(rs),
            "fallback_rate": sum(r["fallback"] for r in rs) / len(rs),
            "errors": dict(Counter(r["error"] for r in rs if r["error"])),
            "p50_ms": statistics.median(lat) if lat else None,
            "p95_ms": lat[math.ceil(.95 * len(lat)) - 1] if lat else None,
            "input_tokens": sum(r["usage"]["input_tokens"] for r in rs),
            "output_tokens": sum(r["usage"]["output_tokens"] for r in rs),
            "billed_cost": "UNVERIFIED: no billed-cost source",
        }
    return {"version": VERSION, "config_hash": config_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "statuses": dict(Counter(r["status"] for r in rows)),
            "models": models,
            "limitations": ["synthetic fixtures only; not agent task completion",
                            "accuracy on <=12 fixtures per model is indicative, never conclusive",
                            "costs unverified; free-tier quota is the binding constraint"]}


def build_evidence(rows, summary, config_hash):
    out = []
    for key, m in summary["models"].items():
        provider, _, mid = key.partition(":")
        if provider == "deterministic" or m["samples"] == 0:
            continue
        out.append({"model_id": mid or "", "provider": provider, "benchmark_version": VERSION,
                    "timestamp": summary["timestamp"], "samples": m["samples"],
                    "accuracy": m["accuracy"], "p50_ms": m["p50_ms"],
                    "fallback_rate": m["fallback_rate"], "config_hash": config_hash,
                    "provenance": "run_provider_benchmark"})
    return out


if __name__ == "__main__":
    raise SystemExit(main())
