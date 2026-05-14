# Fleet Coordination Completion — Phases 3–5

**Date:** 2026-05-14  
**Session type:** Multi-mission (5 sequential missions)  
**Branch:** `main` at `384e486` (even with `origin/main`)  
**Validation state:** All green — 483 coordination tests, 44 projection tests, 24 fleet panel tests, 111 schemas, ruff format/check, pyright

---

## Overview

Five sequential missions implementing fleet coordination infrastructure across Phases 3–5. The work spans runtime lease hardening, patch proposal workflow, test closure, queue runner, and projection read model wiring.

---

## Mission 1 — Phase 3 Runtime Lease Hardening

### Goals
Harden the runtime path lease system so mutating tools cannot silently proceed without a lease when coordination is enabled.

### Key Changes
- `rig_relay/coordination/lease_manager.py`: Changed `LeaseStatusValue` from `str` subclass to `StrEnum`; added `DEFAULT_LEASE_TTL_SECONDS = 120`
- `rig_relay/runtime/context.py`: Added `coordination_enabled: bool = True` to `RuntimeContext`
- `rig_relay/runtime/tool_invocation_adapter.py`: Added `coordination_enabled` and `lease_ttl_seconds` to `RuntimeToolInvocationEnvelope`
- `rig_relay/runtime/tool_invocation_execution.py`: Refactored `_claim_mutation_lease` → `_LeaseClaimOutcome` dataclass; added `_release_mutation_lease` with try/finally around search_replace/write_file
- `docs/schemas/rig.relay.runtime_tool_invocation.v1.schema.json`: Added new fields
- `tests/runtime/test_runtime_lease_acquisition.py`: 10 new tests

### Design Decisions
- `coordination_enabled` defaults to `True` for backward compatibility
- TTL configurable via envelope, defaults to 120s
- Lease release is best-effort (failures silently ignored)
- `_resolve_coordination_root` priority: worktree_path → repo_root → cwd

### Validation
- **80/80** tests (22 lease + 48 execution + 10 acquisition), pyright, ruff, schema validation

---

## Mission 2 — Fleet Patch Proposal Phase 0

### Goals
Implement the minimal PatchProposal artifact workflow — agents propose, orchestrator disposes.

### Key Changes
- `rig_relay/coordination/patch_proposal.py`: New module (196 lines) with `PatchProposal`, `PatchProposalArtifactRef`, `PatchDecision`, `compute_proposal_fingerprint`, `CreateProposalResult`
- `rig_relay/coordination/fleet_models.py`: Re-exports from `patch_proposal`
- `rig_relay/coordination/models.py`: Extended `__all__` with new model names
- `docs/schemas/rig.fleet.patch_proposal.v1.schema.json` (108 lines) + `docs/schemas/rig.fleet.patch_decision.v1.schema.json` (55 lines): Full JSON Schema with `additionalProperties: false`
- `tests/coordination/test_patch_proposal.py`: 27 tests covering validation, artifact ref, decision, fingerprint, content-light, schema validation
- `docs/governance/fleet-coordination-plane.md`: Added §10

### Design Decisions
- Five proposal statuses: `pending`, `accepted`, `rejected`, `needs_revision`, `superseded`
- `compute_proposal_fingerprint` excludes `proposal_id` and `schema_version`
- `expected_before_sha256` is `dict[str, str]` mapping path→hash
- Content-light: tests check for key presence, not raw content

### Validation
- **31/31** patch proposal tests, pyright, schema validation

---

## Mission 3 — Fleet Coordination Test Closure

### Goals
Resolve or isolate all coordination test failures without adding new fleet features.

### Key Changes
- `tests/coordination/test_queue_plan.py`: Fixed `NameError: name 'tmp_path' is not defined` by adding `tmp_path: Path` parameter

### Validation
- **437/437** passed (was 413); runtime **367/367**; schemas **110/110**

### Resolved
- "465/465 but 17 failures" contradiction: the 17 failures were in `test_fleet_projection.py` (dirty state during Mission 4), fixed in Mission 5

---

## Mission 4 — Fleet Queue Runner Phase 0

### Goals
Implement minimal queue runner that executes one runnable item at a time through existing `runtime_exec`, with event-sourced state transitions and content-light boundaries.

### Key Changes
- `rig_relay/coordination/fleet_queue_runner.py`: New module (245 lines) with `FleetQueueRunner`, `FleetQueueRunnerConfig`, `FleetQueueRunnerResult`
- `docs/schemas/rig.fleet.queue_runner_result.v1.schema.json`: Uses `oneOf` for nullable patterned fields
- `tests/coordination/test_fleet_queue_runner.py`: 26 tests

