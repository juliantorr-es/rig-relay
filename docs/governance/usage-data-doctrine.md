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

Existing observability schemas (not modified by this doctrine):

| Schema | Purpose |
|--------|---------|
| `rig.relay.observability.v1` | Event envelope (defined in `local.py`) |
| `rig.relay.artifact.envelope.v1` | Artifact envelope |
| `rig.relay.artifact.tool_reasoning_trace.v1` | Tool reasoning trace |
| `rig.relay.evidence.receipt.v1` | Merkle receipt |
| `rig.relay.result.v1` | Session result |

## Autoimprovement

This doctrine SHALL be reviewed when:
- A new event name is added to `EventName`.
- A new artifact kind is defined in `artifacts.py`.
- A tool begins tracking a new metric (files_read, tests_run, etc.).
- A user requests export or sharing of usage data.
- A PR adds or changes a telemetry field.

## References

- OpenTelemetry: traces, metrics, and logs for understanding system behavior.
- LangSmith: tracing agent decisions, tool calls, retrieved context, costs, latency, failures.
- OpenAI evals: define tasks, run against inputs, analyze results, iterate.
- GitHub Copilot usage metrics: engagement, activity, generated code, PR lifecycle trends.
