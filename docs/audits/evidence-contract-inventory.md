# Audit: Evidence Contract Inventory
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: 24c990e011375078a04cb4a5534d114f98c064ed
Scope: Read-only audit
Owner area: evidence

## Executive Summary
Rig Relay's evidence model is centered around a sequential, append-only JSONL observability log (`observability.jsonl`) and side-loaded JSON artifacts for large data blobs (context assembly, layouts, tool outputs). The system relies on `dump_canonical_json` (sorted keys, compact separators) for most evidence-grade outputs, providing a strong baseline for determinism. However, session-level isolation and current-run guarantees are still maturing.

## Evidence Contract Inventory Table
| Evidence type | File pattern | Event name | Writer | Reader | Current guarantees | Missing guarantees | Test coverage | Maturity |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Observability Log** | `observability.jsonl` | Multiple | `local.log_local_event` | `DuckDBProjection` | Canonical JSON, Sequential | Monotonic sequence IDs | High | Evidence-Grade Candidate |
| **Tool Artifact** | `tool-results/*.json` | `artifact.tool_output_written` | `ArtifactWriter` | User/Manual | Atomic write, SHA256 record | Content-addressed naming | Med | Evidence-Grade |
| **Assembly Report** | `context/assembly_*.json` | `context.assembly_reported` | `assembler.py` | `DuckDBProjection` | Canonical JSON | Hash-based identity | Med | Telemetry |
| **Layout Plan** | `context/layout_*.json` | `context.layout_planned` | `assembler.py` | `AgentLoop` | Canonical JSON | Hash-based identity | Med | Telemetry |
| **Shadow Request** | `context/shadow_*.json` | `context.shadow_request_assembled` | `assembler.py` | Manual/CI | Canonical JSON | Consistent triggering | Low | Telemetry |

## Evidence Lifecycle Map
1.  **Session Start**: `SESSION_STARTED` event emitted to `observability.jsonl`.
2.  **Tool Execution**: Output captured; if >16KB, `ArtifactWriter` writes side-artifact and emits `ARTIFACT_WRITTEN`.
3.  **Context Prep**: `AgentLoop` calls `assembler` to build assembly report and layout plan.
4.  **Reporting**: `ASSEMBLY_REPORTED` and `LAYOUT_PLANNED` events emitted; JSON files written to `context/`.
5.  **LLM Call**: `REQUEST_ACCOUNTED` event emitted with usage/token data.
6.  **Projection**: `DuckDBProjection` sweeps `observability.jsonl` files to produce `ObservabilitySummary`.

## Contract Gaps
### EVIDENCE-CONTRACT-001: Shadow Request Inconsistency
- **Location**: `vibe/core/agent_loop.py`
- **Current behavior**: Shadow requests are only generated during `_chat` turns.
- **Risk**: Turns that stop early (max turns, user cancel) may leave incomplete evidence of the context assembly.
- **Recommended refinement**: Trigger assembly reporting at the start of every turn, regardless of backend call.
- **Priority**: P1

### EVIDENCE-CONTRACT-002: Content-Addressed Artifacts
- **Location**: `vibe/core/telemetry/artifacts.py`
- **Current behavior**: Filenames use UUIDs.
- **Risk**: Harder to deduplicate or verify without reading the payload.
- **Recommended refinement**: Use SHA256 of the payload for the filename.
- **Priority**: P2

## Test Coverage Map
- `tests/telemetry/test_observability_e2e.py`: Covers the full chain from emission to DuckDB.
- `tests/telemetry/test_artifacts.py`: Covers atomic writing and threshold logic.
- `tests/telemetry/test_context_blocks.py`: Covers assembly and layout schema validation.

## Recommended Documentation Structure
- `docs/evidence/observability_schema.md`: Definitions of every event and field.
- `docs/evidence/artifact_lifecycle.md`: How large outputs are handled.
- `docs/evidence/validation_doctrine.md`: How to verify a run's integrity.

## Next Mission Recommendation
**Mission: Monotonic Sequence Enforcement**
Implement a session-local monotonic counter for `observability.jsonl` events to guarantee gap detection and prevent event reordering during high-concurrency async operations.
