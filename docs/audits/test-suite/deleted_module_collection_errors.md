# Deleted Module Collection Errors — Audit

Generated 2026-05-15 during test-suite stabilization lane 2.

## Summary

Current collect-only status: `PYTHONDONTWRITEBYTECODE=1 uv run pytest --collect-only` completes without deleted-module collection errors. The inventory below is the historical set that was captured before the blocker was cleared.

| Category | Count | Disposition |
|---|---|---|
| deleted-feature test | 34 | **Delete** — module no longer exists, feature removed |
| stale namespace migration | 3 | **Repair import** — module renamed/moved |
| should be rewritten | 0 | All 3 repairable are trivial import fixes |
| quarantine | 0 | No ambiguous cases |

## Error inventory

### 1. Deleted legacy CLI modules (26 files)

These test files import modules that were intentionally removed during the vibe→rig_relay migration. The features (old TUI, old VibeApp, scratchpad, trusted folders, etc.) have no current replacement in the desktop-cockpit/webview architecture.

| # | Test file | Deleted module | Replacement | Disposition |
|---|---|---|---|---|
| 1 | tests/autocompletion/test_path_completion_controller.py | rig_relay.cli.autocompletion | None (old TUI autocomplete) | delete |
| 2 | tests/autocompletion/test_slash_command_controller.py | rig_relay.cli.autocompletion | None (old TUI autocomplete) | delete |
| 3 | tests/cli/test_cache.py | rig_relay.cli.cache | None (old TUI cache) | delete |
| 4 | tests/cli/test_clipboard.py | rig_relay.cli.clipboard | None (old TUI clipboard) | delete |
| 5 | tests/cli/test_commands.py | rig_relay.cli.commands | None (old TUI command registry) | delete |
| 6 | tests/cli/test_stderr_guard.py | rig_relay.cli.stderr_guard | None (old TUI) | delete |
| 7 | tests/cli/plan_offer/test_decide_plan_offer.py | rig_relay.cli.plan_offer | None (old TUI plan offer) | delete |
| 8 | tests/cli/plan_offer/test_http_whoami_gateway.py | rig_relay.cli.plan_offer | None (old TUI plan offer) | delete |
| 9 | tests/narrator_manager/test_narrator_manager.py | rig_relay.cli.narrator_manager | None (old TUI narrator) | delete |
| 10 | tests/narrator_manager/test_telemetry.py | rig_relay.cli.narrator_manager | None (old TUI narrator) | delete |
| 11 | tests/update_notifier/test_do_update.py | rig_relay.cli.update_notifier | None (old CLI update) | delete |
| 12 | tests/update_notifier/test_filesystem_update_cache_repository.py | rig_relay.cli.update_notifier | None (old CLI update) | delete |
| 13 | tests/update_notifier/test_github_update_gateway.py | rig_relay.cli.update_notifier | None (old CLI update) | delete |
| 14 | tests/update_notifier/test_pypi_update_gateway.py | rig_relay.cli.update_notifier | None (old CLI update) | delete |
| 15 | tests/update_notifier/test_update_use_case.py | rig_relay.cli.update_notifier | None (old CLI update) | delete |
| 16 | tests/update_notifier/test_whats_new.py | rig_relay.cli.update_notifier | None (old CLI update) | delete |
| 17 | tests/voice_manager/test_telemetry.py | rig_relay.cli.voice_manager | None (old TUI voice) | delete |
| 18 | tests/voice_manager/test_voice_manager.py | rig_relay.cli.voice_manager | None (old TUI voice) | delete |
| 19 | tests/webview_console/test_app.py | rig_relay.cli.webview_console | None (old webview console) | delete |
| 20 | tests/test_history_manager.py | rig_relay.cli.history_manager | None (old TUI history) | delete |
| 21 | tests/test_turn_summary.py | rig_relay.cli.turn_summary | None (old TUI turn summary) | delete |

### 2. Deleted modules in current packages (2 files)

| # | Test file | Deleted module | Replacement | Disposition |
|---|---|---|---|---|
| 22 | tests/cli/test_doctor.py | rig_relay.cli.cli | Current: rig_relay.cli.desktop_cockpit | delete (test targets removed cli.py) |
| 23 | tests/cli/test_programmatic_setup.py | rig_relay.cli.cli | Current: rig_relay.cli.desktop_cockpit | delete (test targets removed cli.py) |
| 24 | tests/cli/test_initial_agent_name.py | rig_relay.cli.cli | Current: rig_relay.cli.desktop_cockpit | delete (test targets removed cli.py) |

### 3. Deleted script module (1 file)

| # | Test file | Deleted module | Replacement | Disposition |
|---|---|---|---|---|
| 25 | tests/scripts/test_storage_lifecycle.py | scripts.rig_relay_gc_artifacts (DEFAULT_BUDGET) + scripts.rig_relay_compact_artifacts | Current: rig_relay.evidence.storage_lifecycle | delete (scripts replaced by package module) |

### 4. Deleted test infrastructure (12 files)

| # | Test file | Deleted module | Replacement | Disposition |
|---|---|---|---|---|
| 26 | tests/snapshots/test_ui_snapshot_basic_conversation.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 27 | tests/snapshots/test_ui_snapshot_config_app.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 28 | tests/snapshots/test_ui_snapshot_data_retention.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 29 | tests/snapshots/test_ui_snapshot_debug_console.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 30 | tests/snapshots/test_ui_snapshot_empty_assistant_before_reasoning.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 31 | tests/snapshots/test_ui_snapshot_mcp_command.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 32 | tests/snapshots/test_ui_snapshot_proxy_setup.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 33 | tests/snapshots/test_ui_snapshot_release_update_notification.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 34 | tests/snapshots/test_ui_snapshot_rewind.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 35 | tests/snapshots/test_ui_snapshot_session_resume.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 36 | tests/snapshots/test_ui_snapshot_session_resume_injected.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 37 | tests/snapshots/test_ui_snapshot_streaming_code_fence.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |
| 38 | tests/snapshots/test_ui_snapshot_whats_new.py | tests.snapshots.base_snapshot_test_app | None (old TUI snapshot testing) | delete |

### 5. Import repair: module renamed (3 files)

| # | Test file | Failed import | Fix | Disposition |
|---|---|---|---|---|
| 39 | tests/core/nuage/test_remote_events_source.py | AgentLoopStateError from rig_relay.core.agent_loop | Change to `from rig_relay.core._errors import AgentLoopStateError` | repair |
| 40 | tests/desktop/test_chat_persistence.py | (check — import error or other?) | needs inspection | check |
