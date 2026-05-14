# Vibe CLI Purge Inventory

## Status

**Draft.** Inventory of user-facing Vibe CLI and Textual surfaces that should
be retired, quarantined, or retained only as compatibility shims.

## Goal

Rig Relay should present as a Relay-native product surface. Legacy Vibe CLI
internals may remain for compatibility, but new users should not be steered
into `vibe` as the product interface.

## Surface Classes

| Class | Meaning |
|---|---|
| `retire` | User-facing surface should disappear from product docs and primary guidance |
| `quarantine` | Legacy surface remains for compatibility but is hidden from primary docs |
| `retain` | Needed compatibility adapter or runtime internals; keep in place |

## User-Facing CLI Entry Points

| Surface | Current Path | Classification | Notes |
|---|---|---|---|
| `rig-relay` | `pyproject.toml`, `rig_relay.cli.entrypoint:main` | `retain` | Primary product command |
| `rig-relay-acp` | `pyproject.toml`, `rig_relay.cli.acp_entrypoint:main` | `retain` | Primary ACP command |
| `vibe` | `pyproject.toml`, `vibe.cli.entrypoint:main` | `quarantine` | Legacy alias; keep for alpha compatibility |
| `vibe-acp` | `pyproject.toml`, `vibe.acp.entrypoint:main` | `quarantine` | Legacy alias; keep for alpha compatibility |
| `rig-relay-cockpit` | `docs/install.md` only | `retain` | Primary cockpit launcher reference |

## Textual Imports

| Surface | Current Path | Classification | Notes |
|---|---|---|---|
| `vibe.cli.textual_ui.app` | `vibe/cli/textual_ui/app.py` | `quarantine` | Legacy TUI runtime retained for compat and tests |
| `vibe.cli.textual_ui.widgets.*` | `vibe/cli/textual_ui/widgets/` | `retain` | Legacy implementation internals |
| `vibe.cli.stderr_guard` | `vibe/cli/stderr_guard.py` | `retain` | Compatibility helper for Textual UI |

## Setup and Install References

| Surface | Current Path | Classification | Notes |
|---|---|---|---|
| `rig-relay --setup` | `README.md` | `retain` | Product onboarding path |
| `vibe --setup` | compatibility alias via entrypoint | `quarantine` | Legacy alias; should not be centered in docs |
| `uv run rig-relay` | `README.md`, `docs/install.md` | `retain` | Product-first install/run path |
| `uv run python scripts/rig_relay_desktop_cockpit.py` | `README.md`, `docs/demo/mcp-night-development-harness-demo.md` | `retain` | Primary desktop cockpit path |

## README References

| Reference | Classification | Notes |
|---|---|---|
| Product headline and overview | `retain` | Should describe Rig Relay as the product |
| Legacy compatibility section | `quarantine` | Must clearly label `vibe` as legacy |
| Install / run instructions | `retain` | Must prefer `rig-relay` and the cockpit |

## Tests That Still Exercise Legacy CLI

| Test Path | Surface | Classification | Notes |
|---|---|---|---|
| `tests/test_ui_rewind.py` | `vibe.cli.textual_ui.app.VibeApp` | `retain` | Textual behavior coverage |
| `tests/cli/test_ui_clipboard_notifications.py` | `vibe.cli.textual_ui.app.VibeApp` | `retain` | Textual behavior coverage |
| `tests/cli/test_ui_session_incremental_renderer.py` | `vibe.cli.textual_ui.app.VibeApp` | `retain` | Textual behavior coverage |
| `tests/cli/test_ui_skill_dispatch.py` | `vibe.cli.textual_ui.app.VibeApp` | `retain` | Textual behavior coverage |
| `tests/update_notifier/test_ui_update_notification.py` | `vibe.cli.textual_ui.app.VibeApp` | `retain` | Textual behavior coverage |
| `tests/tools/test_ui_bash_execution.py` | `vibe.cli.textual_ui.app.VibeApp` | `retain` | Textual behavior coverage |

## Safe-To-Retire vs Compatibility-Required

### Safe To Retire

- Product prose that centers `vibe` over Rig Relay
- New docs that frame Textual as primary UI
- User onboarding copy that omits the pywebview cockpit

### Compatibility Required

- `vibe` and `vibe-acp` entry points during alpha
- `vibe/cli/textual_ui/` runtime internals while tests still depend on them
- Legacy config and environment fallbacks required by alpha compatibility
- Compatibility adapters that bridge `vibe.*` to `rig_relay.*`

## Cross-References

- [Textual TUI Retirement Policy](../governance/textual-retirement-policy.md)
- [Vibe Legacy Deprecation Doctrine](../governance/vibe-legacy-deprecation.md)
- [Vibe Legacy Boundary Inventory](vibe-legacy-boundary-inventory.md)
- [Rig Relay Install Channels](../install.md)

