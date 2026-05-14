# Session Storage Lifecycle

## Status

**Draft.** Conservative lifecycle policy for `~/.rig/sessions`.

## Primary Surface

The primary product surface is an end-of-session agent tool:

- `rig.relay.session_lifecycle.finalize`

The finalize tool may optionally receive a `MissionEnvelope` and will
write a mission-linked lifecycle receipt when one is provided.

CLI scripts remain internal/admin/recovery utilities for now.

## Policy

- `~/.rig/sessions` is hot state, not a long-term archive.
- Dry-run is the default for audit, compaction, and GC tooling.
- Protected classes are never deleted by default.
- Active or pinned sessions are never deleted.
- Shareable outputs must remain content-light.

## Storage Classes

| Class | Treatment |
|---|---|
| Hot | Recent session state, active sessions, pinned sessions |
| Warm | Compaction candidates eligible for rollups |
| Cold | Archivable or pruneable candidates after retention |
| Delete | Only confirmed GC candidates after safety checks |

## Protected Classes

- receipts
- consent
- upload_receipts
- signed_envelopes
- active session markers
- pinned sessions

## Compaction Strategy

- JSONL event-like files may be rolled up to Parquet when DuckDB is available.
- When DuckDB is unavailable, gzip JSONL is the fallback.
- No raw prompts, model outputs, source diffs, stdout, or stderr bodies are
  allowed in shareable rollups.
- Current-session compaction may run automatically during finalization.

## GC Strategy

- GC is dry-run first.
- GC must print exact paths and sizes.
- GC must refuse to delete protected classes.
- GC must stop when the configured delete cap is reached.
- GC may archive candidates instead of deleting them.
- Confirmed deletion only happens when the operator passes the explicit confirm
  flag.
- Cross-session GC is separate maintenance, not part of normal finalization.

## Recovery

- Manual recovery requires the source session tree and the local GC receipt.
- Receipts, consent, and signed envelopes remain untouched.
- Nothing is uploaded.

## Manual Use

- Do not manually delete session trees unless you understand the retention
  policy and the local recovery path.
- Protected classes are never compacted or pruned.
- Lifecycle receipts are part of the evidence trail.
- Mission linkage is optional and must not require ADR or sprint metadata.

## Future CLI Surface

Future Relay CLI commands are expected to expose the same lifecycle actions:

- `rig relay sessions audit`
- `rig relay sessions compact`
- `rig relay sessions gc`

This is future work only. The current implementation is script-based.

## Tool Receipt Evidence Index

Receipt events (`rig.relay.tool_receipt.captured`) can be queried via the
receipt index builder in `rig_relay.evidence.receipt_index`. The index is:

- **Content-light**: no raw stdout, stderr, file contents, diffs, snippets, or secrets.
  Only metadata, SHA256 hashes, byte counts, and structured error classification.
- **Read-only derived evidence**: built from session observability events, never modified.
- **Audit/replay surface**: answers which tools ran, which calls mutated files,
  which were refused or timed out, and which produced before/after hashes.

Currently supported tools: `bash`, `search_replace`.

The CLI script `scripts/rig_relay_receipt_index.py` provides read-only inspection.

## Cross-References

- [Usage Data Doctrine](usage-data-doctrine.md)
- [Storage Retention Policy](storage-retention-policy.md)
- [Relay Local/Remote Boundary](relay-local-remote-boundary.md)
- [Telemetry Contribution Policy](telemetry-contribution-policy.md)
