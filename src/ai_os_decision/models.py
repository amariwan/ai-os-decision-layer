"""Pure data models. No I/O, no ML. stdlib only."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DecisionQuestion:
    """One typed question for the decision engine.

    kind: choice | score | boolean
    For choice: options maps key -> description (description may be None).
    For score/boolean: criteria is an ordered legend / optional wording.
    """

    id: str
    kind: str  # choice | score | boolean
    instructions: str
    options: dict = field(default_factory=dict)
    criteria: list = field(default_factory=list)

    def validate(self) -> None:
        if self.kind not in ("choice", "score", "boolean"):
            raise ValueError(f"unknown question kind: {self.kind}")
        if self.kind == "choice" and len(self.options) < 2:
            raise ValueError(f"choice question {self.id} needs >=2 options")
        if self.kind == "score" and len(self.criteria) < 2:
            raise ValueError(f"score question {self.id} needs >=2 criteria")


@dataclass(frozen=True)
class DecisionState:
    """Minimal structured state. Never a full Brain dump."""

    text: str = ""
    intent: str | None = None
    environment: str = "dev"
    repository: str = ""
    branch: str = ""
    actor_type: str = "user"
    permissions: tuple = ()
    available_agents: tuple = ()
    available_tools: tuple = ()
    extra: dict = field(default_factory=dict)

    def to_laya_state(self) -> dict:
        """Compact dict for Laya. Drops None/empty to save tokens."""
        state: dict = {}
        if self.text:
            state["text"] = self.text[:2000]
        if self.intent:
            state["intent"] = self.intent
        ctx = {
            k: v
            for k, v in {
                "environment": self.environment,
                "repository": self.repository,
                "branch": self.branch,
            }.items()
            if v
        }
        if ctx:
            state["context"] = ctx
        if self.actor_type:
            state["actor"] = {"type": self.actor_type, "permissions": list(self.permissions)}
        if self.available_agents:
            state["available_agents"] = list(self.available_agents)
        if self.available_tools:
            state["available_tools"] = list(self.available_tools)
        for k, v in self.extra.items():
            if k not in state:
                state[k] = v
        return state


@dataclass(frozen=True)
class DecisionAnswer:
    question_id: str
    kind: str
    value: object  # choice key | float score | bool
    confidence: float  # MODEL SCORE, not calibrated probability
    probabilities: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionResult:
    answers: dict  # question_id -> DecisionAnswer
    provider: str  # laya | rule | llm-stub
    latency_ms: float
    fallback_used: bool = False
    policy_override: bool = False
    decision_id: str = ""
    raw_routing: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionLog:
    decision_id: str
    timestamp: str
    decision_type: str
    selected_option: str
    confidence: float
    provider: str
    latency_ms: float
    fallback_used: bool
    policy_override: bool
    execution_result: str = ""


@dataclass(frozen=True)
class ConfidenceGate:
    auto_execute: float = 0.90
    verify: float = 0.70

    def route(self, confidence: float) -> str:
        """high -> execute, medium -> verify, low -> escalate."""
        if confidence >= self.auto_execute:
            return "execute"
        if confidence >= self.verify:
            return "verify"
        return "escalate"


def load_config(path: str | None = None) -> dict:
    """Tiny YAML subset loader (no PyYAML dependency).

    Supports nested maps + lists + scalars used by config.yaml.
    """
    path = path or os.environ.get(
        "AI_OS_DECISION_CONFIG",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "config.yaml"),
    )
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        lines = f.readlines()
    # single recursive parse (no placeholder pass):
    return _parse_simple_yaml(lines)


def _scalar(s: str):
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "Null", "~"):
        return None
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _parse_simple_yaml(lines: list[str]) -> dict:
    root: dict = {}

    def parse_block(idx: int, indent: int):
        obj: dict = {}
        items: list | None = None
        while idx < len(lines):
            raw = lines[idx]
            if not raw.strip() or raw.lstrip().startswith("#"):
                idx += 1
                continue
            cur = len(raw) - len(raw.lstrip(" "))
            if cur < indent:
                break
            if cur > indent:
                idx += 1
                continue
            content = raw.strip()
            if content.startswith("- "):
                if items is None:
                    items = []
                item, idx = _parse_list_item(lines, idx, cur)
                items.append(item)
                continue
            if items is not None:
                break
            if ":" not in content:
                idx += 1
                continue
            key, _, rest = content.partition(":")
            key = key.strip()
            rest = rest.strip()
            if rest != "":
                obj[key] = _scalar(rest)
                idx += 1
            else:
                # peek next non-empty
                nxt = idx + 1
                while nxt < len(lines) and (not lines[nxt].strip() or lines[nxt].lstrip().startswith("#")):
                    nxt += 1
                if nxt < len(lines) and lines[nxt].strip().startswith("- "):
                    lst: list = []
                    idx = nxt
                    while idx < len(lines):
                        r2 = lines[idx]
                        if not r2.strip() or r2.lstrip().startswith("#"):
                            idx += 1
                            continue
                        c2 = len(r2) - len(r2.lstrip(" "))
                        if c2 < len(lines[nxt]) - len(lines[nxt].lstrip(" ")):
                            break
                        cc = r2.strip()
                        if not cc.startswith("- "):
                            break
                        item, idx = _parse_list_item(lines, idx, c2)
                        if isinstance(item, dict):
                            lst.append({k: _split_inline(v) for k, v in item.items()})
                        else:
                            lst.append(_split_inline(item))
                    obj[key] = lst
                else:
                    sub, idx = parse_block(nxt, (len(lines[nxt]) - len(lines[nxt].lstrip(" ")) if nxt < len(lines) else indent + 2))
                    obj[key] = sub
        return obj, idx

    parsed, _ = parse_block(0, 0)
    return parsed


def _parse_list_item(lines: list[str], idx: int, indent: int):
    """Parse one `- ...` item plus its indented continuation lines.

    Multi-key mappings stay a single item instead of silently dropping
    continuation keys (e.g. `- env: production` + `actions: [...]`).
    Returns (item, next_idx).
    """
    content = lines[idx].strip()[2:].strip()
    if ":" in content and not content.startswith('"'):
        k, _, v = content.partition(":")
        k, v = k.strip(), v.strip()
        if v == "":
            sub, idx = _parse_nested_value(lines, idx + 1, indent + 2)
            item: dict = {k: sub}
        else:
            item = {k: _split_inline(_scalar(v))}
            idx += 1
        # Merge continuation `key: value` lines belonging to the same item.
        while idx < len(lines):
            raw = lines[idx]
            if not raw.strip() or raw.lstrip().startswith("#"):
                idx += 1
                continue
            cur = len(raw) - len(raw.lstrip(" "))
            if cur <= indent or raw.strip().startswith("- "):
                break
            cont = raw.strip()
            if ":" not in cont:
                idx += 1
                continue
            ck, _, cv = cont.partition(":")
            ck, cv = ck.strip(), cv.strip()
            if cv == "":
                sub, idx = _parse_nested_value(lines, idx + 1, cur + 2)
                item[ck] = sub
            else:
                item[ck] = _split_inline(_scalar(cv))
                idx += 1
        return item, idx
    idx += 1
    return _split_inline(_scalar(content)), idx


def _parse_nested_value(lines: list[str], idx: int, indent: int):
    """Parse an indented nested block after an empty `key:` (map or list)."""
    nxt = idx
    while nxt < len(lines) and (not lines[nxt].strip() or lines[nxt].lstrip().startswith("#")):
        nxt += 1
    if nxt < len(lines) and lines[nxt].strip().startswith("- "):
        lst: list = []
        idx = nxt
        base = len(lines[nxt]) - len(lines[nxt].lstrip(" "))
        while idx < len(lines):
            r2 = lines[idx]
            if not r2.strip() or r2.lstrip().startswith("#"):
                idx += 1
                continue
            c2 = len(r2) - len(r2.lstrip(" "))
            if c2 < base:
                break
            if not r2.strip().startswith("- "):
                break
            item, idx = _parse_list_item(lines, idx, c2)
            lst.append(item)
        return lst, idx
    # Re-parse a nested map with a minimal recursive descent.
    obj: dict = {}
    while nxt < len(lines):
        raw = lines[nxt]
        if not raw.strip() or raw.lstrip().startswith("#"):
            nxt += 1
            continue
        cur = len(raw) - len(raw.lstrip(" "))
        if cur < indent:
            break
        if cur > indent:
            nxt += 1
            continue
        content = raw.strip()
        if content.startswith("- ") or ":" not in content:
            break
        key, _, rest = content.partition(":")
        key, rest = key.strip(), rest.strip()
        if rest != "":
            obj[key] = _scalar(rest)
            nxt += 1
        else:
            sub, nxt = _parse_nested_value(lines, nxt + 1, cur + 2)
            obj[key] = sub
    return obj, nxt


def _split_inline(v):
    if isinstance(v, str) and v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [ _scalar(p.strip()) for p in inner.split(",") ]
    return v
