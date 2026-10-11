# Client Compatibility (verified 2026-10-11, read-only)

Prior audit evidence (live CLIs + config files) plus repo-side import docs. Registration ≠ invocation: no client was observed auto-invoking any discovery tool.

| Client | Gateway-as-MCP-server | Discovery workflow w/o custom code | Mandatory routing w/o custom code | Repo-side evidence |
|---|---|---|---|---|
| Codex 0.159.0 | CONFIGURATION_ONLY (`[mcp_servers.*]` stdio+HTTP live, 18 servers) | CONFIGURATION_ONLY if gateway exposes 4–5 meta-tools (discover/search/execute); invocation still model-chosen | UNSUPPORTED (only `enabled_tools`/`approval_mode`, no require primitive) | ToolHive: `pkg/client/codex_desktop.go`, adapters (NATIVE-ish). MCPorter: import matrix+fixtures (OFFICIAL_PLUGIN-equivalent). Others: none named |
| OpenCode v2.0.26 | CONFIGURATION_ONLY (`type:local` stdio live) | CONFIGURATION_ONLY (same meta-tool reasoning) | UNSUPPORTED (only `enabled`) | MCPorter: import matrix incl. opencode.jsonc fixture. Others: none named |
| Claude Code 2.1.287 | CONFIGURATION_ONLY (stdio/SSE/HTTP, allow/deny+hooks) | CONFIGURATION_ONLY | UNSUPPORTED (allow/deny are subtractive; Laya-first gate = custom hook) | ToolHive README names Claude Code. MCPorter import matrix. Others: none named |
| Hermes v0.21.6 | CONFIGURATION_ONLY (`mcp add --command`, store empty) | UNVERIFIED (zero servers configured; capability inferred from `--help`) | UNSUPPORTED (no hooks/policies configured) | None of the 9 repos name Hermes; ToolHive `client status` table has NO Hermes row (verified live) |

## Consequences
- A gateway presenting `search_tools`/`execute_tool` meta-tools is usable from all four clients after a few lines of config — but whether the model *calls* search before answering is per-request model behavior, not enforceable (all four: CUSTOM_CODE_REQUIRED for enforcement, which the mission forbids).
- Practical effect: gateways reduce context load (progressive disclosure) and centralize credentials, but **cannot guarantee** the agent discovers instead of guesses. Any claim of "automatic routing" without hooks is UNSUPPORTED.
- Skill discovery: only MCPorter documents a no-duplication pattern (one small skill per server, `generate-cli` alternative). No gateway indexes existing `~/.agents/skills` or per-client skill dirs — skill search stays OUTSIDE every gateway evaluated.
