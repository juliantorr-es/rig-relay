# Agent Loop Boundary

The AgentLoop class (`rig_relay/core/agent_loop.py`) is the turn/session **conductor**, not the runtime kernel. It owns the topology of a conversation: start session, start turn, get context, call model, delegate tools, continue or finish, save state, emit lifecycle events. Policy for each subsystem lives outside AgentLoop.

## Runtime components

| Component | Location | Owns |
|---|---|---|
| **AgentLoop** | `rig_relay/core/agent_loop.py` | Turn/session topology, public API (`act()`, `fork()`, `compact()`, `clear_history()`). Coordinates other runtimes. |
| **AgentRuntimeState** | `rig_relay/core/runtime_state.py` | Mutable session/turn state snapshot. Readiness, stats, limits, session identity. Serializable for debug and durable execution. |
| **ConversationTurnRuntime** | `rig_relay/core/conversation_turn.py` | One-turn phase state machine. Phase transitions, outcome, tool batch metadata. Does not execute LLM or tool calls. |
| **ConversationRuntime** | `rig_relay/core/conversation_runtime/` | Turn phase event recorder, result builder, **trace evidence emitter** (`PhaseTraceHook`), and **loop decision policy** (`ConversationLoopDecision` — Phase 2A). Observes the conversation loop and owns terminal outcome classification. Owns the phase event log and builds JSON-safe `ConversationRuntimeResult`. Accepts optional `PhaseTraceHook` for structured trace consumers. |
| **LLMCallMixin** | `rig_relay/core/_llm_call.py` | Provider call preparation, streaming and non-streaming calls, retry/error classification. |
| **ToolResponseMixin** | `rig_relay/core/_tool_response.py` | Tool response recording, telemetry, failure event construction. |
| **SessionLifecycleMixin** | `rig_relay/core/_session_lifecycle.py` | Message history cleanup, missing response filling, session reset, fork message extraction. |
| **GovernanceMixin** | `rig_relay/core/_governance.py` | Approval callbacks, tool permissions, session rules. |
| **TelemetryMixin** | `rig_relay/core/_telemetry.py` | Session lifecycle telemetry emission, context observation. |
| **ContextEnvelopeMixin** | `rig_relay/core/_context_envelope.py` | Context envelope construction and assembly telemetry. |
| **MiddlewareMetadataMixin** | `rig_relay/core/_middleware_metadata.py` | Middleware pipeline setup, result handling, backend metadata. |

## Future runtimes (planned, not yet extracted)

| Component | Future location | Will own |
|---|---|---|
| **SessionRuntime** | `rig_relay/core/session_runtime.py` | Fork, compact, reset, clear_history, switch_agent, reload_with_initial_messages. |
| **ApprovalRuntime** | `rig_relay/core/approval_runtime.py` | Approval handoff, callbacks, permission rules. |
| **MissionEnvelopeBridge** | `rig_relay/core/mission_envelope.py` | Mission metadata → AgentLoop context/runtime wiring. |

## Dependency boundaries (enforced)

These must not be imported by **AgentLoop** or any mixin in `rig_relay/core/`:

| Forbidden import | Reason |
|---|---|
| `rig_relay.desktop.*` | Desktop is a consumer of projections/intents, not runtime policy. |
| `rig_relay.ralph.*` | Ralph is an observe-only scanner that consumes projections. |
| `rig_relay.scripts.*` | Scripts are CLI entry points, not runtime policy. |
| `rig_relay.analytics.*` | Analytics compiler consumes events/ledgers, must not execute runtime work. |
| `rig_relay.reports.query` | Report query is a consumer, not runtime policy. |
| `rig_relay.bash.query` | Bash analytics is a consumer, not runtime policy. |
| `duckdb` | DuckDB is the analytical compiler substrate. Runtime must not depend on it. |

## Allowed dependency direction

```
Desktop / Ralph / Scripts (outer)
        │
        │ consume projections, intents, events
        ▼
AgentLoop + Runtimes (inner)
        │
        │ use
        ▼
Tools, Config, LLM Backends, Context Compiler (inner)
```

Inner runtime policy must not know outer mechanisms. Desktop, Ralph, and scripts are outer consumers. They import from core; core never imports from them.

## How to add a new runtime component

1. Create the module in `rig_relay/core/` (e.g., `tool_runtime.py`).
2. Add it as a mixin or standalone class depending on coupling.
3. Wire it into AgentLoop through composition or MRO.
4. Add to the table above.
5. Add an architecture test confirming the dependency boundary.
6. Never import desktop, Ralph, scripts, analytics, or DuckDB from the new component.

## Smell tests

A method belongs outside AgentLoop if:

- It can be tested without constructing a full AgentLoop.
- Changing its subsystem policy currently requires editing AgentLoop.
- It spends most of its code using attributes from a single domain (tools, sessions, telemetry, context).

AgentLoop methods that survive extraction should:

- Read as coordination (start → do → check → continue/finish → save).
- Delegate domain work to dedicated runtimes.
- Not know how each subsystem works internally.
