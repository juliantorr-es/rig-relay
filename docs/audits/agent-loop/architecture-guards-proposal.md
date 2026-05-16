# Architecture guard tests — proposed (not implemented)

Proposed date: 2026-05-15

## When to implement

After SubagentRuntime exists and AgentLoop is renamed to OrchestratorLoop.

## Guard tests

| # | Test | Assertion | Risk |
|---|---|---|---|
| 1 | `test_ralph_cannot_instantiate_agent_loop` | Ralph modules import none of `AgentLoop`, `OrchestratorLoop`, `VibeAcpAgentLoop` | Low — Ralph is already observe-only |
| 2 | `test_subagent_profile_uses_subagent_runtime` | Assignable `SubagentProfile` constructs via `SubagentRuntime`, not full `AgentLoop` | High — currently `task.py` spawns full AgentLoop |
| 3 | `test_only_orchestrator_calls_conversation_loop` | `_conversation_loop` is called only from `OrchestratorLoop` (formerly AgentLoop) | Medium — desktop and ACP both call it |
| 4 | `test_tool_runtime_is_only_tool_execution_path` | All tool execution goes through `ToolRuntime.execute_one()` — no bypass | Low — already true |
| 5 | `test_runtime_supervisor_is_only_subprocess_authority` | All subprocess creation goes through `RuntimeSupervisor` — no raw `subprocess.run()` | Medium — bash tool and validate runner both use it |
| 6 | `test_ralph_never_constructs_toolruntime_or_agent` | Ralph modules import no tool execution or agent infrastructure | Low — already observe-only |

## Implementation notes

- Tests 1, 2, 3, and 6 can use AST-based import scanning (like existing `test_architecture_boundaries.py`)
- Tests 4 and 5 need runtime/monkeypatch verification
- All tests are `pytest.mark.xfail` until SubagentRuntime exists
