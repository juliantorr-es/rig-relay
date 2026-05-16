# AgentLoop Ownership Audit

Audit date: 2026-05-15

## Summary

| Metric | Count |
|---|---|
| AgentLoop construction sites | 8 |
| VibeAcpAgentLoop (subclass) construction sites | 7 |
| PatchedAgentLoop (test subclass) sites | 9 |
| `is_subagent=True` construction | 1 |
| `fork()` constructions | 1 |
| Total unique callers of full AgentLoop | ~16 |

## Complete inventory

| # | Path | Symbol | Purpose | Owner type | Should have full loop? | Recommended boundary | Risk |
|---|---|---|---|---|---|---|---|
| 1 | `rig_relay/cli/desktop_cockpit.py:172` | `self._agent_loop = AgentLoop(...)` | Desktop cockpit owner agent | orchestrator | **Yes** | `OrchestratorLoop` (future) | Low — canonical owner |
| 2 | `rig_relay/acp/_session_lifecycle.py:175` | `agent_loop = AgentLoop(...)` | ACP session creation | orchestrator | **Yes** | `OrchestratorLoop` (future) | Low — ACP entry |
| 3 | `rig_relay/core/agent_loop.py` (fork) | `forked = AgentLoop(...)` | Child session fork | orchestrator copy | **Yes** (inherits owner scope) | `OrchestratorLoop.fork()` | Low — fork creates full loop |
| 4 | `rig_relay/core/tools/builtins/task.py` | `subagent_loop = AgentLoop(... is_subagent=True)` | Spawned subagent for mission | subagent | **No** — should use bounded runtime | `SubagentRuntime` (not yet built) | **High** — full loop for bounded worker |
| 5 | `rig_relay/acp/acp_agent_loop.py:228` | `agent = VibeAcpAgentLoop()` | ACP agent construction (main entry) | orchestrator adapter | **Yes** (ACP wrapper) | `OrchestratorLoop` + ACP adapter | Low — ACP facade |
| 6 | `rig_relay/cli/ide_sidecar.py:102` | `agent = VibeAcpAgentLoop()` | IDE sidecar ACP | orchestrator adapter | **Yes** (thin IPC host) | `OrchestratorLoop` + ACP adapter | Low — sidecar |
| 7 | `tests/conftest.py` | `build_test_agent_loop(config, ...)` | Test fixture | test_fixture | N/A | `FakeAgentLoop` or parameterized test builder | Low — test infrastructure |
| 8 | `tests/acp/conftest.py:29` | `VibeAcpAgentLoop()` | ACP test fixture | test_fixture | N/A | ACP test double | Low |

## Ownership categories

| Category | Count | Should have full AgentLoop? |
|---|---|---|
| **Orchestrator** | 4 (desktop cockpit, ACP sessions, fork, ACP main) | **Yes** — these are the owners |
| **Orchestrator adapter** | 2 (IDE sidecar, ACP entry) | **Yes** — thin wrappers |
| **Subagent spawn** | 1 (task.py `is_subagent=True`) | **No** — should be bounded worker |
| **Test fixtures** | 2 (conftest.py, acp/conftest.py) | N/A — test infrastructure |

## High-risk usages

### `task.py` — Subagent spawn with full AgentLoop

```python
subagent_loop = AgentLoop(
    config=call_config,
    agent_name=agent_profile_name,
    is_subagent=True,
    defer_heavy_init=True,
)
```

**Problem:** Creates a full `AgentLoop` with conversation loop, middleware, hooks,
and all mixins for a bounded mission worker. The subagent should not need:
- Full conversation loop (should be single-turn or bounded mission)
- Middleware pipeline (should inherit owner policy)
- Hooks (subagent is not user-facing)
- Fork/compact/switch_agent (bounded lifecycle)

**Recommendation:** Replace with `SubagentRuntime` that owns bounded mission
execution: assigned worktree, allowed tools/profile binding, budget, artifact
contract, validation receipt.

## No Ralph loop exists

Ralph (`rig_relay/ralph/`) currently has no AgentLoop construction. It is
an observe-only scanner. Any future `RalphRuntime` should NOT be built on
AgentLoop — it should use `SubagentRuntime` with `profile_kind=AUTONOMOUS_BACKGROUND`
and `trust_tier=OBSERVE`.
