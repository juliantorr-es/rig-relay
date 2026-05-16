# ToolRuntime Boundary

Rig Relay's execution architecture separates concerns between the
AgentLoop turn conductor, the future ToolRuntime execution authority,
Ralph the scout/approval surface, the desktop HITL boundary, and the
analytics compiler.

## Layered execution model

```
Desktop UI       Renders projections, sends intents.
                 Dumb renderer — no policy.

Desktop Backend  Validates state, processes intents.
                 Owns refusal codes, approval gating.

Ralph            Scans projections, ranks candidates.
                 Owns approval state and decision receipts.
                 Not an executor.

AgentLoop        Turn conductor — conversation topology, middleware,
                 session lifecycle.
                 Does not own governed tool execution.

ToolRuntime      Governed tool execution authority.
                 Owns: normalization, permission, cache, gating,
                 execution, receipt emission, refusal normalization.

Analytics Compiler  Reads ledgers, compiles facts/projections.
                    Never executes tools.
```

## ToolRuntime responsibilities

ToolRuntime owns:

- Tool call normalization and validation
- Permission checks (ToolPermission: ALWAYS / ASK / NEVER)
- Deterministic result cache (pure / repo-state tools)
- Patch proposal gating for mutation tools
- Tool execution via `tool_instance.invoke()`
- Result normalization (success / failure / skipped)
- Tool receipt emission (`build_receipt`)
- Tool analytics event emission
- Refusal normalization (ToolPermissionError → refusal receipt)

## Ralph is not ToolRuntime

Ralph owns:

- Projection scanning (report ledgers, findings registry)
- Candidate ranking by deterministic policy
- Mission candidate proposal
- Approval state and decision receipts
- Desktop event emission for the HITL loop

Ralph may later submit a bounded read-only mission to ToolRuntime
through the desktop HITL boundary. Ralph must never execute tools
directly, bypass permission gates, or mutate the workspace.

## Desktop HITL does not execute tools

The desktop HITL boundary approves or declines mission candidates.
Approval is a state transition, not an action trigger.
Execution requires a separate contract through ToolRuntime.

## Current normal flow

```
RuntimeToolExecutionRunner → validate envelope → lease check if needed →
ToolRuntime.execute_one() → governed tool invocation →
ToolRuntimeResult → runtime audit event
```

RuntimeToolExecutionRunner is now an intent/lease/audit adapter.
It does not own the governed normal execution path.

## Capability boundary

| Component | Allowed | Forbidden |
|---|---|---|
| Ralph scan | Read projections, rank candidates | Execute tools, mutate state |
| Ralph approve/decline | Validate state, emit events, persist state | Execute tools, mutate workspace |
| ToolRuntime | Execute governed tools with permission | Execute without explicit approval |
| Analytics compiler | Read ledgers, compile projections | Execute tools, mutate state |
| Desktop UI | Render projections, send intents | Compute hashes, own policy |

## Remaining seams

- RuntimeSupervisor integration remains separate for subprocess-oriented paths.
- A few concrete tool adapter helpers still exist behind RuntimeToolExecutionRunner.
- AgentLoop still owns its current closure and result adaptation boundary.
