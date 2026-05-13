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

## Implementation Backlog

1.  **Consistent Envelope Versioning**: Update the `ToolOutputArtifactWriter` to emit `rig.relay.artifact.envelope.v1` consistently.
2.  **Tool-Result Validation**: Implement runtime validation of tool-result artifacts against their respective schemas.
3.  **Search Telemetry**: Update search tools (`grep`, `bash` when used for search) to emit typed `search_query` and `search_result` artifacts.
4.  **File I/O Telemetry**: Implement `file_read` and `file_write` artifact emission for all built-in file tools.
5.  **Semantic Placement Reports**: Add artifacts for `search_replace` and other edit tools documenting why a specific placement was selected.
6.  **Token Usage Analysis**: Build tools to analyze token waste based on artifact types and content density.
7.  **Dataset Export Tooling**: Create a `rig-relay doctor export` command that merges typed artifacts into structured evaluation datasets.
