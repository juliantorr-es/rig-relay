# Usage Data Commercial License — Alpha

> **⚠ Attorney review required before public release.**
> This document describes the intended license terms for commercial usage of
> aggregated, anonymized Rig Relay telemetry datasets. It is not a legally
> binding document. A qualified attorney must review and formalize these terms
> before any commercial licensing, sale, or public distribution of derived
> datasets.

## Purpose

Rig Relay alpha collects content-light telemetry to improve the product and
benchmark model providers. This license governs the **commercial use** of
aggregated, anonymized derived datasets produced from that telemetry.

**Commercial dataset licensing is a separate concept from privacy consent.**
A user may grant privacy consent for basic telemetry (usage metrics, crash
reports, coordination metrics, tool refinement metrics) without granting a
commercial dataset license. The commercial dataset license must be explicitly
granted, never inferred, and never bundled with basic telemetry consent.

## Scope

This license applies to derived datasets that:

- Contain **no raw prompts, model outputs, source code, diffs,
  stdout/stderr bodies, secrets, tokens, API keys, or raw authorization
  receipt bodies**.
- Contain only content-light fields: SHA256 hashes, counts, timestamps,
  latency metrics, tool-call metadata (names, durations, success/failure),
  and aggregate statistics.
- Are aggregated across multiple users to a minimum anonymity set size.
- Are produced by the Rig Relay telemetry bundle system.

## Grant

When a user explicitly grants the `commercial_dataset_license` or
`aggregate_public_reporting` scope in their telemetry consent record, Rig
Relay may:

1. Include that user's content-light telemetry in aggregated, anonymized
   derived datasets.
2. Use those derived datasets for:
   - Model provider ranking and benchmarking reports.
   - Local model comfort-score calibration.
   - Public aggregate reports (no individual attribution).
   - Commercial licensing to third parties (under separate terms).

## Limitations

- **No raw data licensing.** Raw telemetry events (individual observation
  lines) are never licensed for commercial use. Only aggregated, anonymized
  derived datasets may be licensed.
- **No re-identification.** Licensed datasets must be aggregated such that
  individual users cannot be re-identified.
- **No API key or secret exposure.** Licensed datasets are screened by the
  content-light guarantee before inclusion.
- **Opt-out at any time.** Users may revoke commercial dataset license at
  any time. Revocation applies prospectively; previously distributed
  aggregated datasets are not recalled.

## Policy Version

This license corresponds to consent policy version:
`alpha-usage-data-license-v1`

## Related Documents

- [Privacy Notice Alpha](./privacy-notice-alpha.md)
- [Telemetry Consent Schema](../schemas/rig.relay.telemetry_consent.v1.schema.json)
- [Usage Data Governance Doctrine](../governance/usage-data-doctrine.md)
