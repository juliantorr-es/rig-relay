# Storage Retention Policy

## Status

**Draft.** Retention policy for local Rig Relay storage.

## Scope

- `~/.rig/sessions`
- `~/.rig/relay`
- `.build/rig-relay`

## Rules

- Hot session storage may be compacted or garbage-collected conservatively.
- Receipts, consent records, signed envelopes, and upload receipts are protected.
- Active sessions are protected.
- Pinned sessions are protected.
- Shareable rollups must be content-light.
- `~/.rig/sessions` is hot operational state, not the canonical archive.
- Audit is read-only.
- End-of-session finalization may compact the current session only.
- Finalization receipts may optionally link a `MissionEnvelope` for the
  triggering mission, but mission-only mode remains valid.
- Compact and GC are dry-run first.
- Confirmed deletion requires explicit flags.
- Do not manually delete session trees unless the retention policy is
  understood.

## Retention Model

| Layer | Description |
|---|---|
| Hot | Active and recent session files |
| Warm | Compaction candidates and audit summaries |
| Cold | Archived session data outside the hot path |
| Delete | Confirmed GC candidates that pass safety checks |

## Required Safeguards

- Dry-run first
- Explicit confirmation for deletions
- Delete cap per run
- Archive fallback
- No raw content in derived outputs

## Cross-References

- [Session Storage Lifecycle](session-storage-lifecycle.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- [Relay Local/Remote Boundary](relay-local-remote-boundary.md)
