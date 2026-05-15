# MCP Night Demo — Ralph Background Lane Lifecycle

## Quick start

```bash
git clone https://github.com/juliantorr-es/rig-relay
cd rig-relay
uv sync
uv run rig-relay
```

## Demo flow

### 1. Create orchestrator missions
Type in chat:
```
/orchestrator - extract the ToolRuntime boundary from AgentLoop
/orchestrator - wire Ralph into pywebview desktop
/orchestrator - harden bash analytics projection
```

### 2. Toggle Ralph ON
Type `/ralph scan` to see current findings.
Toggle Ralph ON (widget button or `/ralph background on`).

### 3. Ralph creates isolated lane
Ralph identifies a convergence threat and creates a worktree:
```
Branch: ralph/toolruntime-boundary-a1b2c3d4
Worktree: .rig/worktrees/ralph/ralph_lane_abc12345
```

### 4. Ralph works in background
Ralph edits only inside its worktree, commits to its own branch:
```
Commit: abc1234 — ralph: lane fix for ToolRuntime extraction
Files: src/core/tool_runtime.py (+3 lines)
```

### 5. Ralph seals review bundle
Ralph finishes work, seals a review bundle:
```
Bundle: bundle_ralph_lane_abc12345
Summary: Fixed DirtyFileGuard singleton ownership across forked agents
Evidence: finding_20260513_dirty_guard_singleton
```

### 6. Review finished lanes
Widget shows "1 lane awaiting review". Click review.
Special orchestrator session shows:
- What Ralph did
- When and why
- Changed files and commits
- Validation results
- Adoption recommendation

### 7. Adoption (requires separate approval)
If relevant to active orchestrator lane:
- Orchestrator reviews compatibility
- Human approves adoption
- Governed merge executes (no-ff merge)
- Merge receipt emitted

### 8. Push to preproduction (requires separate approval)
After merge:
- Required validations pass
- Human approves preproduction push
- Governed push to preproduction branch

## Safety boundaries

- Ralph works ONLY in Ralph-owned worktrees
- Ralph commits ONLY to Ralph-owned branches
- Adoption merge requires separate human approval
- Push to preproduction requires separate human approval
- All transitions emit events and receipts
- ToolRuntime governs all tool execution
