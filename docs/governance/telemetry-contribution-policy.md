# Telemetry Contribution Policy

## Status

**Established.** Defines the consent-gated contribution flow for content-light
Rig Relay usage bundles to a configured Google Drive destination.

## Purpose

Users may contribute content-light telemetry bundles to help improve Rig Relay.
This policy defines the consent gates, content-light guarantee, upload behavior,
and receipt expectations for contribution flows.

## Core Rules

### Rule 1: Consent Required

No bundle is uploaded without explicit, active consent. The contribution flow
checks consent before every upload attempt.

| Contribution Type | Required Consent Scopes |
|---|---|
| Basic contribution | `content_light_bundles`, `usage_metrics` |
| With model observations | Also: `provider_model_benchmarking`, `local_model_benchmarking` |
| Commercial dataset | Also: `commercial_dataset_license` |

### Rule 2: Content-Light Guarantee

All contributed bundles must pass the content-light guarantee:

- No raw prompts or model output text
- No source code, file contents, or diffs
- No stdout/stderr output bodies
- No API keys, tokens, secrets, or passwords
- No raw authorization receipt bodies
- No personal identifiable information
- No raw private paths

The bundle is validated through the shared redaction module
(`rig_relay.evidence.redaction`) before upload.

### Rule 3: Dry-Run by Default

The contribution flow defaults to dry-run mode. No network upload occurs
without explicit `--confirm`. Dry-run creates a local receipt with
`status: "dry_run"` and all metadata fields populated.

### Rule 4: No Auto-Upload

Telemetry is never uploaded automatically. All contributions are
explicitly triggered by the user via the CLI script.

### Rule 5: Content-Light Receipt

Every contribution produces a local receipt with:

- contribution_id
- bundle_sha256 (hash, not raw bundle)
- consent_policy_version
- consent_scopes (active scopes at time of upload)
- Drive folder ID (hashed/redacted)
- Status (dry_run, uploaded, refused_consent, etc.)
- Warnings

Receipts contain no OAuth tokens, no raw Drive file IDs, and no
raw consent record contents.

## Flow

```
User runs contribute script
    → Bundle loaded or created
    → Bundle validated (content-light + schema)
    → Consent checked (required scopes active?)
    → Upload to Google Drive (or dry-run)
    → Receipt written to .build/rig-relay/drive-uploads/
```

### Consent Gate Detail

The contribution flow requires at minimum:

```python
REQUIRED_CONTRIBUTION_SCOPES = {
    TelemetryConsentScope.CONTENT_LIGHT_BUNDLES,
    TelemetryConsentScope.USAGE_METRICS,
}
```

If `--include-model-observations`, additional scopes are required:

```python
MODEL_OBSERVATION_SCOPES = {
    TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING,
    TelemetryConsentScope.LOCAL_MODEL_BENCHMARKING,
}
```

If `--commercial`, the commercial scope is required:

```python
COMMERCIAL_CONTRIBUTION_SCOPE = TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE
```

## Google Drive Behavior

- Uses Google Drive API `files.create` with resumable upload
- Uses `google-api-python-client MediaFileUpload` for file upload
- Uses `https://www.googleapis.com/auth/drive.file` scope
- Resumable upload with 256KB chunks for reliability
- No tokens printed to console or logs
- Dry-run by default unless `--confirm`
- Supports `--state-root`, `--bundle-path`, `--folder-id`, `--receipt-dir`

## Script

The contribution flow is implemented in a single script:

**`scripts/rig_relay_contribute_telemetry_bundle.py`**

Reuses existing modules:
- `create_bundle` from `scripts/rig_relay_create_telemetry_bundle.py`
- `validate_bundle` from `rig_relay.evidence.telemetry_bundle`
- `upload_bundle` from `scripts/rig_relay_upload_google_drive.py`
- `ConsentStore` from `rig_relay.identity.consent_store`
- `redact_for_remote` from `rig_relay.evidence.redaction`

## Cross-References

- [Rig + Intake Cannibalization Plan](../audits/rig-intake-cannibalization-plan.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- [Telemetry Consent Model](../../rig_relay/identity/telemetry_consent.py)
- [Consent Store](../../rig_relay/identity/consent_store.py)
- [Frontend Rendering Safety](frontend-rendering-safety.md)
- [Relay Local/Remote Boundary](relay-local-remote-boundary.md)
- [Identity Provider Policy](identity-provider-policy.md)
