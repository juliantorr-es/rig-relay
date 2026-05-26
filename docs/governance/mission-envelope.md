# Mission Envelope

The mission envelope is the minimal executable bridge object between governance intent and agent runtime context.

It exists so the harness can run a governed mission without requiring a full ADR → Sprint → Mission orchestration tree in the executable path.

## Purpose

- Provide a concrete runtime object for a single mission run.
- Carry the minimum stable metadata needed for context packet compilation.
- Keep ADR and sprint information optional until the orchestration hierarchy is fully executable.

## Core Fields

- `mission_id`
- `title`
- optional `adr_id`
- optional `sprint_id`
- `repo_root`
- `branch`
- `head`
- `dirty_status_fingerprint` or `dirty_file_summary`
- `allowed_paths`
- `protected_paths`
- `instruction_paths`
- `acceptance_checks`
- `handoff_required`
- `created_at`
- `schema_version`

## Release Boundary Contract

Every mission envelope MUST also declare:

- `released_boundary`
- `stated_consumer_purpose`
- `deferred_seams`
- `blocking_defects`
- `freeze_status`

The envelope MUST distinguish a narrow released boundary from broader future integration work. Deferred upstream, downstream, UI, transport, or cross-lane work does not keep the mission open unless it makes the declared boundary unsafe or false.

## Governance Reference

The envelope may carry optional governance metadata:

```json
{
  "governance_ref": {
    "adr_id": null,
    "sprint_id": null,
    "mission_id": "mission-..."
  }
}
```

The key rule is that mission-only mode must work now, and ADR/sprint metadata can be attached later without changing `mission_id`.

## Design Rules

- The envelope must be deterministic to serialize.
- The envelope must reject unknown fields.
- The envelope must not contain raw file bodies, raw prompts, raw stdout/stderr, or secrets.
- The envelope should compile from existing state: AGENTS.md, git status, branch/HEAD, dirty inventory, mission prompt, path policy, validation commands, and optional handoff text.
- Receipts should come before retrieval. Reproducibility first, intelligence later.

## Bridge Relationship

This envelope is the bridge between:

- current task execution
- runtime context resolution
- future ADR/Sprint/Mission orchestration

It is intentionally smaller than the full governance hierarchy.

Executable contract:
- `rig_relay.governance.mission_envelope.MissionEnvelope`
- `docs/schemas/rig.mission_envelope.v1.schema.json`

See also:
- `rig_relay.governance.mission_context_packet.MissionContextPacket`
- `docs/governance/mission-context-packets.md`
