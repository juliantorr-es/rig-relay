# Audit Trail Tamper-Evidence Design Audit

## Status

**Design audit (2026-05).** Produced after P3b (AuditTrailStore) implementation.
Design is documented in `docs/governance/audit-trail-tamper-evidence.md`.
Decision log: `docs/audits/rig-runtime-port/data/audit_tamper_evidence_decisions.jsonl`.

## Files Inspected

| File | Purpose |
|------|---------|
| `rig_relay/evidence/audit_trail.py` | Current AuditTrailStore implementation (297 lines) |
| `rig_relay/evidence/receipt_envelope.py` | ReceiptEnvelope models (294 lines) |
| `tests/evidence/test_audit_trail.py` | Existing audit trail tests (545 lines) |
| `tests/evidence/test_receipt_envelope.py` | Receipt envelope tests (651 lines) |
| `docs/governance/audit-trail.md` | Current audit trail governance doc (64 lines) |
| `docs/governance/receipt-envelope.md` | Receipt envelope governance doc (139 lines) |
| `docs/schemas/rig.relay.audit_event.v1.schema.json` | Current audit event JSON Schema |
| `docs/schemas/rig.relay.receipt_envelope.v1.schema.json` | Receipt envelope JSON Schema |

## Current Limitations (as of P3b)

1. **No cryptographic identity per event.** `AuditEvent` has `event_id` (UUID-style string) but no `event_hash` or `previous_event_hash`. An attacker can rewrite any line in `audit.jsonl` without detection.
2. **Sequence is derived from line count.** `next_sequence()` counts lines. An attacker can insert, delete, or reorder lines and the sequence counter adjusts to match.
3. **No checkpoint mechanism.** There is no periodic summary record that could serve as a tamper-evident root.
4. **No verification method.** `read_events()` returns events and parse errors but does not validate chain integrity.
5. **No signature or external anchor.** Even if events were hash-chained, a local attacker with write access to the trail file could rewrite both events and checkpoints.
6. **Malformed-line tolerance is correct but incomplete.** Malformed lines are reported as read errors — a correct and necessary behavior — but the store provides no mechanism to quarantine or repair them.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Tamper evidence layer | Event hash chain + checkpoint records | Minimal, local-first, no external dependencies |
| Merkle roots | Optional in v0.1 | Reduces implementation complexity; linear chain suffices for single-host detection |
| Checkpoint storage | Separate `audit.checkpoints.jsonl` file | Avoids schema mixing; simpler reader logic |
| Checkpoint frequency | Every 1000 events or explicit | Balances I/O overhead with detection granularity |
| Hash algorithm | SHA-256 | Fast, well-supported, already used elsewhere in codebase |
| Canonical serialization | Existing `dump_canonical_json` | Reuse existing deterministic JSON serializer |
| `event_hash` field | Stored in each AuditEvent | Enables per-event integrity check without recomputing from scratch |
| `previous_event_hash` | Null for genesis | Standard chain pattern; null is unambiguous |
| Backward compatibility | `event_hash`/`previous_event_hash` are optional null fields | Existing events without hashes are valid but unverifiable |
| Auto-repair on chain break | Never | Auto-repair destroys tamper evidence |
| Verification stops at break | Yes | First broken link blocks subsequent verification |
| CLI commands | Deferred to phases 0.3/0.6 | Store-level methods suffice for programmatic verification first |
| External anchoring | Deferred to phase 0.5 | Requires keychain module and signing infrastructure |
| Blockchain | Not adopted | Consensus/network/operational overhead is unjustified for local dogfood |
| NIST SP 800-92 alignment | Noted for future retention/compliance | Design addresses integrity checking; retention/disposal deferred |
| Certificate Transparency alignment | Merkle root + inclusion proof | Deferred to v0.2; CT-style auditability is aspirational |

## Cross-References

- [Audit Trail Tamper Evidence Design](../../governance/audit-trail-tamper-evidence.md)
- [Audit Trail Governance](../../governance/audit-trail.md)
- [Receipt Envelope Governance](../../governance/receipt-envelope.md)
- [Rig Runtime Port Roadmap](./port-roadmap.md)
- [Rig-to-Relay Runtime Audit](./rig-to-relay-runtime-audit.md)
