# Static n8n Workflow Library

The library extends the existing `ai-os` CLI and Python package. One local SQLite/FTS5 database with WAL snapshot reads owns sources, structural groups, behavior variants, provenance, and failed-input issues. It does not connect to n8n or execute workflow code.

## Data and boundaries

Default data directory: `data/workflow-library/`, ignored by Git and ProjectAtlas. Public immutable Git snapshots are stored as compressed upstream archives; official API definitions are cached with document SHA-256 revisions. Raw source snapshots are never modified or checked out. Untrusted names/descriptions/code are data, never agent instructions.

- Source state: `KEEP`, `DROP`, `UNAVAILABLE`. Duplicate rate does not decide source retention. A missing pinned commit is unavailable, not silently fetched from a moving branch. Source seeding is idempotent and preserves an already registered source's state.
- Canonical records: `CANDIDATE` or `UNSAFE` after static analysis. `VERIFIED` is reserved for a future explicit verification procedure and is never automatically assigned.
- Failed source documents: `BROKEN`, separately recorded/searchable; they may contain no parseable workflow at all.
- Occurrences: additional normalized occurrences have relationship status `DUPLICATE`; their canonical security status remains visible.
- Local/cloud/API flags are tri-state: true/false/null (unknown). Unknown integrations and dynamic HTTP destinations never confidently qualify as local. A local-capable dependency can still require installation or configuration. Cost/paid-service need is unknown without account-specific evidence.

## Hash contracts

All three hashes use SHA-256. `raw_hash` hashes exact file bytes for a direct export; for an embedded object it hashes deterministic JSON serialization of that extracted object. `document_raw_hash` always hashes the original containing document, preserving byte provenance for datasets/wrappers. ZIP members retain archive path plus member name. JSONL pointers retain line numbers.

`normalized_hash` hashes directed, typed, indexed connections and executable node parameters/versions/behavior/settings. It removes export IDs, layout, timestamps, node notes/UI properties, account IDs/names and other top-level UI metadata; supported `$node[...]` / `$(...)` references follow renamed nodes. It intentionally preserves endpoint destinations, business IDs, prompts and code because changing them changes behavior. It is not safe to strip arbitrary `id` keys inside business parameters.

`structural_hash` groups canonical topology, node types/versions, credential types and parameter shapes; parameter values remain in separate behavior variants. Directed graph color refinement plus bounded exact permutations avoids relying only on filenames, counts or edge histograms. Highly symmetric graphs exceeding the canonicalization budget retain names and may produce conservative false negatives. Graphs above 512 nodes are explicitly rejected into issues rather than consume unbounded CPU.

Search operates on a single behavior variant and only then groups structural matches. A RAG tag on one variant must never combine with a local flag on an unrelated cloud variant. Details show all variants; search metadata describes the first matching variant and returns the complete matched variant IDs. Other source names/descriptions/tags remain searchable aliases with provenance. Official API wrapper descriptions/categories supplement missing embedded workflow metadata without modifying raw hashes.

## CLI

Run from the repository root:

```sh
uv run ai-os workflows sources --catalog /absolute/path/repository-catalog.json --manifest sources.json
uv run ai-os workflows sync
uv run ai-os workflows sync --source n8n-official
uv run ai-os workflows search "RAG Ollama Postgres local" --exclude-integration openai
uv run ai-os workflows search --source zengfr/n8n-workflow-all-templates --category RAG
uv run ai-os workflows search --status BROKEN
uv run ai-os workflows get WORKFLOW_ID
uv run ai-os workflows report --output outputs/n8n-workflow-registry-report.md
```

`--db PATH` belongs after `workflows` and before the operation. Official sync limit 0 means all catalog entries; a nonzero `--official-limit` is explicitly partial. Repeated sync reuses the pinned source/cache snapshot and occurrence keys. Revisions are retained as provenance; changing hash/analysis logic requires a deliberate fresh database build using the same snapshots.

Large archives/files are bounded; skipped/corrupt inputs and partial source coverage are recorded. Katalog-only repositories remain sources even if they contain zero workflows. Separate linked repositories are not recursively crawled without an explicit source entry.

## Read-only API and MCP

```sh
uv run ai-os workflows serve --port 8766
uv run --extra registry-mcp ai-os workflows mcp
```

HTTP binds only to `127.0.0.1`; GET routes: `/workflows`, `/workflows/{id}`, `/search`, `/categories`, `/integrations`, `/sources`, `/health`. Filters: query, category, node, integration, source, local_capable, risk, status, credentials, external_service, exclude_integration, limit, offset. Search has bounded pagination and parameterized SQL. No execution, mutation or HTTP export endpoint.

The optional official MCP Python SDK v2 adapter exposes `search_workflows`, `get_workflow`, `find_local_workflows`, `find_workflows_by_integration`, `get_workflow_dependencies`, `get_workflow_security_report`. It opens SQLite in read-only mode per call. Neither the keyword search nor CLI requires the SDK, embeddings or cloud inference. The adapter is implemented/tested but no global client configuration or production MCP server is changed.

Example client command: `uv run --directory <path-to-this-repo> --extra registry-mcp ai-os workflows mcp`. Add it to a client only through a separate deliberate configuration change.

## Controlled export

```sh
uv run ai-os workflows export WORKFLOW_ID --variant VARIANT_ID --acknowledge-risk --output reviewed.json
```

First read the detail/dependencies/security report. A multi-variant group requires a variant ID. Export exclusively creates a new local file, forces `active=false`, strips credential bindings/pinned/static data/export identity and redacts recognized secret-bearing fields. Subworkflow references are refused until deliberately rewired. Embedded code requires human inspection: static detection/redaction cannot guarantee that every secret or dangerous behavior is recognized. There is no n8n import or activation method in this module.

## Verification

`uv run --extra dev --extra registry-mcp pytest -q` tests synthetic workflows and real SDK calls, never upstream workflow execution. `uv run ruff check src tests` checks the existing host plus extension. The generated report distinguishes accepted structure, duplicates, broken inputs, coverage gaps and static-only judgments. Licenses must still be reviewed per content before reuse.

Primary references consulted: [official n8n template API contract](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/configuration-examples/configure-a-custom-workflow-templates-library/) and [official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/get-started/first-steps/).
