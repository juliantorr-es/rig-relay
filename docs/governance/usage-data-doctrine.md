# Rig Relay Usage Data Doctrine

## Purpose

Rig Relay produces a behavioral corpus of agent workflow observability data.
This doctrine defines what is collected, how it is retained, and under what
conditions it may be exported, shared, or used for evaluation.

**Ratification:** This doctrine is normative for all Rig Relay sessions.
Automated tooling and human operators SHALL follow it.

## Architecture

Usage data flows through four layers:

```
.raw/         Raw evidence — full tool payloads, transcripts, stdout/stderr,
              receipts, and artifacts.  High fidelity, high volume.
.events/      Canonical event stream — append-only JSONL, one event per
              tool call, state change, refusal, or artifact emission.
.datasets/    Flattened evaluation rows — one row per mission, task,
              tool call, or mutation.  Derived from events.
.manifests/   Hashes, schema versions, provenance, retention metadata.
```

**Principle:**
- Raw logs are evidence.
- Events are observability.
- Datasets are learning material.
- Evals are product feedback.

The canonical redaction boundary for shareable and remote-facing artifacts is
`rig_relay.evidence.redaction`. Bundle writers, export helpers, and audit
artifact builders must route through that shared module so content-light
behavior remains consistent.

## Retention Classes

### Evidence-Retained (always kept locally)

These fields are permanently retained in the local session directory
(`~/.rig/relay/sessions/<session_id>/`). They contain no source code,
no prompt text, and no file contents.

| Field | Source |
|-------|--------|
| session_id | `observability.jsonl` envelope |
| parent_session_id | `observability.jsonl` envelope |
| event_id, event_name, event_hash | `observability.jsonl` envelope |
| sequence, created_at | `observability.jsonl` envelope |
| tool_call_id | `TOOL_CALL_COMPLETED`, `TOOL_REASONING_TRACE` |
| tool_name | `TOOL_CALL_COMPLETED`, `TOOL_REASONING_TRACE` |
| tool_input_sha256 | `TOOL_CALL_COMPLETED` |
| tool_output_sha256 | `TOOL_CALL_COMPLETED`, `TOOL_REASONING_TRACE` |
| tool_output_kind | `TOOL_REASONING_TRACE` |
| determinism_class | `TOOL_REASONING_TRACE` |
| mutation_class | `TOOL_REASONING_TRACE` |
| status | `TOOL_CALL_COMPLETED` |
| decision, approval_type | `TOOL_CALL_COMPLETED` |
| agent_profile_name | `TOOL_CALL_COMPLETED` |
| model | `REQUEST_ACCOUNTED`, `TOOL_CALL_COMPLETED` |
| nb_files_created, nb_files_modified | `TOOL_CALL_COMPLETED` |
| latency_ms, input_bytes, output_bytes | `TOOL_REASONING_TRACE` |
| warnings | `TOOL_REASONING_TRACE`, `GitStateArtifact` |
| repo_state_sha256 | `GitStateArtifact` |
| artifact_record_sha256 | `ArtifactEnvelope` |
| receipt_sha256 | `receipts.jsonl` |
| schema_version | all artifacts |
| thinking_enabled, thinking_type, reasoning_effort | `TaskSessionLinkArtifact` |
| provider | `TaskSessionLinkArtifact` |
| authorization_receipt_sha256 | `desktop.intent.completed`, `desktop.intent.refused` |
| authorization_action | `desktop.intent.completed`, `desktop.intent.refused` |
| authorization_status | `desktop.intent.completed`, `desktop.intent.refused` |
| observation_id | `MODEL_OBSERVATION_CAPTURED` |
| task_kind, task_fingerprint | `MODEL_OBSERVATION_CAPTURED` |
| provider_kind, provider_name, model_id, backend | `MODEL_OBSERVATION_CAPTURED` |
| tool_call_count, tool_success_count, failure_count | `MODEL_OBSERVATION_CAPTURED` |
| latency_ms (observation) | `MODEL_OBSERVATION_CAPTURED` |

### Locally Retained (kept on disk, never exported)

These fields are stored in the local session directory but MUST NOT
be included in any export, upload, or shared dataset without explicit
user opt-in and redaction.

| Field | Source |
|-------|--------|
| Raw prompt text | context assembly artifacts |
| Model output text | `messages.jsonl`, inline tool results |
| stdout/stderr from bash | tool output artifacts |
| File contents (even hashed source) | tool payloads |
| Repository paths beyond repo root | `SearchQueryArtifact.root` |
| User messages | `messages.jsonl` |
| Full search query strings | `SearchQueryArtifact.query` |
| File snippets in search results | `SearchResultArtifact` items |

### Exportable After Redaction

Derived evaluation datasets may be exported or shared IF:

1. The user has explicitly opted in (via config flag or command).
2. All locally-retained fields have been stripped.
3. Only evidence-retained fields plus derived metrics remain.
4. Export passes the redaction validator (`rig-relay doctor redact --check`).

Exportable derived datasets:

| Dataset | Description |
|---------|-------------|
| `tool_failure_patterns.jsonl` | tool_name, status, warnings, determinism_class, model |
| `mission_outcome_dataset.jsonl` | session_id, agent_profile, completion_status, tool counts, refusal count |
| `dirty_file_conflicts.jsonl` | repo_state_sha256, refused_writes count, skipped_files count, dirty_file_count |
| `provider_task_performance.jsonl` | provider, model, thinking_enabled, agent_profile, task_id, status, latency_ms |
| `search_quality_dataset.jsonl` | normalized_query_sha256, result_sha256, files_clicked_after, files_edited_after, mission outcome |
| `fleet_decomposition_dataset.jsonl` | parent_session_id, child_count, child_profiles, parallelism, conflicts, outcome |
| `mutation_safety_dataset.jsonl` | file path hash, before_sha256, after_sha256, protected, hash_matched, allowed |
| `checkpoint_commit_dataset.jsonl` | session_id, task_id, commit_sha, files_committed, pre_commit_head, post_commit_head, branch |

### Checkpoint Events

Checkpoint commits emit these observability events:

| Event Name | Description |
|------------|-------------|
| `rig.relay.checkpoint.committed` | A governed checkpoint commit succeeded. |
| `rig.relay.checkpoint.refused` | A checkpoint commit was refused by the guard. |

