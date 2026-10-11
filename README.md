# AI OS Decision Layer

Deterministic-first local decision host with optional model backends in
**shadow/advisory mode only**. The deterministic rule baseline is authoritative:
no model recommendation can change a route, execute tools, weaken policy, or
block a request.

The same host includes a static n8n Workflow Library: source registry, SHA-256
deduplication with provenance, conservative security/dependency metadata,
SQLite FTS5 search, read-only HTTP/MCP adapters, and explicit inactive export.
See [workflow-library documentation](docs/workflow-library.md). It does not
execute workflows or change any running n8n instance.

## Status legend

- **Implemented + verified**: deterministic `PolicyEngine`, rule fallback,
  Laya shadow adapter (mapping only), JSONL telemetry, CLI, synthetic eval
  harnesses, 134 unit tests, `ruff` clean.
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
cp config.example.yaml config.yaml   # config.yaml is git-ignored
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

- Private/secret-like request text never leaves local execution unless
  `freellm.allow_private: true` **and** per-call approval.
- Shadow/telemetry metadata carries counts and sources only — no prompts, raw
  context, keys, or candidate IDs.
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
- Prior Graphiti episode-vs-fact retrieval fix is UNVERIFIED (no MCP
  reachability); memory code untouched.

## Contributing / Security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
