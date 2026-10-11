# Unified AI-OS task entry

Implemented 2026-10-11 after approval of the bounded CLI design. Extends the
existing decision host and Laya adapter; no additional agent platform,
database, resident service or external model provider was introduced.

## Use from any directory

```sh
uv run --project /Users/snow/dev/ai-os/decision-layer --no-sync ai-os task "Review the Python repository" --require-laya
```

From the repository, use `uv run --no-sync ai-os task "..."`. The command
returns a plan, never executes the task or calls tools. The supplied task
text is not echoed into the JSON response or logged by this command.

The pipeline is input validation → deterministic policy → deterministic
route + local Laya observation → structured `ai-os-task/v1` result. A policy
deny ends before model loading and returns no route. Production approvals
remain visible and yield a nonzero exit. Models cannot weaken this policy or
replace the authoritative route. Model scores are not execution authority.

Laya runs in an isolated subprocess using existing local RLAgent code and
weights. The deadline includes import/model loading; the child is killed and
reaped on timeout. Shadow slots remain held until work actually ends, which
prevents repeated caller timeouts from creating an unbounded queue.

## Configuration and results

Configuration selection: explicit `--config` → existing `config.local.yaml`
→ tracked `config.yaml`. Each file is a complete configuration, not a merged
overlay. The task entry requires an existing file with a mapping `policy`
section and rejects malformed consumed sections with sanitized JSON.

Local checkpoint selection: `--model-dir` → config `laya.model_dir` →
`LAYA_MODEL_DIR` → legacy relative default. Checkpoint directories contain
executable model code and must be trusted. Local configuration is Git-ignored;
the installed `config.local.yaml` is mode 0600. Tracked `config.yaml` retains
its original safe defaults. `--timeout-ms` accepts 10..600000 milliseconds.

- Exit 0: a deterministic plan is available; inspect `laya.status` for the
  actual observation or fallback. No task execution is implied.
- Exit 2: denied, approval required, invalid request or invalid configuration.
- Exit 3: `--require-laya` was set but Laya did not produce an observation.

Cloud remains disabled in both tracked and installed local configurations.
The unified task command has no cloud backend. Global Brain stays the
calling client's existing MCP responsibility; it is not automatically
connected or written by this CLI.

## Verification evidence

- Baseline: 166 tests passed before modifications.
- Final full suite: 194 tests passed; Ruff passed; `git diff --check` clean.
- New regressions were observed failing before implementation: cloud
  transfer fields/model, quoted authorization booleans, recovery status,
  shadow queue admission, new CLI/schema, missing/malformed configuration
  and local config selection.
- Synthetic local RLAgent subprocess tests cover successful observation,
  disagreement with deterministic routing, a missing checkpoint, a blocked
  inference killed/reaped at its deadline and CLI process termination.
- Real existing Laya checkpoint produced successful observations in three
  task probes: approximately 19.9 s, 18.8 s and 19.1 s. The last probe used
  the installed local configuration and `--require-laya`, exit 0. No fallback
  occurred. Laya's reasoning classification differed from the authoritative
  baseline; the baseline remained unchanged. This is an availability and
  isolation check, not an accuracy/calibration benchmark.
- Actual deny and missing-config CLI probes returned structured blocked
  results without Laya invocation.
- Two independent read-only reviews examined task entry/lifecycle and Python
  cloud boundaries. Findings were fixed and rechecked; final reviews reported
  no remaining actionable findings in their scopes.
- Global Brain status was connected to Neo4j; the exact project-group
  retrieval returned no facts/episodes. No new Brain data was written.

Additional audit fixes: the final transferred state, questions and model ID
share one bounded privacy validator in parent and worker; `allow_private`
requires a real boolean, and cloud config string booleans fail closed.
Recognized sensitive content is blocked before transport. This heuristic
cannot prove absence of all private information. Reading circuit-breaker
status no longer reserves the half-open recovery probe.

## Scope and rollback

Pre-existing uncommitted work was preserved. Exact pre-task copies of selected
files and a SHA-256 manifest are in the local audit baseline directory
`/Users/snow/dev/ai-os/audit-2026-10-11/implementation-baseline-201942`.
The original `.gitignore` was also backed up there before adding the local
config exclusion. The tracked configuration matches its baseline hash.

To disable the installed local Laya configuration, move `config.local.yaml`
aside; tracked defaults then apply. To undo code changes, compare each touched
file against the pre-task copy and selectively revert this task's edits.
Never restore the whole working tree over newer edits. New files are
`task_entry.py`, `laya_worker.py` and their two regression test modules.

No deployment, commit, push, credential rotation, database/network change,
workflow activation, automatic client hook or memory write was performed.
Other runtimes do not start using this entry until they explicitly call it.

Skills applied: Superpowers Brainstorming (bounded design approved),
Systematic Debugging, TDD and Verification Before Completion; canonical Code
Review for independent reviews. Existing ProjectAtlas and scoped Brain reads
were used. No `find-skills`, skill installation or model download was needed.
