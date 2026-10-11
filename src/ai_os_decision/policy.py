"""Hard policy pre-check. Always wins over Laya/LLM. Fail closed."""
from __future__ import annotations


def validate_policy_config(policy: dict | None) -> dict:
    """Schema check for the `policy` config contract. stdlib only.

    Incomplete or malformed security rules are explicitly rejected with
    ValueError — never silently accepted or weakened. Missing `policy`
    means fail-closed defaults (deny nothing by pattern, require nothing
    by approval, `fail_closed=True`).
    """
    p = dict(policy or {})
    version = p.get("version", "1.0.0")
    if not isinstance(version, str):
        raise TypeError("policy.version must be a non-empty string")
    if not version.strip():
        raise ValueError("policy.version must be a non-empty string")
    deny = p.get("deny_patterns", [])
    if not isinstance(deny, list):
        raise TypeError("policy.deny_patterns must be a list of non-empty strings")
    if any(not isinstance(x, str) or not x.strip() for x in deny):
        raise ValueError("policy.deny_patterns must be a list of non-empty strings")
    approvals = p.get("approval_required", [])
    if not isinstance(approvals, list):
        raise TypeError("policy.approval_required must be a list")
    for rule in approvals:
        if not isinstance(rule, dict):
            raise TypeError("policy.approval_required entries must be mappings")
        env = rule.get("env")
        actions = rule.get("actions")
        if not isinstance(env, str):
            raise TypeError("policy.approval_required entries need a non-empty 'env'")
        if not env.strip():
            raise ValueError("policy.approval_required entries need a non-empty 'env'")
        if not isinstance(actions, list):
            raise TypeError("policy.approval_required entries need a non-empty 'actions' list")
        if (not actions or any(not isinstance(a, str) or not a.strip() for a in actions)):
            raise ValueError("policy.approval_required entries need a non-empty 'actions' list")
        if set(rule) - {"env", "actions"}:
            raise ValueError("policy.approval_required entries allow only 'env' and 'actions'")
    fail_closed = p.get("fail_closed", True)
    if type(fail_closed) is not bool:
        raise TypeError("policy.fail_closed must be a boolean")
    return {"version": version, "deny_patterns": list(deny),
            "approval_required": [dict(r) for r in approvals],
            "fail_closed": fail_closed}


class PolicyEngine:
    def __init__(self, config: dict):
        p = validate_policy_config((config or {}).get("policy"))
        self.version: str = p["version"]
        self.deny_patterns: list[str] = [x.lower() for x in p["deny_patterns"]]
        self.approval_required: list[dict] = p["approval_required"]
        # Fail-closed is the only safe default; every consumer must refuse to
        # run weakened policy silently (invalid configs raise above).
        self.fail_closed: bool = p["fail_closed"]

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
