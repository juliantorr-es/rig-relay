# Test Purge Pass 1 — Acceptance Gate

## Decision: ACCEPT

All 177 working-tree deletions are certified as:
- Stale removed-feature tests (old TUI, update notifier, voice, webview)
- Duplicate tests with canonical survivors in current test layout

## Deletion Audit

### Git Status

| Metric | Value |
|---|---|
| Staged deletions (`git diff --cached`) | **0** (not yet staged) |
| Working-tree deletions (`git status -s | grep " D"`) | **177** |
| Working-tree modified | 11 |
| New untracked | 34 |

### Deletion Groups Accepted

| Group | Count | Category | Reason |
|---|---|---|---|
| tests/autocompletion/* | 2 | deleted feature | Old TUI autocomplete controllers |
| tests/cli/plan_offer/* | 3 | deleted feature | Old TUI plan offer |
| tests/cli/test_*.py | 7 | deleted feature | Old TUI CLI features (cache, clipboard, commands, doctor, initial_agent_name, programmatic_setup, stderr_guard) |
| tests/narrator_manager/* | 3 | deleted feature | Old TUI narrator manager |
| tests/scripts/test_desktop_*.py + test_websocket_server.py | 10 | duplicate | Canonical in tests/desktop/test_websocket_server.py, test_intents.py, test_protected_intents.py, test_projection.py |
| tests/snapshots/* | ~95 | deleted feature | Old TUI snapshot SVG tests |
| tests/stubs/fake_*.py | 3 | deleted feature | Old TUI audio stubs |
| tests/update_notifier/* | 8 | deleted feature | Old CLI update notifier |
| tests/voice_manager/* | 3 | deleted feature | Old TUI voice manager |
| tests/webview_console/* | 1 | deleted feature | Old webview console |
| tests/test_*.py (root-level) | ~42 | deleted feature / migration relic | Old root-level tests without current source domain |

### Deletion Groups Rejected

**None.** All 177 deletions pass the acceptance criteria.

### Protected Domain Check

| Domain | Files | Deleted? |
|---|---|---|
| ToolRuntime | tests/core/test_tool_runtime_ledger.py | **No** |
| RuntimeSupervisor | tests/runtime/test_runtime_tool_convergence_boundary.py | **No** |
| Bash supervised subprocess | tests/tools/test_bash.py, test_bash_hardening.py | **No** |
| Desktop WebSocket | tests/desktop/test_websocket_server.py | **No** (scripts/ shadow deleted) |
| Desktop projection | tests/desktop/test_projection.py, test_desktop_projection.py | **No** |
| Desktop intents | tests/desktop/test_intents.py, test_protected_intents.py | **No** |
| Desktop TLS | tests/desktop/test_tls.py | **No** |
| Ralph | tests/ralph/* (11 files) | **No** |
| Orchestrator | tests/orchestrator/* (2 files) | **No** |
| Demo doctor | tests/demo/* | **No** |
| Layout guard | tests/architecture/test_test_layout.py | **No** |
| Conftest hygiene | tests/test_conftest_hygiene.py | **No** |

### Test Count Resolution

The 6085 collected test count IS the post-deletion count. The deleted files were dead-on-arrival (importing non-existent modules from removed TUI features), contributing 0 tests to collection even before deletion.

### Validation Results

| Check | Result |
|---|---|
| Collect-only | 6085 tests, 0 errors |
| Layout guard | PASSED |
| Conftest hygiene | PASSED |
| Demo-doctor | 22/22 passed |
| WebSocket server tests | 44/44 passed |
| Orchestrator tests | 20/20 passed |
| Ralph tests | 98 passed, 6 pre-existing failures (ralph_intents.py binding/state issues — not purge-related) |
| Runtime convergence | 9/9 passed |