### Cross-Session Coordination Datasets

Coordination events from [Cross-Session Coordination](cross-session-coordination.md) feed these derived datasets.
They measure session/task orchestration behavior across multiple active Rig Relay sessions.

#### `cross_session_coordination_dataset.jsonl`

Purpose: Measure session/task coordination behavior across multiple active Rig Relay sessions.

Row fields:

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | uuid | The session emitting the coordination event. |
| `parent_session_id` | uuid\|null | Parent session if delegated. |
| `fleet_id` | string\|null | Fleet identifier for grouped sessions. |
| `task_id` | string\|null | Delegation task identifier. |
| `agent_profile_name` | string | Agent profile (reviewer, implementer, tester, documenter, aggregator). |
| `event_name` | string | Coordination event name (e.g., `coord.path.reserved`). |
| `coord_event_hash` | sha256 | SHA256 of the canonical coordination event. |
| `provider` | string | LLM provider. |
| `model` | string | Model identifier. |
| `thinking_enabled` | boolean | Whether extended thinking was active. |
| `reservation_mode` | string\|null | `read` or `write`, if a path reservation event. |
| `reservation_status` | string\|null | `granted`, `refused`, `stale`, or `released`. |
| `reserved_path_count` | integer | Number of paths reserved in this event. |
| `reserved_path_hashes` | array of sha256 | Salted SHA256 hashes of reserved paths. |
| `conflict_count` | integer | Number of conflicts in this event. |
| `artifact_count` | integer | Number of artifacts published in this event. |
| `handoff_count` | integer | Number of handoffs in this event. |
| `latency_ms` | number | Wall-clock latency for the coordination operation. |
| `outcome` | string | `completed`, `blocked`, `refused`, or `failed`. |

#### `coordination_conflict_dataset.jsonl`

Purpose: Measure conflicts, refusals, stale leases, and successful conflict resolution.

Row fields:

| Field | Type | Description |
|-------|------|-------------|
| `conflict_id` | string | Unique conflict identifier. |
| `conflict_kind` | string | `path_write_overlap`, `stale_lease`, `dirty_file_protected`, or `dependency_unsatisfied`. |
| `session_id` | uuid | Session that reported the conflict. |
| `other_session_id` | uuid\|null | Other session involved in the conflict. |
| `task_id` | string\|null | Task identifier if task-scoped. |
| `path_hashes` | array of sha256 | Salted SHA256 hashes of paths involved in the conflict. |
| `resolution` | string | `serialized`, `scope_split`, `abandoned`, `takeover`, or `manual_review`. |
| `prevented_write` | boolean | Whether the conflict prevented a file mutation. |
| `outcome` | string | `resolved`, `unresolved`, or `false_positive`. |

#### `artifact_reuse_dataset.jsonl`

Purpose: Measure whether sessions reuse existing artifacts instead of duplicating search/audit/test work.

Row fields:

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | uuid | Session consuming the artifact. |
| `task_id` | string\|null | Task identifier if task-scoped. |
| `artifact_kind` | string | `search_results`, `git_state`, `task_session_link`, or `tool_reasoning_trace`. |
| `artifact_sha256` | sha256 | SHA256 of the artifact. |
| `producer_session_id` | uuid | Session that produced the artifact. |
| `consumer_session_id` | uuid | Session that consumed the artifact. |
| `reuse_kind` | string | `read`, `referenced`, `validated`, or `superseded`. |
| `avoided_tool_call` | boolean | Whether reusing the artifact avoided a duplicate tool call. |
| `outcome` | string | `useful`, `stale`, or `irrelevant`. |

### Coordination Data Retention

Coordination data follows the same three-class retention model.

**Evidence-retained** (always kept locally):

| Field | Classification |
|-------|----------------|
| `session_id`, `parent_session_id`, `fleet_id`, `task_id` | Evidence-retained |
| `event_name`, `coord_event_hash` | Evidence-retained |
| reservation mode, reservation status | Evidence-retained |
| salted path hashes | Evidence-retained |
| artifact hashes | Evidence-retained |
| conflict kind, resolution kind | Evidence-retained |
| timing/latency | Evidence-retained |
| provider, model, thinking metadata | Evidence-retained |

**Locally retained** (kept on disk, never exported):

| Field | Classification |
|-------|----------------|
| Raw task prompts | Locally retained |
| Raw handoff messages | Locally retained |
| Raw artifact bodies | Locally retained |
| Raw paths (unsalted) | Locally retained |
| Raw search queries | Locally retained |
| stdout/stderr from child sessions | Locally retained |
| Raw child model outputs | Locally retained |

**Exportable after redaction:**

| Field | Classification |
|-------|----------------|
| Salted path hashes | Exportable |
| Event categories | Exportable |
| Counts | Exportable |
| Durations | Exportable |
| Provider/model/task profile metadata | Exportable |
| Outcome labels | Exportable |

### Derived Coordination Dataset Exporter

The script `scripts/rig_relay_export_coordination_datasets.py` transforms normalized coordination/checkpoint event envelopes into schema-validated derived dataset JSONL rows.

Usage:
```
uv run python scripts/rig_relay_export_coordination_datasets.py \
    --events .build/rig-relay/coordination/events.jsonl \
    --output-dir .build/rig-relay/derived \
    --schemas-dir docs/schemas
```

Output (all in `--output-dir`):
- `cross_session_coordination_dataset.jsonl`
- `coordination_conflict_dataset.jsonl`
- `artifact_reuse_dataset.jsonl`
- `checkpoint_eval_dataset.jsonl`

### Built-in Tool Refinement Reports

Built-in tool refinement reports convert observed usage data into a ranked implementation backlog. They consume derived datasets only, not raw observability logs, and they stay content-light by using counts, labels, hashes, and schema-safe aggregates.

The refinement loop is:

1. Export or compact derived datasets.
2. Generate a refinement report from the derived corpus.
3. Review the ranked backlog for built-ins that should be improved, split, hardened, promoted, or replaced.
4. Implement the smallest safe slice and re-run the report to verify pressure changed.

Refinement reports are product feedback artifacts, not raw evidence exports.

### Built-in Refinement Packets

