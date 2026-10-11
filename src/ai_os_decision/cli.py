"""Small local CLI for the decision-layer shadow runtime."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ai_os_decision.models import load_config
from ai_os_decision.shadow import ShadowRuntime


def _runtime() -> ShadowRuntime:
    cfg = load_config(str(Path(__file__).resolve().parents[2] / "config.yaml"))
    laya = cfg.get("laya", {}) or {}
    timeout = int((cfg.get("decision_engine", {}) or {}).get("timeouts", {}).get("laya_ms", 150))
    return ShadowRuntime(laya.get("model_dir"), timeout, cfg)


def main() -> int:
    parser = argparse.ArgumentParser(prog="ai-os")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    decide = sub.add_parser("decide")
    decide.add_argument("text")
    decide.add_argument("--environment", default="dev")
    system_one = sub.add_parser("system-one", help="explicit recommendation-only shadow prototype")
    system_one.add_argument("request", help="trusted local request JSON; never a model-generated inventory")
    system_one.add_argument("--backend", choices=["deterministic", "qwen", "d1", "freellm"], default="deterministic")
    system_one.add_argument("--model")
    system_one.add_argument("--snapshot")
    system_one.add_argument("--python")
    system_one.add_argument("--approve-d1", action="store_true")
    system_one.add_argument("--approve-cloud", action="store_true",
                            help="explicit per-run approval for FreeLLMAPI cloud execution (disabled by default)")
    from ai_os_decision.workflows.cli import configure, run
    configure(sub)
    args = parser.parse_args()
    if args.command == "workflows":
        return run(args)
    if args.command == "system-one":
        from ai_os_decision.system_one_io import run_cli
        return run_cli(args)
    runtime = _runtime()
    if args.command == "health":
        print(runtime.laya.health())
        return 0
    result = runtime.handle(args.text, args.environment, os.environ.get("AI_OS_SHADOW_LOG"))
    print(json.dumps({"baseline": result["baseline"].answers, "shadow": result["shadow"]}, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
