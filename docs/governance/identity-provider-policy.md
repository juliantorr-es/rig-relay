# Identity Provider Policy

## Status

**Draft.** Identity provider scaffold for Rig Relay alpha testing.

## Doctrine

Identity is separate from authority. Knowing who the user is does not grant
what they may do. This policy defines the boundaries for identity provider
integration (GitHub, Google) in Rig Relay.

## Identity Is Not Authority

Signing in with GitHub or Google does **not** grant:

| Not Granted | Reason |
|---|---|
| Mutation authority (write_file, bash, etc.) | Requires local authorization receipt |
| Telemetry consent | Separate toggle in cockpit |
| Drive access scope | Deferred, incremental authorization |
| GitHub repo scope | Deferred, identity-only for now |
| Protected intent execution | Receipt-gated, local-only |

Identity answers:

- Who is this tester/user?
- Which alpha cohort / install is this?
- Where do telemetry bundles belong?
- Which remote account may receive shared content-light data?

## Minimal Scopes by Provider

### GitHub (identity-only)

- `read:user` — read user profile
- `user:email` — read user email address

No repo scope. No workflow scope. No admin scope.

GitHub App user auth is preferred over classic OAuth App. If not practical
for alpha, OAuth App fallback is acceptable.

### Google (identity-only, OIDC)

- `openid` — OIDC authentication
- `email` — email address
- `profile` — display name, avatar

No Drive scope. Drive access is deferred and will use incremental
authorization when implemented.

## Desktop OAuth Flow

Must follow RFC 8252:

1. User clicks Sign in in System mode
2. Backend opens system browser (not pywebview embedded webview)
3. OAuth redirects to `http://127.0.0.1:<port>/callback`
4. Backend captures code via loopback HTTP server
5. Backend exchanges code for tokens
6. Token stored locally (Keychain later; dev file store now)
7. Cockpit projection refreshes identity status

## Token Storage

| Store | Status | Encryption |
|---|---|---|
| DevFileTokenStore | Current (dev scaffold) | None — plaintext warning |
| MacKeychainTokenStore | Future placeholder | macOS Keychain |

Tokens never enter:

- Audit logs
- Telemetry bundles
- Result artifacts
- Frontend storage (localStorage, sessionStorage, IndexedDB)

## Audit Content-Light Rules

Intent audit may record:

- provider name
- status (signed_out, pending, signed_in, error)
- state_hash
- scopes
- account_id_hash (if signed in)

Intent audit must **not** record:

- access_token
- refresh_token
- id_token
- authorization code
- raw email (if avoidable)
- client_secret

## Sign-In Does Not Imply Telemetry Consent

These are separate toggles:

- `identity_status` — who is the user
- `telemetry_sharing_status` — whether telemetry is shared
- `drive_upload_status` — whether Drive is authorized
- `github_repo_access_status` — whether GitHub repo access is granted

## Cross-References

- [Desktop Cockpit UI](desktop-cockpit-ui.md)
- [Frontend Rendering Safety Doctrine](frontend-rendering-safety.md)
- [Relay Local/Remote Boundary](relay-local-remote-boundary.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- [Identity Provider Schema](../schemas/rig.relay.identity_provider.v1.schema.json)
- [Identity Session Schema](../schemas/rig.relay.identity_session.v1.schema.json)
- [OAuth Callback Receipt Schema](../schemas/rig.relay.oauth_callback_receipt.v1.schema.json)
