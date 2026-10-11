"""Opt-in local backends. Child processes enforce real deadlines and release model RAM."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

REVISION = "051bcc464b01b9f92942b364d9586b0ef5912432"


def run_worker(python, arguments, payload, timeout):
    if not math.isfinite(timeout) or not .01 <= timeout <= 600:
        raise ValueError("timeout must be 0.01..600 seconds")
    env = dict(os.environ)
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
               TOKENIZERS_PARALLELISM="false")
    # No shell, no command interpolation, no remote host. subprocess.run kills and
    # waits for the child on timeout; there are no inference worker threads left running.
    result = subprocess.run([str(python), *arguments], input=json.dumps(payload, allow_nan=False),
                            capture_output=True, text=True, timeout=timeout, env=env, check=False)
    if result.returncode:
        # Third-party tracebacks can contain input; never propagate them into logs.
        raise RuntimeError("local backend worker failed")
    if len(result.stdout) > 262144:
        raise ValueError("oversized worker response")
    return json.loads(result.stdout)


class LiquidD1Backend:
    name = "liquid-d1"

    def __init__(self, snapshot=None, python=None, *, enabled=False, approved=False, timeout=120):
        self.snapshot = Path(snapshot).resolve() if snapshot else None
        self.python = Path(python).resolve() if python else None
        self.enabled, self.approved, self.timeout = enabled, approved, timeout

    def infer(self, request):
        if not self.enabled or not self.approved:
            raise RuntimeError("d1 disabled or awaiting resource/code approval")
        if not self.snapshot or not self.python or not self.python.is_file():
            raise RuntimeError("isolated interpreter and pinned local snapshot required")
        payload = request.wire()
        payload.update(snapshot=str(self.snapshot), revision=REVISION)
        return run_worker(self.python, [str(Path(__file__).with_name("system_one_worker.py")), "d1"],
                          payload, self.timeout)


class ExistingQwenBackend:
    name = "qwen"

    def __init__(self, model, inventory, *, timeout=60):
        inventory.validate()
        if not any(c.id == model and c.kind == "model" and c.completion for c in inventory.capabilities):
            raise ValueError("Qwen must be a discovered completion-capable model")
        if "qwen" not in model.lower():
            raise ValueError("Qwen backend requires a Qwen model")
        self.model, self.timeout = model, timeout

    def infer(self, request):
        if self.model not in request.inventory.ids("model"):
            raise ValueError("model absent from request snapshot")
        payload = request.wire()
        payload.update(model=self.model, timeout=self.timeout)
        return run_worker(sys.executable, [str(Path(__file__).with_name("system_one_worker.py")), "qwen"],
                          payload, self.timeout)


def _cloud_exc(err):
    kind = err.get("type", "provider") if isinstance(err, dict) else "provider"
    if kind == "unauthorized":
        return PermissionError("cloud unauthorized")
    if kind == "missing_credentials":
        return RuntimeError("cloud credentials not configured")
    if kind == "rejected":
        return ValueError("cloud rejected request")
    if kind == "rate_limited":
        return RuntimeError("cloud rate-limited")
    return RuntimeError("cloud provider error")


class FreeLLMBackend:
    """FreeLLMAPI cloud escalation. Disabled unless explicitly enabled+approved."""

    name = "freellm"

    def __init__(self, model, inventory, *, base_url=None, json_mode=False,
                 quota=None, enabled=False, approved=False, timeout=90):
        import os
        inventory.validate()
        if not any(c.id == model and c.kind == "model" and c.completion
                   and c.source.startswith("freellm:") for c in inventory.capabilities):
            raise ValueError("cloud model must be a discovered available FreeLLMAPI model")
        base = (base_url or os.environ.get("FREELLMAPI_BASE_URL", "http://127.0.0.1:31415")).rstrip("/")
        from urllib.parse import urlparse
        if urlparse(base).scheme != "http" or urlparse(base).hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("cloud gateway must be a loopback URL")
        self.model, self.base_url = model, base
        self.json_mode, self.quota = bool(json_mode), quota
        self.enabled, self.approved, self.timeout = enabled, approved, timeout

    def _record(self, err):
        record = getattr(self.quota, "record", None)
        if callable(record):
            try:
                record(err if isinstance(err, dict) else {"type": "error"})
            except Exception:
                return

    def infer(self, request):
        if not self.enabled or not self.approved:
            raise RuntimeError("cloud disabled: explicit approval required")
        if self.model not in request.inventory.ids("model"):
            raise ValueError("model absent from request snapshot")
        payload = request.wire()
        payload.update(model=self.model, base_url=self.base_url,
                       json_mode=self.json_mode, timeout=self.timeout)
        try:
            raw = run_worker(sys.executable, [str(Path(__file__).with_name("system_one_worker.py")),
                                              "freellm"], payload, self.timeout)
        except Exception as exc:
            self._record({"type": type(exc).__name__})
            raise
        if type(raw) is not dict:
            self._record({"type": "malformed"})
            raise TypeError("cloud provider error")
        err = raw.get("transport_error")
        if isinstance(err, dict):
            self._record(err)
            raise _cloud_exc(err)
        self._record({"type": "ok"})
        return raw
