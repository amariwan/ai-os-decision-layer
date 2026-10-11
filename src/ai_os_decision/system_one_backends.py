"""Opt-in local backends. Child processes enforce real deadlines and release model RAM.

Data flow to cloud (FreeLLMBackend only):
  BoundedRequest -> sanitize_cloud_payload() [allowlist] -> validate_cloud_payload()
  [final serialized check] -> run_worker() [bounded subprocess] -> cloud_json()
  [loopback-only transport, key from environment].
Unlisted state/extra/metadata never leaves the process; rejected payloads
raise before any transport call (zero transport calls on reject).
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
from dataclasses import asdict
from pathlib import Path

REVISION = "051bcc464b01b9f92942b364d9586b0ef5912432"

# Process-local bound on concurrent inference workers. No queue builds up:
# overload fails closed instead of spawning unbounded processes. This limit
# is per-process and is not shared across processes or hosts.
MAX_CONCURRENT_WORKERS = 4
_WORKER_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_WORKERS)

# Explicit allowlist of BoundedRequest state fields that may be transferred
# to a cloud transport. Everything else (repository, branch, actor,
# permissions, capability snapshots, extra/metadata) stays local.
CLOUD_STATE_ALLOWLIST = frozenset({"text", "intent", "environment"})
CLOUD_PAYLOAD_MAX_BYTES = 65536

# Hint classes that must not appear in cloud-bound text unless explicitly
# authorized. Mirrors the local privacy screen without importing runtime code
# (this module is also imported by tests in isolation).
_CLOUD_SENSITIVE_HINTS = ("api_key", "apikey", "bearer ", "authorization:", "-----begin",
                          "private key", "password", "passwd", "aws_secret", "ghp_", "gsk_",
                          "sk-", "xoxb-", "credentials", "client_secret")


def sanitize_cloud_payload(request) -> dict:
    """Project a BoundedRequest onto the explicit cloud-transfer allowlist.

    Returns {"state": {...}, "questions": {...}}. Drops all non-allowlisted
    state fields, capability data, and metadata. Raises on images (cloud text
    baselines never evaluate visual fixtures) and on non-scalar values.
    """
    if getattr(request, "images", ()):
        raise ValueError("cloud payload must not contain images")
    state = asdict(request.state)
    clean: dict = {}
    for key in CLOUD_STATE_ALLOWLIST:
        value = state.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"cloud state field {key!r} must be a string")
        clean[key] = value
    questions = request.wire()["questions"]
    if not isinstance(questions, dict) or not questions:
        raise ValueError("cloud payload needs bounded questions")
    return {"state": clean, "questions": questions}


def validate_cloud_payload(payload: dict, *, allow_private: bool = False, model: str | None = None) -> bytes:
    """Validate the final serialized cloud payload at the transport boundary.

    Checks: exact top-level shape, allowlisted scalar state fields only, no
    nested structures beyond the bounded question map, 64 KiB size bound, and
    a secret-hint screen on the transfer text. Returns the serialized bytes
    to send. Raises ValueError on any violation — callers must raise before
    any transport call so rejected payloads cause zero transport calls.
    """
    if type(allow_private) is not bool:
        raise TypeError("allow_private must be a boolean")
    if model is not None and (not isinstance(model, str) or not model or len(model) > 512):
        raise ValueError("invalid cloud model identifier")
    if set(payload) != {"state", "questions"}:
        raise ValueError("cloud payload has unexpected top-level fields")
    state, questions = payload["state"], payload["questions"]
    if not isinstance(state, dict) or not isinstance(questions, dict):
        raise TypeError("cloud payload sections must be mappings")
    if set(state) - set(CLOUD_STATE_ALLOWLIST):
        raise ValueError("cloud payload carries non-allowlisted state")
    for value in state.values():
        if not isinstance(value, str):
            raise TypeError("cloud state values must be bounded strings")
        if len(value) > 8192:
            raise ValueError("cloud state values must be bounded strings")
    if not 1 <= len(questions) <= 32:
        raise ValueError("cloud payload needs 1..32 questions")
    for qid, question in questions.items():
        if not isinstance(qid, str) or not qid or len(qid) > 512 or not isinstance(question, dict):
            raise ValueError("invalid cloud question")
        if set(question) - {"type", "instructions", "criteria"}:
            raise ValueError("unexpected cloud question fields")
        instructions = question.get("instructions", "")
        if not isinstance(instructions, str) or len(instructions) > 2000:
            raise ValueError("invalid cloud question instructions")
        kind, criteria = question.get("type"), question.get("criteria")
        if kind == "choice":
            if not isinstance(criteria, dict) or not 2 <= len(criteria) <= 64:
                raise ValueError("invalid cloud choice criteria")
            if any(not isinstance(k, str) or not isinstance(v, (str, type(None))) for k, v in criteria.items()):
                raise ValueError("cloud choice criteria must contain text only")
        elif kind == "score":
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10 or any(not isinstance(v, str) for v in criteria):
                raise ValueError("invalid cloud score criteria")
        elif kind != "noul" or criteria is not None:
            raise ValueError("invalid cloud question type or criteria")
    try:
        transfer = dict(payload, model=model) if model is not None else payload
        raw = json.dumps(transfer, allow_nan=False, ensure_ascii=False).encode()
    except (TypeError, ValueError):
        raise ValueError("cloud payload is not JSON-serializable")
    if len(raw) > CLOUD_PAYLOAD_MAX_BYTES:
        raise ValueError("cloud payload exceeds 64 KiB")
    # Screen every transferred value and key, including questions, option
    # descriptions, intent and environment, rather than just state.text.
    hits = sorted(h for h in _CLOUD_SENSITIVE_HINTS if h in raw.decode().lower())
    if hits and not allow_private:
        raise ValueError("cloud payload blocked: sensitive-content:" + hits[0])
    return raw


def run_worker(python, arguments, payload, timeout):
    if not math.isfinite(timeout) or not .01 <= timeout <= 600:
        raise ValueError("timeout must be 0.01..600 seconds")
    if not _WORKER_SEMAPHORE.acquire(blocking=False):
        raise RuntimeError("worker-overloaded: too many concurrent inference workers")
    try:
        env = dict(os.environ)
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                   TOKENIZERS_PARALLELISM="false")
        # No shell, no command interpolation, no remote host. subprocess.run kills and
        # waits for the child on timeout; there are no inference worker threads left running.
        result = subprocess.run([str(python), *arguments], input=json.dumps(payload, allow_nan=False),
                                capture_output=True, text=True, timeout=timeout, env=env, check=False)
    finally:
        _WORKER_SEMAPHORE.release()
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
                 quota=None, enabled=False, approved=False, timeout=90,
                 allow_private=False):
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
        if type(allow_private) is not bool:
            raise TypeError("allow_private must be a boolean")
        self.allow_private = allow_private

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
        # Transport boundary: allowlist + final serialized validation BEFORE
        # any worker/transport call. Rejects raise here => zero transport calls.
        payload = sanitize_cloud_payload(request)
        validate_cloud_payload(payload, allow_private=self.allow_private, model=self.model)
        payload.update(model=self.model, base_url=self.base_url,
                       json_mode=self.json_mode, timeout=self.timeout)
        if self.allow_private:
            payload["allow_private"] = True
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
