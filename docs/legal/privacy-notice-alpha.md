# Privacy Notice — Alpha

> **⚠ Attorney review required before public release.**
> This document describes the intended privacy practices for Rig Relay alpha
> telemetry. It is not a legally binding privacy policy. A qualified attorney
> must review and formalize this notice before any public distribution of the
> software or collection of user data.

## Overview

Rig Relay alpha collects content-light telemetry for product improvement,
model provider benchmarking, and coordination optimization. This notice
explains what is collected, what is explicitly not collected, and how users
control their data.

## What We Collect (Content-Light Only)

All telemetry is content-light. No raw user content is ever collected.

| Category | Fields Collected |
|---|---|
| Usage metrics | Tool invocation counts, latency percentiles, error rates |
| Crash reports | Stack trace hashes, exception type, count |
| Coordination metrics | Task counts, lease durations, conflict counts |
| Tool refinement | Tool name, success/failure counts, retry counts |
| Model benchmarking | Task fingerprints (SHA256), model IDs, latency, token counts, memory usage |
| Provider ranking | Aggregated provider/model scores, task-type success rates |

## What We Never Collect

- Raw prompts or user messages
- Model outputs or completions
- Source code, file contents, or diffs
- stdout/stderr output bodies
- API keys, tokens, secrets, or passwords
- Authorization receipt bodies
- Personal identifiable information (email, name, IP address)
- Raw file paths or directory structures
- Machine hostnames or usernames

## Consent Model

Consent is **explicit, scoped, and revocable**:

- **Basic telemetry scopes** (usage metrics, content-light bundles, crash
  reports, coordination metrics, tool refinement metrics): Users opt in by
  granting consent. Default is not requested.
- **Commercial dataset license scopes** (provider model benchmarking, local
  model benchmarking, commercial dataset license, aggregate public
  reporting): Never granted by default. Must be explicitly checked by the
  user. These scopes permit inclusion in aggregated, anonymized derived
  datasets for benchmarking reports and potential commercial licensing.

Consent is recorded locally in `~/.rig/relay/state/telemetry_consent.json`.
It is never uploaded without explicit user action. Remote sync is opt-in.

## Data Storage and Retention

- Raw telemetry events are stored locally under `~/.rig/relay/sessions/`.
- Derived datasets are produced by the telemetry bundle system.
- Users may delete all local telemetry data at any time.
- No cloud storage occurs without explicit opt-in remote sync.

## Your Rights

1. **Right to know**: Review your consent record and scopes at any time via
   the System → Telemetry Consent card.
2. **Right to withdraw**: Revoke consent at any time. Revocation is
   prospective.
3. **Right to deletion**: Delete all local telemetry data.
4. **Right to opt out of commercial use**: Never grant commercial dataset
   license scopes. Basic telemetry functions independently.

## Changes to This Notice

Users will be notified of material changes and asked to re-confirm consent
if policy version changes.

## Contact

For questions about this privacy notice or Rig Relay data practices, open
an issue in the Rig Relay repository.

## Policy Version

This notice corresponds to consent policy version:
`alpha-usage-data-license-v1`
