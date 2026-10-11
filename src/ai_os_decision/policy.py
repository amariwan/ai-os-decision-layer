"""Hard policy pre-check. Always wins over Laya/LLM. Fail closed."""
from __future__ import annotations


class PolicyEngine:
    def __init__(self, config: dict):
        p = (config or {}).get("policy", {})
        self.version: str = str(p.get("version", "1.0.0"))
        self.deny_patterns: list[str] = [str(x).lower() for x in p.get("deny_patterns", [])]
        self.approval_required: list[dict] = list(p.get("approval_required", []) or [])
        self.fail_closed: bool = bool(p.get("fail_closed", True))

    def check(self, text: str, environment: str = "", action_hint: str = "") -> dict:
        """Returns {denied, approval_required, risk, reasons}."""
        t = (text or "").lower()
        reasons: list[str] = []
        denied = any(pat in t for pat in self.deny_patterns)
        if denied:
            reasons.append("deny_pattern_match")
        approval = False
        for rule in self.approval_required:
            env = str(rule.get("env", ""))
            actions = [str(a).lower() for a in rule.get("actions", [])]
            if env and env.lower() == (environment or "").lower():
                if any(a in t for a in actions) or (action_hint and action_hint.lower() in actions):
                    approval = True
                    reasons.append(f"approval_required:env={env}")
                    break
        risk = 1.0 if denied or approval else 0.0
        return {"denied": denied, "approval_required": approval, "risk": risk, "reasons": reasons}
