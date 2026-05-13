# Audit: Config Root Resolution Policy
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: 24c990e011375078a04cb4a5534d114f98c064ed
Scope: Read-only audit
Owner area: config

## Executive Summary
Rig Relay's root resolution is "Global-First" by design. This audit evaluates the trade-offs of this model and confirms that centralized evidence storage in `~/.rig/relay` is the correct default for durable history, while identifying the need for better isolation semantics for tests and experiments.

## Findings Matrix
| ID | Area | Priority | Location | Current Behavior | Risk | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **CONF-001** | Home Resolution | P0 | `_vibe_home.py` | Defaults to `~/.rig/relay`. | Large evidence files can clutter the home directory if not managed. | Maintain global default; improve `doctor` tools for history cleanup. |
| **CONF-002** | Legacy Fallback | P1 | `_vibe_home.py` | Automatically loads `~/.vibe` if it exists. | Users may be unknowingly running with legacy Vibe config/state. | Require explicit `VIBE_HOME` or disable legacy by default in `rig-relay`. |
| **CONF-003** | Env Variable Shadowing | P2 | `_settings.py` | Both `VIBE_` and `RIG_RELAY_` prefixes work. | Confusion over which environment variable takes precedence. | Deprecate `VIBE_` prefix in the `rig-relay` binary. |

## Detailed Findings
### CONF-001: Global-First Doctrine
Location: `vibe/core/paths/_vibe_home.py`
Current behavior: `_get_vibe_home` checks `RIG_RELAY_HOME`, then defaults to `~/.rig/relay`.
Risk: Centralized evidence simplifies history management but requires users to be aware of where data lives.
Confirmed policy: Centralized history in `~/.rig/relay` is the preferred operational model. Repo-local storage is reserved for explicit isolation via `RIG_RELAY_HOME`.

## Recommended Backlog
1.  **Mission: Better Isolation Tools**: Add flags or commands to easily move sessions between global and local roots.
2.  **Mission: Diagnostic Command**: Add `rig-relay doctor` to show resolved paths and warn about legacy bleed.
