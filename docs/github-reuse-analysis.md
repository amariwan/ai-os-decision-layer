# GitHub Reuse Analysis (verified 2026-10-11 via model card + GitHub API)

Rule applied throughout: do not install entire frameworks to reuse one small
feature; no installation scripts executed; no dependencies added.

| Capability / Repo | License / Stars | Verdict | Rationale |
|---|---|---|---|
| Native decision model — `LiquidAI/d1-3B` (model card read) | lfm1.0; Decision Index 48.57; `system_one` / `system_one_batch`, `noul`/`choice`/`score`, zero output tokens, `transformers>=5.14`, `trust_remote_code=True` | **ADAPT_MINIMALLY** (already done) | Existing adapter already mirrors the official interface exactly (same call shapes, same answer fields, output_tokens==0 enforced). Keep pinned-snapshot + hash-verification approach. Note: `lfm1.0` is not OSI-approved — legal flag before production. Weights NOT downloaded (6.25 GB, needs approval). |
| Semantic routing — `aurelio-labs/semantic-router` (MIT, 3.9k★; 1.x rewrite in progress on `main`) | MIT | **NOT_NEEDED** | Embedding-similarity route selection needs an encoder (OpenAI/Cohere API or local HF model) plus vector index — new deps, new failure modes, API keys — for a problem already solved deterministically here (typed questions + policy + keyword rules). Re-evaluate only if a genuine classification gap is measured. |
| LLM routing — `lm-sys/RouteLLM` (Apache-2.0, 5.6k★) | Apache-2.0 | **NOT_NEEDED** | Strong/weak cost-based routing trained on GPT-4/Mixtral; still requires `OPENAI_API_KEY` for embeddings even with local models. Local Ollama inference has no per-token cost, so the cost-saving premise does not apply. Benchmark harness ideas may inform future eval design (BUILD_MISSING if ever needed). |
| LLM gateway — `BerriAI/litellm` (60k★; license reported as Other/NOASSERTION) | Other | **NOT_NEEDED** | Unified provider routing/failover only matters with multiple hosted providers. Current system is local-Ollama + deterministic; no provider routing need exists. Revisit if hosted failover becomes a requirement. |
| Skill discovery — `vercel-labs/skills` (MIT, 33k★; `npx skills`, skills.sh) | MIT | **REUSE_EXISTING** | The Agent Skills `SKILL.md` convention it standardizes is already what `~/.agents/skills/` (~400 local skills) and `discover_skills()` (exact `SKILL.md` paths, 64 KiB bound) implement. No new tooling needed; keep exact-path discovery, never recursive hub enumeration. |
| Engineering skills — `mattpocock/skills` (MIT, 285k★) | MIT | **REUSE_EXISTING** | Local skill library already covers the same ground (tdd-workflow, code-review, debugging, architecture, typescript, etc.). If a gap is demonstrated, use `find-skills`/selective install — never bulk-install. No gap demonstrated in this session. |
| Memory — `getzep/graphiti` (Apache-2.0, 31k★) | Apache-2.0 | **REUSE_EXISTING** | Existing Graphiti/Neo4j Global Brain stays the only memory system. No second memory service. Prior session's episode-retrieval fix is UNVERIFIED from here (no MCP reachability in this session) and must be re-verified before being relied upon. |

## Build-vs-reuse matrix (5 priority use cases)

| Use case | Decision |
|---|---|
| Skill selection | REUSE_EXISTING (`discover_skills` + local skills) |
| LLM routing | REUSE_EXISTING (`ExistingQwenBackend` + live `discover_models`) |
| Tool selection | REUSE_EXISTING (bounded `CapabilitySnapshot`, boolean `tool:` questions) |
| Task complexity | REUSE_EXISTING (`complexity` choice domain + deterministic fallback) |
| Memory relevance | REUSE_EXISTING (Graphiti; `retrieve_memory` boolean contract) |

**Minimal approach:** keep the stdlib-only core; the only justified future
integration is native d1 inference after resource approval (isolated env +
pinned snapshot + hash verification, as already scaffolded). Nothing else
needs building or installing.
