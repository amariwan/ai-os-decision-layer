# Provider Intelligence & Adaptive Routing (2026-10-11)

Evidence-driven model selection. Adaptive ranking is implemented and tested
but **not activated**: `provider_intelligence.enabled: false`, and the
production path (deterministic policy → local → fallback) is unchanged.

## 1. Provider inventory (refreshed 2026-10-11)

- Local Ollama (`127.0.0.1:11434`): 9 models live, incl. `qwen3.5:9b-mlx`,
  `gemma4:e2b-mlx`, `gemma4:26b-mlx`, `ornith-1.5:35b`,
  `orcarouter/Qwen3.8-27B-Uncensored:q5_K_M`, `embeddinggemma:300m`
  (embedding-only, never a completion candidate), `qwen3.6:35b-mlx`,
  `tev1:latest`, `qwen3.8:27b-mlx`. No per-token fee, no quota.
- FreeLLMAPI (`127.0.0.1:31415`): **222 advertised, 27 available** (unchanged
  from prior observation; 195 `needsKey`). Record builder:
  `provider_intel.build_inventory()` → 231 normalized `ModelRecord`s
  (9 ollama + 222 freellm), 195 `advertised` (never eligible).
- Capabilities recorded only from discovery proof (`completion`/`json`/`tools`).
  **Vision support: UNVERIFIED** — no discovery source exposes it, so it is
  never claimed. Pricing: `None` (unknown) for cloud; prior $0 observation
  noted in `docs/freellm.md` but not stored as a pricing fact.
- Availability ladder: advertised < available < tested < verified. Promotion
  requires observation; staleness demotes to insufficient-evidence.

## 2. Benchmark fixtures (`eval/provider_intel/`, 12, EN+DE)

Engineering (5): Vue fix, TS type error, FastAPI validation, ADR decision,
auth-middleware security. Agent (4): skill select, tool select, complexity,
risk-critical. Reliability (3): garbled-input robustness, privacy-restricted
(`cloud_ok: false` — cloud runners skip, never transmit), ambiguous DE request.
All validate against `BoundedRequest`; deterministic baseline 12/12 (fixture
calibration — measures fixture quality, not intelligence).

## 3. Runner (`eval/run_provider_benchmark.py`, `provider-benchmark/v1`)

Dry-run default (plan + deterministic only). `--live` executes model backends
with: global/per-model budgets, per-provider cooldowns, shared `QuotaTracker`s
(honors `Retry-After`, eliminates models after 3 consecutive fallbacks),
one-at-a-time calls, checkpoint JSONL + resume, sanitized rows (no state text,
no keys), config-hash provenance, evidence export for the ranker. Cloud pairs
additionally require `--approve-cloud`, `freellm.enabled`, per-fixture
`cloud_ok`, and `cloud_eligible`. d1 pairs are BLOCKED (no native inference).

## 4. Measured results (synthetic fixtures only)

- Deterministic: 12/12 correct (expected == fallback by construction), ~0.05 ms.
- Local Qwen pilot (4 fixtures): accuracy 1.0 on 3 successes, 1 fallback
  (`RuntimeError`), p50 2.4 s, 588 in / 41 out tokens. `outputs/provider-benchmark-qwen-pilot.json`.
- Cloud pilot (`gemma-4-26b-a4b`, 2 fixtures): fallback_rate 1.0
  (`RuntimeError`, throttled) — evidence of unreliability, not quality.
  `outputs/provider-benchmark-cloud-pilot.json`.
- Full 27-model sweep explicitly NOT run (quota-bound free tier; staged
  evaluation required). No winner declared: largest sample is n=4.

## 5. Adaptive ranking (`provider_intel.rank_candidates`)

Deterministic capability filter first (json/tools/context/provider/cloud
policy), then evidence ordering with `min_samples: 3`, `max_age_days: 30`
(from config), local tie-break within 0.05 accuracy, `insufficient-evidence` /
`stale-evidence` tiers that can never outrank measured models. Live demo on
current evidence: engineering → `ollama:qwen3.5:9b-mlx` (measured-n=4) first;
engineering+json → no measured candidate (honest empty top). Insufficient
evidence falls back to deterministic routing — always defined behavior.

## 6. Recommendations by task category (provisional, n≤4)

- Local engineering/agent decisions: `ollama:qwen3.5:9b-mlx` (only measured
  candidate; keep deterministic authority + fallback).
- Structured-output cloud tasks: no verified candidate; next pilot:
  `glm-5.3-flash` / `gemma-4-26b-a4b` (json-capable, available) when quota allows.
- Cloud escalation in general: not recommended until fallback_rate < 0.5 is
  measured over ≥10 samples; free-tier cooldowns dominate latency.
- d1 candidate shortlist for later: any `verified` inventory IDs only; d1
  execution stays disabled, no weights downloaded.

## 7. Feature flag, activation, rollback

- `provider_intelligence.enabled: false` (config.yaml). Evidence collection via
  the isolated runner is allowed; production adaptive routing is not wired in.
- Activation (requires explicit approval): collect ≥`min_samples` fresh
  evidence per candidate, verify fallback_rate and latency, then wire
  `rank_candidates` output into the advisory path only — deterministic policy
  stays authoritative. Never auto-activate on n=1.
- Rollback: delete `provider_intel.py`, `eval/provider_intel/`,
  `eval/run_provider_benchmark.py`, `tests/test_provider_intel.py`,
  `outputs/provider-benchmark-*.json`, `docs/provider-intelligence.md`, the
  `freellm_inventory_rows` helper, and the config flag; re-run
  `uv run pytest -q` (expect 123) + `uv run ruff check src tests eval`.

## 8. Remaining risks / unverified assumptions

- Sample sizes (n≤4) cannot support model selection — pilots only.
- Cloud availability churns (27/222 today); inventory must be refreshed live.
- Costs UNVERIFIED (no billed-cost source); vision support UNVERIFIED;
  skill precision/recall UNVERIFIED (no multilabel corpus).
- Graphiti/Neo4j not operational from here (no package, no env) — findings
  live in versioned JSON + docs with provenance instead; no second database
  created. Re-check Brain reachability before storing durable memories, and
  never store raw prompts, credentials, or large logs.
- d1 native inference BLOCKED (no weights/env/approval); mocked adapter tests
  are not quality evidence.
- Repository is intentionally unversioned (no `.git`, no parent repo).
  `.gitignore` now also excludes weights/snapshots/secrets. Safe init proposal:
  `git init && git add -A && git commit` by the owner (explicitly NOT done
  without authorization); current tree is the review baseline.