Built-in refinement packets convert ranked usage-data findings into bounded implementation missions. They bridge the refinement backlog into the reviewer/orchestrator loop without requiring a human to rewrite the same scope text each time.

Packet generation rules:

1. Start from `builtin_tool_refinement_backlog.jsonl`.
2. Select the top ranked items by priority and deterministic score.
3. Emit one mission packet per selected item.
4. Keep packet content-light and bounded to the targeted tool/refinement slice.

The packet is a planning artifact. It does not carry raw evidence or raw operational data.

The first high-value shell replacement built-in is `validation_suite` (✅ implemented): it is allowlist-based, returns structured evidence with content-light hashes+previews, replaces repeated validation command bundles without arbitrary shell execution, and is wired into the Desktop Intent API as `run_validation_suite`.
- `export_manifest.json`

Mapping:
- Every `coord.*` event → `cross_session_coordination` row
- `coord.conflict.reported` / `coord.path.reservation_refused` → `coordination_conflict` row
- `coord.artifact.published` → `artifact_reuse` row
- `rig.relay.checkpoint.committed` / `rig.relay.checkpoint.refused` (from observability) → `checkpoint_eval` row

Features:
- Content-light enforcement: rejects payloads containing raw prompts, model outputs, file contents, stdout/stderr, diff bodies
- Schema validation via `jsonschema` (optional dependency, graceful fallback)
- `--strict` mode: fail on first validation error or missing input
- Tolerates missing input files with clear warnings
- Writes `export_manifest.json` with row counts, schema versions, warnings

### Normalized Coordination Event Payload Contracts

Every `coord.*` and checkpoint event now uses a normalized payload contract designed for reliable transformation into derived evaluation rows. Payloads are hash-heavy and content-light: no raw file contents, no raw prompts, no model outputs. Raw paths are replaced with salted SHA256 path hashes for exportability.

**Canonical payload fields (where applicable):**

- `session_id`, `parent_session_id`, `task_id`, `fleet_id`
- `agent_profile_name`, `event_kind`, `status`, `outcome`
- `provider`, `model`, `thinking_enabled`
- `reservation_mode`, `reservation_status`
- `path_hashes` (salted), `path_count`
- `artifact_kind`, `artifact_sha256`
- `conflict_kind`, `conflict_id`, `resolution_kind`
- `handoff_from_session_id`, `handoff_to_session_id`
- `latency_ms` / `duration_ms`
- `warnings`

**Checkpoint committed payload fields:**

- `session_id`, `task_id`, `branch`
- `pre_commit_head`, `post_commit_head`
- `commit_sha`
- `files_committed_count`
- `validation_summary_hash`
- `checkpoint_artifact_sha256`
- `status`: `"committed"`

**Checkpoint refused payload fields:**

- `session_id`, `task_id`
- `refusal_code`
- `status`: `"refused"`
- `warnings`

**Artifact reuse hooks (`coord.artifact.published`):**

- `producer_session_id` (defaults to `session_id` of the publishing session)
- `consumer_session_id` — null/future; available when cross-session artifact discovery is implemented
- `artifact_kind`, `artifact_sha256`
- `task_id`
- `reuse_kind` — null/future; populated when the coordination layer tracks consumption
- `avoided_tool_call` — null/future

For detailed payload field contracts, see the coordination event schemas in `docs/schemas/`.

### Fleet/Delegate Derived Metrics

From cross-session coordination events, these fleet-level metrics can be derived for evaluation:

| Metric | Description |
|--------|-------------|
| `parallelism_width` | Maximum number of concurrent child sessions. |
| `child_session_count` | Total number of child sessions delegated. |
| `read_only_child_count` | Child sessions with only read reservations. |
| `writer_child_count` | Child sessions with at least one write reservation. |
| `path_reservation_refusal_count` | Times a path reservation was refused. |
| `conflict_count` | Total coordination conflicts reported. |
| `handoff_count` | Total handoffs requested. |
| `artifact_reuse_count` | Times an artifact was reused by a different session. |
| `duplicate_search_count` | Times the same search query was executed by different sessions. |
| `blocked_duration_ms` | Total time sessions spent blocked waiting for reservations. |
| `active_duration_ms` | Total wall-clock time from first session start to last session close. |
| `time_to_first_artifact_ms` | Time from fleet start to first published artifact. |
| `time_to_first_conflict_ms` | Time from fleet start to first reported conflict. |
| `time_to_resolution_ms` | Time from conflict report to resolution. |
| `tests_run_count` | Total test commands executed across all child sessions. |
| `refusal_count` | Total write refusals across all sessions. |
| `successful_mutation_count` | Total successful file mutations across all sessions. |
| `protected_file_refusal_count` | Times a dirty file guard blocked a write. |
| `final_outcome` | Fleet-level outcome: `completed`, `partial`, `failed`, `cancelled`. |

## Privacy and Security Boundaries

1. **Local-first by default.** No usage data leaves the machine unless the
   user explicitly enables remote telemetry or export.

2. **Hash-heavy, content-light.** Derived datasets use SHA256 hashes instead
   of raw text for queries, outputs, file contents, and repository paths.

3. **Explicit opt-in for sharing.** Export and remote telemetry are
   controlled by separate configuration flags. Neither defaults to on.

4. **Redaction before export.** A redaction validator runs on every export
   path and rejects any row containing a locally-retained field.

5. **No secrets.** `observability.jsonl` and derived datasets MUST NOT
   contain API keys, tokens, environment variable values, or file contents.

6. **No raw private code in public evals.** Even hashed, file paths may
   reveal proprietary structure. The redaction validator SHALL replace
   repository-relative paths with a salted path hash before export.

## Data Layout on Disk

```
~/.rig/relay/sessions/<session_id>/
├── observability.jsonl      # Canonical event stream (evidence-retained fields)
├── receipts.jsonl           # Merkle-linked evidence receipts
├── manifest.json            # Session index (schema versions, file listing, hashes)
├── artifacts/
│   ├── tool-results/        # Tool output payloads (locally retained)
│   ├── context/             # Context assembly artifacts (locally retained)
│   └── task-links/          # Task session link artifacts (evidence-retained)
└── derived/                 # Optional: flattened eval datasets (exportable)
```

## Schema Governance

All usage data schemas live under `docs/schemas/` with the naming convention:

