# Phase 4 Architecture Map — Orchestrator Shell Hardening and Turn Evidence Envelope v1

Analysis date: 2026-05-16
Inspected HEAD: c5a31bbe
Status: Phase 3 TRANSFERRED_WITH_GAPS (1 stub remains)

## Phase 3 Residual Inventory — What Still Lives in AgentLoop

| Responsibility | Classification | ~Lines | Phase 4 Move? |
|---|---|---|---|
| `_perform_llm_turn()` — LLM call + streaming | adapter/capability | 786-870 | Keep in adapter |
| `_execute_tool_call()` — tool execution via ToolRuntime | adapter via ToolRuntime | 956-1130 | Keep in adapter |
| `_handle_tool_calls()` — tool batch orchestration | adapter via ToolRuntime | 1132-1200 | Keep in adapter |
| `_run_tools_concurrently()` — concurrent execution queue | adapter | 1164-1207 | Keep in adapter |
| `_build_loop_adapter()` — adapter factory | adapter boundary | 746-748 | Formalize |
| `_ConversationLoopAdapter` — all methods except `execute_tool_batch()` | adapter | 1495-1584 | Finish `execute_tool_batch()`, then freeze |
| `_should_execute_tool()` / `_ask_approval()` — governance | adapter | 1245-1279 | Keep; future: move to GovernanceRuntime |
| `fork()` — session fork and handoff | adapter | 1281-1316 | Keep; future: HandoffReceipt |
| `_get_conversation_runtime()` — CR factory | adapter | 644-647 | Keep |
| `_get_tool_runtime()` — ToolRuntime factory with closures | adapter/bridge | 362-578 | Extract closure factory; keep in adapter |
| `tool_manager` / `config` / `messages` / `stats` — state | adapter state | class attrs | Keep in adapter |
| `act()` — entry point + telemetry + cleanup | adapter | 649-674 | Keep; rename to `orchestrate()`? |
| `compact()` / `clear_history()` / `switch_agent()` — session ops | adapter | 1344-1421 | Keep |
| `_save_messages()` — persistence | adapter | 630-638 | Keep |
| `_build_context_envelope()` — context assembly | adapter → future move | elsewhere | Move to ContextAssemblyPlan v1 (Phase 5) |
| `_create_connector_registry()` — external connectors | adapter | 597-612 | Keep; future: ProviderArbitration |
| `teleport_service` / `teleport_to_vibe_code()` — external | adapter | 676-740 | Keep |

### Key insight

After Phase 3, AgentLoop is already a clean adapter shell — ~19 class-level methods, 1 inner adapter class. The `execute_tool_batch()` stub is the only Phase 3 gap. Beyond that, AgentLoop is an **orchestrator**: it bridges user-facing I/O, provider/model backend, ToolRuntime effects, session persistence, and ConversationRuntime loop policy.

The rename to `OrchestratorLoop` is a one-liner alias. The hardening work is strengthening boundaries and evidence, not moving code.

## Phase 4 Objective — Chosen

**Phase 4 — Orchestrator Shell Hardening and Turn Evidence Envelope v1**

Three tightly-coupled goals:

| Goal | Meaning |
|---|---|
| **4A — OrchestratorLoop shell contract** | AgentLoop → OrchestratorLoop alias/rename; adapter protocol formalized; no-loop-regrowth guards |
| **4B — ConversationRuntime Turn Envelope v1** | Canonical turn result model with hashes, trace_ids, safe summaries — the turn becomes a first-class evidence artifact |
| **4C — HandoffReceipt v1** | `fork()` / subagent spawn produce transfer receipts: owner_before/after, scope, budget, return_condition, trace_id |

These three goals form one convergent phase because they're all about making the orchestrator boundary formal, provable, and evidence-backed. They don't require moving any major code — they require hardening what's already there.

## Alternatives Considered

| Candidate | Rejected/Deferred Because |
|---|---|
| Orchestrator rename only | Thin — 4A alone would be a renamed AgentLoop with no new evidence. Combine with 4B+4C for a meaningful convergence. |
| ContextAssemblyPlan v1 | Major new subsystem (context compiler, task-aware sections, symbol indexing). Needs its own phase (Phase 5) after shell hardening. |
| ProviderArbitration v1 | Model/provider routing is stable enough. Evidence/ownership hardening should come first. |
| Projection/Evidence UI v1 | Desktop frontend work — orthogonal. Defer to Phase 4D after shell hardening. |
| Multi-agent lane governance | Ralph + subagent orchestration rules. Needs handoff receipts first. Defer to Phase 6. |

## Entry Gates — Required Before Phase 4

| Gate | Current |
|---|---|
| Phase 3 PHASE_3_COMPLETE | ❌ TRANSFERRED_WITH_GAPS — `execute_tool_batch()` stub |
| collect-only green | ✅ 6391 tests, 0 errors |
| demo-doctor green | ✅ 22/22 |
| no silent legacy direct | ✅ guarded |
| desktop correlation | ✅ integrated |
| ToolRuntime envelope | ✅ fields exist |
| ConversationRuntime loop ownership | ✅ guarded |
| 29/29 parity tests | ✅ all pass |

## Exit Gates — Definition of Done

