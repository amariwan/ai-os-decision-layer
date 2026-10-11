"""Small local CLI for the decision-layer shadow runtime."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ai_os_decision.models import load_config
from ai_os_decision.shadow import ShadowRuntime


def _runtime(config_path=None, model_dir=None, timeout_ms=None, *, require_policy=False) -> ShadowRuntime:
    root = Path(__file__).resolve().parents[2]
    local = root / "config.local.yaml"
    path = Path(config_path) if config_path else (local if local.exists() else root / "config.yaml")
    if require_policy and not path.is_file():
        raise ValueError("task entry requires an existing local policy config")
    cfg = load_config(str(path))
    if require_policy and not isinstance(cfg.get("policy"), dict):
        raise ValueError("task entry requires an explicit policy section")
    laya, engine = cfg.get("laya", {}), cfg.get("decision_engine", {})
    if not isinstance(laya, dict) or not isinstance(engine, dict):
        raise TypeError("laya and decision_engine must be mappings")
    timeouts = engine.get("timeouts", {})
    if not isinstance(timeouts, dict):
        raise TypeError("timeouts must be a mapping")
    timeout = int(timeouts.get("laya_ms", 150)) if timeout_ms is None else timeout_ms
    if not 10 <= timeout <= 600000:
        raise ValueError("local inference deadline must be 10..600000 ms")
    return ShadowRuntime(model_dir or laya.get("model_dir"), timeout, cfg)


def main() -> int:
    parser = argparse.ArgumentParser(prog="ai-os")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    decide = sub.add_parser("decide")
    decide.add_argument("text")
    decide.add_argument("--environment", default="dev")
    task = sub.add_parser("task", help="prepare a task through policy + local Laya; never execute tools")
    task.add_argument("text")
    task.add_argument("--environment", default="dev")
    task.add_argument("--action", default="", help="trusted action hint for policy evaluation")
    task.add_argument("--config", help="explicit local config file")
    task.add_argument("--model-dir", help="existing trusted local RLAgent checkpoint directory")
    task.add_argument("--timeout-ms", type=int, help="hard local inference deadline (10..600000 ms)")
    task.add_argument("--require-laya", action="store_true", help="exit 3 if Laya cannot return an observation")
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
    if args.command == "task":
        from ai_os_decision.task_entry import prepare_task
        if args.timeout_ms is not None and not 10 <= args.timeout_ms <= 600000:
            parser.error("--timeout-ms must be 10..600000")
        try:
            result = prepare_task(args.text, args.environment,
                                  _runtime(args.config, args.model_dir, args.timeout_ms, require_policy=True), args.action)
        except (OSError, ValueError, TypeError):
            # Do not print config values or user text in errors.
            print(json.dumps({"schema": "ai-os-task/v1", "status": "invalid_config",
                              "route": None, "execution_enabled": False,
                              "laya": {"attempted": False, "status": "not_attempted"}}))
            return 2
        print(json.dumps(result, indent=2, allow_nan=False))
        if result["status"] != "ready":
            return 2
        return 3 if args.require_laya and result["laya"]["status"] != "ok" else 0
    runtime = _runtime()
    if args.command == "health":
        print(runtime.laya.health())
        return 0
    result = runtime.handle(args.text, args.environment, os.environ.get("AI_OS_SHADOW_LOG"))
    print(json.dumps({"baseline": result["baseline"].answers, "shadow": result["shadow"]}, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
