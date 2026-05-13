# Provider Onboarding Policy

## Status

**Draft.** Defines the security and product boundaries for cloud model provider
API key onboarding in Rig Relay's desktop cockpit.

## Core Principles

### Provider onboarding is separate from identity

- **Identity** answers: _Who is this tester?_ (GitHub/Google sign-in)
- **Provider keys** answer: _Which model APIs can this local install call?_
- **Authorization receipts** answer: _What protected actions may this machine perform?_

These three concerns must never be conflated. Provider onboarding must not grant
protected intent authority, must not imply telemetry consent, and must not
change identity semantics.

### No remote key storage

API keys are stored **only on the local machine**:

| Store | Path | Security |
|---|---|---|
| Environment variables | `$OPENAI_API_KEY`, etc. | Read at runtime via `os.environ` |
| Dev file store | `~/.rig/relay/providers/<provider>.key` | `chmod 0600`, excluded from git/build/bundles |
| macOS Keychain | Not yet implemented | Placeholder for future `keyring` integration |

### No keys in telemetry, audit, or frontend storage

- Intent audit may record: provider name, configured status, key source,
  key fingerprint (SHA256 prefix), health status, warnings
- Intent audit must **never** record: `api_key`, `provider_api_key`,
  `authorization`, `bearer_token`, or any raw credential field
- The shared redaction layer (`rig_relay.evidence.redaction`) marks all
  provider key field names as `FORBIDDEN` — they are redacted to `[REDACTED]`
- Frontend never stores keys in `localStorage`, `sessionStorage`, cookies,
  or IndexedDB
- Key input fields use `type="password"` and are cleared after save

## Supported Providers

| Provider | Env Var | Alt Env Var | Key Source Detection |
|---|---|---|---|
| OpenAI | `OPENAI_API_KEY` | — | Exact match |
| Anthropic | `ANTHROPIC_API_KEY` | — | Exact match |
| Google Gemini | `GEMINI_API_KEY` | `GOOGLE_API_KEY` | Prefers `GEMINI_API_KEY`; warns if both set |
| OpenRouter | `OPENROUTER_API_KEY` | — | Exact match |
| DeepSeek | `DEEPSEEK_API_KEY` | — | Supports optional `base_url` |

## Key Store Abstraction

Three backends implement the `ProviderKeyStore` protocol:

1. **`EnvProviderKeyStore`** — Read-only. Reads from environment variables.
   Cannot `set_key()` or `remove_key()`. Used for runtime key detection.

2. **`DevFileProviderKeyStore`** — Read-write. Stores keys in individual files
   under `~/.rig/relay/providers/`. Files created with `chmod 0600`.
   Excluded from telemetry/bundles/audit intentionally by the redaction layer.

3. **`MacKeychainProviderKeyStore`** — Placeholder. Not yet implemented.
   Will use the `keyring` library (already a dependency) when implemented.

## Health Check Behavior

Default: **No network calls.** `network_allowed=False` returns configured/skipped
status based on key presence and SHA256 fingerprint only.

"valid" means a real provider-specific network check succeeded. "configured"
means a key exists but has not been network-validated.

| Scenario | Status Returned |
|---|---|
| Key present, `network_allowed=False` | `valid` (key-presence based) |
| No key found | `skipped` with warning |
| `network_allowed=True`, check not implemented | `unknown` with `network_check_not_implemented` warning |
| `network_allowed=True`, check implemented | `valid` / `invalid` / `error` |

Network checks are explicit (`network_allowed=True`). They must not run in
tests, must not print raw keys, must timeout quickly, and must return
content-light status only. Unimplemented network checks always return
`unknown`, never `valid`.

## Desktop Intents

Four safe/control-plane intents for provider onboarding:

| Intent | Description | Content-Light? |
|---|---|---|
| `provider_status` | Return provider summaries for all providers | ✅ |
| `provider_onboarding_save_key` | Save provider key locally | ✅ Returns fingerprint only |
| `provider_onboarding_remove_key` | Delete local provider key | ✅ |
| `provider_health_check` | Check provider health | ✅ No network by default |

These intents do **not** grant protected action authority. They are
categorized as safe/control-plane, not protected.

## Frontend Placement

| Mode | Widget | Key Controls? |
|---|---|---|
| **Operate** | Provider Health Pill (configured count) | ❌ No |
| **System** | Model Providers card (list, status, key fields) | ✅ Save/Remove/Check |

The Operate mode shows only a small health indicator — no key input fields.
Key controls are restricted to System mode, two clicks from the default view.

## Audit Compliance

Intent audit may record (content-light):
- `provider` — provider name
- `configured` — boolean
- `key_source` — env, dev_file, missing
- `key_fingerprint` — SHA256 prefix
- `status` — valid, skipped, error
- `warnings` — string list

Intent audit must **not** record:
- `api_key` or any `*_api_key` variant
- `authorization` header
- `bearer_token`
- Any raw credential

The shared redaction boundary (`assert_remote_safe` in `rig_relay.evidence.redaction`)
enforces this by marking all credential field names as `FORBIDDEN`.

## Cross-References

- [Frontend Rendering Safety Doctrine](frontend-rendering-safety.md)
- [Relay Local/Remote Boundary](relay-local-remote-boundary.md)
- [Desktop Cockpit UI](desktop-cockpit-ui.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- [Provider Config Schema](../schemas/rig.relay.provider_config.v1.schema.json)
- [Provider Status Schema](../schemas/rig.relay.provider_status.v1.schema.json)
- [Provider Onboarding Result Schema](../schemas/rig.relay.provider_onboarding_result.v1.schema.json)
