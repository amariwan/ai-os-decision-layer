# Optional native System-One extension

Status: pre-download prototype, d1 disabled. Native inference is BLOCKED by the
explicit resource approval boundary. No production routing is enabled.

The existing `DecisionEngine` remains the single host entry point. Its existing
`decide` and Laya path are unchanged. `recommend(request, backend)` returns a typed
recommendation; `observe(request, backend)` additionally returns the deterministic
authority separately from the model observation. Neither method executes actions.
The CLI exposes the latter through an explicit `ai-os system-one` subcommand.

## Contracts and trust boundaries

`BoundedRequest` contains the existing `DecisionState`/`DecisionQuestion` types,
a caller-verified `CapabilitySnapshot`, deterministic fallback/required answers,
and an explicit action/risk/approval envelope. These inputs are trusted caller
policy, not fields extracted from the task or a model. Exact skill paths avoid
name collisions. Tools/agents must come from current-client exposed metadata;
registration in config does not prove access. Context IDs must come from validated
retrieval candidates. No backend grants permissions or invokes tools.

The request is limited to 32 questions and 64 KiB, choices to 2–64 options,
scores to 2–10 levels, images to two local files of at most 4 MiB each. Native
outputs must contain exactly the requested questions, allowed keys, finite
probabilities summing to one, consistent choices/expectations/confidence, matching
score legends, and nonnegative integer usage. Invalid input is rejected before
inference; invalid output/unavailability/timeouts use explicit deterministic
fallback. Unknown/protected actions require human approval regardless of model
output. Existing PolicyEngine denies/approvals are also applied. Required answers
cannot be removed. Risk recommendations can only raise the trusted risk floor.

`Recommendation.application_contract` produces and validates normalized planning
fields. Unasked fields remain null. Selected model IDs and boolean skill/tool IDs
are checked against the same snapshot. `confidence_semantics` distinguishes
native distributions, Qwen one-hot transport encoding, and deterministic answers.
None is treated as measured real-world reliability. Low native confidence and all
Qwen answers are marked uncertain. There is no automatic execution confidence gate
in this extension.

## Backends and inference strategy

1. Deterministic policies/runtime discovery precede every decision.
2. Use `DeterministicFallback` when approved rules/configuration suffice.
3. Select `LiquidD1Backend` explicitly only for ambiguous bounded classification.
4. Select `ExistingQwenBackend` explicitly when reasoning is needed.
5. Protected actions still need caller-side human authorization.

No automatic model escalation/agent delegation is activated. This avoids adding
another orchestration framework. The fallback answers are caller-approved safe
defaults, not a new language classifier. The existing rule router remains available.

D1 requires both an explicit enabled/approved flag, an isolated interpreter, and a
local snapshot. The worker verifies inspected source/config/license hashes and the
weight hash before importing remote model code. It sets Hugging Face/Transformers
offline mode, uses `local_files_only=True`, and loads a local path with
`trust_remote_code=True`. There is no automatic download. The native
`system_one` and `system_one_batch` APIs are used; independent questions over a
state share the native forward pass. The worker warms once and measures the next
batch call. This is a cold worker per request, intentionally not a permanent
service. `subprocess.run` enforces a 0.01–600 second deadline and kills/waits for
the child on timeout. Disk weight verification is part of total cold overhead,
not model load time. Device selection is MPS or CPU; CPU uses float32.

The reusable runtime has a bounded, in-memory-only cache keyed by the complete
request, requirements, inventory and image contents. Repeated calls through the
same DecisionEngine/backend instance reuse it; new model/config/inventory state
requires a fresh backend/snapshot. Cache hits report zero newly consumed tokens.
No prompts, raw context, errors or candidate IDs enter shadow metadata. Logging is
caller-controlled; no new database, hook, daemon or automatic log writer is added.
The explicit CLI prints decisions to the invoking user and is not a telemetry sink.

## Reproduce without installations

Use the existing host environment (no `uv sync` required):

```sh
cd <path-to-this-repo>
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests eval/run_system_one_eval.py
.venv/bin/python -m ai_os_decision.cli system-one eval/system_one/UC03-en-request.json
PYTHONPATH=src .venv/bin/python eval/run_system_one_eval.py --output outputs/system-one-deterministic.json
PYTHONPATH=src .venv/bin/python eval/run_system_one_eval.py --backend qwen --model qwen3.5:9b-mlx --output outputs/system-one-qwen.json
```

The benchmark covers 30 synthetic German/English microtasks, including two
reproducible PNG visual fixtures. The two visual cases are excluded from the text
Qwen baseline. This corpus is intentionally small and is not proof of agent task
completion, calibrated confidence, skill multilabel precision/recall, production
error rate or token/cost savings. A fallback result is not counted as a successful
model inference. The configured-fallback baseline is not a strong optimized rule
router; no comparative quality claim should be based on it alone.

## Approval and rollout

After resource approval only: create an isolated CPython 3.12 environment outside
the host's `.venv`, resolve a complete transitive dependency lock using
`docs/d1-requirements.txt`, install there, download only revision
`051bcc464b01b9f92942b364d9586b0ef5912432` into a dedicated local snapshot,
and run the native probe using `--backend d1 --snapshot ... --python ...
--approve-d1`. Do not change the Ollama installation/environments. The current
pins are a proposal, not a tested native environment. No hosted Liquid API is used.

Stage A still needs successful native text/noul/choice/score/batch/image inference,
repeatability, offline/no-egress confirmation and measured memory under concurrent
Qwen. Stage B requires representative shadow labels, drift handling and bounded
failure recovery. Stage C/D require explicit separate activation approval, zero
critical permission/invalid-option regressions, acceptable measured latency/RAM,
and evidence of useful task completion against both current rules and Qwen.
A numerical acceptance threshold should be selected with a representative labeled
corpus before limited routing; the 30 illustrative cases do not justify one.

Rollback: the delivery includes exact before/after hashes, source patch and a guarded
rollback helper. It refuses rollback over newer edits. Global instructions, policy,
Ollama configuration, dependency lock and existing service/data state are unchanged.