```
rig.relay.<domain>.<version>.schema.json
```

Current evaluation schemas:

| Schema | Purpose |
|--------|---------|
| `rig.relay.workflow_event.v1.schema.json` | Canonical event stream row |
| `rig.relay.mission_outcome.v1.schema.json` | Flattened mission eval row |
| `rig.relay.tool_call_eval.v1.schema.json` | Tool-call-level eval row |
| `rig.relay.cross_session_coordination.v1.schema.json` | Normalized coordination event row for delegate/fleet analysis |
| `rig.relay.coordination_conflict.v1.schema.json` | Normalized conflict/refusal event row |
| `rig.relay.artifact_reuse.v1.schema.json` | Normalized artifact publication/reuse event row |
| `rig.relay.checkpoint_eval.v1.schema.json` | Normalized checkpoint commit/refusal event row |
| `rig.relay.telemetry_consent.v1.schema.json` | Explicit opt-in consent record with share_level |
| `rig.relay.telemetry_bundle_manifest.v1.schema.json` | Content-light bundle manifest with content hash |
| `rig.relay.google_drive_upload_receipt.v1.schema.json` | Upload receipt for beta artifact lake |
| `rig.relay.contribution_receipt.v1.schema.json` | Content-light contribution receipt with hashed Drive IDs |
| `rig.relay.contribution_result.v1.schema.json` | Orchestration result for contribution flow |
| `rig.relay.telemetry_settings.v1.schema.json` | Telemetry mode and feature gate settings |

Existing observability schemas (not modified by this doctrine):

| Schema | Purpose |
|--------|---------|
| `rig.relay.observability.v1` | Event envelope (defined in `local.py`) |
| `rig.relay.artifact.envelope.v1` | Artifact envelope |
| `rig.relay.artifact.tool_reasoning_trace.v1` | Tool reasoning trace |
| `rig.relay.evidence.receipt.v1` | Merkle receipt |
| `rig.relay.result.v1` | Session result |

## Dataset Reports

Rig Relay has a local report generator (`scripts/rig_relay_dataset_report.py`) that
reads event streams and findings registries and emits a human-readable Markdown
summary to `.build/rig-relay/reports/dataset-summary.md`.

Dataset reports are **local, content-light Markdown summaries** generated from
event streams and findings. They are for human inspection and do not export raw
private data.

**Report sections:**
- Executive Summary (session counts, event counts, mutations, checkpoints, findings)
- Event Volume (table by event_name)
- Tool Behavior (table by tool_name, status)
- Guard and Safety (dirty-file snapshots, write refusals)
- Coordination (claims, reservations, refusals, conflicts, heartbeats)
- Checkpoints (committed/refused counts, refusal reasons)
- Provider / Model Use (model distribution from request accounting events)
- Findings (out-of-scope findings grouped by severity)
- Warnings / Missing Inputs (when data sources are unavailable)
- Recommended Next Slices (derived from findings and checkpoint refusals)
- Data Sources Used (paths and status of each input source)

**Privacy safeguards:**
- Never includes raw prompt text, model output, file contents, stdout/stderr bodies
- Never includes raw private code paths beyond what the local doctrine permits
- Uses event names, counts, statuses, hashes, finding IDs/titles/severity only
- SHA256 hashes for all content-derived references

**Usage:**

```bash
uv run python scripts/rig_relay_dataset_report.py
uv run python scripts/rig_relay_dataset_report.py --output path/to/report.md
uv run python scripts/rig_relay_dataset_report.py --export-csv path/to/counts.csv
```

### Dataset Exports

Rig Relay also has a local dataset exporter (`scripts/rig_relay_dataset_export.py`)
that transforms event streams and findings into clean derived JSONL/CSV files
for machine consumption.

Dataset export is **local, content-light, schema-validated** where schemas exist,
and intended as the machine-readable input to reports, interactive inspectors,
and evaluation pipelines.

**Output datasets** (written to `.build/rig-relay/derived/`):

| Dataset | Source Events | Schema |
|---------|---------------|--------|
| `cross_session_coordination_dataset.jsonl` | All `coord.*` events | `rig.relay.cross_session_coordination.v1` |
| `coordination_conflict_dataset.jsonl` | `coord.conflict.reported`, `coord.path.reservation_refused` | `rig.relay.coordination_conflict.v1` |
| `artifact_reuse_dataset.jsonl` | `coord.artifact.published` | `rig.relay.artifact_reuse.v1` |
| `checkpoint_eval_dataset.jsonl` | `rig.relay.checkpoint.committed`, `rig.relay.checkpoint.refused` | `rig.relay.checkpoint_eval.v1` |
| `tool_failure_patterns_dataset.jsonl` | `rig.relay.tool.call_completed` with non-success status | — |
| `provider_task_performance_dataset.jsonl` | `rig.relay.context.request_accounted` | — |
| `findings_dataset.jsonl` | `docs/findings/out-of-scope-findings.jsonl` | — |
| `export_manifest.json` | Generated manifest with row counts, validation results, warnings | — |

**Private safeguards:**
- Never includes raw prompt text, model output, file contents, stdout/stderr bodies
- Uses event names, counts, statuses, hashes, finding IDs/titles/severity only
- SHA256 hashes for all content-derived references
- Transformers strip raw payload fields not mapped to the schema
- `content_light_guarantee: true` recorded in every manifest

**Schema validation:**
- The four coordination/checkpoint datasets are validated against their schemas
  when `jsonschema` is available (stdlib dependency)
- Validation results are recorded in the manifest (valid/total/errors per dataset)
- Non-blocking by default; `--strict` mode fails on missing inputs

**Usage:**

```bash
uv run python scripts/rig_relay_dataset_export.py
uv run python scripts/rig_relay_dataset_export.py --output-dir .build/rig-relay/derived
uv run python scripts/rig_relay_dataset_export.py --format csv
uv run python scripts/rig_relay_dataset_export.py --strict
```

**Requirements:**
- `jsonschema` is optional (used for schema validation when available).
- DuckDB is optional (used when available via the `obs` extra). Falls back to
  stdlib JSONL parsing.
- No large dashboard or web dependencies.

### Interactive Inspector

Rig Relay provides an interactive marimo notebook inspector
(`notebooks/rig_relay_dataset_inspector.py`) that loads derived datasets and
renders filterable tables, charts, and completeness overviews.

