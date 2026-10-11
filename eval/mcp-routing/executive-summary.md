# Executive Summary — MCP Discovery & Universal Decision Routing (rev. 2, with ToolHive PoC)

Date: 2026-10-11. Method: live GitHub API + isolated ToolHive v0.51.4 PoC (SHA-256 verified) + 120-case CPU benchmark. No production changes; no custom code.

## Bottom line (unchanged, now evidence-backed)
No maintained open-source project combines multi-server aggregation, semantic 100+ selection with abstention, native Laya use, and official 4-agent support. The PoC **downgraded** the leading gateway candidate: ToolHive's search is keyword-only (all 8 multi-word queries → zero hits), so the recommended shape stays a **composition**: ToolHive (runtime/registry) + BGE reranker (measured 0.796 top-1, flat to 100 options) + aurelio threshold gate (only native abstention) + Laya MCP server as leaf tool.

## Ranked platforms (30/25/20/15/10 weights — criteria, not facts)
1. **ToolHive 0.51.4 — 0.68** (was 0.71; −0.03 after PoC disproved semantic search). Real: container isolation, `--tools` filter, Codex/Claude/OpenCode client rows. Not real: semantic ranking, stdio adoption, live serving in our env (colima networking BLOCKED it).
2. **ContextForge 1.0.11 — 0.66.** Unchanged, UNMEASURED (PoC-2 not run). Richest federation/governance; heaviest ops.
3. **agentgateway 1.6.0 — 0.58.** Unchanged, needs deep inspection before any PoC.
4. **MCPorter 0.14.2 — 0.44.** Per-server CLI+skills pattern, best client-import matrix; not a gateway.
5. **fastmcp-gateway 0.33.0 — 0.38.** Genuine disclosure design, bus-factor 1, Alpha.
6. **Portkey filter 1.0.0 — 0.35 component.** STALE since 2025-11-08.
Excluded: DMCP (stale, no license file), mcp-router (EOL).

## Benchmark headline (measured, spot-verified)
BGE 0.796 / EmbeddingGemma 0.787 / Laya 0.639 / aurelio-forced 0.639 (n=108, CPU). ToolHive discovery: 7/13 single-keyword hits, 0/8 multi-word; 114/120 benchmark cases NOT_APPLICABLE (server-catalog search ≠ option selection). Gateway top-1/top-3/MRR stay UNMEASURED — no estimates reported.

## Direct answers (§11)
1. Best community+features: **ToolHive** (2,268★, 133 contrib, pushed today, Apache-2.0) — with the PoC caveat above.
2. 100+ discovery: **none measured**; BGE reranker is the only measured 100-option ranker (0.75) but has no server interface.
3. Abstention: **aurelio** only (native `None`; tuning required).
4. All four agents officially: **none** — Hermes appears in zero repos' support evidence.
5. Laya without wrapper: **registration-only** (CONFIGURATION_ONLY); semantic hand-off needs custom code.
6. Fewest services: MCPorter (CLI); among gateways ToolHive (one binary).
7. Retireable: custom routing logic, per-client MCP sprawl, ad-hoc shortlists — only after measured bars + per-step approval. Never: policy gates, Graphiti/Neo4j, Ollama, Skills, logs.
8. Unsupported w/o custom code: enforced discovery routing, skill-dir search, Ollama privacy routing, Laya-as-ranker, gateway abstention guarantees.

## Approvals outstanding
PoC-2 (ContextForge) install+benchmark; colima-network fix for ToolHive live re-test; persisting dataset into `eval/`; any client config registration.
