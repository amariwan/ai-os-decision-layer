# Laya model AUTO

The existing FreeLLMAPI backend can select and call a concrete model through
the loopback gateway. This is a recommendation-only System-One invocation:
the deterministic baseline remains authoritative and no tool is executed.
It does not change the model running a Codex chat.

```sh
uv run --no-sync ai-os system-one examples/auto-model.json --backend freellm --model auto
```

Omitting `--model` with `--backend freellm` also selects AUTO. Other backends
keep their existing defaults. `--config` overrides the normal selection of
`config.local.yaml` when present, otherwise `config.yaml`.

Local configuration must contain `freellm.enabled: true` and
`freellm.auto_enabled: true`. A cloud invocation needs either `--approve-cloud`
or the standing opt-in `freellm.allow_auto_calls: true`. Tracked defaults disable
all three flags; this workstation's ignored local configuration enables them
under the user's approval. Setting `auto_enabled: false` rolls AUTO back.

Credentials come from `FREELLMAPI_KEY`, otherwise the macOS generic-password
Keychain item with service `ai-os.freellmapi`, account `gateway`. The credential
is never put in config, request JSON, model prompts or decision output.
Native storage uses Apple's
[SecItem APIs](https://developer.apple.com/documentation/security/adding-a-password-to-the-keychain).
Unavailable or locked credentials yield a visible transport failure. URLs
accept the loopback HTTP root or `/v1`; proxies and redirects are disabled for
authenticated gateway requests. The gateway can forward content to external
providers; a loopback URL does not make their inference local.

Before discovery or inference, AUTO checks the complete cloud-bound payload
against the existing secret-hint screen, hard policy, and deterministic
approval result. Protected actions, pending approval, denied requests and
images cannot use AUTO. AUTO always keeps `allow_private=False`.
The screen detects configured patterns and known secret hints; it is not a
general proof that arbitrary natural-language content is public.

Each invocation refreshes `/v1/models`. Only exact `available=true` rows with
a valid context length covering the serialized request plus 2048 tokens of
conservative overhead are eligible. It excludes embedding IDs, opaque
`auto`/`fusion` routers, and models outside the configured allowlist. Missing
capability or pricing metadata is not invented. JSON mode is requested only
when the gateway advertises `response_format` support.

The first four eligible IDs in lexical order form a bounded shortlist for
local Laya. A single eligible model is selected directly. The checkpoint's
context guard rejects overflow; timeout, invalid answers or unavailable Laya
produce a visible deterministic choice from the same shortlist. This is an
eligible-model recommendation, not a benchmark-proven best-model selector.
Quality and pricing remain unknown. There is one completion attempt per
invocation, without automatic provider retries. The existing quota tracker
is process-local and does not preserve cooldown across CLI runs.

JSON output includes `model_routing` (selection source, candidate counts,
fallback and inference status), `cloud_eligibility`, and the existing shadow
metadata. Exit codes: 0 for a valid completion, 2 for a blocked/no-eligible AUTO
request, 3 for discovery, routing setup or inference failure. A Laya failure
with a valid deterministic selection and successful completion returns 0
with `fallback_used=true`.

## Observed synthetic verification, 2026-10-11

- Authenticated discovery through Keychain: 224 advertised, 27 available.
- AUTO filters retained 16 eligible models and shortlisted four.
- Local Laya selected `dots3-note-preview`; the gateway returned a valid bounded
  answer with 122 input / 400 output tokens, no fallback, exit 0.
- No real user payload, repository content, Brain data or tool execution was
  involved. These observations establish one working route, not the quality,
  entitlement, or availability of every advertised model.
