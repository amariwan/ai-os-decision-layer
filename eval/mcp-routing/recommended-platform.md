# Recommended Platform + PoC Plans

## Weighted score (30% functional / 25% no-custom-code / 20% community / 15% decision quality / 10% ops)
| Platform | Func | NoCustom | Commun. | DecQual | Ops | **Total** |
|---|---|---|---|---|---|---|
| ToolHive 0.51.4 | 0.55 | 0.75 | 0.70 | 0.45* | 0.85 | **0.68** |
| ContextForge 1.0.11 | 0.60 | 0.80 | 0.85 | 0.50* | 0.55 | **0.66** |
| agentgateway 1.6.0 | 0.55 | 0.70 | 0.75 | 0.45* | 0.70 | **0.58** |
| MCPorter 0.14.2 | 0.35 | 0.70 | 0.60 | 0.20 | 0.80 | **0.44** |
| fastmcp-gateway 0.33.0 | 0.45 | 0.60 | 0.20 | 0.35 | 0.60 | **0.38** |
*Decision-quality for gateways is UNMEASURED — scores reflect evidenced ranking primitives only (Portkey local 0.70-class as reference). Weights are initial criteria, not facts.

## Recommendation
**PoC ToolHive first, ContextForge second (isolated, reversible, Codex-only).** MCPorter as complementary CLI (per-server skills pattern), not as gateway. No global adoption before measured gateway numbers beat BGE-0.796 with comparable abstention.

## PoC-1: ToolHive (approval requested)
1. `toolhive --version` via goreleaser binary 0.51.4 (or ghcr image); `toolhive registry` up locally; register 3 read-only test upstreams (context7-remote, local echo server, one stdio toy). Disk ~100MB. No client changes.
2. Replay 120 states through `search` + run tools; record matrix per decision-benchmark.md §B.
3. Read-only Codex test: register PoC gateway URL in a *temporary* `CODEX_HOME` copy (never `~/.codex`), `codex mcp list` + one `laya_status`-equivalent listing call. Rollback = delete temp dir + `toolhive stop`.
4. Success bar: top-1 ≥ 0.80 with no-match precision ≥ 0.70, p95 < 500ms, zero scope broadening.

## PoC-2: ContextForge (only if PoC-1 fails its bar)
Same protocol against `mcp-contextforge-gateway` (PyPI pin) or `ghcr.io/ibm/mcp-context-forge:1.0.11` (~1GB). Extra checks: federation of the same 3 upstreams, Admin-UI search behavior, JWT/OAuth PoC secrets via env-only. Heavier; decommission by container/image removal.

## What this deliberately does NOT do
No OpenCode/Claude/Hermes changes, no production migration, no mandatory routing, no public ports, no custom code regardless of gaps found.
