# Decision Benchmark — reuse + gateway protocol

## A. Reused measurements (120-case set, /tmp/bench_dataset.jsonl, CPU, spot-verified 4/4 bit-identical)
| Candidate | Top-1 | Top-3 | MRR | p50 | Notes |
|---|---|---|---|---|---|
| BGE reranker v2-m3 | 0.796 (n=108) | 0.870 (n=100) | 0.842 | 57ms | 0.75 @100 opts; DE 8/8; unbounded logits, no native abstention |
| EmbeddingGemma (Ollama) | 0.787 | 0.935 | 0.868 | ~7ms amort. | threshold t≈0.30: prec 0.78/rec 0.58 |
| Laya typed-decisions | 0.639 | 0.815 | 0.739 | 125ms | 0.00 @100; confidence inverted — never gate on it |
| Aurelio+MiniLM forced | 0.639 | UNMEASURED | UNMEASURED | 3ms | defaults abstain 102/120 incl. 12/12 no-match |

Dataset: skill 32 / tool 21 / model 20 / workflow 20 / memory 15 / nomatch 12 / DE 8; sizes 2–100 from real catalogs; giveaway-grep 0 hits. Limits: tool sizes ≤5 (only 5 real tools); single seed; single-authored descriptions shared across candidates.

## B. Gateway benchmark protocol (ToolHive PoC EXECUTED 2026-10-11 — see toolhive-poc.md)
Measured: registry search 0.06–0.08s/query offline; 7/13 single-keyword hits, 0/8 multi-word; result sets unordered, no scores; live `run` BLOCKED by colima bridge networking (evidence logged, shared infra untouched); 114/120 cases NOT_APPLICABLE (catalog search ≠ option selection). Gateway top-1/top-3/MRR remain UNMEASURED by construction.
Remaining protocol (ContextForge PoC-2, still BLOCKED on install approval):
For ToolHive and ContextForge (then agentgateway if needed):
1. Install official release into an isolated PoC (ToolHive: `ghcr.io/stacklok/toolhive:0.51.4` or goreleaser binary; ContextForge: `mcp-contextforge-gateway` PyPI pin or `ghcr.io/ibm/mcp-context-forge:1.0.11`). Approximate pulls: ToolHive ~50–100MB binary; ContextForge image ~1GB + Python deps. No client config changes.
2. Register the same upstream inventory used in the 120-case set (5 real MCP servers already configured for Codex + `laya-mcp-server` if its install is separately approved — NOT included by default).
3. Replay the 120 states as discovery queries (`search`/filter эквивалент); record top-1/top-3 vs expected server+tool, no-match behavior (12 cases), p50/p95 per query, cold start, RSS.
4. Score with the identical rubric (§5 of mission); report gateway numbers side-by-side with the table above. Estimates are forbidden — UNMEASURED stays UNMEASURED until run.
5. No-match probes: 12 existing + 10 gateway-specific (unknown server, valid server/wrong tool, ambiguous duplicates).

## C. What changes approval is requested for (nothing done yet)
- Binary/image downloads listed in (B.1); disk budget ~2GB.
- No model-weight downloads beyond already-approved BGE/MiniLM.
- No writes to `~/.codex`, `~/.config/opencode`, `~/.claude`, `~/.hermes`.
- No public exposure (localhost only), no mandatory routing, no migration.