The inspector is **reactive** — changing a filter dropdown re-renders the
relevant tables without recomputing the full load.

**Architecture:**
- `scripts/rig_relay_dataset_inspector_lib.py` — reusable data-loading/summary
  logic (loads derived JSONL files, computes aggregates, filter/aggregation
  helpers). Testable and importable without marimo.
- `notebooks/rig_relay_dataset_inspector.py` — marimo notebook UI wrapping the
  lib. One cell per view section.

**Views (13 cells):**
| View | What it shows |
|------|---------------|
| `init_state()` | Loads all datasets, computes summary |
| `overview()` | 8 stat cards: sessions, coordination, conflicts, artifacts, checkpoints, tool failures, provider perf, findings |
| `export_info()` | Export timestamp, manifest warnings, missing files, empty datasets, schema validation |
| `filters()` | Dropdowns: session_id, event_name, tool_name, model, severity, kind, checkpoint status, artifact kind |
| `coordination_view()` | Event name counts, session breakdown, status distribution |
| `conflicts_view()` | Conflict table or neutral message when empty |
| `artifact_view()` | Artifact kind counts, completeness gap analysis |
| `tool_failure_view()` | Tool × status counts, warnings table |
| `provider_view()` | Model counts, token stats (min/max/avg) |
| `checkpoint_view()` | Committed/refused counts, refusal codes, files committed stats |
| `findings_view()` | By severity, kind, repo area, suggested slices |
| `completeness_view()` | File present/missing status, schema validation results |
| `about()` | Metadata footer |

**Chart helpers** (6, content-light list-of-dicts for Altair/marimo tables):
- `event_counts_for_chart` — coordination event rows → `{event_name, count}`
- `tool_status_counts_for_chart` — tool failures → `{tool_name, status, count}`
- `model_counts_for_chart` — provider perf → `{model, requests}`
- `findings_severity_counts_for_chart` — findings → `{severity, count}`
- `artifact_kind_counts_for_chart` — artifact reuse → `{artifact_kind, count}`
- `checkpoint_status_counts_for_chart` — checkpoints → `{status, count}`

**Altair charts** (6 cells, one per chart helper, graceful degradation on empty data):
- Coordination events bar chart (`mo.ui.altair_chart`)
- Tool failures bar chart (color-coded by status)
- Model request counts bar chart
- Findings severity bar chart
- Artifact kind bar chart
- Checkpoint outcomes bar chart

**DuckDB helper** (optional, degrades gracefully):
- `HAS_DUCKDB` module-level flag
- `_find_derived_jsonl_files()` — maps view names to existing JSONL paths
- `create_derived_connection()` — in-memory DuckDB connection with `read_json_auto` views
- `CANNED_QUERIES` dict with 6 canned SQL queries
- `run_canned_query()` — executes a named query and returns list-of-dicts

**SQL Workbench** (marimo cell, shown only when DuckDB is available):
- Lists available views
- Dropdown selector for 6 canned queries
- Results displayed as tables
- "Run exporter first" warning when no derived datasets found

**Filter helpers** (5, reusable outside notebook):
- `filter_by_session_id`, `filter_by_task_id`, `filter_by_event_name`,
  `filter_by_tool_name`, `filter_by_model`

**Aggregation helpers** (3):
- `count_by_field` — grouped counts, sorted descending
- `count_by_field_pair` — two-field cross counts
- `unique_values` — sorted unique field values

**Privacy safeguards:**
- Content-light: loads only derived datasets (never reads raw events or
  observability files)
- All forbidden raw-content fields filtered by the export pipeline before
  the inspector sees data
- Inspector tests verify no raw fields surface in loaded datasets

**Dependencies** (optional `inspector` extra):
- `marimo>=0.10.0` — reactive notebook runtime
- `duckdb>=1.5.0` — embedded query engine (shared with `obs` extra)
- `altair>=5.5.0` — declarative charts (Vega-Lite)
- `pandas>=2.0.0` — data manipulation for altair and summary tables

**Usage:**

```bash
uv sync --extra inspector
uv run marimo run notebooks/rig_relay_dataset_inspector.py
```

**Run tests:**
```bash
uv run pytest tests/scripts/test_rig_relay_dataset_inspector_lib.py -v
```


### Coordination Dataset Exporter (Current)

The current coordination dataset exporter (`scripts/rig_relay_export_coordination_datasets.py`) is a
standalone script that reads coordination `events.jsonl` (and optional `observability.jsonl`) and writes
the four coordination/checkpoint datasets:

```bash
uv run python scripts/rig_relay_export_coordination_datasets.py \
    --events .build/rig-relay/coordination/events.jsonl \
    --output-dir .build/rig-relay/derived

uv run python scripts/rig_relay_export_coordination_datasets.py \
    --events .build/rig-relay/coordination/events.jsonl \
    --observability .build/rig-relay/sessions/s-1/observability.jsonl \
    --output-dir .build/rig-relay/derived \
    --schemas-dir docs/schemas \
    --strict
```

**Flags:**
- `--events`: Path to coordination `events.jsonl` (required)
- `--observability`: Path to session `observability.jsonl` (optional, needed for checkpoint events)
- `--output-dir`: Output directory (default: `.build/rig-relay/derived`)
- `--schemas-dir`: Schema directory (default: `docs/schemas`)
- `--strict`: Fail on missing input files (default: warn and continue)

**Event-to-dataset mapping:**
| Dataset | Source Events |
|---------|---------------|
| `cross_session_coordination_dataset.jsonl` | All `coord.*` events |
| `coordination_conflict_dataset.jsonl` | `coord.conflict.reported`, `coord.path.reservation_refused` |
| `artifact_reuse_dataset.jsonl` | `coord.artifact.published` |
| `checkpoint_eval_dataset.jsonl` | `rig.relay.checkpoint.committed`, `rig.relay.checkpoint.refused` (from observability) |

The exporter uses the normalized payload builders from `vibe/core/coordination/_models.py` to
construct safe-field-only rows and applies three-layer content-light enforcement:
event payload scan, safe-field-only row construction, and row-level forbidden-field check.

## Review Packet Protocol

