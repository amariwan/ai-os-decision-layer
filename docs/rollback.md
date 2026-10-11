# Rollback

No git repository exists here, so rollback is file-based. No commits were made;
all prior uncommitted work (if any) was preserved — this session only edited
the files listed below and added four new docs.

## 1. Changed files (this session only)

1. `src/ai_os_decision/system_one_worker.py` — `model_capabilities()` hardened
   (validate inline list; guarded `/api/show` probe; `[]` on any failure).
2. `src/ai_os_decision/system_one_io.py` — `discover_models()` hardened
   (`TypeError` on malformed envelope; skip malformed rows; per-row probe
   failure → `completion=False`).
3. `tests/test_system_one.py` — appended 8 regression tests after
   `test_existing_deny_policy_is_applied_to_shadow` (do not touch earlier tests).
4. New docs: `docs/implementation-report.md`, `docs/github-reuse-analysis.md`,
   `docs/benchmark-report.md`, `docs/rollback.md` (this file).

## 2. How to revert safely

- Delete the four new docs, then restore the two source functions from the
  descriptions above (or from file backup if the owner snapshotted them):
  - `model_capabilities`: `if "capabilities" in row: return row["capabilities"]; return http_json("/api/show", …).get("capabilities", [])`
  - `discover_models`: single-expression version reading `http_json("/api/tags")["models"]`.
  - Remove the appended tests; re-run `uv run pytest -q` (expect 79 passed) and
    `uv run ruff check src tests`.
- Reverting restores the prior crash-on-malformed-inventory behavior; the new
  behavior is strictly more fail-closed, so prefer keeping it.

## 3. Disabling experimental features

- d1: already disabled by default (`LiquidD1Backend` requires
  `enabled=True, approved=True` + snapshot + interpreter). Verify with
  `test_d1_disabled_never_spawns`. Never pass `--approve-d1`.
- Qwen backend: omit `--backend qwen`; `DecisionEngine` defaults to
  deterministic/Laya-shadow paths. No persistent services were started.
- No global OpenCode settings, credentials, hooks, or services were changed —
  nothing to disable.

## FreeLLMAPI changes (2026-10-11 session)

Changed: `src/ai_os_decision/system_one_worker.py` (`cloud_json`, `freellm`,
`_answers_from_values` shared with `qwen`), `system_one_backends.py`
(`FreeLLMBackend`, `_cloud_exc`), `system_one.py` (`privacy_screen`,
`QuotaTracker`, `cloud_eligible`), `system_one_io.py`
(`discover_freellm_models`, `run_cli` freellm branch), `cli.py`
(`--backend freellm`, `--approve-cloud`), `config.yaml` (`freellm:` section,
`enabled: false`), `eval/run_system_one_eval.py` (freellm branch),
`tests/test_system_one.py` (28 new tests), new `docs/freellm.md`.
To revert: delete the freellm branches/functions/tests/docs listed above and
restore `qwen()`'s inline answer coercion; re-run `uv run pytest -q`
(expect 95 passed) and `uv run ruff check src tests eval`.
To disable without reverting: keep `freellm.enabled: false` (default) — the
backend refuses without `enabled+approved`, and no key is stored anywhere.
The `FREELLMAPI_KEY` env var (if exported) should be unset; no rotation needed
beyond normal hygiene as it never left the local machine.
