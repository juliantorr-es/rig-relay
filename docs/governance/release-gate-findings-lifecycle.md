# Release Gate Findings Lifecycle

## Why This Exists

The Release Evidence Gate produces findings — deterministic observations about the repository's release readiness. Without a lifecycle, every finding is either ignored (eroding trust) or treated as a blocker (paralyzing progress). The findings lifecycle provides governed classification so the gate can be honest about debt while allowing intentional, auditable deferral.

## Lifecycle States

| State                     | Meaning                                               | Blocks Release?                                                            |
| ------------------------- | ----------------------------------------------------- | -------------------------------------------------------------------------- |
| `accepted_false_positive` | Known not to represent a real product/release risk    | No                                                                         |
| `intentional_deferred`    | Work intentionally deferred; visible but not blocking | No (unless `release_blocking_override: true`)                              |
| `known_debt`              | Real debt; remains visible                            | Yes, by default. Can be overridden with `release_blocking_override: false` |
| `needs_fix`               | Confirmed actionable; must block                      | Yes (always)                                                               |
| `not_applicable`          | Finding does not apply to the current release surface | No                                                                         |
| `watch`                   | Non-blocking observation                              | No                                                                         |

## Core Principle: Triage Does Not Delete

Findings are never removed from the gate output. Triage means **classify and alter release-blocking effect while preserving evidence**. Suppressed or deferred findings remain visible with their effective state, original severity, and lifecycle classification. The Romulans may cloak ships; Rig does not cloak findings.

## How Expiration Works

- Entries with an `expires` date become invalid after that date
- Expired entries **do not suppress or downgrade** findings
- Expired entries are reported in the gate output as `triage_expired: true`
- The triage reason is prefixed with `[EXPIRED]`
- Entries without `expires` are permanent (use sparingly for blocker/high findings)

## How to Add a Policy Entry

1. Open `docs/json/release_gate/findings_lifecycle.v1.json`
2. Add an entry to the `entries` array:

```json
{
  "finding_id": "trace.violation.TC-0021",
  "check_id": "runtime.trace_contract.clean_or_triaged",
  "lifecycle_state": "accepted_false_positive",
  "reason": "String literal check_id in source, not a trace event emission.",
  "owner": "lane-c",
  "expires": "2026-12-31",
  "evidence_refs": ["rig_relay/release_gate/_runtime_readiness.py"]
}
```

3. Run the gate to verify: `uv run python -m rig_relay.release_gate --lifecycle docs/json/release_gate/findings_lifecycle.v1.json --output .build/rig-relay/release-gate.json`
4. Check that the finding is classified, original severity is preserved, and release-blocking effect is appropriate

## How to Run the Gate With and Without Lifecycle

```bash
# Without lifecycle (raw findings)
python -m rig_relay.release_gate --output .build/rig-relay/release-gate-raw.json

# With lifecycle (classified findings)
python -m rig_relay.release_gate \
  --lifecycle docs/json/release_gate/findings_lifecycle.v1.json \
  --output .build/rig-relay/release-gate-classified.json
```

## Gate Output With Lifecycle

When lifecycle is active, each flattening finding gains additional fields:

- `original_severity` — the check's original severity
- `effective_severity` — severity after lifecycle application
- `lifecycle_state` — the matched lifecycle state (empty if unmatched)
- `release_blocking` — whether this finding blocks release (after lifecycle)
- `triage_reason` — justification from the policy entry
- `triage_owner` — accountable person/team
- `triage_expires` — expiration date (empty if permanent)
- `triage_evidence_refs` — supporting evidence references
- `triage_expired` — true if the entry has expired

The `lifecycle` section of the gate output reports:

- `policy_id`, `schema_version`
- `entries_loaded`, `entries_applied`, `entries_expired`, `entries_unmatched`
- `policy_findings` — findings about the lifecycle policy itself (e.g., unmatched entries)

## How This Supports Release Discipline

- **Honest gate**: The gate fails for real untriaged blockers; it does not fail for known, governed exceptions
- **Auditable**: Every classification has a reason, owner, and optional expiration
- **Visible debt**: `known_debt` findings remain visible in output even when non-blocking
- **Expiration enforced**: Classifications that outlive their justification automatically revert to blocking
- **No mass suppression**: Each entry matches exact `finding_id + check_id` — no wildcards, no blanket exemptions

## Avoiding Abuse

- Do not classify real blockers as `accepted_false_positive` without evidence
- Do not use `known_debt` with `release_blocking_override: false` to normalize broken windows — set an expiration
- Every `accepted_false_positive` entry should reference evidence (a source file, commit, or issue)
- If more than 20% of findings are triaged, the triage policy itself is probably a finding

## Connection to Telemetry/Tracing Governance

This lifecycle aligns with the tracing governance doctrine (`docs/governance/usage-data-doctrine.md`):

- Findings are evidence-bearing observations with identity, severity, source, and recommendation
- The lifecycle policy is schema-governed (`rig.release_gate.findings_lifecycle.v1`)
- Policy effects are exposed in machine-readable gate output
- The system is observable: lifecycle application is reported, not hidden

## Schema

- **Schema**: `docs/schemas/rig.release_gate.findings_lifecycle.v1.schema.json`
- **Policy**: `docs/json/release_gate/findings_lifecycle.v1.json`
- **Implementation**: `rig_relay/release_gate/findings_lifecycle.py`
- **Models**: `rig_relay/release_gate/models.py` (LifecycleState, LifecycleEntry, LifecyclePolicy, etc.)
- **Tests**: `tests/release_gate/test_findings_lifecycle.py`
