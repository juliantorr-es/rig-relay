# Coordination Migration Inventory

This inventory maps the coordination seam that started in `vibe.core.coordination`
and now lives in `rig_relay.coordination.models`, `rig_relay.coordination.store`,
and the Relay-native coordination tool execution helpers. `vibe.core.coordination`
remains a compatibility adapter during alpha. The planning slice is inventory-first:
no event-name changes, no schema changes, no payload behavior changes, and no
circular imports from `rig_relay` back into `vibe`.

## Status

**Slice B complete (2026-05-13).** All three Relay-native modules are live:

- `rig_relay/coordination/_canonical_json.py` — stdlib-only JSON helper
- `rig_relay/coordination/models.py` — full implementation, 10 Pydantic model classes
- `rig_relay/coordination/store.py` — full implementation, `CoordinationStore` dataclass

`vibe.core.coordination._models`, `vibe.core.coordination._store`, and
`vibe.core.coordination.__init__` are compatibility adapters. All 64 coordination
tests pass through the Relay-native modules. No schema changes, no event-name
changes, no circular imports.

**Next:** Coordination tool surface (`vibe.core.tools.builtins.coordination`→`rig_relay.coordination.tool`) — deferred by user.

## Current `vibe.core.coordination` Surface

### `vibe/core/coordination/_models.py`

- Legacy compatibility adapter re-exporting the Relay-native coordination models.
- Existing imports still resolve for sessions, claims, reservations, conflicts,
  artifact references, state projections, event envelopes, payload builders,
  and hash helpers.

### `vibe/core/coordination/_store.py`

- Legacy compatibility adapter re-exporting the Relay-native file-backed store.
- Session registration, heartbeat, task claim, path reservation, artifact
  publication, conflict reporting, release, handoff, stale-lease, and
  checkpoint-facing store flows continue to work unchanged.
- Reads and writes coordination state under `.build/rig-relay/coordination/`.

### `vibe/core/coordination/__init__.py`

- Re-exports the public coordination models and store for current callers.
- Acts as the compatibility import surface for legacy `vibe.*` code.
- This module now points at Relay-owned coordination modules.

## Public API Summary

### Classes

- `CoordinationSession`
- `CoordinationHeartbeat`
- `CoordinationTaskClaim`
- `CoordinationPathReservation`
- `CoordinationArtifactRef`
- `CoordinationConflict`
- `CoordinationClaimResult`
- `CoordinationReservationResult`
- `CoordinationStateProjection`
- `CoordinationEvent`
- `CoordinationStore`

### Functions

- `salted_path_hash`
- `reset_path_salt_for_testing`
- `stable_path_key`
- `normalize_path`
- `now_plus`
- `build_session_registered_payload`
- `build_heartbeat_payload`
- `build_task_claim_payload`
- `build_task_released_payload`
- `build_path_reserved_payload`
- `build_path_released_payload`
- `build_reservation_refused_payload`
- `build_artifact_published_payload`
- `build_conflict_reported_payload`
- `build_handoff_requested_payload`
- `build_handoff_accepted_payload`
- `build_handoff_rejected_payload`
- `build_projection_read_payload`
- `build_lease_expired_payload`
- `build_lease_marked_stale_payload`
- `build_checkpoint_committed_payload`
- `build_checkpoint_refused_payload`

## Current Import Sites

- `vibe/core/tools/builtins/coordination.py`
- `vibe/core/tools/builtins/task.py`
- `vibe/core/tools/builtins/write_file.py`
- `vibe/core/tools/builtins/search_replace.py`
- `vibe/core/tools/builtins/checkpoint.py`
- `rig_relay/coordination/current_state.py`
- `rig_relay/coordination/cleanup_leases.py`
- `rig_relay/evidence/storage_lifecycle.py`

## Tests Covering Coordination

- `tests/coordination/`
- `tests/coordination/test_current_state.py`
- `tests/scripts/test_storage_lifecycle.py`

