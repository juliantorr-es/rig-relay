# Relay Local/Remote Authority Boundary

## Status

**Draft.** Derived from Intake's
[Hosted/Local Boundary](https://github.com/juliantorr-es/Intake/blob/main/docs/architecture/hosted-local-boundary.md)
and adapted for Rig Relay's telemetry and alpha-sharing model.

## Doctrine

Rig Relay follows a split-brain architecture for all remote communication:

- **Local Rig Relay Cockpit** is the authority. It holds raw artifacts,
  receipts, private code context, and protected action authority. It connects
  **outbound only** to any remote service.
- **Remote Telemetry Store** (future) is a boring, append-only, content-light
  store. It receives ciphertext, redacted metadata, hashes, counts, and opaque
  artifact references. It has **no mutation authority**.
- **External Agents** (future ACP/MCP) propose work. They do not own authority.

## Canonical Redaction Boundary

The shared redaction module in `rig_relay.evidence.redaction` is the canonical
implementation for content-light remote/shareable artifacts.

- Local cockpit retains raw receipts, prompts, outputs, and source context.
- Remote/shareable outputs are redacted or hashed before publication.
- Remote data cannot authorize mutations, even if it is structurally valid.
- Bundle builders, audit writers, and export helpers must route through the
  shared redaction boundary rather than copy their own sensitive-field rules.

## Core Boundaries

### No private keys in the remote store

The remote telemetry store never holds private decryption keys. The local
cockpit owns all decryption authority.

### Local-only decryption

Sensitive data (raw receipts, prompts, model outputs, source context) is only
decrypted within the local cockpit. The remote store sees only:
- Content-light projections (counts, statuses, hashes)
- Ciphertext of sensitive payloads (if encryption is enabled)
- Redacted metadata (timestamps, event names, operation IDs)

### Outbound-only sync

The local cockpit initiates all connections to the remote store. The remote
store never connects inbound to a local machine.

### No raw content in remote storage

| Data | Local | Remote |
|---|---|---|
| Raw receipts | ✅ Full | ❌ Never |
| Raw prompts/outputs | ✅ Full | ❌ Never |
| Raw stdout/stderr | ✅ Full | ❌ Never |
| Source code/diffs | ✅ Full | ❌ Never |
| Secrets/keys | ✅ Full | ❌ Never |
| Action IDs, timestamps | ✅ Full | ✅ Redacted |
| Event counts, statuses | ✅ Full | ✅ Aggregated |
| Hashes (SHA256) | ✅ Full | ✅ For deduplication |
| Ciphertext | ✅ Full | ✅ If encryption enabled |

### No authoritative receipts in remote audit

The remote store never holds receipts in a form that could be confused with
local authority. Remote event rows are content-light and non-authoritative.

### Signed local action envelopes

Any mutation sent from local cockpit to remote store must be wrapped in a
signed local action envelope (see
[Local Action Envelope Schema](../schemas/rig.relay.local_action_envelope.v1.schema.json))
containing:
- Canonicalized action payload
- Replay prevention fields (action_id, nonce, issued_at)
- Cryptographic signature (Ed25519)

The remote store verifies the signature against a registered public key before
executing any mutation.

## Contract Rules

1. Backend (local cockpit) is authority. Remote is render-only and
   append-only.
2. Remote store must not infer governance, checkpointability, or promotion
   readiness.
3. Missing remote connectivity degrades gracefully to local-only operation.
4. Alpha telemetry is opt-in only. Default is local-first.
5. All remote communication is outbound-initiated.
6. Signed local action envelopes are the only mutation path to remote stores.
7. No raw session tokens, prompts, model outputs, or source code in remote
   storage.

## Mapping to Existing Rig Relay

| Rig Relay concept | Local | Remote |
|---|---|---|
| `~/.rig/relay/sessions/` | Full evidence | — |
| Observability JSONL | Full events | Hashes + counts |
| Coordination store | Full leases/claims | — |
| Desktop projection | Full widget state | Non-authoritative excerpt |
| Authorization receipts | Full receipt | — |
| Telemetry bundles | Full bundle | Content-light manifest |
| Action intents | Full intent | — |

## Mapping from Intake

| Intake concept | Rig Relay equivalent | Adaptation |
|---|---|---|
| Hosted Intake (public) | Remote Telemetry Store | No business domain; telemetry-only |
| Local Intake Console | Local Rig Relay Cockpit | Same split-brain pattern |
| EncryptedPayload | Content-light + optional ciphertext | Relaxed to "no raw content" baseline |
| SignedLocalDeviceAction | Signed Local Action Envelope | Same pattern, Relay-specific fields |
| Sync Protocol (outbound) | Outbound telemetry push | Same direction constraint |

## Cross-References

- [Rig + Intake Cannibalization Plan](../audits/rig-intake-cannibalization-plan.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- [Telemetry Redaction Boundary](telemetry-redaction-boundary.md)
- [Desktop Cockpit UI](desktop-cockpit-ui.md)
