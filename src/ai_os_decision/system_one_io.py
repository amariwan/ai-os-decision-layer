"""Explicit client adapter and bounded discovery; no background activation."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ai_os_decision.engine import DecisionEngine
from ai_os_decision.models import DecisionQuestion, DecisionState, load_config
from ai_os_decision.system_one import BoundedRequest, Capability, CapabilitySnapshot, cloud_eligible, QuotaTracker
from ai_os_decision.system_one_backends import ExistingQwenBackend, FreeLLMBackend, LiquidD1Backend
from ai_os_decision.system_one_worker import cloud_json, http_json, model_capabilities


def freellm_inventory_rows(base_url=None):
    """Validated raw /v1/models rows for intelligence building. No credentials included."""
    import os
    base = (base_url or os.environ.get("FREELLMAPI_BASE_URL", "http://127.0.0.1:31415")).rstrip("/")
    parsed, _ = cloud_json(base, "/v1/models", None, timeout=15)
    if type(parsed) is not dict:
        raise TypeError("malformed cloud inventory")
    if "transport_error" in parsed:
        raise RuntimeError("cloud discovery failed: " + str(parsed["transport_error"].get("type")))
    rows = parsed.get("data", parsed.get("models"))
    if type(rows) is not list:
        raise TypeError("malformed cloud inventory")
    if len(rows) > 512:
        raise ValueError("cloud inventory exceeds bounds")
    return [m for m in rows if isinstance(m, dict)]


def discover_freellm_models(base_url=None):
    """Live FreeLLMAPI /v1/models; only available models are completion candidates.

    Never includes credentials: sources carry model IDs only. Discovery is
    restricted to the loopback gateway. Returns (capabilities, json_capable_ids).
    """
    rows = freellm_inventory_rows(base_url)
    caps, json_ok = [], set()
    for m in rows:
        mid = m.get("id")
        if not isinstance(mid, str) or not mid or len(mid) > 256:
            continue
        if not m.get("available"):
            continue  # advertised but not provisioned for this account: never a candidate
        completion = "embed" not in mid.lower()
        params = m.get("supported_parameters") or []
        if isinstance(params, list) and "response_format" in params:
            json_ok.add(mid)
        name = m.get("name") if isinstance(m.get("name"), str) else ""
        caps.append(Capability(mid, "model", "freellm:/v1/models:" + mid,
                               name[:200], completion=completion))
    return tuple(caps), frozenset(json_ok)


def discover_models():
    """Live tags, completion capability, and digest; registration is not inference proof.

    Malformed rows are skipped, never invented or repaired. A malformed envelope
    raises. Per-row capability probes that fail yield completion=False (fail closed).
    """
    resp = http_json("/api/tags")
    rows = resp.get("models") if isinstance(resp, dict) else None
    if type(rows) is not list:
        raise TypeError("malformed Ollama inventory")
    if len(rows) > 128:
        raise ValueError("Ollama inventory exceeds bounds")
    out = []
    for m in rows:
        if not isinstance(m, dict):
            continue
        name, digest = m.get("name"), m.get("digest")
        if not isinstance(name, str) or not name or len(name) > 512:
            continue
        if not isinstance(digest, str) or not digest:
            continue
        try:
            caps = model_capabilities(m)
        except Exception:
            caps = []
        out.append(Capability(name, "model", "ollama:/api/tags:" + digest,
                              completion="completion" in caps))
    return tuple(out)


def discover_skills(paths):
    """Read exact locally approved metadata paths; never recursively enumerate hubs."""
    if len(paths) > 64:
        raise ValueError("too many skill metadata paths")
    out = []
    for p in paths:
        p = Path(p).resolve(strict=True)
        if p.name != "SKILL.md" or p.stat().st_size > 65536:
            raise ValueError("invalid local skill metadata")
        lines = p.read_text().splitlines()
        meta = {}
        if lines and lines[0] == "---":
            for line in lines[1:]:
                if line == "---":
                    break
                key, _, value = line.partition(":")
                if key in {"name", "description"}:
                    meta[key] = value.strip().strip('"')
        # Paths distinguish colliding skill names; IDs cannot be inferred from names alone.
        out.append(Capability(str(p), "skill", str(p), meta.get("description", "")[:2000]))
    return tuple(out)


def read_request(path):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise ValueError("request exceeds 64 KiB")
    data = json.loads(path.read_text())
    # Resolve repo-relative image fixtures against the request file so
    # published fixtures stay portable. Validation still requires bounded
    # absolute local files; resolution happens before validation, never
    # instead of it.
    data["images"] = [
        i if Path(i).is_absolute() else str((path.parent / i).resolve())
        for i in data.get("images", [])
    ]
    data["state"] = DecisionState(**data["state"])
    data["questions"] = tuple(DecisionQuestion(**q) for q in data["questions"])
    data["inventory"] = CapabilitySnapshot(tuple(Capability(**c) for c in data["inventory"]["capabilities"]))
    req = BoundedRequest(**data)
    req.validate()
    return req


def run_cli(args):
    req = read_request(args.request)
    config = load_config(str(Path(__file__).resolve().parents[2]/"config.yaml"))
    backend = None
    cloud_gate = None
    if args.backend == "qwen":
        backend = ExistingQwenBackend(args.model or "", req.inventory)
    elif args.backend == "d1":
        backend = LiquidD1Backend(args.snapshot, args.python, enabled=args.approve_d1, approved=args.approve_d1)
    elif args.backend == "freellm":
        fcfg = config.get("freellm", {}) or {}
        qcfg = fcfg.get("quota") if isinstance(fcfg.get("quota"), dict) else {}
        quota = QuotaTracker(**{k: qcfg[k] for k in ("max_failures", "cooldown") if k in qcfg})
        cloud_gate = cloud_eligible(req, config, quota, args.model)
        if cloud_gate["allowed"] and args.approve_cloud:
            _, json_ok = discover_freellm_models(fcfg.get("base_url"))
            backend = FreeLLMBackend(args.model or "", req.inventory,
                                     base_url=fcfg.get("base_url"),
                                     json_mode=(args.model or "") in json_ok, quota=quota,
                                     enabled=True, approved=True,
                                     allow_private=fcfg.get("allow_private", False))
    observed = DecisionEngine(config).observe(req, backend)
    out = {"authoritative": asdict(observed.authoritative),
           "shadow": asdict(observed.observation),
           "metadata": observed.metadata()}
    if cloud_gate is not None:
        out["cloud_eligibility"] = cloud_gate
    print(json.dumps(out, indent=2, allow_nan=False))
    return 0
