# Audit: Evidence Manifest and Receipt Chain Design
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: e389b446706173ebc5950931994ba4cdb6a7d9f4
Scope: Read-only design audit
Owner area: evidence

## Executive Summary
This document designs a verifiable evidence graph for Rig Relay. Currently, evidence files (observability logs, artifacts, context reports) exist in the filesystem but are not cryptographically linked. We propose a `manifest.json` that acts as the anchor for a session's integrity, enabling detection of corruption, deletion, or tampering.

## Proposed Docs Path
`docs/architecture/evidence-manifest-receipt-chain.md`

## Evidence Manifest Schema Sketch
```json
{
  "schema_version": "rig.relay.manifest.v1",
  "session_id": "uuid-or-hash",
  "root_mode": "repo_local",
  "created_at": "ISO-8601",
  "entries": [
    {
      "file_path": "observability.jsonl",
      "event_range": [0, 10],
      "sha256": "file-level-hash",
      "line_hashes": ["hash1", "hash2", "..."]
    },
    {
      "file_path": "context/assembly_abc123.json",
      "event_id": "event-uuid-1",
      "sha256": "hash"
    }
  ],
  "final_hash": "merkle-root-of-all-entries"
}
```

## Receipt Chain Options
1.  **Append-Only Journal**: The manifest is a `.jsonl` itself, where each new evidence file added to the session appends a "receipt" line. This is robust against mid-session crashes.
2.  **Session Finalizer**: A single `manifest.json` written when the session closes. Simpler but loses evidence if the agent is killed.
3.  **Merkle-Linked Observability**: Each event in `observability.jsonl` contains the hash of the previous event, creating a blockchain-like chain of custody.

## Recommended Minimal Implementation Slice (Slice 4)
- Implement a `ManifestManager` that tracks all files written during a session.
- Write a `manifest.jsonl` in the session directory.
- Add `manifest_sha256` to the `SESSION_CLOSED` event.

## Risks and Non-Goals
- **Non-Goal**: We are not implementing a global ledger or blockchain. The proof is local to the repository.
- **Risk**: Performance overhead of hashing large artifacts on every turn.
- **Risk**: Clock skew affecting `created_at` ordering if multiple processes write to the same root (mitigated by sequence numbers).

## Migration/Backward-Compatibility Plan
- Old sessions without manifests will be treated as "Unverifiable".
- `DuckDBProjection` will warn but still process sessions missing manifests.

## Tests Required Before Implementation
- `test_manifest_detects_deleted_artifact`
- `test_manifest_detects_corrupt_jsonl_line`
- `test_manifest_handles_mid_session_crash`
