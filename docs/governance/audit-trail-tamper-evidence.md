# Audit Trail Tamper-Evidence Design

## Status

**Design (2026-05).** Not yet implemented. See
`docs/audits/rig-runtime-port/audit-trail-tamper-evidence-design.md` for the
implementation audit and decision log.

## Purpose

Add tamper evidence to the existing `AuditTrailStore` (P3b) so that unauthorized
modification of the audit trail — whether by a compromised process, a user with
filesystem access, or a supply-chain attacker — is detectable at verification
time.

This is **tamper-evident**, not tamper-proof. Without external anchoring
(signing, trusted timestamping, remote witness), a local attacker with write
access to both the trail and the checkpoint file can rewrite both. The design
makes that attack detectable as soon as any independently retained checkpoint
root is compared.

## Design Overview

Three layers, implemented incrementally:

| Layer | Mechanism | Detects |
|-------|-----------|---------|
| 1. Event hash chain | Each event stores `event_hash` and `previous_event_hash` | Line modification, deletion, insertion, reordering |
| 2. Checkpoint records | Periodic batch records store chain head hash + Merkle root | Missing/truncated sections, broken chain |
| 3. External anchoring (future) | Signing, TSA, remote witness | Local rewrite of both trail and checkpoints |

### Layer 1: Event Hash Chain

**Canonical event representation:**

Each `AuditEvent` gains two new optional fields:

```
event_hash: str | None          # sha256:<hex> of canonical event without event_hash/previous_event_hash
previous_event_hash: str | None # sha256:<hex> of the preceding event's event_hash, or null for genesis
```

**Computation:**

```
canonical = dump_canonical_json(event.model_dump(mode="json", exclude={"event_hash", "previous_event_hash"}, exclude_none=True))
event_hash = "sha256:" + sha256(canonical.encode("utf-8")).hexdigest()
```

Where `dump_canonical_json` is the existing `rig_relay.coordination._canonical_json.dump_canonical_json` — deterministic, sorted-keyed JSON without whitespace.

**Chain rules:**

1. The genesis event (sequence=1) has `previous_event_hash = None`.
2. Every subsequent event has `previous_event_hash` = the preceding event's `event_hash`.
3. `event_hash` is computed **before append** and stored in the event.
4. `previous_event_hash` is read from the store's `latest_event()` before computing the new event.
5. On read, the store verifies the chain: every event's `event_hash` must match recomputation, and `previous_event_hash` must match the prior event's `event_hash`.

**Sequence monotonicity:**

`next_sequence()` remains a count of lines. After hash chaining, sequence gaps are still detectable (the chain breaks at a missing sequence). Duplicate sequence numbers become detectable because they produce a fork (two events claim the same parent).

**Timestamp handling:**

Timestamps are informational. The hash chain provides ordering, not timestamps. A future event with a backdated timestamp is still detected as a break in the hash chain if it claims the wrong `previous_event_hash`.

**Malformed lines:**

- Malformed lines (non-JSON, non-validating) are still reported as read errors.
- The chain cannot verify past a malformed line. Verification stops at the last valid event before the malformed line.
- A future repair workflow could quarantine malformed lines and splice the chain.

**Redaction/deletion:**

- Deleting a line breaks the chain at that point.
- The store cannot "heal" the chain after deletion without re-signing all subsequent events (which invalidates tamper evidence).
- **Policy:** never auto-repair. Report the exact sequence where the break occurs.

**Compaction (future):**

- If old events are archived/removed, the chain is broken.
- Compaction must produce a new checkpoint that covers the surviving range, signed with the old checkpoint's root as `previous_checkpoint_hash`.

### Layer 2: Checkpoint Records

**AuditCheckpoint model:**

```python
class AuditCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.audit_checkpoint.v1"
    checkpoint_id: str
    trail_id: str                    # identifies which audit trail this checkpoint belongs to
    created_at: str                  # ISO 8601
    from_sequence: int               # first event sequence in this checkpoint window
    to_sequence: int                 # last event sequence in this checkpoint window
    event_count: int                 # number of events in this window
    chain_head_hash: str             # event_hash of the last event in this window
    merkle_root_sha256: str | None   # Merkle root over event hashes in this window (optional in v0.1)
    previous_checkpoint_hash: str | None  # sha256 of the previous checkpoint, or null for genesis
    checkpoint_sha256: str           # sha256 of this checkpoint's canonical JSON (excluding checkpoint_sha256)
    signer_id: str | None = None     # reserved for future signing
    signature: str | None = None     # reserved for future signing
```

