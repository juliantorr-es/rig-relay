# Telemetry Consent Enforcement

**Status**: active
**Version**: v0 (alpha)
**Governed by**: `docs/schemas/rig.relay.telemetry_consent.v1.schema.json`
**Implements**: `rig_relay/core/telemetry/send.py` (`_evaluate_consent_gate`)

---

## Architecture

Rig Relay telemetry has two independent sinks:

| Sink                    | Default | Requires                                                                         | Degrades when off                                                          |
| ----------------------- | ------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| **Local observability** | ON      | `enable_local_observability=True`                                                | Governed mode, fleet, checkpoint, coordination, replay, autonomous spawn   |
| **Remote beta sharing** | OFF     | `enable_remote_telemetry=True` **AND** valid consent record with required scopes | Remote upload, maintainer debugging, shared benchmarks, cross-user reports |

Consent enforcement adds a second gate to the remote sink. Before remote upload:

1. Settings gate: `enable_remote_telemetry` or `enable_telemetry` must be `True`.
2. Consent gate: A `TelemetryConsentRecord` must exist, be `GRANTED`, and cover the required scopes for the event.

If either gate fails, remote upload is blocked and a locally auditable denial event is written.

---

## Consent Decision Model

```python
@dataclass
class TelemetryUploadDecision:
    allowed: bool
    reason: str              # remote_disabled, consent_not_found, consent_not_requested,
                             # consent_denied, consent_revoked, consent_policy_invalid,
                             # scope_missing, consent_granted
    consent_status: str | None
    matched_scopes: list[str]
    missing_scopes: list[str]
    policy_version: str | None
    remote_enabled: bool
    decided_at: str
```

### Decision Reasons

| Reason                   | Meaning                                              | Remote upload         |
| ------------------------ | ---------------------------------------------------- | --------------------- |
| `remote_disabled`        | `enable_remote_telemetry` is `False`                 | Blocked               |
| `consent_not_found`      | Consent getter returned `None` or threw an exception | Blocked (fail closed) |
| `consent_not_requested`  | Consent record exists but status is `NOT_REQUESTED`  | Blocked               |
| `consent_denied`         | User explicitly denied telemetry                     | Blocked               |
| `consent_revoked`        | User revoked previously granted consent              | Blocked               |
| `consent_policy_invalid` | Consent record is malformed or has unknown status    | Blocked               |
| `scope_missing`          | Consent is granted but required scopes are missing   | Blocked               |
| `consent_granted`        | All gates pass                                       | Allowed               |

### Fail-Closed Semantics

- Loader exception → `consent_not_found` → **blocked**
- `None` consent → `consent_not_found` → **blocked**
- Malformed record → `consent_policy_invalid` → **blocked**
- Unknown scope mapping → defaults to `USAGE_METRICS` → allowed only if scope present

### Revocation Beats Settings

A revoked consent record always blocks remote upload, even if `enable_remote_telemetry` or the legacy `enable_telemetry` alias is `True`.

---

## Scope Mapping

Events are mapped to consent scopes by prefix:

| Event prefix                    | Required scope                |
| ------------------------------- | ----------------------------- |
| `rig.relay.tool.*`              | `TOOL_REFINEMENT_METRICS`     |
| `rig.relay.session.*`           | `USAGE_METRICS`               |
| `rig.relay.context.*`           | `USAGE_METRICS`               |
| `rig.relay.checkpoint.*`        | `COORDINATION_METRICS`        |
| `coord.*`                       | `COORDINATION_METRICS`        |
| `rig.relay.model_observation.*` | `PROVIDER_MODEL_BENCHMARKING` |
| All other events                | `USAGE_METRICS` (default)     |

Model observation events require `PROVIDER_MODEL_BENCHMARKING`, which is **never in the default grant set**. This scope requires explicit opt-in.

---

## Local Audit Trail

Every consent decision — both allowed and denied — is logged locally:

| Event                             | When emitted                         |
| --------------------------------- | ------------------------------------ |
| `telemetry.remote_upload.allowed` | Consent gate passed, upload proceeds |
| `telemetry.remote_upload.denied`  | Consent gate failed, upload blocked  |

Denial events are content-light:

- `original_event` — the event that was blocked
- `reason` — the denial reason
- `consent_status` — consent record status (if available)
- `matched_scopes` / `missing_scopes` — scope match details
- `remote_enabled` — whether remote was enabled in settings
- `decided_at` — ISO timestamp

**No raw content, no subject hash, no PII is included in denial events.**

---

## Local Observability Unaffected

Consent enforcement **only** gates the remote upload path. The local observability sink (`observability.jsonl`) is written regardless of consent status. This is intentional: local observability is product infrastructure for governed mode, fleet coordination, and Ralph projections.

---

## Debug Bundles

Debug bundle upload (Google Drive) is a separate explicit user action governed by its own consent path. This slice does not change debug bundle behavior.

---

## Test Coverage

15 tests in `tests/core/test_telemetry_consent_gate.py`:

| Test                                                  | Proves                           |
| ----------------------------------------------------- | -------------------------------- |
| Remote disabled → no upload even with consent granted | Settings gate supersedes consent |
| Remote enabled + consent granted → upload occurs      | Happy path                       |
| Remote enabled + consent revoked → no upload          | Revocation blocks upload         |
| Revoked consent beats legacy `enable_telemetry=True`  | Revocation > settings            |
| Consent not-requested → no upload                     | Fail closed on missing consent   |
| No consent getter → no upload                         | Fail closed on missing getter    |
| Consent getter returns None → no upload               | Fail closed on None              |
| Missing required scope → no upload                    | Scope enforcement                |
| Consent loader exception → no upload                  | Fail closed on exceptions        |
| Local observability writes when remote denied         | Local sink unaffected            |
| Denial writes auditable local decision                | Audit trail                      |
| Decision preserves content-light boundary             | No PII leakage                   |
| Existing debug bundle behavior unchanged              | No regression                    |
| Revoked consent blocks upload with sensitive payload  | E2E revocation                   |
| Decision never leaks subject_hash                     | Content-light guarantee          |

Existing telemetry send tests (39 tests) pass via a backward-compatible bypass fixture.

---

## Configuration

```python
# In _agent_init.py, the TelemetryClient is constructed with:
consent_record_getter=self._load_consent_record

# _load_consent_record reads from:
#   .rig/relay/telemetry_consent.json
#
# If the file doesn't exist, consent is None → upload blocked (fail closed).
```

To grant consent, write a valid `TelemetryConsentRecord` to `.rig/relay/telemetry_consent.json`:

```json
{
  "schema_version": "rig.relay.telemetry_consent.v1",
  "consent_id": "cons_abc123def456",
  "subject_hash": "<sha256 of anonymous identifier>",
  "provider": "local",
  "status": "granted",
  "scopes": [
    "usage_metrics",
    "content_light_bundles",
    "crash_reports",
    "coordination_metrics",
    "tool_refinement_metrics"
  ],
  "granted_at": "2026-05-17T00:00:00Z",
  "policy_version": "alpha-usage-data-license-v1",
  "local_only": true
}
```

---

## Remaining Risks

1. **Consent store is file-based** — the `.rig/relay/telemetry_consent.json` path is fragile. A proper consent store with migration support should replace this in the next slice.
2. **No UI for consent management** — currently requires manual JSON editing. The desktop cockpit should expose consent controls.
3. **No per-repo scoping** — consent is global per machine. A user cannot grant consent for one repo but not another.
4. **No consent expiry enforcement** — the `expires_at` field exists on `TelemetryConsentRecord` but is not enforced by the gate.

These are deferred to future slices. The enforcement boundary itself is now closed.
