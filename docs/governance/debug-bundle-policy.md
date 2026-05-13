# Debug Bundle Policy

## Status

**Deferred.** A consolidated `rig-relay debug bundle` command is deferred.
Existing ChatGPT dev bundle and telemetry bundle scripts remain available
independently.

## Current State

Rig Relay currently has two bundle scripts:

- `scripts/rig_relay_create_chatgpt_dev_bundle.py` — produces a ChatGPT
  development bundle from session artifacts.
- `scripts/rig_relay_create_telemetry_bundle.py` — produces a telemetry
  bundle with consent status and content-light event rows.

Both scripts produce content-light bundles with no raw prompts, model
outputs, source code, diffs, or secrets.

## Deferred Consolidation

A future `rig-relay debug bundle` command would:

- Unify both bundle types under one CLI command.
- Accept a `--kind` flag (`chatgpt_dev`, `telemetry`, `full`).
- Include a debug metadata header with session ID, version, and source
  artifact timestamps.
- Route through the shared redaction module for content-light guarantees.

## Cross-References

- [Rig + Intake Cannibalization Plan](../audits/rig-intake-cannibalization-plan.md)
- [ChatGPT Dev Bundle Schema](../schemas/rig.relay.chatgpt_dev_bundle_manifest.v1.schema.json)
- [Telemetry Bundle Manifest Schema](../schemas/rig.relay.telemetry_bundle_manifest.v1.schema.json)
