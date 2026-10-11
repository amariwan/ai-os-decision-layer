# FreeLLMAPI Cloud Escalation (2026-10-11, measured)

Local-first routing is unchanged and authoritative. Cloud is an opt-in,
explicitly-approved escalation path. Default state: **disabled**.

## 1. Provider compatibility matrix (live `/v1/models`, 2026-10-11)

- Gateway: `http://127.0.0.1:31415` (loopback only; adapter rejects non-loopback).
- Auth: `Authorization: Bearer $FREELLMAPI_KEY`. No key → `missing_credentials`;
  bad key → `authentication_error`. Key lives in env only, never in repo/config/logs.
- Advertised **222** models, actually **available: 27** (~12%). 195 return
  `available:false` / `execution_status:needsKey` / `unavailable_reason:no_key`.
  **Never infer availability from advertisement** — discovery filters to available.
- Working endpoints (probed): `GET /v1/models`, `POST /v1/chat/completions`
  (canonical per gateway UI), `POST /v1/messages` (Anthropic format),
  `POST /api/chat` (Ollama format), `POST /v1/completions` (needs `prompt`).
- Upstream routes observed: UnoRouter (`unorouter/<model>:free`), plus local
  `-mlx` mirrors of Ollama models and `auto`/`fusion`/`claude-*` router slots.
  No per-provider breakdown is exposed (`owned_by` is uniformly `freellmapi`).
- Tool calling: `tools`/`tool_choice` in `supported_parameters` for most
  available chat models; **not** for `auto`, `fusion`, `claude-*` slots,
  `nemotron-3-nano-30b-reasoning`, `nemotron-3.5-content-safety`.
- Structured output: `response_format` supported by 14 of 27 available models;
  discovery returns the JSON-capable ID set and the worker sends
  `response_format:json_object` only for those (`json_mode` flag).
- Context: 32K–1M tokens on cloud models (e.g. `glm-5.3-flash` 1M,
  `lfm2.5-2.6b` 32K). Local `-mlx` mirror entries expose no context metadata
  (`ctx=None`) — treat as unknown, prefer local Ollama metadata for those.
- Pricing: free tier, **$0 measured**; no pricing fields exposed by the API,
  so no cost claim beyond "no charge observed".
- Rate limits (measured, tight): account `X-RateLimit-Limit: 120` plus
  per-model cooldowns (`Retry-After: 74`, "soonest reset ~2m", UnoRouter 503
  busy). 429s observed after ~2 rapid requests. The adapter honors
  `Retry-After` (clamped 1–3600 s) and opens the circuit breaker — **do not
  treat free-tier models as unlimited**.

## 2. Implemented adapters (repo-native: backend + worker + discovery)

- `FreeLLMBackend` (`system_one_backends.py`, `name="freellm"`): mirrors
  `ExistingQwenBackend` validation (model must be discovered + completion +
  `freellm:` source; must be in request snapshot) plus d1-style
  `enabled+approved` gating. Loopback-only base URL. Records quota on every
  outcome; maps transport errors to `PermissionError` (auth) / `ValueError`
  (rejected) / `RuntimeError` (rate-limit, provider, timeout) → all fall back.
- `freellm()` + `cloud_json()` (`system_one_worker.py`): stdlib-only worker,
  key from env only, 256 KiB bounds, 0.01–600 s deadline via `run_worker`.
  Reuses `_answers_from_values()` coercion shared with `qwen()`. Usage from
  real `prompt_tokens`/`completion_tokens`; absent usage → zeros flagged with
  `measurement.usage_missing` (never fabricated). Rate-limit headers preserved
  in `measurement`. Confidence labeled `synthetic-encoding-not-model-confidence`.
- `discover_freellm_models()` (`system_one_io.py`): returns
  `(capabilities, json_capable_ids)`; skips unavailable/malformed rows;
  `TypeError` on malformed envelope; `RuntimeError` (type only, no key
  material) on transport failure. No credentials in `Capability` fields.
- `privacy_screen()` / `QuotaTracker` / `cloud_eligible()` (`system_one.py`):
  secret-hint screen (blocks `api_key`, `bearer`, `-----begin`, `private key`,
  `password`, `ghp_`/`sk-`/etc. unless `allow_private`), in-memory circuit
  breaker (failures + `Retry-After` cooldown), and the single escalation gate
  (disabled → privacy → allowlist → quota).
- Routing priority (enforced): deterministic policy → local Ollama →
  d1 recommendation (still disabled) → **cloud only if eligible + approved** →
  deterministic fallback. No auto-escalation loop; no retry storms (one attempt
  per call, circuit breaker across calls).
- CLI: `--backend freellm --model ID --approve-cloud`; without both config
  `enabled:true` and the flag, the observation stays deterministic and the
  output reports `cloud_eligibility.reason`. Eval: `--backend freellm
  --approve-cloud` (visual fixtures excluded, construction failures → BLOCKED).

## 3. Benchmark (representative synthetic task UC03, measured)

