# Implementation Report — Codex Handoff Continuation (2026-10-11)

## 1. Recovered state (verified from source, not from prior claims)

- The working tree was **not a git repository** when this report was written (no `.git`,
  no stash, no diff to inspect). Recovery was done by reading source directly.
- Prior claim "19 tests passed" is stale: the suite now contains **79 tests**
  before this session's changes, all passing.
- Architecture found intact: deterministic `PolicyEngine` → `LayaDecisionEngine`
  (shadow only) → `RuleBasedDecisionEngine` fallback; typed `DecisionQuestion`
  (`choice`/`score`/`boolean`); `SystemOneRuntime` recommendation/shadow extension
  with `DeterministicFallback`, `ExistingQwenBackend`, `LiquidD1Backend` (disabled
  without explicit `enabled+approved`); JSONL observability; `ai-os system-one` CLI.
- No model weights downloaded, no dependencies installed, no global settings changed.

## 2. Files changed this session

1. `src/ai_os_decision/system_one_worker.py` — hardened `model_capabilities()`.
2. `src/ai_os_decision/system_one_io.py` — hardened `discover_models()`.
3. `tests/test_system_one.py` — 8 new regression tests (16 with parametrization).
4. `docs/{implementation-report,github-reuse-analysis,benchmark-report,rollback}.md` — new.

## 3. Outstanding issues — resolution

| ID | Status | Evidence |
|----|--------|----------|
| A. Model inventory validation | Already enforced; extended | `BoundedRequest.validate` rejects undiscovered `selected_model` (`test_reserved_model_cannot_bypass_mapping`); `ExistingQwenBackend.__init__` + `infer` reject non-inventoried models; `application_contract` re-checks. New: `test_qwen_backend_rejects_non_completion_model`, live `discover_models()` returned 9 real models, 4 Qwen completion-capable. |
| B. Ollama capability discovery | **Fixed this session** | `model_capabilities()` previously crashed on missing `capabilities` key handling gaps: unvalidated inline values, unguarded `/api/show` (connection errors, non-dict, malformed `capabilities`). Now: trusts inline only if list-of-str; otherwise probes `/api/show`; any failure → `[]` (fail closed). `discover_models()` previously raised `KeyError` on rows missing `name`/`digest` and on envelopes missing `models`. Now: `TypeError` on malformed envelope, skips malformed rows, per-row probe failure → `completion=False`. 8 new regression tests. |
| C. Confidence semantics | Already enforced; verified | `deterministic-encoding-not-statistical-confidence` / `synthetic-encoding-not-model-confidence` / `native-distribution-not-task-calibrated`; Qwen one-hot confidence forced into `uncertainty`. Live check: Qwen answer carried `synthetic-encoding-not-model-confidence` with `uncertainty=["UC03"]`. |
| D. Telemetry | Already present; pinned by test | `decision_source`, `latency_ms`, `fallback_used`, `error`, `usage` (real `prompt_eval_count`/`eval_count` for Qwen, honest zeros for deterministic/cache), `measurement` (cache hits, d1 device/RAM fields when present), `confidence_semantics`. New `test_recommendation_telemetry_contract`. No fabricated tokens. |

## 4. Test results (observed)

- `uv run pytest -q`: **95 passed** (79 pre-existing + 16 new parametrized cases).
- `uv run ruff check src tests`: **All checks passed**.
- Live `discover_models()` vs Ollama `127.0.0.1:11434`: 9 models, correct
  completion flags (PASS).
- Live `ai-os system-one eval/system_one/UC03-en-request.json --backend qwen
  --model qwen3.5:9b-mlx`: authoritative deterministic + Qwen shadow, real usage
  `{input_tokens: 178, output_tokens: 15}`, latency ~3.4 s (PASS).
- Deterministic system-one eval (`eval/run_system_one_eval.py`): runs, accuracy
  0.3 on the 30-case synthetic set (see benchmark-report; not a quality claim).

## 5. Runtime status

- Deterministic router: active, authoritative. Qwen router: working via local
  Ollama, advisory/shadow only. Liquid d1: adapter present, **disabled for live
  routing**, native inference BLOCKED (no weights, no isolated env — by policy).
- d1 adapter remains isolated: `LiquidD1Backend.infer` raises unless
  `enabled+approved` with snapshot + interpreter; worker verifies source/weight
  hashes before importing remote model code.

## 6. Remaining issues / risks

- `REVISION` pin (`051bcc4…`) in `system_one_backends.py` could not be verified
  against the upstream repo from this session (hash refers to the snapshot contents
  manifest, verified at inference time by `verify_snapshot`). Re-verify when
  weights are ever approved.
- d1 model card license is `lfm1.0` (not OSI-approved) — flag for legal before any
  production use. No download performed.
- No git repo: changes are uncommitted and unversioned; recommend `git init` +
  initial commit by repo owner (not done — out of scope without approval).
- Graphiti retrieval fix from prior session: **UNVERIFIED** — no Graphiti/MCP
  tooling is reachable from this OpenCode session, so the episode-vs-fact
  retrieval path could not be exercised. No memory code was touched.