## Runtime Dependencies

- `rig_relay/coordination/current_state.py` reads coordination sessions,
  leases, events, and derived storage summaries.
- `rig_relay/coordination/cleanup_leases.py` scans lease files for stale and
  expired entries.
- `rig_relay/evidence/storage_lifecycle.py` exposes the storage summary used
  by current_state and fleet preflight.
- Tool builtins use the coordination store for claims, reservations, artifact
  publication, and conflict reporting.

## Generated Artifact Locations

- `.build/rig-relay/coordination/events.jsonl`
- `.build/rig-relay/coordination/sessions/*.json`
- `.build/rig-relay/coordination/leases/paths/*.json`
- `.build/rig-relay/coordination/artifacts/*.json`
- `.build/rig-relay/coordination/conflicts/*.json`
- `.build/rig-relay/refinement-packets/P0-coordination-add_coordination_hook/mission_packet.json`

## Event Names Emitted

- `coord.session.registered`
- `coord.session.heartbeat`
- `coord.task.claimed`
- `coord.task.released`
- `coord.path.reserved`
- `coord.path.released`
- `coord.path.reservation_refused`
- `coord.artifact.published`
- `coord.conflict.reported`
- `coord.lease.marked_stale`
- `coord.session.handoff_requested`

## Schema Dependencies

- `docs/schemas/rig.relay.cross_session_coordination.v1.schema.json`
- `docs/schemas/rig.relay.coordination_conflict.v1.schema.json`
- `docs/schemas/rig.relay.artifact_reuse.v1.schema.json`
- `docs/schemas/rig.relay.checkpoint_eval.v1.schema.json`
- `docs/schemas/rig.relay.current_state.v1.schema.json`
- `docs/schemas/rig.relay.mission_packet.v1.schema.json`

## Migration Risk

- High. Coordination is load-bearing for claims, path reservations, task
  release, artifact publication, checkpoint metadata, current_state, storage
  preflight, and delegate/fleet readiness.
- The safe path is inventory-first, then move the models and store, then
  convert `vibe.core.coordination` into compatibility adapters.

## Target Relay-Native Boundary

### `rig_relay.coordination.models`

- `CoordinationSession`
- `CoordinationTaskClaim`
- `CoordinationPathReservation`
- `CoordinationArtifactRef`
- event envelopes and typed payload builders

### `rig_relay.coordination.store`

- `CoordinationStore`
- file-backed store implementation

### `rig_relay.coordination.events`

- coordination event names
- envelope/hash helpers if currently embedded in model/store files

### `rig_relay.coordination.tool`

- Relay-native coordination action executor
- helper surface for the built-in coordination tool

## Adapter Strategy

1. Move implementation into `rig_relay.coordination.*`.
2. Convert `vibe.core.coordination.*` into compatibility adapters/re-exports.
3. Update product-facing imports to Relay-native modules where safe.
4. Preserve legacy imports during alpha for runtime and tool callers.
5. Prevent circular imports from `rig_relay` back into `vibe`.

## Dataset-Backed Motivation

- Refinement item: `refine_406d97c0abd2`
- Priority: `P0`
- Tool name: `coordination`
- Refinement kind: `add_coordination_hook`
- Packet: `.build/rig-relay/refinement-packets/P0-coordination-add_coordination_hook/mission_packet.json`

Coordination migration should precede delegate/fleet and broader Intent API
execution because the store is the shared boundary for claims, leases,
conflicts, and current-state readiness.

The tool layer is now partially Relay-owned: `rig_relay.coordination.tool`
owns the action executor while `vibe.core.tools.builtins.coordination` remains
the registry-compatible adapter. Full tool registry migration is still deferred.

## Planning-Slice Rules

- No event-name changes in this slice.
- No schema changes in this slice.
- No payload behavior changes in this slice.
- No circular imports from `rig_relay` to `vibe`.