| Router | Answer | Latency | Tokens | Fallback |
|---|---|---|---|---|
| A. Deterministic | terminal | 0.08 ms p50 | 0/0 | no |
| B. Local Qwen (`qwen3.5:9b-mlx`) | projectatlas | ~3.4 s | 178/15 | no |
| C. FreeLLMAPI (`auto` slot) | projectatlas | 1408 ms | 164/168 | no |
| C. FreeLLMAPI (`gemma-4-26b-a4b`, throttled) | terminal (fallback) | 456 ms | 0/0 | **yes, RuntimeError recorded** |
| D. Liquid d1 | — | — | — | BLOCKED (no weights) |

Cloud/local Qwen agreed (`projectatlas`) against deterministic (`terminal`) on
this synthetic case — agreement signal only, not a quality claim. No savings
claimed: free tier is quota-bound (429s measured), not unlimited.

## 4. Security assessment

- Credential review: single gateway bearer for a loopback service (limited
  blast radius). No key-export file found on disk; NavyAI/OpenRouter/OrcaRouter/
  UnoRouter appear only as gateway-side upstream routes (UnoRouter named in a
  429 trail). No raw upstream provider keys handled in this session.
- Handling: env-only (`FREELLMAPI_KEY`), never written to repo/config/logs/
  reports/Brain; discovery sources carry model IDs only; `transport_error`
  payloads carry types, never bodies/keys. Verified: key fragment absent from
  `src tests eval docs config.yaml`.
- Privacy: secret-like request text is blocked from cloud unless
  `allow_private:true` **and** caller approval; images rejected by the worker;
  shadow metadata carries counts/sources only. Policy engine denys still apply
  first (authoritative deterministic path untouched).
- Attack surface added: one outbound HTTPS-shaped path, constrained to
  loopback base URL, bounded sizes/timeouts, no retries in-worker, circuit
  breaker across calls. No new dependencies (stdlib only), no services started.

## 5. Activation procedure (explicit approval required)

1. `export FREELLMAPI_KEY=<gateway key>` (never commit it).
2. Set `freellm.enabled: true`, optionally `allowed_models:` (`- id` per line)
   and `allow_private: false` (keep false for private content) in `config.yaml`.
3. Refresh inventory per run: `discover_freellm_models()` — only `available`
   models are candidates; re-check before relying (availability churns).
4. Invoke per call: `ai-os system-one <request> --backend freellm --model <id>
   --approve-cloud`. Each call re-evaluates `cloud_eligibility`.
5. Monitor `measurement` (rate-limit fields), `error`, `fallback_used`; on
   repeated `quota-cooldown`, stop and wait — do not hammer free tier.
6. To deactivate: `enabled: false` (default) — cloud path then refuses without
   code changes. d1 remains separately gated (`--approve-d1`).

## 7. AUTO / AUTO_FREE (2026-10-11, fixed + added)

- **Bug:** `select_model()` accepted every `available:true` row. The gateway
  advertises router slots (`claude-*`, no `execution_status`) as available
  but rejects them at inference (`404 model_not_found`, "use `auto`").
  Laya picked `claude-haiku-4-5` → inference failed → deterministic fallback.
- **Fix:** candidates require `execution_status == "ready"` (the gateway's
  own readiness signal, cf. `needsKey` above). Verified live: slots gone
  from shortlist, Laya chose `dots3-note-preview` from 4 ready models.
- **Failover:** `--model auto` tries the ordered shortlist (Laya choice
  first, max 4) via one `observe()` per candidate and keeps the first
  working backend. Per-candidate `cloud_eligible` quota check; stop on
  `quota-cooldown`. Attempts logged in `model_routing.attempts`
  (`[{model, error}]`, IDs + error types only). Live: 2× `RuntimeError`
  (throttled tier) then clean stop on cooldown — no retry storm.
- **AUTO_FREE** (`--model auto-free`): same candidates, plus a response-side
  cost gate. Rows expose no pricing, so free is verified from observed
  `usage`: `cost == 0`, `is_byok == false`, `upstream_inference_cost == 0`
  (worker passes these through as `measurement.cost/upstream_cost/is_byok`;
  allowlisted in `SystemOneRuntime.decide`). Missing cost evidence fails
  closed (`non_free_cost`, next candidate; none free → `no_free_model`,
  exit 2). No config change needed; same `allow_auto_calls` authorization.
  Live-verified: `dots3-note-preview`, first attempt ok,
  `measurement {cost: 0, upstream_cost: 0, is_byok: false}`.
- Laya advised `gateway-auto-only`; rejected with reason: user requires a
  Laya choice from filtered models plus an auditable free-only mode, and
  the `auto` slot is opaque (no per-model attribution). Status-filter uses
  existing gateway evidence with zero extra calls (probing rejected:
  429 after ~2 rapid requests).

## 8. Known limits

- Availability churn: 27/222 today; models can go `needsKey` at any time —
  always discover live, never hardcode.
- `auto`/`fusion` slots are opaque routers (no per-model latency/cost
  attribution); `fusion` fans out to a panel (quota multiplier) — avoid for
  routine escalation.
- No token/cost savings claim; no end-to-end task-completion evidence.
- Graphiti episode-vs-fact retrieval fix from prior work remains UNVERIFIED
  (no MCP reachability in this session); memory code untouched.