Rig Relay provides a local review packet protocol for human/model review of completed missions.
The protocol is ChatGPT-Mac-app-independent — reviewer responses are not executed directly,
they inform the next mission prompt.

### Purpose

Review packets bridge the gap between:
- A completed mission (with its final report, artifacts, datasets, and coordination state)
- The next mission prompt (refined by a human or model reviewer)

This enables:
- **Iterative development**: Each mission produces a review packet; the reviewer's response
  becomes the seed for the next mission prompt.
- **Human oversight**: A human can review changes, datasets, risks, or architecture decisions
  before authorizing continuation.
- **Model review loops**: A second model (e.g., a stronger model or a risk-review specialist)
  can review a mission's output and recommend improvements.
- **Dataset quality review**: Exported datasets can be reviewed for schema compliance and
  content-light guarantees before they enter an eval pipeline.

### Packet Layout

The `create_review_packet` function (`scripts/rig_relay_create_review_packet.py`) produces
five files in the output directory:

| File | Purpose |
|------|---------|
| `review_packet.json` | Schema-validated packet metadata (20 fields, 7 required) |
| `final_report.md` | Copy of the mission's final report |
| `README.md` | Manual review instructions with review-kind-specific guidance |
| `reviewer_response.md` | Empty placeholder — reviewer writes their response here |
| `resume_prompt.md` | Empty placeholder — reviewer moves/soft-links their response here |

### Review Kinds

| Kind | Description |
|------|-------------|
| `next_slice` | Review the completed mission and recommend the next implementation slice |
| `risk_review` | Review the mission for safety, privacy, or architectural risks |
| `prompt_generation` | Review the mission and generate a refined prompt for continuation |
| `commit_review` | Review changes before a governed checkpoint commit |
| `dataset_review` | Review exported dataset quality and schema compliance |
| `architecture_review` | Review architectural decisions and design trade-offs |

### Packet Schema

The packet validates against `docs/schemas/rig.relay.review_packet.v1.schema.json` (draft-07).
Key fields:

- **schema_version**: `const: rig.relay.review_packet.v1`
- **review_id**: Auto-generated (`review_<YYYYMMDD_HHMMSS>`)
- **session_id**: The mission session being reviewed
- **parent_session_id**: Optional parent session for review chains
- **task_id**: Optional task within the session
- **status**: `needs_review` / `in_review` / `reviewed` / `cancelled`
- **requested_review_kind**: One of the six kinds above
- **final_report_path**: Resolved path to the copied final report
- **artifact_manifest_path**, **coordination_summary_path**, **dataset_report_path**, **checkpoint_summary_path**: Optional resolved paths to copied manifests
- **content_policy**: `"content_light"` (default)
- **forbidden_fields**: Default list of field names that must not appear in payloads

**Required fields**: schema_version, review_id, session_id, status, requested_review_kind,
final_report_path, created_at

### Content-Light Safeguards

- **Review packet JSON does not embed raw file contents.** Referenced files are COPIED
  to the output directory but their content never appears inside `review_packet.json`.
- **Default forbidden fields**: `raw_file_contents`, `secrets`, `raw_private_code`,
  `raw_prompt_text`, `model_output_text`, `stdout_bodies`, `stderr_bodies`
- **Schema validation**: Uses `jsonschema` if available, falls back to required-field checks.
  Validation errors are recorded as warnings in the packet.

### Usage

```bash
# Basic: create a review packet for next-slice review
uv run python scripts/rig_relay_create_review_packet.py \
    --session-id session_20250101_000000 \
    --task-id call_00_example \
    --final-report .build/rig-relay/reviews/latest/final_report.md \
    --review-kind next_slice \
    --output-dir .build/rig-relay/reviews/review_20250101

# With optional manifests
uv run python scripts/rig_relay_create_review_packet.py \
    --session-id s-1 --task-id t-1 \
    --final-report docs/output.md \
    --artifact-manifest .build/rig-relay/artifacts/manifest.json \
    --dataset-report .build/rig-relay/derived/export_manifest.json \
    --review-kind risk_review

# With git state
uv run python scripts/rig_relay_create_review_packet.py \
    --session-id s-1 --final-report docs/output.md \
    --review-kind commit_review \
    --branch main --head 40a2d04
```

### Reviewer Response Flow

1. **Create**: Run the script to produce the 5-file packet in the output directory.
2. **Review**: The human or model reads `final_report.md` and any optional manifests.
3. **Respond**: The reviewer writes their structured response in `reviewer_response.md`
   (summary, findings, next-slice recommendation, optional rejection).
4. **Resume**: The response is moved or soft-linked to `resume_prompt.md`.
5. **Validate**: Rig Relay validates the response before any agent executes a new mission
   based on it — responses are never executed directly.

### Reviewer Response Format

```markdown
## Summary

One-paragraph assessment of the mission.

## Findings

- What worked well
- What to improve
- Risks identified

## Next slice recommendation

A compact prompt for the next mission. Be specific about files, goals, and
non-goals. Do not include raw private code or unredacted transcripts.

## Rejected? (optional)

If the work should not continue, state why and close the review.
```

### Safety Constraints

- **Reviewer responses are not executed directly.** They inform the next mission prompt.
  Rig Relay validates the response before any agent executes a new mission.
- **No ChatGPT Mac app automation.** The protocol works with any text editor or model
  that can write a Markdown file.
- **No raw content in packet JSON.** All referenced content stays in separate files.
- **Non-execution guarantee.** Even if `resume_prompt.md` contains code, it is not executed
  by the review packet tool — it's consumed by the next mission's agent prompt assembly.

## Autoimprovement

This doctrine SHALL be reviewed when:
- A new event name is added to `EventName`.
- A new artifact kind is defined in `artifacts.py`.
- A tool begins tracking a new metric (files_read, tests_run, etc.).
- A user requests export or sharing of usage data.
- A PR adds or changes a telemetry field.

## Semantic Change Snippets

Semantic change snippets are content-light, anonymized representations of code
changes that preserve change intent and structure without exporting raw source
code, identifiers, literals, comments, secrets, file paths, or diffs.

### Design

```
actual diff → syntax-aware anonymized snippet → content-light dataset row → evals/reports
```

### Anonymization Pipeline

1. **Secret scan**: Reject snippet if it contains token-like material (API keys,
   private keys, raw diffs, prompt markers, file content markers, stdout/stderr
   blocks).
