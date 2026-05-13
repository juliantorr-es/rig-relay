# Artifact Schema Doctrine

Rig Relay uses typed, versioned artifacts to ensure that evidence collected during dogfood sessions is analyzable, validatable, and useful for future optimization. Generic JSON blobs are avoided in favor of strict schemas that define the structure and meaning of evidence data.

## Why Typed Artifacts Matter

1.  **Deterministic Hardening**: Schemas allow automated analysis of tool behavior across thousands of sessions.
2.  **Token Optimization**: By understanding the structure of artifacts, we can implement smart summarization and deduplication to reduce token usage without losing critical context.
3.  **Fuzzy-Search Analysis**: Typed search results enable evaluation of ranking strategies and query effectiveness.
4.  **Dataset Export**: Stable schemas facilitate exporting evidence to external evaluation and training pipelines.
5.  **Provenance**: Following the mental model of W3C PROV, every artifact establishes the provenance of a piece of evidence (who produced it, what tool was used, and what was the repo state).

## Schema Versioning

Schemas are versioned using a trailing `.vN` suffix (e.g., `rig.relay.artifact.envelope.v1`).
- **Breaking changes**: Increment the version number (v1 -> v2).
- **Non-breaking changes**: May be added to the same version, but explicit versioning is preferred for critical evidence structures.

## Naming Conventions

- **Schemas**: `rig.relay.artifact.<kind>.v<N>.schema.json`
- **Schema ID**: `https://rig-relay.vibe.dev/schemas/rig.relay.artifact.<kind>.v<N>.schema.json`
- **Schema Version Field**: Matches the schema name (e.g., `rig.relay.artifact.envelope.v1`).

## Core Architecture

### Artifact Envelope vs. Payload

Rig Relay artifacts consist of an **Envelope** and a **Payload**.
- **Envelope**: Contains metadata about the artifact (id, session, timestamp, hashes, schema version).
- **Payload**: Contains the tool-specific or activity-specific data.

### Canonical JSON

All artifacts must be serialized as **Canonical JSON** (lexicographical key order, no unnecessary whitespace) to ensure stable SHA256 hashes.

## Common Fields

Every artifact envelope MUST include:
- `schema_version`: The versioned identifier for the artifact schema.
- `artifact_kind`: A short name for the type of artifact (e.g., `search_result`).
- `session_id`: Unique identifier for the Rig session.
- `tool_call_id`: Unique identifier for the tool call that produced the artifact (if applicable).
- `created_at`: ISO 8601 UTC timestamp.
- `payload_sha256`: SHA256 hash of the payload section.
- `artifact_record_sha256`: SHA256 hash of the entire envelope (calculated after other fields are populated).

## Registered Schemas

| Schema File | Kind | Status |
|---|---|---|
| `rig.relay.artifact.envelope.v1.schema.json` | envelope | Active |
| `rig.relay.artifact.tool_call.v1.schema.json` | tool_call | Active |
| `rig.relay.artifact.tool_result.v1.schema.json` | tool_result | Active |
| `rig.relay.artifact.tool_reasoning_trace.v1.schema.json` | tool_reasoning_trace | **New** |
| `rig.relay.artifact.search_query.v1.schema.json` | search_query | Active |
| `rig.relay.artifact.search_result.v1.schema.json` | search_result | Active |
| `rig.relay.artifact.search_results.v1.schema.json` | search_result | Active |
| `rig.relay.artifact.file_read.v1.schema.json` | file_read | Draft |
| `rig.relay.artifact.file_write.v1.schema.json` | file_write | Active |
| `rig.relay.artifact.git_state.v1.schema.json` | git_state | Active |
| `rig.relay.artifact.task_session_link.v1.schema.json` | task_session_link | Active |
| `rig.relay.artifact.semantic_placement.v1.schema.json` | semantic_placement | Draft |
| `rig.relay.artifact.tool_determinism_summary.v1.schema.json` | tool_determinism_summary | Active |
| `rig.relay.evidence.manifest.v1.schema.json` | evidence_manifest | Active |
| `rig.relay.evidence.receipt.v1.schema.json` | evidence_receipt | Active |

## Tool Reasoning Traces

The `tool_reasoning_trace` artifact records observable metadata around tool use (latency, byte sizes, determinism class) without capturing hidden chain-of-thought. Rationale fields are left empty when the provider does not expose them. This is a non-envelope artifact — it is emitted as an observability event, not a standalone file in the artifacts directory.

## Implementation Backlog

1.  **Consistent Envelope Versioning**: Update the `ToolOutputArtifactWriter` to emit `rig.relay.artifact.envelope.v1` consistently.
2.  **Tool-Result Validation**: Implement runtime validation of tool-result artifacts against their respective schemas.
3.  **Search Telemetry**: Update search tools (`grep`, `bash` when used for search) to emit typed `search_query` and `search_result` artifacts with backend/count/order evidence.
4.  **File I/O Telemetry**: Implement `file_read` and `file_write` artifact emission for all built-in file tools.
5.  **Git State Telemetry**: `git_status` emits typed repo-state evidence with branch, HEAD, dirty counts, and upstream metadata where observable.
6.  **Semantic Placement Reports**: Add artifacts for `search_replace` and other edit tools documenting why a specific placement was selected.
7.  **Task Delegation Linkage**: Add rollup tooling for `task_session_link` artifacts so parent sessions can summarize child manifest provenance without storing hidden reasoning.
8.  **Token Usage Analysis**: Build tools to analyze token waste based on artifact types and content density. The reasoning trace event (`TOOL_REASONING_TRACE`) now provides per-call inline vs artifacted byte counts and latency for this analysis.
9.  **Dataset Export Tooling**: Create a `rig-relay doctor export` command that merges typed artifacts into structured evaluation datasets.
