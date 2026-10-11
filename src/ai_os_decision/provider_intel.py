"""Provider intelligence: typed inventory, benchmark evidence, adaptive ranking.

Pure logic over caller-supplied snapshots; the only I/O is loading a local
evidence file. No inference, no credentials, no network. Factors:

- availability: advertised (listed, not provisioned) < available (provisioned)
  < tested (at least one benchmark attempt) < verified (fresh evidence, >=
  minimum samples). Never promoted without observation.
- capabilities: only what discovery proves (completion/json/tools). Vision is
  never claimed: no discovery source exposes it.
- pricing: None means unknown. "free-tier" is recorded only after a $0-charge
  observation path exists; it never implies unlimited quota.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

AVAILABILITY = ("advertised", "available", "tested", "verified")
PROVIDERS = ("ollama", "freellm")


@dataclass(frozen=True)
class ModelRecord:
    provider: str
    model_id: str
    availability: str
    capabilities: frozenset
    context: int | None
    rate_limit: str | None = None
    pricing: str | None = None
    last_observed: str | None = None
    p50_ms: float | None = None
    success_rate: float | None = None
    samples: int = 0

    def validate(self):
        if self.provider not in PROVIDERS:
            raise ValueError("unknown provider")
        if not self.model_id or len(self.model_id) > 256:
            raise ValueError("invalid model id")
        if self.availability not in AVAILABILITY:
            raise ValueError("invalid availability")
        if not self.capabilities <= {"completion", "json", "tools"}:
            raise ValueError("invented capability")
        if self.context is not None and (not isinstance(self.context, int) or self.context <= 0):
            raise ValueError("invalid context")
        if self.samples < 0:
            raise ValueError("invalid samples")

    def has(self, capability):
        return capability in self.capabilities

    def to_json(self):
        return {"provider": self.provider, "model_id": self.model_id,
                "availability": self.availability, "capabilities": sorted(self.capabilities),
                "context": self.context, "rate_limit": self.rate_limit, "pricing": self.pricing,
                "last_observed": self.last_observed, "p50_ms": self.p50_ms,
                "success_rate": self.success_rate, "samples": self.samples}


def _context_of(row):
    for key in ("context_window", "context_length"):
        value = row.get(key)
        if isinstance(value, int) and value > 0:
            return value
    return None


def build_inventory(ollama_caps, freellm_rows, *, observed_at):
    """Normalize live discovery snapshots into ModelRecords. No invention.

    ollama_caps: Capability tuple from discover_models (completion flags).
    freellm_rows: validated raw /v1/models dicts (freellm_inventory_rows).
    Unavailable cloud rows stay 'advertised'; available ones become 'available'.
    """
    out = []
    for c in ollama_caps or ():
        if c.kind != "model":
            continue
        out.append(ModelRecord("ollama", c.id, "available",
                               frozenset({"completion"}) if c.completion else frozenset(),
                               None, rate_limit="local-no-quota",
                               pricing="local-inference-no-per-token-fee",
                               last_observed=observed_at))
    for m in freellm_rows or ():
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        if not isinstance(mid, str) or not mid or len(mid) > 256:
            continue
        params = m.get("supported_parameters")
        params = params if isinstance(params, list) else []
        caps = set()
        if m.get("available") and "embed" not in mid.lower():
            caps.add("completion")
        if "response_format" in params:
            caps.add("json")
        if "tools" in params:
            caps.add("tools")
        out.append(ModelRecord(
            "freellm", mid, "available" if m.get("available") else "advertised",
            frozenset(caps), _context_of(m),
            rate_limit="tight-free-tier-cooldowns" if m.get("available") else "unprovisioned",
            pricing=None, last_observed=observed_at))
    for r in out:
        r.validate()
    return tuple(out)


@dataclass(frozen=True)
class ModelEvidence:
    model_id: str
    provider: str
    benchmark_version: str
    timestamp: str
    samples: int
    accuracy: float | None
    p50_ms: float | None
    fallback_rate: float | None
    config_hash: str
    provenance: str

    def validate(self):
        if not self.model_id or self.provider not in PROVIDERS or not self.benchmark_version:
            raise ValueError("invalid evidence identity")
        if not isinstance(self.samples, int) or self.samples < 0:
            raise ValueError("invalid evidence samples")
        for field in (self.accuracy, self.fallback_rate):
            if field is not None and not 0 <= field <= 1:
                raise ValueError("evidence rate outside [0,1]")
        if self.p50_ms is not None and self.p50_ms < 0:
            raise ValueError("invalid evidence latency")


def load_evidence_file(path):
    """Load benchmark evidence keyed by (provider, model_id). Malformed entries raise."""
    data = json.loads(Path(path).read_text())
    items = data.get("evidence") if isinstance(data, dict) else None
    if type(items) is not list:
        raise TypeError("malformed evidence file")
    out = {}
    for e in items:
        ev = ModelEvidence(**{k: e[k] for k in (
            "model_id", "provider", "benchmark_version", "timestamp", "samples",
            "accuracy", "p50_ms", "fallback_rate", "config_hash", "provenance")})
        ev.validate()
        out[(ev.provider, ev.model_id)] = ev
    return out


def evidence_is_fresh(ev, *, max_age_days, now_ts):
    """Freshness by timestamp; naive or unparseable timestamps are stale (fail closed)."""
    from datetime import datetime
    try:
        then = datetime.fromisoformat(ev.timestamp)
        if then.tzinfo is None:
            return False
        age = now_ts - then.timestamp()
    except (ValueError, AttributeError):
        return False
    return 0 <= age <= max_age_days * 86400


@dataclass(frozen=True)
class TaskRequirements:
    category: str
    require_json: bool = False
    require_tools: bool = False
    min_context: int | None = None
    allow_cloud: bool = False
    providers: tuple | None = None


def filter_eligible(records, req, *, policy_allows_cloud):
    """Deterministic capability filter. Cloud needs policy + task approval."""
    out = []
    for r in records:
        r.validate()
        if r.availability == "advertised" or "completion" not in r.capabilities:
            continue
        if req.require_json and "json" not in r.capabilities:
            continue
        if req.require_tools and "tools" not in r.capabilities:
            continue
        if req.min_context is not None and (r.context is None or r.context < req.min_context):
            continue
        if req.providers is not None and r.provider not in req.providers:
            continue
        if r.provider != "ollama" and not (policy_allows_cloud and req.allow_cloud):
            continue
        out.append(r)
    return out


def rank_candidates(records, evidence, req, *, min_samples=3, max_age_days=30, now_ts,
                    policy_allows_cloud=False):
    """Rank eligible models by measured evidence. Returns [(record, score|None, reason)].

    score None means insufficient evidence — ranked below measured models and
    never declared a winner. Local models win ties within 0.05 accuracy
    (prefer-local-when-sufficient). Empty ranking + reason when nothing qualifies.
    """
    eligible = filter_eligible(records, req, policy_allows_cloud=policy_allows_cloud)
    ranked, unmeasured = [], []
    for r in eligible:
        ev = evidence.get((r.provider, r.model_id))
        fresh = (ev is not None and ev.samples >= min_samples
                 and evidence_is_fresh(ev, max_age_days=max_age_days, now_ts=now_ts))
        if fresh and ev.accuracy is not None:
            ranked.append((r, ev.accuracy, f"measured-n={ev.samples}"))
        else:
            unmeasured.append((r, None, "insufficient-evidence" if ev is None or ev.samples < min_samples
                               else "stale-evidence"))
    ranked.sort(key=lambda t: (t[1], 1 if t[0].provider == "ollama" else 0), reverse=True)
    # Prefer local on near-ties: bubble an ollama record past a cloud record
    # whose accuracy lead is within 0.05.
    for i in range(len(ranked) - 1):
        if (ranked[i + 1][0].provider == "ollama" and ranked[i][0].provider != "ollama"
                and ranked[i][1] - ranked[i + 1][1] <= 0.05):
            ranked[i], ranked[i + 1] = ranked[i + 1], ranked[i]
    ordered = ranked + sorted(unmeasured, key=lambda t: t[0].model_id)
    return ordered
