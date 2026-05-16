# Orchestrator Loop Boundary

Defines ownership doctrine for Rig Relay runtimes: who may run a full
turn loop, and which runtime components own what.

## Principle 1 — Only an owner may run a full turn loop

An **owner** is an entity that:
- Faces the user (directly or through an adapter)
- Owns the session
- Decides delegation/handoff/approval/disposition
- Synthesizes final answers
- Controls merge/push

Owners: desktop cockpit, ACP server, IDE sidecar.
Subagents, Ralph, and test fixtures are NOT owners.

## Principle 2 — OrchestratorLoop

The `OrchestratorLoop` (currently AgentLoop) owns:

| Domain | Methods |
|---|---|
| User-facing turn orchestration | `act()`, user message intake |
| Model call sequence | `_perform_llm_turn()` |
| Tool-call planning | `_handle_tool_calls()` |
| Delegation/handoff decisions | `fork()`, subagent spawn |
| Approval boundaries | `_should_execute_tool()`, `_ask_approval()` |
| Mission assignment | (currently in task.py; future: `MissionAssignment`) |
| Final synthesis | `_conversation_loop()` result |

## Principle 3 — ConversationRuntime

`ConversationRuntime` owns:

| Domain | Methods |
|---|---|
| Turn phase state | `_phase()`, `_finish()` |
| Loop decision policy | `decide_after_middleware()`, `decide_after_model_turn()`, `decide_after_hook_processing()`, `decide_after_tool_batch()`, `decide_after_budget_check()` |
| Outcome classification | `_finish_decision()` |
| Trace/phase evidence | `PhaseTraceHook`, `PhaseTraceAttributes` |
| JSON-safe result | `build_result()` |

## Principle 4 — SubagentRuntime (IMPLEMENTED v1)

`SubagentRuntime` (`rig_relay/core/subagents/runtime.py`) owns:

| Domain |
|---|
| Bounded mission execution |
| Lifecycle evidence emission via `TraceRecorder` |
| Explicit `tool_execution_mode` marker (currently `"legacy_direct"`) |
| Structured `SubagentResult` with metadata |
| Assigned lane/worktree |
| Allowed tools/profile/model binding |
| Budget (turns, price, time) |
| Expected artifact contract |
| Validation receipt |
| Patch proposal or report output |

SubagentRuntime explicitly does NOT own:

| Not owned | Reason |
|---|---|
| Global session history | Scoped to mission |
| Final user-facing answer | Synthesized by owner |
| Global approval policy | Inherited from owner |
| Unbounded tool loops | Budget-enforced |
| Merge/push | Orchestrator-only |
| Switch_agent / compact / fork | Bounded lifecycle |

## Principle 5 — RalphRuntime (planned, uses SubagentRuntime)

`RalphRuntime` will use `SubagentRuntime` with
`profile_kind=AUTONOMOUS_BACKGROUND` and `trust_tier=OBSERVE`.

| Domain |
|---|
| Background observation (read-only) |
| Report generation |
| Proposal output |
| No normal assignable missions |
| No merge/push |

## Principle 6 — ToolRuntime

`ToolRuntime` owns governed tool execution. It is NOT a loop owner.
See `docs/governance/tool-runtime-boundary.md`.

## Principle 7 — Handoff receipt

Ownership transfer (e.g., orchestrator → subagent) requires a handoff:

| Field | Description |
|---|---|
| `owner_before` | Session/agent ID of delegator |
| `owner_after` | Session/agent ID of subagent |
| `reason` | Why the handoff is needed |
| `scope` | What the subagent may do |
| `budget` | Turns, price, time limits |
| `return_condition` | When ownership returns |
| `trace_id` | For observability correlation |

## Phase 3 recommendation

Phase 3 should:

1. **Move the while-loop** into `ConversationRuntime.execute_turn()` —
   making `OrchestratorLoop` a thin adapter.
2. **Not** create full AgentLoops for subagents — build `SubagentRuntime`
   as a separate bounded class.
3. **Not** give Ralph any loop ownership — it uses `SubagentRuntime`
   with `profile_kind=AUTONOMOUS_BACKGROUND`.
4. AgentLoop should be renamed to `OrchestratorLoop` only after
   SubagentRuntime exists to prevent confusion.
