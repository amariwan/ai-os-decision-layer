# Security Review (read-only, no probes executed)

## Per-project posture (observed files, advisories UNVERIFIED — registry API 403)
| Project | SECURITY.md | Auth model | Secret handling | Notes |
|---|---|---|---|---|
| ContextForge | YES (Admin-UI-dev-only, no backport patches) | Basic/JWT/custom, per-user OAuth, upstream-auth passthrough, rate limits | `JWT_SECRET_KEY`+`AUTH_ENCRYPTION_SECRET` required at deploy | Largest attack surface (Admin UI, federation, REST virtualization); pin + isolate PoC |
| ToolHive | YES (security@stacklok.com) | Per-request identity+policy, IdP OIDC/OAuth, SSO, OTel audit | Container isolation per server | PoC-observed: unverified images run with WARNING only (no deny); `--tools` filter + permission profiles + egress proxy verified in `--help` |
| MCPorter | NOT FOUND | Client-side OAuth/bearer/env, allow/block lists | Vault helper | No server side — risk sits in local CLIs it generates; low blast radius |
| fastmcp-gateway | NOT FOUND | Bearer registration token, per-domain headers, fnmatch allow/deny, execution hooks | Registration token is the crown jewel — PoC must rotate, never commit | Alpha + bus-factor 1: audit before any non-localhost use |
| Portkey filter | NOT FOUND | None (embedding key only) | API keys only if cloud embeddings chosen; local Xenova avoids exfiltration | Lib, no network surface of its own |
| DMCP | UNKNOWN | ? | ? | Excluded regardless |
| agentgateway | UNVERIFIED (not fetched) | ? (likely JWT/OIDC per proxy norms — UNVERIFIED) | ? | Verify before PoC phase 2 |

## Policy constraints (binding for any PoC)
- No private task content to cloud: PoC uses the 120 synthetic states only; cloud embedding options (OpenAI/Voyage/Cohere in Portkey/aurelio) are FORBIDDEN in PoC — local Xenova/MiniLM/BGE/EmbeddingGemma only.
- Localhost-only; no public exposure; no credential writes to agent configs; `LAYA_API_KEY`-style bearer tokens via env, never committed (policy §17: no secrets in memory/handoffs/logs).
- Hard authorization/privacy gates stay deterministic in the Decision Layer — no gateway policy replaces `deny_patterns`, production approvals, or `fail_closed:true`.
- Existing MCP inventory already includes secret-adjacent servers (Obsidian vault, Docker, browsers) — a federating gateway must not broaden their scopes; PoC registers read-only test upstreams first.
