"""Unified task entry: real local worker protocol and CLI, synthetic models."""
import json
import os
import subprocess
import sys
import time

import pytest

from ai_os_decision.cli import main


def checkpoint(tmp_path, body=None):
    model = tmp_path / "checkpoint"
    model.mkdir()
    model.joinpath("rl_agent_api.py").write_text(body or '''
class RLAgent:
    def __init__(self, model_dir):
        pass
    def system_one(self, state, questions):
        answers = {}
        for qid, q in questions.items():
            if q["type"] == "choice":
                choice = list(q["criteria"])[-1]
                answers[qid] = {"type": "choice", "choice": choice, "confidence": 0.9}
            else:
                answers[qid] = {"type": "noul", "noul": 0.0}
        return {"answers": answers}
''')
    return model


def invoke(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["ai-os", "task", *map(str, args)])
    code = main()
    return code, json.loads(capsys.readouterr().out)


def test_task_calls_laya_but_keeps_deterministic_route(tmp_path, monkeypatch, capsys):
    model = checkpoint(tmp_path)
    code, out = invoke(monkeypatch, capsys, "Refactor Python repository", "--model-dir", model,
                       "--timeout-ms", 2000)
    assert code == 0
    assert out["schema"] == "ai-os-task/v1"
    assert out["status"] == "ready"
    assert out["route"]["agent"] == "coding_agent"
    assert out["laya"]["status"] == "ok"
    assert out["laya"]["observation"]["agent_route"] == "direct"
    assert out["execution_enabled"] is False
    assert "Refactor Python repository" not in json.dumps(out)


def test_task_missing_laya_reports_fallback_and_strict_failure(tmp_path, monkeypatch, capsys):
    code, out = invoke(monkeypatch, capsys, "Fix Python bug", "--model-dir", tmp_path / "missing",
                       "--require-laya", "--timeout-ms", 1000)
    assert code == 3
    assert out["laya"]["status"] == "unavailable"
    assert out["laya"]["fallback_used"] is True
    assert out["route"]["agent"] == "coding_agent"


def test_task_deny_skips_laya_and_never_returns_an_executable_route(tmp_path, monkeypatch, capsys):
    config = tmp_path / "policy.yaml"
    config.write_text('policy:\n  deny_patterns:\n    - "delete production database"\n')
    model = checkpoint(tmp_path, 'raise AssertionError("policy must stop before model import")\n')
    code, out = invoke(monkeypatch, capsys, "delete production database", "--config", config,
                       "--model-dir", model)
    assert code == 2
    assert out["status"] == "denied"
    assert out["route"] is None
    assert out["laya"]["status"] == "skipped_policy"
    assert out["laya"]["attempted"] is False


def test_task_production_approval_is_visible(tmp_path, monkeypatch, capsys):
    model = checkpoint(tmp_path)
    code, out = invoke(monkeypatch, capsys, "deploy Python service", "--environment", "production",
                       "--config", "config.example.yaml", "--model-dir", model)
    assert code == 2
    assert out["status"] == "approval_required"
    assert out["policy"]["approval_required"] is True
    assert out["execution_enabled"] is False


@pytest.mark.parametrize("kind", ["missing", "empty", "no_policy"])
def test_task_missing_or_incomplete_config_cannot_weaken_policy(kind, tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.yaml"
    if kind != "missing":
        config.write_text("" if kind == "empty" else "decision_engine:\n  provider: laya\n")
    code, out = invoke(monkeypatch, capsys, "deploy Python service", "--environment", "production",
                       "--config", config, "--model-dir", tmp_path / "missing")
    assert code == 2
    assert out["status"] == "invalid_config"
    assert out["route"] is None
    assert out["laya"]["attempted"] is False


@pytest.mark.parametrize("section", ["laya: malformed", "decision_engine: malformed",
                                    "decision_engine:\n  timeouts: malformed"])
def test_task_malformed_nested_config_returns_sanitized_json(section, tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.yaml"
    config.write_text("policy:\n  fail_closed: true\n" + section + "\n")
    code, out = invoke(monkeypatch, capsys, "Fix Python bug", "--config", config)
    assert code == 2
    assert out["status"] == "invalid_config"
    assert out["laya"]["attempted"] is False


def test_default_task_uses_local_policy_override(tmp_path, monkeypatch, capsys):
    from ai_os_decision import cli
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(cli, "__file__", str(root / "src" / "ai_os_decision" / "cli.py"))
    (root / "config.yaml").write_text('policy:\n  deny_patterns:\n    - "base-only"\n')
    (root / "config.local.yaml").write_text('policy:\n  deny_patterns:\n    - "local-only"\n')
    code, out = invoke(monkeypatch, capsys, "local-only")
    assert code == 2
    assert out["status"] == "denied"
    assert out["laya"]["attempted"] is False


def test_isolated_laya_deadline_reaps_the_actual_model_worker(tmp_path):
    from ai_os_decision.laya_engine import IsolatedLayaDecisionEngine
    from ai_os_decision.models import DecisionQuestion, DecisionState
    pidfile = tmp_path / "worker.pid"
    body = f'''import os,time
from pathlib import Path
class RLAgent:
    def __init__(self, model_dir):
        Path({str(pidfile)!r}).write_text(str(os.getpid()))
    def system_one(self, state, questions):
        time.sleep(30)
'''
    model = checkpoint(tmp_path, body)
    engine = IsolatedLayaDecisionEngine(str(model), timeout_ms=400)
    with pytest.raises(subprocess.TimeoutExpired):
        engine.decide(DecisionState(text="synthetic"), [DecisionQuestion("x", "boolean", "Check")])
    assert pidfile.exists(), "worker must reach the blocking inference"
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


def test_cli_task_timeout_does_not_hold_process_open(tmp_path):
    model = checkpoint(tmp_path, '''import time
class RLAgent:
    def __init__(self, model_dir):
        pass
    def system_one(self, state, questions):
        time.sleep(30)
''')
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-m", "ai_os_decision.cli", "task", "Fix Python bug",
                           "--model-dir", str(model), "--timeout-ms", "200"],
                          capture_output=True, text=True, timeout=5, check=False)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["laya"]["status"] == "timeout"
    assert time.monotonic() - started < 5


@pytest.mark.parametrize("bad", ["", "x" * 8193], ids=["empty", "oversized"])
def test_task_rejects_invalid_input_before_inference(bad, monkeypatch, capsys):
    code, out = invoke(monkeypatch, capsys, bad)
    assert code == 2
    assert out["status"] == "invalid_request"
    assert out["laya"]["attempted"] is False
