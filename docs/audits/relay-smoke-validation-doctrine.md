# Audit: Relay Smoke and Validation Doctrine
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: 24c990e011375078a04cb4a5534d114f98c064ed
Scope: Read-only audit
Owner area: tests

## Executive Summary
This doctrine defines the taxonomy of Rig Relay validation gates to ensure clear separation between "does the CLI work?" and "is the evidence correct?". It clarifies the distinction between Command Viability, Provider Behavior, and Evidence Determinism.

## Smoke Taxonomy
| Class | Goal | Evidence Requirement | Determinism |
| :--- | :--- | :--- | :--- |
| **CLI Inspection Smoke** | Prove the CLI can boot, parse args, and display UI. | Visual/TUI check, Logs. | Low (depends on TUI/OS) |
| **Evidence Smoke** | Prove the relay produces correct, isolated JSONL/artifacts. | JSONL + Schema + Artifact existence. | High (must be provider-independent) |
| **Provider E2E** | Prove integration with live model backends. | Response quality, valid usage metrics. | None (stochastic) |
| **Deterministic Unit** | Prove core logic (assembly, layout) in isolation. | Fixed hashes/content. | Absolute (Level 4) |

## What each smoke proves
- **Evidence Smoke**: Proves that if the model *were* to respond, the relay would record it correctly in the selected evidence root (e.g., repo-local for isolation).
- **CLI Smoke**: Proves that the user's environment is compatible with the `vibe` entrypoint.

## What each smoke does not prove
- Evidence smoke does not prove the model will give a "good" answer.
- CLI smoke does not prove the telemetry will survive a 100MB tool output.

## Recommended CI/Local Doctor Gates
1.  **Gate: Evidence Parity**: Every successful `_chat` turn MUST result in a `REQUEST_ACCOUNTED` event.
2.  **Gate: Root Isolation**: Evidence MUST NOT bleed into the global home during repo-local runs.
3.  **Gate: Schema Strictness**: Every line in `observability.jsonl` MUST validate against the V1 schema.

## Anti-patterns to avoid
- **Avoid**: Using a live Mistral key for an "Evidence Smoke" (slow, non-deterministic).
- **Avoid**: Using `tmp_path` without resetting the singleton `HarnessFilesManager` (causes cross-test pollution).

## Proposed Docs Path
`docs/architecture/validation_doctrine.md`
