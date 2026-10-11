# ToolHive PoC Report — Isolated MCP Discovery (2026-10-11)

Env: /tmp/toolhive-poc, HOME-isolated state, disposable. Real configs untouched (verified: no writes outside /tmp + shared Docker image pulls, since removed).

## 1. Release / license / integrity — PASS
`thv` = ToolHive v0.51.4 (commit 61aaf42, Go 1.27.1, darwin/arm64). Release v0.51.4 published 2026-09-27. License Apache-2.0 (API + LICENSE file in tarball). Tarball SHA-256 `fc3159ae…0b27bb` matches `toolhive_0.51.4_checksums.txt`. Sigstore/SBOM assets present, not independently verified. Deps: Go binary 128MB + Docker (colima) at runtime; no Python.

## 2. Native discovery — PARTIAL (keyword, not semantic)
`thv search` hits an embedded registry offline in 0.06–0.08s. 21 queries run. Single keywords work: github (111 hits), slack (2), postgres (5), kubernetes (2), fetch, docs (4), docker, sqlite (2). **All 8 multi-word natural queries return zero** (incl. "github pull request", "send slack message", "read pdf"). "blender", "code review", "pdf" → zero despite ecosystem servers existing. Output columns NAME/TYPE/DESCRIPTION/TRANSPORT/STARS with **no relevance scores and no documented ordering** (github hits not star-ordered). The README "semantic search / −85% tokens" claim is NOT verified by observed behavior — consistent with substring matching.

## 3. Benchmark vs 120-case set
- Reuse verdict: only ~6 tool-category states map to registry-server queries; skill/model/workflow/memory options have no registry counterpart → 114/120 NOT_APPLICABLE (discovery-over-server-catalog ≠ selection-among-given-options; different task, stated to avoid false comparison).
- Discovery hit rate on 13 content queries: 7/13 single-keyword hits (relevance unchecked beyond name), 0/8 multi-word.
- 5/20/50/100 scaling: NOT_APPLICABLE — no ranking layer exists to evaluate; result sets are unordered and tiny (or 111 unordered for "github").
- Discovery vs ranking failures: ALL observed failures are retrieval (empty results); ranking failures N/A (no ranker). Top-1/top-3/MRR: NOT_APPLICABLE to ToolHive search.

## 4. No-match behavior
Clean `"No servers found"` string (exit 0) — usable as absence signal, but false absences dominate (valid needs like "read pdf" also absent). No-match precision as classification: UNMEASURED (requires relevance judgments over the full registry, out of PoC scope).

## 5. Live invocation — BLOCKED (environment, with evidence)
`thv run io.github.stacklok/sqlite` pulled the image (5.3s) then failed: `failed to resolve MCP container IP for ingress: container poc-sqlite has no IP address on network toolhive-poc-sqlite-internal` (colima bridge networking). Per safety rule, shared Docker/colima networking was NOT reconfigured — no `thv mcp list/call`, no isolated-Codex invocation. `thv rm` cleaned the workload; image/network leftovers verified gone (`docker ps -a`, `network ls` clean).

## 6. Client compatibility (observed `thv client status` table)
Codex / claude-code / opencode: officially supported client types (table rows exist). Hermes: NO row — UNSUPPORTED, no evidence anywhere. Isolated-Codex invocation test: BLOCKED (§5). Registration pattern is standard MCP proxy URL; no client-specific magic observed.

## 7. Laya integration — BLOCKED + structural gap
`laya-mcp-server` not on PATH (laya package uninstalled) → registration untestable. Structural: `thv run` offers registry / image / uvx:// / npx:// / go:// / URL — **no raw-stdio path**, so an existing local stdio server (laya-mcp-server, graphify, projectatlas) cannot be adopted without containerizing first → CUSTOM_CODE_REQUIRED (packaging), not config-only. Objective 11 verdict: cannot be verified in this env; adoption path is heavier than assumed.

## 8. Skills
`thv skill {build,install,list,sync,…}` exists (Artifact-locked project skills) — untested (installing skills writes project state; out of scope). No indexing of existing `~/.agents/skills` observed.

## 9. Security findings
- Image without provenance → warning only, proceeds (`skipping image verification`). Policy default-deny for unverified images: NOT evidenced.
- Egress proxy + per-server network + `--tools` filter + `--tools-override` + permission profiles (`none|network|path`) observed — genuine least-privilege primitives.
- Secrets via `thv secret` + `--env/--env-file` (content unexamined; no secrets used in PoC).
- No public exposure (127.0.0.1 proxy default); no private data left the machine (only synthetic queries + public registry pulls).

## 10. Resources
Binary 128MB; `thv search` ~0.07s, negligible RAM (Go CLI); server containers unmeasurable (never started). Image pulls during PoC: ~60MB total, removed afterwards. Operational deps: Docker/colima daemon (running), GHCR access for images.

## 11. vs ContextForge (verified features only, no install)
ToolHive: lighter (one binary vs FastAPI+gunicorn+Helm), client table incl. 3/4 agents, `--tools` filtering; weaker on governance UI/federation breadth. ContextForge: richer registry/federation/observability, 179 contributors vs 133, but heavier ops and 971-issue backlog. Decision-quality comparison impossible — neither has measured ranking.

## 12. GO / NO-GO — NO-GO for adoption, GO for narrow use
- NO-GO as universal discovery/ranking layer: keyword-only retrieval, zero multi-word recall, no ranker, no Laya-stdio adoption, live serving unverified in this environment.
- CONDITIONAL GO as containerized MCP runtime + client-config manager (if colima networking is fixed outside PoC): isolation, `--tools` filtering, permission profiles are real and valuable.
- Gateway benchmark numbers stay UNMEASURED. Next step if wanted: fix colima bridge networking (needs explicit approval — shared infra), then re-run §5 + isolated-Codex invocation.

## Cleanup
`thv rm poc-sqlite` done; no containers/networks/images remain (verified). To fully remove PoC: `rm -rf /tmp/toolhive-poc` (161MB). Real configs: untouched.
