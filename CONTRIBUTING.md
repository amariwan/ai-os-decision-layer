# Contributing

## Ground rules

- Deterministic policy stays authoritative. Advisory backends (local model,
  cloud, d1) must fail closed to fallback — never fail open, never execute.
- Smallest coherent change; existing tests must keep passing.
- No credentials, weights, datasets, telemetry, or local paths in commits.
  Secrets go in environment variables (`LAYA_MODEL_DIR`, `FREELLMAPI_KEY`).
- Synthetic fixtures only in `eval/` — no real user data, prompts, or logs.

## Workflow

```bash
uv sync --extra dev
uv run ruff check src tests eval
uv run pytest
```

Add regression tests for fixed defects where feasible. Experimental features
(d1, cloud escalation, adaptive routing) stay behind explicit approval flags
and ship disabled by default, with rollback notes in `docs/rollback.md`.

## License

By contributing you agree your contribution is licensed under the repository
`LICENSE` (MIT). Third-party code or weights (e.g. Liquid d1 under `lfm1.0`,
upstream n8n templates) are never vendored — reference upstream instead.