**Storage decision:**

Checkpoint records are stored in a **separate file** — `audit.checkpoints.jsonl` alongside `audit.jsonl`. Reasons:

- Avoids mixing event types in the same JSONL, which would complicate schema validation and reader logic.
- Checkpoints have a different schema version and required fields.
- Separate file simplifies replay: events are one file, checkpoints are another.

**Checkpoint frequency:**

- **Default:** every 1000 events, or on explicit `checkpoint()` call.
- **On demand:** `store.create_checkpoint()` produces a checkpoint at the current chain head.
- **On read:** verification can use the latest checkpoint, or a specific checkpoint by `checkpoint_id`.

**Verification of checkpoints:**

1. Load all events up to `to_sequence`.
2. Recompute chain hashes from `from_sequence` to `to_sequence`.
3. Verify `chain_head_hash` matches.
4. If `merkle_root_sha256` is present, recompute the Merkle root and compare.
5. Load the previous checkpoint (if any) and verify `previous_checkpoint_hash` matches the previous checkpoint's `checkpoint_sha256`.
6. A checkpoint is **trusted** only if its own `checkpoint_sha256` matches recomputation.

### Layer 3: Merkle Checkpoint Option

**Design decision:** Merkle roots are optional in v0.1. The checkpoint stores a `merkle_root_sha256` field that is `None` until Merkle tree computation is implemented.

**Leaf hash:** `event_hash` of each event in the checkpoint window.

**Tree shape:** Binary Merkle tree over the sequence of leaf hashes. If the number of leaves is not a power of two, duplicate the last leaf (or use a balanced tree — design deferred to implementation).

**Inclusion proof (future):**

```python
class MerkleInclusionProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leaf_hash: str
    leaf_index: int
    proof_hashes: list[str]   # sibling hashes from leaf to root
    root_hash: str
```

**Consistency proof (future):** Deferred. Not needed until cross-checkpoint verification between two versions of the same trail is required.

**Recommendation:** Implement v0.1 with linear hash chain + checkpoint root only. Add Merkle inclusion proofs in v0.2 when external verification/sharing matters.

## Verification Workflow

### `rig-relay audit verify <trail>`

Reads the trail and checkpoints, then reports:

| Status | Meaning |
|--------|---------|
| `verified` | All events pass hash chain check, latest checkpoint matches |
| `broken_chain` | A hash mismatch was found at sequence N |
| `missing_checkpoint` | No checkpoint file exists for this trail |
| `malformed_event` | An event line is unparseable, chain stops there |
| `sequence_gap` | Sequence numbers are not strictly monotonic |
| `checkpoint_mismatch` | Checkpoint `chain_head_hash` does not match recomputed value |
| `unsupported_version` | Event or checkpoint schema version is unknown |

**Output:** JSON report with `verification_status`, `first_broken_sequence`, `event_count`, `checkpoint_count`, `error_count`, `warnings[]`.

### `rig-relay audit checkpoint <trail>`

Creates a new checkpoint at the current chain head. Does not modify existing events or checkpoints.

### `rig-relay audit inspect <event_id>`

Prints a single event with its chain neighbors (previous and next event_id, sequence, event_hash).

## Failure/Recovery Policy

1. **Never auto-repair.** The audit trail is append-only. Automatic repair would destroy tamper evidence.
2. **Report exact break location.** The verification report includes `first_broken_sequence` and the expected vs. actual hash values.
3. **Allow quarantining** (future): A manual repair workflow could export events up to the break point, then start a fresh chain from the last valid checkpoint.
4. **Never silently rewrite.** Any operation that modifies the trail or checkpoints must be explicit and user-approved.

**Chain verification stops** at the first broken link. Subsequent events are reported as "unverifiable" rather than "failed".

## Security Boundary

### What tamper evidence detects