| Gate | Feature |
|---|---|
| **Shell boundary** | `AgentLoop` aliased to `OrchestratorLoop`; outer-facing name uses `Orchestrator` consistently. Internal class may remain `AgentLoop` with alias. |
| **No loop regrowth** | AST guards + architecture test: `_while True_` or `while not should_break_loop` does not appear in AgentLoop/Orchestrator; loop lives only in ConversationRuntime. |
| **Adapter protocol** | `ConversationRuntimeCallbacks` protocol is the only adapter interface; no undocumented private access from CR back into AgentLoop. |
| **Turn envelope schema** | `TurnEvidenceEnvelope` model with: `turn_id`, `trace_id`, `outcome`, `phase_count`, `tool_call_count`, `tool_success_count`, `tool_failure_count`, `tool_refusal_count`, `budget_decision`, `duration_ms`, `summary_hash` |
| **Turn envelope emitted** | `build_result()` produces envelope; envelope linked to trace span |
| **Turn envelope has no raw content** | No stdout/stderr, raw args, task text, secrets, or full LLM output |
| **HandoffReceipt model** | `HandoffReceipt` with: `owner_before`, `owner_after`, `scope`, `budget.max_turns`, `budget.max_tool_calls`, `return_condition`, `trace_id`, `timestamp`, `reason` |
| **HandoffReceipt emitted** | `fork()` and `task.py` SubagentRuntime construction produce handoff receipts |
| **collect-only** | green |
| **demo-doctor** | green |
| **Phase 4 guard tests** | pass |

## Implementation Slices

| Slice | Scope | Dependencies |
|---|---|---|
| **Phase 4A — OrchestratorLoop Shell Contract** | AgentLoop alias to OrchestratorLoop; adapter protocol formalization; anti-loop-regrowth AST guards | Phase 3 COMPLETE |
| **Phase 4B — ConversationRuntime Turn Envelope v1** | `TurnEvidenceEnvelope` model; `build_result()` enriched; trace span linking; privacy-safe attributes | 4A (for adapter protocol stability) |
| **Phase 4C — HandoffReceipt v1** | `HandoffReceipt` model; emission in `fork()` and `task.py`; trace_id propagation through SubagentRuntime | 4B (for envelope pattern) |
| **Phase 4D — AgentLoop → OrchestratorLoop rename** | Internal rename; alias preserved for backward compat; docs updated; import paths stable | 4A+4B+4C (don't rename prematurely) |

Sequence: 4A → 4B → 4C → 4D. Each slice builds on the previous without major refactors.

## Risk Map

| Risk | Severity | Mitigation |
|---|---|---|
| **Rename breaks imports** | Medium | Alias `AgentLoop` as `OrchestratorLoop` first; remove old name in Phase 4D only after all callers use new name |
| **Turn envelope grows too large** | Low | Content-light fields only: hashes, counts, trace_ids. No raw content. |
| **Handoff receipt adds friction** | Low | Receipts are evidence-only, not blocking. Emission is non-disruptive to existing fork/delegate flows. |
| **Phase 3 gap stalls 4A** | Medium | Phase 4 entry gate requires PHASE_3_COMPLETE. If gap unresolved, Phase 4 does not start. |
| **ContextAssemblyPlan scope creep** | Medium | Explicitly deferred to Phase 5. Context envelope build stays in adapter. |
| **Parallel lane conflicts** | Low | Phase 4 has one clear converged objective. Lane split: A=shell+rename, B=envelope+receipts, C=docs+guards. Known pattern from Phase 3. |

## Tests/Docs Needed

### Tests

| Test file | Purpose |
|---|---|
| `tests/core/test_phase4_shell_guards.py` | AgentLoop has no while-loop; ConversationRuntime has while-loop; adapter protocol is the only interface |
| `tests/core/test_phase4_turn_envelope.py` | TurnEvidenceEnvelope schema; privacy; trace linkage; build_result() compliance |
| `tests/core/test_phase4_handoff_receipt.py` | HandoffReceipt model; fork() emits receipt; task.py emits receipt |
| `tests/core/test_phase4_docs_truth.py` | Docs say PHASE_3_COMPLETE before Phase 4; docs reflect OrchestratorLoop name after rename |

### Docs

| Doc | Update |
|---|---|
| `docs/audits/agent-loop/phase4-architecture-map.md` | This document |
| `docs/audits/agent-loop/phase4-slice-plan.jsonl` | Machine-readable slice plan |
| `docs/governance/orchestrator-loop-boundary.md` | Add TurnEvidenceEnvelope and HandoffReceipt doctrine |
| `docs/audits/runtime/runtime-evidence-spine-v1.md` | Add turn envelope to evidence chain |
| `docs/audits/agent-loop/conversation-runtime-extraction-plan.md` | Mark Phase 4 in progress |

## Recommendation

**First Phase 4 prompt: Phase 4A — OrchestratorLoop Shell Contract**

```
Mission: Phase 4A — OrchestratorLoop Shell Contract.

After Phase 3, AgentLoop is a clean adapter shell delegating the while-loop to ConversationRuntime. Formalize this boundary.

1. Create `AgentLoop` → `OrchestratorLoop` module-level alias in `rig_relay/core/agent_loop.py`.
2. Formalize the `ConversationRuntimeCallbacks` protocol as THE only adapter interface.
3. Add anti-regrowth AST guards: AgentLoop/Orchestrator must not contain `while True` or `while not should_break` loop patterns.
4. Preserve all imports and backward compat.
5. Add docs: `docs/audits/agent-loop/phase4a-shell-contract.md`.
6. Tests: shell boundary guards, no-loop-regrowth, adapter protocol enforcement.
```

This is a 1-slice gate, not a mega-phase. Build the shell first, then the evidence inside it.
