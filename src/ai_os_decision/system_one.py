"""Bounded recommendations for the existing host; no tool execution or permission grants.

The caller is the trusted boundary: inventories and deterministic requirements come
from runtime discovery/policy, never from task text or a model. No persistent store.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from ai_os_decision.laya_engine import to_laya_questions
from ai_os_decision.models import DecisionAnswer, DecisionQuestion, DecisionState
from ai_os_decision.policy import PolicyEngine

Risk = Literal["low", "medium", "high", "critical"]
RISKS = ("low", "medium", "high", "critical")
SAFE_ACTIONS = {"read", "local-edit", "local-test", "diagnose"}


@dataclass(frozen=True)
class Capability:
    id: str
    kind: Literal["skill", "model", "tool", "agent", "context"]
    source: str
    description: str = ""
    completion: bool = False


@dataclass(frozen=True)
class CapabilitySnapshot:
    capabilities: tuple[Capability, ...]

    def validate(self):
        pairs = [(c.kind, c.id) for c in self.capabilities]
        if len(pairs) != len(set(pairs)) or len(pairs) > 256:
            raise ValueError("duplicate or excessive capabilities")
        for c in self.capabilities:
            if c.kind not in {"skill", "model", "tool", "agent", "context"}:
                raise ValueError("invalid capability category")
            if not c.id or not c.source or len(c.id) > 512 or len(c.description) > 2000:
                raise ValueError("invalid capability provenance/size")

    def ids(self, kind):
        return {c.id for c in self.capabilities if c.kind == kind}


@dataclass(frozen=True)
class BoundedRequest:
    state: DecisionState
    questions: tuple[DecisionQuestion, ...]
    fallback_answers: dict
    inventory: CapabilitySnapshot
    candidate_kinds: dict[str, str] = field(default_factory=dict)
    required_answers: dict = field(default_factory=dict)
    minimum_risk: Risk = "medium"
    # Unknown action is protected; do not derive authority from a model prediction.
    action: str = "unknown"
    approval_required: bool = False
    denied: bool = False
    images: tuple[str, ...] = ()

    def validate(self):
        self.inventory.validate()
        if self.minimum_risk not in RISKS or type(self.approval_required) is not bool or type(self.denied) is not bool:
            raise ValueError("invalid trusted policy envelope")
        ids = [q.id for q in self.questions]
        if not ids or len(ids) > 32 or len(ids) != len(set(ids)):
            raise ValueError("questions must have unique bounded IDs")
        if set(self.fallback_answers) != set(ids) or not set(self.required_answers) <= set(ids):
            raise ValueError("incomplete deterministic answers")
        if not set(self.candidate_kinds) <= set(ids):
            raise ValueError("unknown candidate question")
        for q in self.questions:
            q.validate()
            if not q.id or len(q.id) > 512 or len(q.instructions) > 2000:
                raise ValueError("question exceeds bounds")
            if q.kind == "choice" and not 2 <= len(q.options) <= 64:
                raise ValueError("choice size exceeds bounds")
            if q.kind == "score" and not 2 <= len(q.criteria) <= 10:
                raise ValueError("score needs 2..10 levels")
            reserved = {"selected_model": "model", "selected_tool": "tool", "selected_skill": "skill", "selected_agent": "agent"}
            kind = reserved.get(q.id, self.candidate_kinds.get(q.id))
            if q.id in reserved and q.id in self.candidate_kinds and self.candidate_kinds[q.id] != reserved[q.id]:
                raise ValueError("reserved candidate category mismatch")
            if kind is not None:
                if q.kind != "choice" or not set(q.options) <= self.inventory.ids(kind):
                    raise ValueError("undiscovered candidate")
            domains = {"complexity": {"low", "medium", "high"},
                       "risk": set(RISKS),
                       "task_type": {"bugfix", "feature", "refactor", "research", "operations", "other"}}
            if q.id in domains and (q.kind != "choice" or not set(q.options) <= domains[q.id]):
                raise ValueError("invalid normalized field domain")
            if q.id in {"retrieve_memory", "needs_review", "requires_human_approval"} and q.kind != "boolean":
                raise ValueError("normalized field requires boolean")
            _validate_value(q, self.fallback_answers[q.id])
            if q.id in self.required_answers:
                _validate_value(q, self.required_answers[q.id])
            for prefix, kind in (("skill:", "skill"), ("tool:", "tool")):
                if q.id.startswith(prefix) and (q.kind != "boolean" or q.id[len(prefix):] not in self.inventory.ids(kind)):
                    raise ValueError("undiscovered boolean candidate")
        if len(self.images) > 2:
            raise ValueError("maximum two local image fixtures")
        for image in self.images:
            p = Path(image)
            if not p.is_absolute() or not p.is_file() or p.stat().st_size > 4*1024*1024:
                raise ValueError("image must be a bounded local file")
        # Bound complete serialized input; never silently truncate safety context.
        if len(json.dumps(asdict(self), allow_nan=False).encode()) > 65536:
            raise ValueError("request exceeds 64 KiB")

    def wire(self):
        return {"state": asdict(self.state), "questions": to_laya_questions(list(self.questions)), "images": self.images}


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("nonfinite or nonnumeric model value")
    return float(value)


def _prob(value):
    p = _number(value)
    if not 0 <= p <= 1:
        raise ValueError("probability outside [0,1]")
    return p


def _validate_value(q, value):
    if q.kind == "choice" and (not isinstance(value, str) or value not in q.options):
        raise ValueError("invalid choice")
    if q.kind == "boolean" and type(value) is not bool:
        raise ValueError("invalid boolean")
    if q.kind == "score" and not 0 <= _number(value) <= len(q.criteria)-1:
        raise ValueError("invalid score")


def validate_native(req: BoundedRequest, raw: dict):
    """Reject incomplete, inconsistent, invented or nonfinite native responses."""
    req.validate()
    if not isinstance(raw, dict) or set(raw.get("answers", {})) != {q.id for q in req.questions}:
        raise ValueError("incomplete native answers")
    result = {}
    for q in req.questions:
        a = raw["answers"][q.id]
        expected = {"boolean": "noul", "choice": "choice", "score": "score"}[q.kind]
        if a.get("type") != expected:
            raise ValueError("native answer type mismatch")
        if q.kind == "boolean":
            p = _prob(a["noul"])
            result[q.id] = DecisionAnswer(q.id, q.kind, p >= .5, max(p, 1-p), {"true": p, "false": 1-p})
            continue
        keys = set(q.options) if q.kind == "choice" else {str(i) for i in range(len(q.criteria))}
        probs = {k: _prob(v) for k, v in a["probabilities"].items()}
        if set(probs) != keys or abs(sum(probs.values()) - 1) > 1e-5:
            raise ValueError("invalid distribution")
        confidence = _prob(a["confidence"])
        if abs(confidence - max(probs.values())) > 1e-5:
            raise ValueError("inconsistent confidence")
        value = a[expected]
        _validate_value(q, value)
        if q.kind == "choice" and abs(probs[value] - confidence) > 1e-5:
            raise ValueError("choice disagrees with distribution")
        if q.kind == "score":
            if abs(_number(value) - sum(int(k)*p for k, p in probs.items())) > 1e-5:
                raise ValueError("score disagrees with expectation")
            if a.get("legend") != {str(i): x for i, x in enumerate(q.criteria)}:
                raise ValueError("score legend mismatch")
        result[q.id] = DecisionAnswer(q.id, q.kind, value, confidence, probs)
    usage = raw.get("usage", {})
    if set(usage) != {"input_tokens", "output_tokens"} or any(type(v) is not int or v < 0 for v in usage.values()):
        raise ValueError("invalid token usage")
    return result, dict(usage)


class Backend(Protocol):
    name: str

    def infer(self, request: BoundedRequest) -> dict: ...


class DeterministicFallback:
    name = "deterministic"

    def infer(self, request):
        request.validate()
        answers = {}
        for q in request.questions:
            v = request.required_answers.get(q.id, request.fallback_answers[q.id])
            if q.kind == "boolean":
                answers[q.id] = {"type": "noul", "noul": float(v)}
            elif q.kind == "choice":
                answers[q.id] = {"type": "choice", "choice": v, "confidence": 1.0,
                                 "probabilities": {k: float(k == v) for k in q.options}}
            else:
                # Represent fractional expected levels by adjacent levels.
                lo, hi = math.floor(v), math.ceil(v)
                probs = {str(i): 0.0 for i in range(len(q.criteria))}
                probs[str(lo)] = 1 - (v-lo)
                if hi != lo:
                    probs[str(hi)] = v-lo
                answers[q.id] = {"type": "score", "score": float(v), "confidence": max(probs.values()),
                                 "probabilities": probs, "legend": {str(i): x for i, x in enumerate(q.criteria)}}
        return {"answers": answers, "usage": {"input_tokens": 0, "output_tokens": 0}}


@dataclass(frozen=True)
class Recommendation:
    answers: dict[str, DecisionAnswer]
    decision_source: str
    risk: Risk
    requires_human_approval: bool
    denied: bool
    fallback_used: bool
    uncertainty: tuple[str, ...]
    latency_ms: float
    usage: dict
    error: str | None = None
    confidence_semantics: str = "deterministic-encoding-not-statistical-confidence"
    measurement: dict = field(default_factory=dict)

    def application_contract(self, inventory: CapabilitySnapshot):
        """Optional normalized planning fields; absence stays None, never invented."""
        get = lambda key: self.answers[key].value if key in self.answers else None
        model = get("selected_model")
        skills = [k.removeprefix("skill:") for k, a in self.answers.items() if k.startswith("skill:") and a.value is True]
        tools = [k.removeprefix("tool:") for k, a in self.answers.items() if k.startswith("tool:") and a.value is True]
        if model is not None and model not in inventory.ids("model"):
            raise ValueError("unavailable normalized model")
        if not set(skills) <= inventory.ids("skill") or not set(tools) <= inventory.ids("tool"):
            raise ValueError("unavailable normalized capability")
        if get("complexity") not in (None, "low", "medium", "high"):
            raise ValueError("invalid normalized complexity")
        if get("task_type") not in (None, "bugfix", "feature", "refactor", "research", "operations", "other"):
            raise ValueError("invalid normalized task type")
        for key in ("retrieve_memory", "needs_review"):
            if get(key) is not None and type(get(key)) is not bool:
                raise ValueError("invalid normalized boolean")
        return {"task_type": get("task_type"), "complexity": get("complexity"), "risk": self.risk,
                "selected_model": model, "selected_skills": skills, "selected_tools": tools,
                "retrieve_memory": get("retrieve_memory"), "needs_review": get("needs_review"),
                "decision_source": self.decision_source, "requires_human_approval": self.requires_human_approval}


@dataclass(frozen=True)
class ShadowObservation:
    authoritative: Recommendation
    observation: Recommendation

    def metadata(self):
        # Counts and source names only: no task, arbitrary IDs, selected values or exception text.
        return {"schema": "system-one-shadow/v1", "source": self.observation.decision_source,
                "fallback": self.observation.fallback_used, "error": self.observation.error,
                "latency_ms": self.observation.latency_ms, "usage": self.observation.usage,
                "questions": len(self.authoritative.answers),
                "agreements": sum(self.authoritative.answers[k].value == a.value
                                  for k, a in self.observation.answers.items())}


# Heuristic pre-cloud screen. Blocks secret-like content unless explicitly authorized.
# Never logs or returns the input; reasons name only the matched hint class.
SENSITIVE_HINTS = ("api_key", "apikey", "bearer ", "authorization:", "-----begin",
                   "private key", "password", "passwd", "aws_secret", "ghp_", "gsk_",
                   "sk-", "xoxb-", "credentials", "client_secret")


def privacy_screen(text, *, allow_private=False):
    """Decide whether request text may leave the local environment."""
    hits = sorted({h for h in SENSITIVE_HINTS if h in (text or "").lower()})
    if hits and not allow_private:
        return {"allowed": False, "reason": "sensitive-content:" + hits[0]}
    return {"allowed": True, "reason": "clear" if not hits else "explicitly-authorized"}


class QuotaTracker:
    """In-memory cloud circuit breaker. No persistence, no background threads."""

    def __init__(self, max_failures=3, cooldown=300):
        self.max_failures = max(1, int(max_failures))
        self.cooldown = max(1.0, min(float(cooldown), 3600.0))
        self.failures = 0
        self.cool_until = 0.0

    def record(self, err):
        import time
        kind = err.get("type") if isinstance(err, dict) else None
        if kind == "ok":
            self.failures, self.cool_until = 0, 0.0
            return
        self.failures += 1
        if kind == "rate_limited" and isinstance(err, dict):
            try:
                wait = max(1.0, min(float(err.get("retry_after") or self.cooldown), 3600.0))
            except (TypeError, ValueError):
                wait = self.cooldown
            self.cool_until = max(self.cool_until, time.time() + wait)
        elif self.failures >= self.max_failures:
            self.cool_until = max(self.cool_until, time.time() + self.cooldown)

    def allow(self):
        import time
        if time.time() < self.cool_until:
            return False
        return self.failures < self.max_failures

    def state(self):
        return {"consecutive_failures": self.failures, "cool_until": self.cool_until,
                "open": not self.allow()}


def cloud_eligible(request, config, quota=None, model=None):
    """Gate cloud escalation: disabled by default, privacy-screened, quota-aware."""
    cfg = (config or {}).get("freellm", {}) or {}
    if not cfg.get("enabled"):
        return {"allowed": False, "reason": "cloud-disabled"}
    screen = privacy_screen(request.state.text, allow_private=bool(cfg.get("allow_private")))
    if not screen["allowed"]:
        return {"allowed": False, "reason": screen["reason"]}
    allowed = cfg.get("allowed_models") or []
    if isinstance(allowed, str):
        # The minimal config loader keeps inline `[]` as a string.
        allowed = [] if allowed.strip() in ("", "[]") else [allowed]
    if model is not None and allowed and model not in allowed:
        return {"allowed": False, "reason": "model-not-allowlisted"}
    if quota is not None and not quota.allow():
        return {"allowed": False, "reason": "quota-cooldown"}
    return {"allowed": True, "reason": "eligible"}


class SystemOneRuntime:
    """Recommendation-only extension used by DecisionEngine. No active routing mode."""
    def __init__(self, backend: Backend | None = None, config: dict | None = None, cache_size=128):
        self.backend = backend or DeterministicFallback()
        self.fallback = DeterministicFallback()
        self.policy = PolicyEngine(config or {})
        self.cache_size = max(0, min(cache_size, 128))
        self._cache = {}

    def decide(self, req: BoundedRequest):
        req.validate()
        started = time.perf_counter()
        pol = self.policy.check(req.state.text, req.state.environment, req.action)
        denied = req.denied or pol["denied"]
        protected = req.action not in SAFE_ACTIONS
        approval = bool(denied or protected or req.approval_required or pol["approval_required"])
        floor = max(RISKS.index(req.minimum_risk), 2 if approval else 0)
        cache_input = {"request": asdict(req), "images": [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in req.images]}
        key = hashlib.sha256(json.dumps(cache_input, sort_keys=True, allow_nan=False).encode()).hexdigest()
        fallback, error, measurement = False, None, {}
        source = self.backend.name
        try:
            if denied:
                raise PermissionError("deterministic deny")
            if key in self._cache:
                answers, _ = self._cache[key]
                usage = {"input_tokens": 0, "output_tokens": 0}
                measurement = {"cache_hit": True}
            else:
                raw = self.backend.infer(req)
                answers, usage = validate_native(req, raw)
                for name, value in raw.get("measurement", {}).items():
                    if name in {"load_ms", "warm_ms", "mps_allocated_bytes", "mps_driver_bytes", "rss_bytes", "cpu_seconds"}:
                        if value is not None and _number(value) < 0:
                            raise ValueError("invalid measurement")
                        measurement[name] = value
                    elif name == "device" and value in {"mps", "cpu", "cuda"}:
                        measurement[name] = value
                if source == "liquid-d1" and usage["output_tokens"] != 0:
                    raise ValueError("d1 must use native decisions")
                if self.cache_size:
                    if len(self._cache) >= self.cache_size:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[key] = (answers, usage)
        except Exception as exc:
            answers, usage = validate_native(req, self.fallback.infer(req))
            fallback, source, error = True, self.fallback.name, type(exc).__name__
        # Copy before enforcing requirements: cached data must not be mutable output.
        answers = {k: DecisionAnswer(a.question_id, a.kind, a.value, a.confidence, dict(a.probabilities))
                   for k, a in answers.items()}
        for q in req.questions:
            if q.id in req.required_answers:
                answers[q.id] = validate_native(req, self.fallback.infer(req))[0][q.id]
        model_risk = answers.get("risk")
        if model_risk and isinstance(model_risk.value, str) and model_risk.value in RISKS:
            floor = max(floor, RISKS.index(model_risk.value))
        # A recommendation may increase caution, never decrease it.
        model_approval = answers.get("requires_human_approval")
        approval = approval or bool(model_approval and model_approval.value is True)
        uncertainty = tuple(k for k, a in answers.items() if a.confidence < .7 or source == "qwen")
        semantics = {"qwen": "synthetic-encoding-not-model-confidence",
                     "liquid-d1": "native-distribution-not-task-calibrated"}.get(
                         source, "deterministic-encoding-not-statistical-confidence")
        result = Recommendation(answers, source, RISKS[floor], approval, denied, fallback, uncertainty,
                                (time.perf_counter()-started)*1000, dict(usage), error, semantics, measurement)
        result.application_contract(req.inventory)
        return result

    def shadow(self, req):
        baseline = SystemOneRuntime(config={"policy": {"deny_patterns": self.policy.deny_patterns,
                                   "approval_required": self.policy.approval_required}}).decide(req)
        return ShadowObservation(baseline, self.decide(req))


# Kept here as the public interface; optional inference dependencies stay in a worker.
from ai_os_decision.system_one_backends import ExistingQwenBackend, FreeLLMBackend, LiquidD1Backend  # noqa: F401
