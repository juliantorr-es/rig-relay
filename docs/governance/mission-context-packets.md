# Mission Context Packets

Mission context packets are the deterministic bridge from a mission envelope to the bounded context an agent run should receive.

They are not the canonical governance ledger. Canonical sources remain files:

- `docs/governance/**/*.md`
- `docs/schemas/**/*.json`
- `docs/audits/**/*.jsonl`
- `.rig/work/**/*.jsonl` when present
- receipt stores when present

DuckDB may be used later as a rebuildable analytical index over those files, but the packet itself is compiled from canonical inputs and remains content-light.

## Contract

Executable model:

- `rig_relay.governance.mission_context_packet.MissionContextPacket`
- `rig_relay.governance.mission_context_packet.MissionContextPacketReceipt`
- `rig_relay.governance.mission_context_compiler.MissionContextCompiler`

Schemas:

- `docs/schemas/rig.mission_context_packet.v1.schema.json`
- `docs/schemas/rig.mission_context_packet_receipt.v1.schema.json`

## Design Rules

- Deterministic serialization.
- Strict schema validation.
- Mission-envelope linkage is optional but supported.
- No raw prompts, stdout, stderr, patches, diffs, or secrets.
- Source references are explicit and content-light.
- DuckDB is a cache/index only, never the canonical source of truth.

## Compiler Inputs

- an explicit `MissionEnvelope`
- explicit allow-listed source paths or allow-listed source roots
- optional dirty-file states
- optional required checks

## Compiler Outputs

- `MissionContextPacket`
- `MissionContextPacketReceipt`

The receipt captures packet and mission envelope fingerprints, counts, and the declared index backend.

## Ordering Rules

- source discovery is deterministic
- source refs are emitted in lexicographic path order
- explicit mission-envelope ordering is preserved for the envelope-owned path/check lists

## Runtime Integration

Runtime integration is active. Set ``governed_context_enabled = true`` in
``VibeConfig`` to route context envelope construction through
``compile_governed_context()`` instead of the ad-hoc ``ContextCompiler``
assembly. When enabled, the AgentLoop builds a ``MissionContextPacket``
with governed source refs, dirty-file states, blockers, and warnings.
When disabled, the legacy ad-hoc path is used (backward compatible).

## Relationship To Mission Envelope

The mission envelope supplies the mission identity and immediate runtime boundary.
The context packet compiles the relevant supporting context for that mission from canonical files and safe state summaries.

The packet can exist without higher-order ADR or sprint orchestration.
