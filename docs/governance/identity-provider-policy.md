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

## GitHub-Connected Review Boundary

GitHub-connected review tooling is a bounded snapshot, not a live mirror.

- A connected repository snapshot remains in the state it had when imported; later pushes do not auto-sync into the same Gemini chat.
- Keep the review slice within the provider limit of one repository per chat, up to 5,000 files and 100 MB.
- Private repositories require a linked GitHub account that already has access to the repo.
- If the linked account is disconnected, public repositories can still be imported, but private repositories must be re-linked before reuse.
- Gemini GitHub import cannot read commit history, pull requests, or other repo metadata, cannot read a repository by raw URL in the prompt, and cannot write back into the repository.
- Treat `.github/workflows/` as outside the review surface for Gemini-connected repository imports.
- Work or school accounts may be blocked by Google Workspace policy or firewall restrictions even when the repo itself is valid.
- Consumer GitHub Code Assist review quotas are limited to 33 pull request reviews per day, while the enterprise tier allows at least 100 per day depending on codebase and review cost. Review slices should stay narrow and intentionally published for review rather than trying to turn a whole repository into one session.

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

## Telemetry Consent

Sign-in does **not** imply telemetry consent. These are separate toggles:

| Toggle | Scope | UI Location |
|---|---|---|
| `identity_status` | Who is the user | System → Identity |
| `telemetry_consent_status` | Whether telemetry is shared | System → Telemetry Consent |
| `telemetry_consent_grant` | Grant consent for content-light telemetry | System → Telemetry Consent |
| `telemetry_consent_revoke` | Revoke existing consent | System → Telemetry Consent |

### Consent Behavior

- Consent records are stored locally in `~/.rig/relay/consent/telemetry_consent.json`
- OAuth tokens are stored separately in `~/.rig/relay/identity/` — never in consent records
- Consent records are content-light: no raw email, raw tokens, raw prompts, raw code, raw output
- Revocation updates the record to `revoked` status — does not delete history
- Telemetry bundles include consent status (status + subject_hash + scopes + policy_version) when consent exists

### Consent Scopes

Consent is granular per scope. Basic scopes (usage metrics, content-light bundles, crash reports, coordination metrics, tool refinement metrics) are opt-in defaults. Commercial scopes (provider model benchmarking, local model benchmarking, commercial dataset license, aggregate public reporting) are **never default** — must be explicitly checked by the user.

- **Commercial scopes** permit inclusion in aggregated, anonymized derived datasets for benchmarking reports and potential commercial licensing.
- **Basic and commercial scopes are independent.** A user may grant basic telemetry consent without granting commercial dataset license.
- The `has_commercial_dataset_license()` helper checks for the `COMMERCIAL_DATASET_LICENSE` scope specifically.
- Current policy version: `alpha-usage-data-license-v1`.
- See [Usage Data Commercial License](../legal/usage-data-license-alpha.md) and [Privacy Notice](../legal/privacy-notice-alpha.md) for legal terms.

### Content-Light Guarantee

Telemetry bundles and consent records follow the content-light guarantee:
- No raw prompts or model outputs
- No source code or file contents
- No stdout/stderr bodies
- No diffs or secrets
- No raw receipt bodies
- No OAuth tokens

## State Root

All identity and consent state is rooted under an explicit state root directory.

### Production Default

```
~/.rig/relay/
├── identity/       # OAuth token bundles (DevFileTokenStore)
├── consent/        # Telemetry consent records (ConsentStore)
│   └── telemetry_consent.json
└── providers/       # Provider onboarding keys (future)
```

### Test Isolation

Tests must pass `tmp_path` as an explicit root. Banks must never read from
`~/.rig/relay/` during unit tests.

```python
# Test: explicit store_root prevents home access
store = ConsentStore(store_root=tmp_path / "consent")
store.save(record)
```

### Bundle Isolation

- `--consent-file PATH` reads consent from the exact file path.
- `--state-root PATH` auto-detects consent from `<state_root>/consent/`.
- Without either flag, the bundle creator does **not** auto-read `~/.rig/relay/`.
- Identity summary is only included if `--state-root` is provided and identity
  data exists at `<state_root>/identity/`.

### State Root Helpers

The `rig_relay.identity.state_paths` module provides root helpers:

| Helper | Returns |
|---|---|
| `default_relay_state_root()` | `~/.rig/relay/` |
| `identity_state_root(root)` | `<root>/identity` |
| `consent_state_root(root)` | `<root>/consent` |
| `provider_state_root(root)` | `<root>/providers` |

## Cross-References

- [Desktop Cockpit UI](desktop-cockpit-ui.md)
- [Frontend Rendering Safety Doctrine](frontend-rendering-safety.md)
- [Relay Local/Remote Boundary](relay-local-remote-boundary.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- [Identity Provider Schema](../schemas/rig.relay.identity_provider.v1.schema.json)
- [Identity Session Schema](../schemas/rig.relay.identity_session.v1.schema.json)
- [OAuth Callback Receipt Schema](../schemas/rig.relay.oauth_callback_receipt.v1.schema.json)
- [Telemetry Consent Schema](../schemas/rig.relay.telemetry_consent.v1.schema.json)
- [Telemetry Bundle Manifest Schema](../schemas/rig.relay.telemetry_bundle_manifest.v1.schema.json)