### Item Routing
- validate → `execute_validate()`
- runtime_exec → `execute_runtime_exec()` (governed path)
- message/handoff_note → immediate completion
- pause/resume → no-op (completes)
- unsupported → blocked

### Design Decisions
- One item per call (no looping)
- State transitions: running→completed/failed/blocked (event-sourced via queue.mark_*)
- Minimal `RuntimeContext` with `coordination_enabled=False`
- `FleetQueueRunnerResult` carries only metadata fields, no raw content
- Schema uses `oneOf: [{"type": "string"}, {"type": "null"}]` for nullable fields

### Validation
- **26/26** runner tests, **67/67** fleet queue tests, **12/12** runtime exec orchestrator, **482/482** coordination suite, **111/111** schemas

---

## Mission 5 — Fleet Projection Phase 0 Closure

### Goals
Close the Fleet Projection / TUI Read Model Phase 0 slice by resolving test ambiguity, validating schemas, updating docs, wiring queue/proposal summaries.

### Key Changes
- `tests/coordination/test_fleet_projection.py`: Added `test_model_dump_validates_without_exclude_none` (44 tests total)
- `tests/cli/textual_ui/rig_console/test_fleet_panel.py`: Added `TestMountedFleetPanel` with 2 mounted Textual tests (24 tests total)
- `vibe/cli/textual_ui/rig_console/providers.py`: Fixed pre-existing `IndentationError` (duplicate import block); added missing `QueueRunnerBridge` import

### Verification
- Schema validates `model_dump(mode="json")` without `exclude_none=True` ✅
- `FleetProjection` uses `additionalProperties: false` in all sub-models ✅
- Queue summaries wired through `build_queue_summary_from_snapshot()` ✅
- Patch proposal summaries wired through `build_patch_proposal_summary()` ✅
- Empty-safe defaults for missing roots/files ✅

### Validation
- Projection tests: **44/44** passed
- Fleet panel tests: **24/24** passed
- Full coordination suite: **483/483** passed
- Schema validation: **111/111** passed
- ruff format/check, pyright: ✅

---

## Files Changed Across All Missions

### New Files
- `rig_relay/coordination/patch_proposal.py`
- `rig_relay/coordination/fleet_queue_runner.py`
- `tests/coordination/test_patch_proposal.py`
- `tests/coordination/test_fleet_queue_runner.py`
- `tests/runtime/test_runtime_lease_acquisition.py`
- `docs/schemas/rig.fleet.patch_proposal.v1.schema.json`
- `docs/schemas/rig.fleet.patch_decision.v1.schema.json`
- `docs/schemas/rig.fleet.queue_runner_result.v1.schema.json`

### Modified Clean Files
- `rig_relay/runtime/context.py`
- `rig_relay/runtime/tool_invocation_adapter.py`
- `rig_relay/coordination/fleet_models.py`
- `tests/coordination/test_queue_plan.py`

### Modified Dirty Files (preserved existing edits)
- `rig_relay/coordination/lease_manager.py`
- `rig_relay/runtime/tool_invocation_execution.py`
- `rig_relay/coordination/models.py`
- `vibe/cli/textual_ui/rig_console/providers.py`
- `tests/coordination/test_fleet_projection.py`
- `tests/cli/textual_ui/rig_console/test_fleet_panel.py`
- `docs/governance/fleet-coordination-plane.md`
- `docs/schemas/rig.relay.runtime_tool_invocation.v1.schema.json`
- `docs/governance/runtime-tool-invocation-execution.md`

### Pre-existing Dirty Files (not modified by these missions)
- `docs/governance/textual-rig-console.md`
- `docs/schemas/rig.fleet.projection.v1.schema.json`
- `rig_relay/coordination/fleet_projection.py`
- Various TUI widget files in `vibe/cli/textual_ui/rig_console/`

---

## Key Design Principles Applied

1. **Content-light**: No raw diffs, patches, file contents, stdout, stderr, or secrets in events or result models
2. **Agents propose; orchestrator disposes**: Patch proposals separate proposal from application
3. **Event-sourced state transitions**: Queue runner transitions are recorded as events, not in-place mutations
4. **Empty-safe defaults**: All projection models handle missing roots/files gracefully
5. **Schema-first**: All new models have corresponding JSON Schema with `additionalProperties: false`
6. **Governed mutation paths**: Runtime exec goes through `RuntimeToolExecutionRunner` with lease checks

---

## Out-of-scope Findings Recorded

None during these missions — all changes were in-scope for the five missions.

---

## Continuation Points

Future work (not started):
- Patch application workflow (post-Phase 0)
- Full scheduler (supervisor dispatch loop)
- Supervisor projection integration
- TUI queue panel execution controls
- DuckDB indexing for fleet events
- Scheduler retry/recovery policies
