# Laya Integration (official 0.4.2)

## What Laya natively offers
- `laya-mcp-server` (extra `laya[mcp]`, `mcp>=2.2.0`): tools `laya_decide`, `laya_route_batch`, `laya_shortlist`, `laya_status` (+ `laya_preset` family in 0.3.x line). Single resident Router, preload control, `LAYA_API_KEY` bearer auth. Docs: `docs/cli-mcp.md` (15.9KB). CPU (125ms) + MPS verified locally on typed-decisions.
- Measured limits (binding): top-1 0.639 overall, **0.00 at 100 options**, confidence inverted (never gate on it), no native abstention.

## Gateway + Laya compositions (no custom wrapper permitted)
| Composition | Classification | Evidence / note |
|---|---|---|
| Register `laya-mcp-server` as one upstream server in ToolHive / ContextForge / agentgateway | CUSTOM_CODE_REQUIRED (packaging) — PoC finding: `thv run` offers registry/image/uvx/npx/go/URL but NO raw-stdio path, so an existing local stdio server cannot be adopted config-only; containerize first |
| Semantic hand-off (gateway ranker → Laya typed decision, or vice versa) | CUSTOM_CODE_REQUIRED | Zero Laya references in all 9 repo trees (~7k files grepped). No official plugin on either side. |
| Laya presets (guard/triage/router) as gateway policy | UNSUPPORTED | No gateway documents external decision-tool policies. |
| Laya for 100-skill/tool ranking | UNSUPPORTED | Measured 0.00 — do not force (mission §6). |
| Laya for small-set typed decisions behind gateway | CONFIGURATION_ONLY (if PoC confirms) | Correct fit: `choice` ≤10 options, `score` rubrics, presets; temperature refit still required before trusting probabilities. |

## Recommendation
Keep Laya as a **leaf decision tool** (one registered upstream among many), never as the discovery ranker. Its MCP server is the only component in this landscape that is simultaneously (a) first-party, (b) already verified on local weights, and (c) consumable by all four clients — that is its integration value, not routing quality.