- Any modification of an event's fields (the `event_hash` will not match recomputation).
- Deletion of a line (the chain breaks at the missing `previous_event_hash` reference).
- Insertion of a forged event (cannot produce a valid `previous_event_hash` without the private key, and the chain will break).
- Reordering of events (the `sequence` field changes, and the `previous_event_hash` will not match).
- Truncation of the trail (the chain breaks at the cut point).

### What tamper evidence does NOT detect

- Simultaneous rewrite of both `audit.jsonl` and `audit.checkpoints.jsonl` by an attacker with filesystem write access.
- Modification of events before the first checkpoint (all events prior to the genesis checkpoint have no checkpoint root to verify against).

### Trust model

| Attacker capability | Detectable? | Notes |
|---------------------|-------------|-------|
| Read-only access | N/A | No damage |
| Write to audit.jsonl only | Yes | Chain breaks, checkpoint detects |
| Write to audit.checkpoints.jsonl only | Yes | Event chain breaks, or checkpoint hash mismatch |
| Write to both files | No (v0.1) | Need external anchoring |
| Write to both + signing key | No | Need hardware-backed key |
| Write to both files + timestamp authority | No | Need RFC 3161 TSA |

### Future hardening (not in v0.1)

- **Signing:** Each checkpoint is signed with an Ed25519 key. The public key is retained separately.
- **Local keychain:** Key stored in OS keychain (macOS Keychain, Linux Secret Service, Windows Credential Manager).
- **Passkey anchoring:** Future passkey-based signing of checkpoints.
- **Remote witness:** Periodically upload checkpoint roots to a remote witness service (IPFS, GitHub releases, S3).

### Documented contract

The `audit-trail.md` governance document (and the docstring of `AuditTrailStore`)
must state clearly:

> This store provides append-only JSONL persistence with best-effort fsync
> durability. It does **not** provide cryptographic tamper evidence. Hash-chain
> tamper evidence is designed separately — see
> docs/governance/audit-trail-tamper-evidence.md.

## Required Schema Changes

### `AuditEvent` gains two optional fields

```
event_hash: str | None = None
previous_event_hash: str | None = None
```

Both are `["string", "null"]` in the JSON Schema. Existing events without these
fields are valid (backward compatibility). On read, events missing
`event_hash`/`previous_event_hash` are treated as **unhashed** — verification
skips them rather than failing.

### New schema: `rig.relay.audit_checkpoint.v1`

Schema file: `docs/schemas/rig.relay.audit_checkpoint.v1.schema.json`

Required fields:

```
checkpoint_id, trail_id, created_at, from_sequence, to_sequence,
event_count, chain_head_hash, checkpoint_sha256
```

Optional fields:

```
merkle_root_sha256, previous_checkpoint_hash, signer_id, signature
```

## Implementation Phases

| Phase | Scope | Dependencies |
|-------|-------|-------------|
| 0.1 | Event hash chain on append + verify on read | None (pure store change) |
| 0.2 | Checkpoint record model + `create_checkpoint()` | Phase 0.1 |
| 0.3 | `rig-relay audit verify` CLI command | Phase 0.2 |
| 0.4 | Merkle root computation in checkpoints | Phase 0.2 |
| 0.5 | External anchoring (signing, TSA) | Keychain module |
| 0.6 | `rig-relay audit checkpoint` CLI command | Phase 0.2 |

Phase 0.1 and 0.2 are the minimum viable tamper-evidence layer. They can be
implemented without CLI changes — the store methods suffice for programmatic
verification.

## Relationship to Receipt Envelope

`ReceiptEnvelope` (P3a) is separate from tamper evidence. The audit trail stores
`AuditEvent` records which may reference or embed `ReceiptEnvelope` instances.
The hash chain operates on the `AuditEvent` itself — not on the embedded
envelope. This means:

- If the `AuditEvent` fields are tampered with (e.g., `decision` changed from
  `allowed` to `blocked`), the chain detects it.
- If the embedded `ReceiptEnvelope` is tampered with inside a serialized
  `AuditEvent`, the chain detects it (because the canonical JSON of the
  `AuditEvent` changes).
- `ReceiptEnvelope` objects stored independently (not embedded in audit events)
  are not covered by the audit trail's hash chain. They need their own integrity
  mechanism (deferred to future work).
