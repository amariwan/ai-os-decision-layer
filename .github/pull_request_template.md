## What changes?

## Why?

## Verification

- [ ] `uv run ruff check src tests eval` clean
- [ ] `uv run pytest -q` passes (report counts)
- [ ] No credentials, weights, datasets, telemetry, or local paths added
- [ ] Deterministic policy remains authoritative (advisory backends fail closed)
