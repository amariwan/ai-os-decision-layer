# Migration & Rollback Plan

## Current state (nothing migrated, nothing installed in this task)
All four clients keep independent configs; Decision Layer deterministic gates unchanged; Graphiti/Neo4j untouched; gateway PoCs not started. Rollback baseline = present state (zero drift — verified: no writes outside `decision-layer/eval/mcp-routing/*.md` docs).

## Retireable-if-PoC-passes (only after measured bars + explicit approval each)
1. Custom Decision Layer routing logic → gateway registry + BGE/aurelio rankers. KEEP the deterministic policy gates (`deny_patterns`, approvals, `fail_closed`) permanently — they are not rankers and never migrate into a model.
2. Per-client MCP sprawl (18 Codex servers, 3 OpenCode, etc.) → single gateway inventory with per-client views. Migrate one client at a time, Codex first, others only after 2 weeks of shadow agreement ≥ 0.95.
3. Ad-hoc skill/tool shortlists → gateway search + per-server SKILL.md pattern (MCPorter-style, no rewrites).

## Never retired
Graphiti/Neo4j memory, Ollama model serving, local Skills directories, Laya leaf-decision role, audit logs.

## Rollback per stage (all reversible, all local)
- PoC binaries/containers: `toolhive stop` / remove image + temp `CODEX_HOME`; verify `mcp list` outputs match pre-PoC snapshots (take before/after diffs as evidence).
- Failed bars: keep Decision Layer as-is; archive PoC logs under `eval/mcp-routing/poc-<name>/`; no client ever pointed at removed infra (temp HOME only).
- Accidental scope broadening: revoke PoC tokens, rotate any touched secret (none planned), re-run read-only config diff.
- Data: benchmark dataset stays in `/tmp` until a persistence approval moves it into `eval/`; no production data enters PoC queries (120 synthetic states only).
