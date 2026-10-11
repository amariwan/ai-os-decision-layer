# Benchmark Report (measured 2026-10-11; synthetic fixtures only)

## 1. What was actually run

| Measurement | Command | Result |
|---|---|---|
| Full unit suite | `uv run pytest -q` | **95 passed** |
| Lint | `uv run ruff check src tests` | **clean** |
| Deterministic system-one eval (30 synthetic DE/EN microtasks, 2 visual fixtures) | `eval/run_system_one_eval.py` (deterministic backend) | accuracy **0.3**, p50 **0.08 ms**, p95 **0.20 ms**, 0 fallbacks, tokens `{0, 0}` |
| Live Qwen shadow, single case UC03-EN | `ai-os system-one … --backend qwen --model qwen3.5:9b-mlx` | shadow answer `projectatlas` vs authoritative `terminal`; usage `{input:178, output:15}`; latency **~3.4 s**; `fallback_used=false`, `synthetic-encoding-not-model-confidence` |
| Live Ollama inventory | `discover_models()` | **9 models**, 4 Qwen completion-capable |

## 2. Router comparison (A/B/C)

| Router | Accuracy (30-case synth) | Latency | Status |
|---|---|---|---|
| A. Deterministic | 0.3 (illustrative only) | p50 0.08 ms | measured, authoritative |
| B. Qwen (`qwen3.5:9b-mlx`) | single-case agreement observed; full 30-case Qwen eval NOT run (cost/time) | ~3.4 s/case (n=1) | partially measured, advisory only |
| C. Liquid d1 | n/a | n/a | BLOCKED (no weights/env); adapter tests pass, native inference UNVERIFIED |
| Semantic Router (optional) | n/a | n/a | NOT evaluated — no capability gap demonstrated; not installed |

## 3. Explicit limitations (do not over-claim)

- The 30-case corpus is synthetic and tiny: NOT proof of agent task completion,
  calibrated confidence, skill precision/recall, production error rate, or
  token/cost savings.
- The deterministic baseline is a configured fallback, not a strong optimized
  rule router — no comparative quality claim may rest on it alone.
- Qwen full-eval, risk-classification error rates, memory usage, and end-to-end
  task success were NOT measured this session.
- Fallback results are reliability evidence, never counted as model-inference
  successes.
- No token-savings claim is made; the only measured token figures are the live
  Qwen single-case counts above.
