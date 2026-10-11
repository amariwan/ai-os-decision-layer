# AI OS Decision Layer

[![CI](https://github.com/amariwan/ai-os-decision-layer/actions/workflows/ci.yml/badge.svg)](https://github.com/amariwan/ai-os-decision-layer/actions/workflows/ci.yml)

Deterministic-first local decision host with optional model backends in
**shadow/advisory mode only**. For task routing, the deterministic rule baseline is authoritative:
no model recommendation can change a route, execute tools, weaken policy, or
block a request.

Six local recommendation profiles cover model routing, tool risk, intent/domain,
loop decisions, RAG reranking and guardrails through `ai-os recommend`.
Profiles may flag review, while hard policy and execution limits remain binding.
See [usage, examples and observed model-quality limits](docs/laya-profiles.md).

The same host includes a static n8n Workflow Library: source registry, SHA-256
deduplication with provenance, conservative security/dependency metadata,
SQLite FTS5 search, read-only HTTP/MCP adapters, and explicit inactive export.
See [workflow-library documentation](docs/workflow-library.md). It does not
execute workflows or change any running n8n instance.

## Status legend

- **Implemented + verified**: deterministic `PolicyEngine`, rule fallback,
  Laya shadow adapter with isolated inference, JSONL telemetry, CLI, synthetic
  eval harnesses, unit/regression tests and `ruff` checks.
- **Implemented, advisory only**: local Qwen/Ollama backend, FreeLLMAPI cloud
  escalation (disabled by default, explicit per-call approval).
- **Experimental, disabled**: Liquid d1 native backend (`lfm1.0` license —
  not OSI-approved; no weights or snapshot included; native inference
  UNVERIFIED).
- **Explicitly unverified**: confidence calibration, skill precision/recall,
  production error rates, token/cost savings, end-to-end task completion.

## Architecture

```
caller request (BoundedRequest: state + questions + capability snapshot + policy)
  → PolicyEngine (hard denies, approvals, fail-closed)      [authoritative]
  → DecisionEngine: deterministic → Laya (shadow) → rule fallback
  → SystemOneRuntime.recommend() / .observe()               [advisory]
       backends: DeterministicFallback | ExistingQwenBackend (local Ollama)
                 | LiquidD1Backend (disabled) | FreeLLMBackend (disabled)
  → JSONL observability (decision source, latency, fallback, usage)
```

Key files: `src/ai_os_decision/` (`engine.py`, `policy.py`, `rule_engine.py`,
`laya_engine.py`, `shadow.py`, `system_one*.py`, `provider_intel.py`,
`workflows/`), `tests/`, `eval/` (synthetic fixtures + runners), `docs/`.

## Installation

Requires Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone <this-repo> && cd ai-os-decision-layer
uv sync --extra dev
```

No model weights, datasets, or services are downloaded or started by setup.

## Configuration (safe defaults)

```bash
cp config.example.yaml config.local.yaml   # local override is git-ignored
```

Defaults are fail-closed: cloud escalation **disabled**, adaptive routing
**disabled**, d1 backend requires explicit snapshot + interpreter + approval
flag, raw user text is never logged (`log_text: false`). Secrets live in
environment variables only (`LAYA_MODEL_DIR`, `FREELLMAPI_KEY`) — never in
config, logs, or reports. See `config.example.yaml` and
[FreeLLMAPI notes](docs/freellm.md).

## Running tests and checks

```bash
uv run ruff check src tests eval
uv run pytest
uv run ai-os health
uv run ai-os decide "Refactor this Python repository"
PYTHONPATH=src uv run python eval/run_shadow_eval.py
PYTHONPATH=src uv run python eval/run_system_one_eval.py --output outputs/system-one-deterministic.json
```

`healthy` requires a successful minimal Laya inference. Without a local
checkpoint the expected health state is `unavailable`; the baseline continues
unchanged.

## Unified task entry: AI-OS + Laya

```bash
uv run ai-os task "Refactor this Python repository" --require-laya
uv run ai-os task "deploy service" --environment production --action deploy
```

`task` checks the configured policy first, asks the existing local Laya model
for a shadow observation, and returns an `ai-os-task/v1` JSON plan. The
deterministic route stays authoritative. A deny skips Laya and returns no
route; production approval requirements remain visible. The command never
executes tools, activates workflows, contacts a cloud model, or writes Brain
memory. It does not switch the model used by the calling chat client.

Configure `laya.model_dir` in the ignored local `config.local.yaml`, set
`LAYA_MODEL_DIR`, or pass `--model-dir /absolute/trusted/checkpoint` per call.
The directory must contain the existing `rl_agent_api.py` and local weights;
it is trusted executable model code. No dependency or weight is downloaded.
Without `--config`, `task`, `decide` and `health` load `config.local.yaml` when present, otherwise
the tracked safe defaults in `config.yaml`. These are complete alternative
configurations, not a partial merge: copy the example before customizing.
`--config` selects an existing local configuration with an explicit `policy`
mapping. Missing files, missing policy sections and malformed consumed
config sections produce `invalid_config` without a model call.
`--timeout-ms` overrides
the inference deadline (10..600000 ms). Cold model loading counts against
that deadline, so set it from a measured local probe rather than assuming
the default 2 seconds will suffice. Each call starts an isolated model
process and releases it afterwards; no resident inference service is added.

Exit codes: `0` means the plan is available, including an explicitly reported
fallback; `2` means denied, approval required, or invalid input/config;
`3` means `--require-laya` was set and no successful Laya observation was
available. `laya.status`, `attempted`, `fallback_used` and `error` expose the
actual model outcome. Neither exit 0 nor `status: ready` means a task ran.
The JSON does not echo the task text, and `task` writes no prompt log.

Global Brain retrieval remains the caller's existing MCP responsibility;
this CLI does not claim a Brain connection from configuration alone.

## Optional backends

- **Local Qwen (Ollama)**: advisory shadow only; see `docs/system-one.md`.
  Full 30-case model eval not run (cost/time); single-case agreement observed.
- **FreeLLMAPI cloud escalation**: opt-in, disabled by default, loopback
  gateway only, per-call `--approve-cloud`, secret-hint privacy screen, circuit
  breaker; see [docs/freellm.md](docs/freellm.md). Free tier is quota-bound
  (429s measured) — not unlimited.
- **Liquid d1 (experimental)**: adapter present, native inference BLOCKED
  without resource approval, isolated interpreter, pinned snapshot
  (`051bcc4…`), and `--approve-d1`. Model card license is `lfm1.0`; get legal
  review before any production use. Weights NOT included (6.25 GB).

## Privacy boundaries

- Private/secret-like transferred content is screened across state and questions,
  including option descriptions, intent and environment. Recognized content
  stays local unless
  `freellm.allow_private: true` **and** per-call approval.
- Cloud payloads carry an explicit allowlist only (`text`, `intent`,
  `environment` + bounded questions): state extras, permissions, capability
  snapshots, and metadata are stripped, and the final serialized payload is
  re-validated at the transport boundary. Rejected payloads cause zero
  transport calls.
- Shadow/telemetry metadata carries counts and sources only — no prompts, raw
  context, keys, or candidate IDs.
- The cloud circuit breaker is closed → open → half-open (one probe per
  cooldown) on a monotonic clock; quotas are process-local. Reading its status
  never reserves the recovery probe.
- Shadow slots remain occupied until their Future actually finishes, so
  repeated timeouts cannot queue unbounded jobs. The default Laya adapter
  runs in a subprocess that is killed and reaped at its deadline. Injected
  in-process adapters remain non-interruptible and should be used only for
  controlled tests.
- The deterministic baseline (`SystemOneRuntime.authoritative`) is the single
  authority; model output is a non-authoritative observation and cannot
  override it. Policy configs with incomplete security rules are rejected at
  startup (fail closed).
- The Global Brain / MCP executor remain documented future boundaries; no
  memory code is included that transmits credentials.

## Known limitations

- The 30-case system-one corpus and 12-case provider-intel set are synthetic
  and tiny: not proof of task completion, calibration, precision/recall,
  error rates, or savings. See [benchmark report](docs/benchmark-report.md).
- The deterministic baseline is a configured fallback, not a strong optimized
  router — no comparative quality claim rests on it alone.
- Cloud model availability churns (27/222 on 2026-10-11); always discover
  live, never hardcode.
- Brain availability must be checked through the current caller's MCP session;
  this CLI does not prove client-wide connectivity or automatic retrieval.

## Contributing / Security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
