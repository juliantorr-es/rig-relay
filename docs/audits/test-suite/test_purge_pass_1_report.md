# Test Purge Pass 1 Report

## Baseline Metrics

| Metric | Value |
|---|---|
| Branch/HEAD | main / 8d0b13c802e182c72ade51e58ae70b6abafdadc3 |
| Collected test count | 6085 |
| Test files (test_*.py) | 325 |
| Total .py files in tests/ | 360 |
| Layout guard | PASSED |
| Conftest hygiene | PASSED |
| Collect-only errors | 0 |
| Dirty files (modified in tree) | ~36 M + ~177 D staged |

## Deletions Executed

All 177 deletions were already staged by a prior agent in the main branch. No additional deletions were performed in this pass.

### Deletion Categories

| Category | Count | Examples |
|---|---|---|
| Old TUI autocomplete | 2 | tests/autocompletion/test_path_completion_controller.py, test_slash_command_controller.py |
| Old TUI plan offer | 3 | tests/cli/plan_offer/* |
| Old TUI CLI features | 7 | tests/cli/test_cache.py, test_clipboard.py, test_commands.py, test_doctor.py, test_initial_agent_name.py, test_programmatic_setup.py, test_stderr_guard.py |
| Old TUI narrator | 2 | tests/narrator_manager/* |
| Duplicate scripts tests | 8 | tests/scripts/test_desktop_*.py, test_websocket_server.py, etc. |
| Old TUI snapshots | ~90 | tests/snapshots/__snapshots__/*.svg, test_ui_snapshot_*.py |
| Old TUI stubs | 3 | tests/stubs/fake_audio_recorder.py, fake_transcribe_client.py, fake_voice_manager.py |
| Old update notifier | 8 | tests/update_notifier/* |
| Old voice manager | 2 | tests/voice_manager/* |
| Old webview console | 1 | tests/webview_console/* |
| Root-level migration tests | 20+ | test_agents.py, test_cli_programmatic_preload.py, test_history_manager.py, test_message_id.py, test_message_merging.py, test_model_observations.py, test_observation_consent_integration.py, test_rig_relay.py, test_tagged_text.py, test_telemetry_consent.py, test_turn_summary.py |

## Canonical Survivor Coverage

All desktop/WebSocket functionality from deleted tests/scripts/* is covered by canonical tests in tests/desktop/test_websocket_server.py, test_desktop_projection.py, test_intents.py, and test_protected_intents.py (all 44 + tests pass).

All orchestration/projection functionality is covered by tests in tests/desktop/, tests/ralph/, tests/orchestrator/, tests/runtime/.

## Remaining Purge Candidates

| ID | Path | Category | Risk | Action |
|---|---|---|---|---|
| purge-layout-split | tests/scripts/ surviving files | misc | low | Auditing remaining scripts/ tests for future relocation |
| purge-demo-mcp | tests/demo/test_mcp_night_demo_fixtures.py | stale | low | Defer — imports redaction module, needs investigation |
| purge-historical-migration | tests/docs/test_vibe_legacy_boundary.py | historical | low | Defer — documents migration, may be kept as audit |
| purge-textual-retirement | tests/docs/test_textual_retirement_policy.py | policy | low | Defer — documents TUI retirement, useful as audit evidence |

## Validation

| Check | Result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 uv run pytest --collect-only -q` | 6085 tests collected, 0 errors |
| Layout guard | PASSED |
| Conftest hygiene | PASSED |
| demo-doctor | 22/22 passed |
| Desktop tests (full) | 326/326 passed |
| Runtime convergence tests | 9/9 passed |
| Ralph tests | All passing |
| Orchestrator tests | All passing |

## Inventories Created

- `docs/audits/test-suite/test_purge_candidates.jsonl` — 10 candidate groups documented
- `docs/audits/test-suite/canonical_coverage_keep_list.jsonl` — 20 canonical test groups protected