2. **Identifier anonymization**: Replace function names (FN_001), class names
   (CLASS_001), variable names (VAR_001), and attribute names (ATTR_001) with
   stable local placeholders.
3. **Literal stripping**: Replace string literals with `<STR>`, numeric literals
   with `<NUM>`, booleans with `<BOOL>`, None with `<NONE>`.
4. **Comment removal**: Strip Python comments and docstrings.
5. **Path hashing**: Use content-light SHA256 path hashes, not raw paths.
6. **Length cap**: Maximum 20 snippet lines.
7. **Content-light assertion**: Final row scan for forbidden raw fields.

### Fields

| Field | Description |
|---|---|
| snippet_id | Unique snippet identifier |
| language | Programming language (python, json, markdown, etc.) |
| change_kind | High-level classification (guard_added, test_added, schema_added, etc.) |
| operation | Structural operation (insert, replace, delete, split, etc.) |
| symbol_kind | What was changed (function, class, test, schema, etc.) |
| snippet_lines | Anonymized snippet lines with placeholders |
| semantic_labels | Tags for downstream evals |
| privacy_class | Always content_light |
| redaction_level | identifier_anonymized, literal_stripped, or structure_only |
| forbidden_content_detected | True if source was excluded |

### Privacy Guarantee

Semantic change snippets are **not source-code exports**. They are syntax-aware
summaries of code changes that preserve operation shape and safety/evaluation
labels while removing identifiers, literals, comments, raw paths, secrets, and
file contents. Raw code stays private; the dataset still learns what agents are
doing.

### Current Implementation

- **Python**: stdlib `ast` for structure analysis + line-level replacement.
- **Other languages**: basic anonymization (JSON, Markdown, shell fallback).
- **Tree-sitter**: Deferred for multi-language support in a future version.

### Script

`scripts/rig_relay_export_semantic_change_snippets.py` reads write_file,
search_replace, and checkpoint artifacts plus coordination events, then writes
anonymized snippets to `.build/rig-relay/derived/semantic_change_snippets.jsonl`.

### Schema

`docs/schemas/rig.relay.semantic_change_snippet.v1.schema.json`

## External Tester Telemetry Sharing

Rig Relay supports an optional remote beta sharing system for external testers.
This is strictly separate from the local operational usage data described above.

### Three Telemetry Layers

| Layer | Required? | Purpose |
|-------|-----------|---------|
| Local operational (observability.jsonl) | Required for governed mode | Tool calls, events, session lifecycle — never leaves the machine |
| Local derived datasets | Required for orchestration | Flattened eval rows from coord.* events — never leaves the machine |
| Remote beta sharing | Optional, opt-in | Content-light bundles uploaded to Google Drive artifact lake |

### What Is Never Uploaded

- Raw source code, file contents, or private keys
- Raw prompts or model outputs
- stdout/stderr bodies or diffs
- Secrets, tokens, API keys
- Participant identity beyond an anonymous ID

### What Remote Sharing Includes (content-light only)

- Schema-validated derived datasets (cross-session coordination, conflicts, tool failures, etc.)
- Row counts, statuses, durations
- SHA256 hashes (no reversible raw content)
- An anonymous participant ID (self-assigned)
- A consent record with share level

### Feature Gating

When remote beta sharing is disabled:
- `remote_upload`, `maintainer_debugging`, `shared_benchmarks`, `cross_user_reports` are all disabled
- Advanced orchestration features remain available (governed mode, delegate/fleet)

When local operational telemetry is disabled:
- Governed mode is disabled entirely
- All advanced features (delegate/fleet, checkpoint, coordination, etc.) are disabled

### Telemetry Budget

Telemetry collection is capped to prevent unbounded storage growth and protect privacy.

#### Schema: `rig.relay.telemetry_budget.v1`

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | `"rig.relay.telemetry_budget.v1"` |
| `max_bundle_mb` | integer (1–1000) | Maximum export bundle size in MB. Default: 100. |
| `max_rows_per_dataset` | integer (1–10,000,000) | Maximum rows per derived dataset. Default: 100,000. |
| `max_semantic_snippets_per_session` | integer (0–10,000) | Maximum semantic change snippets per session. Default: 200. 0 disables snippet collection. |
| `raw_retention_days` | integer (1–365) | Days to retain raw event files locally. Default: 14. |
| `derived_retention_days` | integer (1–730) | Days to retain derived dataset files locally. Default: 180. |
| `upload_mode` | string | `"local_only"`, `"rollup_only"`, `"rollup_plus_samples"`, or `"full"`. Default: `"rollup_only"`. |

Upload modes:

| Mode | Behavior |
|------|----------|
| `local_only` | No remote upload. All data stays local. |
| `rollup_only` | Upload aggregate counts only. No content payloads. |
| `rollup_plus_samples` | Upload rollup + representative samples (max 10 per dataset). |
| `full` | Upload all bounded datasets (within budget caps). |

