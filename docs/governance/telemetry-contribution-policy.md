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

Every contribution produces a local receipt and a result dict, both governed
by JSON schemas.

**Contribution receipt** (`rig.relay.contribution_receipt.v1.schema.json`):

- contribution_id
- bundle_sha256 (hash, not raw bundle)
- bundle_size_bytes
- destination_kind (always `google_drive`)
- consent_policy_version
- consent_scopes (active scopes at time of upload)
- contribution_mode (basic, model_observations, or commercial)
- Drive folder/file IDs (hashed only -- never raw)
- upload_method
- Status (dry_run, uploaded, refused_consent, etc.)
- content_light_guarantee
- Warnings

**Contribution result** (`rig.relay.contribution_result.v1.schema.json`):

- Orchestration metadata: consent_checked, upload_attempted, upload_confirmed
- Status (dry_run, uploaded, refused_consent, refused_content_light, etc.)
- receipt_path and receipt_sha256
- content_light_guarantee

Receipts and results contain no OAuth tokens, no raw Drive file IDs, no raw
Drive folder IDs, and no raw consent record contents. Raw identifiers are
replaced with SHA256 hashes.

## Schema Governance

Telemetry contribution artifacts are governed by the following JSON schemas:

| Schema | Purpose |
|--------|---------|
| `rig.relay.contribution_receipt.v1.schema.json` | Content-light contribution receipt with hashed Drive IDs, bundle identity via `bundle_sha256`, explicit `contribution_mode`, and `content_light_guarantee`. No raw Drive folder/file IDs are retained — identifiers are represented as SHA256 hashes where needed. |
| `rig.relay.contribution_result.v1.schema.json` | Orchestration result for the contribution flow. Contains consent check status, upload attempt metadata, step statuses (`steps`), upload receipt (`upload_receipt`), receipt path/SHA256, and `content_light_guarantee`. Separate from raw telemetry/event bundles. |

Both schemas enforce `additionalProperties: false` and are self-validated by the global schema validation script (`scripts/rig_relay_validate_schemas.py`). Contribution receipts and results are content-light artifacts distinct from raw telemetry/event bundles.

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

## Tool Receipt Evidence Index

Receipt events are indexed by `rig_relay.evidence.receipt_index` for query,
validation, and replay inspection. The index is:

- **Content-light**: no raw stdout, stderr, file contents, diffs, or snippets.
- **Read-only derived evidence**: built from session observability, never modified.
- **Audit surface**: answers which tools ran, mutations, refusals, timeouts.
- **Governed by** `docs/schemas/rig.relay.tool_receipt_index.v1.schema.json`.

See [Session Storage Lifecycle](session-storage-lifecycle.md#tool-receipt-evidence-index).

## Cross-References

- [Rig + Intake Cannibalization Plan](../audits/rig-intake-cannibalization-plan.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- [Telemetry Consent Model](../../rig_relay/identity/telemetry_consent.py)
- [Consent Store](../../rig_relay/identity/consent_store.py)
- [Frontend Rendering Safety](frontend-rendering-safety.md)
- [Relay Local/Remote Boundary](relay-local-remote-boundary.md)
- [Session Storage Lifecycle](session-storage-lifecycle.md)
- [Identity Provider Policy](identity-provider-policy.md)
