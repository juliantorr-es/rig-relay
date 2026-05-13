Before doing anything, read AGENTS.md and summarize the Git discipline rules you will follow. Do not edit files until you have done that.

Mission: Built-In Tool Refinement Packet Mission
Goal:
Turn the ranked built-in refinement backlog item for `coordination` into a bounded implementation mission packet.
Context:
- source_item_id: refine_406d97c0abd2
- tool_name: coordination
- refinement_kind: add_coordination_hook
- priority: P0
- confidence: 0.85
- evidence_window: latest derived datasets present in .build/rig-relay/derived

Non-goals:
- Do not implement new built-in tools.
- Do not change provider behavior.
- Do not change tool behavior.
- Do not delete or compact artifacts.
- Do not upload anything.

Required files to inspect:
- AGENTS.md
- scripts/rig_relay_builtin_tool_refinement.py
- docs/schemas/rig.relay.builtin_tool_refinement_item.v1.schema.json
- docs/schemas/rig.relay.mission_packet.v1.schema.json
- docs/governance/reviewer-orchestrator.md
- docs/governance/delegate-fleet-orchestration.md
- docs/governance/usage-data-doctrine.md
- .build/rig-relay/derived/builtin_tool_refinement_backlog.jsonl
- .build/rig-relay/reports/built-in-tool-refinement.md

Implementation requirements:
- Create a bounded mission packet for the reviewer/orchestrator loop.
- Keep the packet content-light.
- Include allowed files or path hints only when inferable.
- Include recommended validation commands.
- Include final report requirements.

Tests:
- Add focused tests for packet generation and validation.

Validation:
- Run schema validation and the focused packet tests.

Final report requirements:
- Include branch and HEAD before/after.
- Include dirty files before/after.
- Include files changed.
- Include generated packet paths.