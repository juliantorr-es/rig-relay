# Future Passkey Plan

## Status

**Deferred.** WebAuthn/passkey authentication for Rig Relay is documented
here for future reference. No implementation work is planned for this slice.

## Context

Intake's passkey implementation uses WebAuthn with the following caveats
applicable to Rig Relay:

- Local development WebAuthn RP IDs must be `localhost`, not `127.0.0.1`,
  because the Web Authentication spec forbids IP addresses as RP IDs.
- Passkey registration requires a secure context (HTTPS or localhost).
- pywebview does not natively support WebAuthn; a custom JS bridge or
  native handler would be needed.

## When to Implement

- When Rig Relay needs passwordless authentication for remote telemetry
  or multi-user session management.
- When pywebview or an alternative shell provides WebAuthn support.
- After the local/remote authority boundary is exercised by real users.

## Cross-References

- [Rig + Intake Cannibalization Plan](../audits/rig-intake-cannibalization-plan.md)
- [Relay Local/Remote Boundary](relay-local-remote-boundary.md)