Content-light guarantee applies to all modes: raw file contents, prompts, model outputs, and diffs are never exported. Only anonymized semantic snippets (see [Semantic Change Snippets](#semantic-change-snippets)) may be included.

#### Default Budget

```json
{
    "schema_version": "rig.relay.telemetry_budget.v1",
    "max_bundle_mb": 100,
    "max_rows_per_dataset": 100000,
    "max_semantic_snippets_per_session": 200,
    "raw_retention_days": 14,
    "derived_retention_days": 180,
    "upload_mode": "rollup_only"
}
```

#### Enforcing the Budget

- Bundle creation rejects payloads exceeding `max_bundle_mb`.
- Dataset export truncates at `max_rows_per_dataset` (oldest rows dropped first).
- Snippet generation stops per-session at `max_semantic_snippets_per_session`.
- Retention pruning runs on session close and at daily intervals.
- The `upload_mode` is enforced at bundle-creation time; no raw event files are ever included in bundles.


#### Step-Up Authorization

High-authority actions (real upload, telemetry share level change, checkpoint commit, lease cleanup, credential changes) require step-up authorization. See [`docs/governance/step-up-authorization.md`](step-up-authorization.md).

Uploads require a valid authorization receipt before execution. See the authorization policy at `scripts/rig_relay_authorization_policy.py` and `docs/schemas/rig.relay.step_up_authorization_receipt.v1.schema.json`.


#### Google Drive Core Dependency

Google Drive upload libraries (`google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`) are **core beta dependencies** of Rig Relay.

This does not mean uploads are automatic:
- Upload is always gated by remote sharing settings (consent mode).
- Bundle validation must pass before upload.
- Credentials must be configured (`~/.rig/relay/drive_credentials.json`).
- A folder ID must be provided.
- `--confirm` is required for real upload.
- Dry-run mode is the default and performs no network calls.

The Google Drive upload path uses OAuth 2.0 (desktop app flow) with resumable upload. Credentials are never stored in the repository. Tokens are cached in `~/.rig/relay/drive_token.json`.

Google's OAuth 2.0 desktop authentication obtains credentials from the Google Cloud Console, requests access tokens, then sends those tokens to the Drive API. This design keeps credentials out of the repo and provides user-visible consent on first authentication.

See:
- `scripts/rig_relay_upload_google_drive.py` — upload client with dry-run and resumable modes.
- `docs/schemas/rig.relay.google_drive_upload_receipt.v1.schema.json` — structured receipt.

#### Stale Lease Cleanup

Coordination leases (path reservations and task claims) accumulate under `.build/rig-relay/coordination/leases/paths/` and `tasks/`. Stale leases can cause conservative/noisy decisions in the reviewer orchestrator.

Cleanup is governed through a dedicated script:

```
uv run python scripts/rig_relay_cleanup_coordination_leases.py --dry-run
uv run python scripts/rig_relay_cleanup_coordination_leases.py --archive --confirm
```

- Dry-run is the default.
- Active leases are never touched.
- Archive mode moves stale/expired files to `.build/rig-relay/coordination/archived/`.
- Deletion requires explicit `--confirm` and `--remove`.

### Storage Lifecycle

The `.build/rig-relay/` artifact tree has three storage tiers with explicit retention defaults.
Storage lifecycle must exist **before** delegate/fleet execution.

See [Storage Retention Policy](storage-retention-policy.md) for the full doctrine.

#### Tiers

| Tier | Contents | Retention |
|------|----------|-----------|
| **Hot** | Raw observability, coordination artifacts, leases, desktop snapshots, telemetry bundles | Hours-to-days |
| **Warm** | Derived JSONL datasets, reports, ChatGPT bundles, cockpit snapshots | Weeks-to-months |
| **Cold** | Parquet rollups, manifests | Months-to-permanent |

#### Budget Schema: `rig.relay.storage_budget.v1`

| Field | Default | Purpose |
|-------|---------|---------|
| `warn_local_mb` | 1024 | Warning threshold |
| `max_local_mb` | 2048 | Hard cap — blocks compaction |
| `refuse_fleet_over_mb` | 4096 | Blocks fleet/delegate execution |
| `raw_observability_days` | 3 | Retention for raw observability JSONL |
| `raw_tool_artifacts_days` | 3 | Retention for coordination artifacts |
| `coordination_events_days` | 14 | Retention for events.jsonl |
| `stale_leases_hours` | 24 | Age threshold for stale leases |
| `derived_jsonl_days` | 30 | Retention for derived JSONL (after Parquet exists) |
| `parquet_rollups_days` | 365 | Retention for Parquet files |

#### Protected Classes (Never Deleted)

- Rollup manifests, export manifests
- Upload receipts, checkpoint receipts
- Parent convergence reports
- Active coordination leases

#### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/rig_relay_storage_audit.py` | Read-only storage inspection + budget status |
| `scripts/rig_relay_compact_artifacts.py` | DuckDB JSONL→Parquet compaction (dry-run default) |
| `scripts/rig_relay_gc_artifacts.py` | Retention-based GC (dry-run default, protected classes preserved) |

#### Compaction Pipeline

```
derived/*.dataset.jsonl ──→ DuckDB SELECT/filter/count ──→ derived/*.parquet
                               └─→ derived/rollup_manifest.json
```

- Never destructive. Raw logs stay until GC.
- Dry-run is the default. `--confirm` required for writes.
- Never compacts raw logs (prefixes: `raw_`, `observability`, `events`, `tool_artifacts`).

#### GC Enforcement

- Fleet/delegate must check `storage_audit.total_size_mb < refuse_fleet_over_mb`
- Audit returns budget status: `ok`, `warn`, `over_budget`, `fleet_blocked`
- Allowed GC candidates: stale leases, old projection snapshots, old telemetry zips (keep manifest), old raw observability, old derived JSONL (after Parquet exists), temp files


### Consent and Privacy

- Explicit opt-in with written consent record (`rig.relay.telemetry_consent.v1`)
- **Commercial dataset licensing is separate from privacy consent.** The `commercial_dataset_license` and `aggregate_public_reporting` scopes are never default — must be explicitly granted.
- Bundle manifest with content-light guarantee (`rig.relay.telemetry_bundle_manifest.v1`)
- Redaction validator scans all bundle content before creation
- Google Drive upload is resumable, with local receipt (`rig.relay.google_drive_upload_receipt.v1`)
- Settings schema (`rig.relay.telemetry_settings.v1`) controls feature gating

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/rig_relay_create_telemetry_bundle.py` | Creates content-light zip bundles from derived datasets + reports |
| `scripts/rig_relay_validate_telemetry_bundle.py` | Validates bundle content-light guarantee and schema conformance |
| `scripts/rig_relay_upload_google_drive.py` | Dry-run or resumable upload to Google Drive artifact lake |
| `vibe/core/config/telemetry_modes.py` | Feature gate helpers: `can_use_*()` and `disabled_features_for_settings()` |

### Onboarding

See [Beta Telemetry Onboarding](beta-telemetry-onboarding.md) for the plain-language
guide given to external testers.

## References

- [Delegate/Fleet Orchestration Doctrine](delegate-fleet-orchestration.md) : Pending work queue, ready work planner, parent convergence report

- OpenTelemetry: traces, metrics, and logs for understanding system behavior.
- LangSmith: tracing agent decisions, tool calls, retrieved context, costs, latency, failures.
- OpenAI evals: define tasks, run against inputs, analyze results, iterate.
- GitHub Copilot usage metrics: engagement, activity, generated code, PR lifecycle trends.
