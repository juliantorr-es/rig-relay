# Step-Up Authorization Doctrine

## Purpose

Define a step-up authorization boundary for high-authority Rig Relay actions so
they cannot execute silently. Passkeys are the target long-term verification
method, but the alpha implementation begins with action-scoped authorization
receipts and policy enforcement.

## Core Rules

1. **Low-risk read-only actions must remain smooth** — no step-up required for
   current_state, dry-run operations, reports, schema validation, or basic
   search/read.

2. **High-authority actions require step-up authorization** — real upload,
   checkpoint commits, fleet/spawn execution, destructive cleanup, credential
   changes, and telemetry share level changes must not execute without explicit
   user verification.

   In the desktop cockpit dev/local phase, `mint_authorization_receipt_dev`,
   `mint_authorization_receipt_local`, and `inspect_authorization_receipt`
   exist as control-plane aids for `checkpoint.commit` and
   `lease_cleanup.archive`. They do not expose protected execution buttons.

3. **Authorization receipts are short-lived and action-scoped** — a receipt
   authorizes exactly one action on exactly one resource for a limited time.

4. **Receipts contain no secrets** — no private keys, raw biometric data,
   passwords, or raw credential material.

   Audit and result artifacts record receipt hashes, status, and expiry only.
   Raw receipt bodies remain out of audit logs.

## Protected Actions

| Action | Description |
|--------|-------------|
| `remote_upload.confirm` | Execute real Google Drive upload |
| `telemetry.share_level.change` | Change remote telemetry sharing level |
| `checkpoint.commit` | Create a governed checkpoint commit |
| `spawn.execute` | Spawn a child session for autonomous execution |
| `fleet.execute` | Execute a fleet of child sessions |
| `lease_cleanup.archive` | Archive stale coordination leases |
| `lease_cleanup.remove` | Permanently remove stale coordination leases |
| `credentials.configure` | Configure or rotate credentials |
| `update.restart_now` | Restart Rig Relay after an update |

## Authorization Methods

| Method | Description | Alpha Status |
|--------|-------------|-------------|
| `none_dev_only` | Dev/test bypass (no real verification) | Verified |
| `local_system_auth` | Platform-native auth (macOS Touch ID, Face ID, Passcode) | Implemented / Verified |
| `passkey_webauthn` | WebAuthn passkey (origin-scoped FIDO2 credential) | Schema/doctrine only |
| `remote_passkey` | Remote relying-party passkey service | Schema/doctrine only |

## Architecture Notes

### WebAuthn / Passkeys Are Origin-Scoped

The W3C WebAuthn spec defines that credentials are scoped to a relying party
and can only be accessed by origins belonging to that relying party. A local
pywebview app serving from `file://` or `127.0.0.1` needs careful origin
handling.

Three implementation paths exist:

1. **WebAuthn with localhost origin** — Serve the desktop cockpit from
   `https://127.0.0.1:<port>` and use WebAuthn APIs in the frontend.

2. **Native platform auth wrapper** — Use macOS LocalAuthentication / Touch ID
   or Windows Hello directly for step-up, mapped through the authorization
   receipt system.

3. **Remote passkey relying-party service** — A small service (e.g.
   `auth.rigrelay.dev`) owns the RP identity. Users register a passkey there.
   The local app requests a challenge, performs WebAuthn, and receives an
   authorization token.

#
## Local Action Envelope (Schema Only)

The [Local Action Envelope Schema](../schemas/rig.relay.local_action_envelope.v1.schema.json)
defines a signed cryptographic container for future protected intent requests
and local-to-remote authority mutations.

**Current slice status:** Schema and model only. Not wired to protected execution.
Not yet used by intent dispatch or authorization receipt flows.

The envelope wraps:
- A canonicalized action payload (deterministic JSON key ordering)
- Replay prevention fields (action_id, nonce, issued_at, expires_at)
- An Ed25519 signature over the envelope body (excluding the signature field)

The model is defined in ``rig_relay/governance/local_action_envelope.py`` and
includes deterministic canonicalization, payload hashing, signing bytes
computation, and structural shape verification.

### Key design decisions
- **No raw secrets in the envelope.** The canonical payload does not include
  authorization receipt bodies — only the receipt hash.
- **``local_only`` defaults true** in the current slice. Remote mutations (future)
  will require additional review.
- **Replay window defaults to 300 seconds** (5 minutes), max 3600 (1 hour).
- **Ed25519** is the only supported signature algorithm.
- **Signing is optional** in this slice. The model supports it but does not
  enforce it for shape validation.

See ``tests/governance/test_local_action_envelope.py`` for 49 validated tests
covering schema, canonicalization, shape validation, replay policy, and content
safety.

## Implementation Order

1. Receipt validator enforced by upload/cleanup/checkpoint/spawn gates
2. macOS `local_system_auth` proof of concept
3. pywebview step-up modal
4. WebAuthn/passkey backend or secure-origin local implementation

## Receipt Lifecycle

```
Request created  →  User prompted  →  User verified  →  Receipt issued
                                                           ↓
                                                    Action executes
                                                           ↓
                                                    Receipt expires
```

## Content-Light Guarantee

Authorization receipts never contain:
- Private keys or raw credential material
- Raw biometric data (fingerprint templates, face maps)
- Passwords or passphrases
- Raw file contents or diffs
- Prompt text or model outputs

## References

- `docs/schemas/rig.relay.step_up_authorization_request.v1.schema.json`
- `docs/schemas/rig.relay.step_up_authorization_receipt.v1.schema.json`
- `docs/schemas/rig.relay.authorization_policy.v1.schema.json`
- `scripts/rig_relay_authorization_policy.py`
- FIDO Alliance: [Passkeys](https://fidoalliance.org/passkeys/)
- W3C WebAuthn: [Web Authentication API](https://www.w3.org/TR/webauthn-3/)
- Apple: [Passkey support](https://support.apple.com/en-us/102195)
