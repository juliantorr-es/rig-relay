# Audit: Relay Validation Gates and Doctor Roadmap
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: e389b446706173ebc5950931994ba4cdb6a7d9f4
Scope: Read-only roadmap audit
Owner area: tests

## Executive Summary
This roadmap defines the automated validation gates required to mature Rig Relay's evidence model. It distinguishes between CI-level regressions and user-facing "doctor" checks for local environment health.

## Gate Inventory
| Gate Name | Maturity | Target | Description |
| :--- | :--- | :--- | :--- |
| **Root Isolation Check** | Level 3 | CI/Doctor | Verify that repo-local runs do not touch the global home. |
| **Schema Parity** | Level 4 | CI | Ensure all JSONL lines validate against the V1 schema. |
| **Sorted Traversal** | Level 3 | CI | Regress non-deterministic file discovery in tool/agent managers. |
| **Artifact Parity** | Level 2 | Doctor | Verify that `ARTIFACT_WRITTEN` events have matching files. |
| **Path Sanitization** | Level 2 | CI | Detect absolute paths in evidence metadata. |
| **Stale Session Cleaner** | Level 1 | Doctor | Identify and suggest cleanup for unfinished/broken sessions. |

## Gate Maturity Levels
- **Level 1**: Advisory only (warnings).
- **Level 2**: Recommended for local dev.
- **Level 3**: Mandatory for CI PRs.
- **Level 4**: Block-on-fail for production releases.

## Which Gates Belong in CI
- Schema Parity
- Sorted Traversal
- Path Sanitization
- Root Isolation (using mocked home)

## Which Gates Belong in Local Doctor
- Artifact Parity
- Stale Session Detection
- Legacy Config Detection

## Suggested Command Names
- `rig-relay doctor`: General health check.
- `rig-relay verify-session <id>`: Deep integrity check for a specific run.
- `rig-relay doctor evidence --evidence-root <path> --session <id>`: Selected-session evidence validation gate with manifest-aware parity checks.

## Recommended Implementation Order
1.  **Sorted Traversal Guard**: Add a unit test that mock-shuffles directories and asserts stable discovery.
2.  **Schema Validator**: Integrate `jsonschema` into the telemetry test suite.
3.  **Doctor Basic**: Implement `rig-relay doctor --paths`.
4.  **Evidence Doctor**: Validate a selected session with canonical JSON, explicit file references, and optional manifest coverage.
