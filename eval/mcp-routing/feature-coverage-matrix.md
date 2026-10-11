# Feature Coverage Matrix

Evidence: repo trees + READMEs + raw manifests, 2026-10-11. `YES` = file/doc evidence observed; `~` = partial; `?` = UNVERIFIED; `—` = no evidence. Laya row = official 0.4.2 package (not the stale fork).

| Capability | ContextForge 1.0.11 | ToolHive 0.51.4 | MCPorter 0.14.2 | fastmcp-gw 0.33.0 | Portkey filter 1.0.0 | DMCP (stale) | agentgateway 1.6.0 | Laya 0.4.2 | Aurelio 0.1.16 |
|---|---|---|---|---|---|---|---|---|---|
| Central registry | YES | YES | — (local json) | YES (in-mem) | — (lib input) | YES | YES | — | — |
| Dynamic discovery | YES (federation+gRPC) | YES (hybrid) | ~ (per-server) | YES (REST+token) | — | YES | YES | — | — |
| Search across tools | YES (UI; semantic ?) | NO (PoC: keyword-only; 0/8 multi-word) | — | YES (domains) | YES (cosine) | YES (HNSW) | ? | — | — |
| Progressive disclosure | ~ (TOON+preview) | YES (filter/descs) | ~ (brief/schema) | YES (4 meta-tools) | YES (topK/schema) | YES (meta-tool) | ? | — | — |
| Auth / ACL | YES (JWT/OAuth/rate) | YES (OIDC/Policy) | ~ (client-side) | YES (hooks+globs) | — | ? | ? | YES (API key) | — |
| 100+ selection | ? | NO (PoC: unordered sets, no ranker) | — | YES (100s) | YES (1000→20) | YES (claim) | ? | NO (0.00 meas.) | weak (meas.) |
| Semantic ranking | ? | NO (PoC-measured absence) | — | — | YES | YES (e5) | ? | ~ (small sets) | YES (emb.) |
| Min-relevance cfg | ? | ? | — | — (depth only) | YES (minScore) | ? | ? | ~ (gates) | YES (threshold) |
| Abstention | ? | ? | ~ (decline elicitation) | ~ (not_found+hint) | ~ (empty list ?) | ? | ? | NO (meas.) | YES (meas. None) |
| Local inference | ? | — | — (advocates sep. skills) | — | YES (Xenova) | — | — | YES (CPU/MPS) | YES (local extra) |
| SKILL.md dirs | — | ~(contrib only) | YES (per-server) | — | — | — | — | — | — |
| Ollama routing | — | — | — | — | — | — | — | — | — |
| Graphiti/Neo4j | — | — | — | — | — | — | — | — | — |
| MCP server (own) | YES (proxy) | YES (gateway) | — (CLI+daemon) | YES | — | YES | YES | YES (4 tools) | — |
| HTTP endpoint | YES | YES | ? | YES | — | YES | YES | YES | — |

## Read-out
- No candidate covers the Skills + Ollama + Graphiti rows — those stay with existing infrastructure regardless of platform choice (see recommended-platform.md).
- Discovery+disclosure is genuinely covered by 4+ projects; **semantic ranking with a tunable threshold is only evidenced in Portkey (lib) and aurelio (lib)** — gateways claim search but expose no measurable relevance knob without install-and-probe.
- Abstention worth the name exists only in aurelio (`None`) among measured systems; gateway `tool_not_found` hints are error paths, not decisions.
- Zero repos reference Laya/convaiinnovations (tree greps across ~7k files) — any gateway+Laya composition is CONFIGURATION_ONLY at registration level, CUSTOM_CODE_REQUIRED for semantic hand-off.
