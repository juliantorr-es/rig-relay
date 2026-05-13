# Audit: Config Root Resolution Policy
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: 24c990e011375078a04cb4a5534d114f98c064ed
Scope: Read-only audit
Owner area: config

## Executive Summary
Rig Relay's root resolution is currently "Global-First" with "Local-Optional" overrides. This audit identifies the risks of ambient state bleed and proposes a "Local-First" policy to align with the Relay mission.

## Findings Matrix
| ID | Area | Priority | Location | Current Behavior | Risk | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **CONF-001** | Home Resolution | P0 | `_vibe_home.py` | Defaults to `~/.rig/relay` or `~/.vibe`. | Evidence from different repos mixes in a single global directory. | Implement repo-local `.rig/relay` discovery as primary. |
| **CONF-002** | Legacy Fallback | P1 | `_vibe_home.py` | Automatically loads `~/.vibe` if it exists. | Users may be unknowingly running with legacy Vibe config/state. | Require explicit `VIBE_HOME` or disable legacy by default in `rig-relay`. |
| **CONF-003** | Env Variable Shadowing | P2 | `_settings.py` | Both `VIBE_` and `RIG_RELAY_` prefixes work. | Confusion over which environment variable takes precedence. | Deprecate `VIBE_` prefix in the `rig-relay` binary. |

## Detailed Findings
### CONF-001: Ambient State Bleed
Location: `vibe/core/paths/_vibe_home.py`
Current behavior: `_get_vibe_home` checks `RIG_RELAY_HOME`, then defaults to `~/.rig/relay`.
Risk: Without an explicit environment variable, every user run writes to a shared global space. This makes per-repo evidence management impossible.
Recommended refinement: If inside a Git repository, check for `.rig/relay/` in the repo root before falling back to Home.

## Recommended Backlog
1.  **Mission: Repo-Local Discovery**: Update `_get_vibe_home` to walk up to the Git root and check for config/evidence markers.
2.  **Mission: Diagnostic Command**: Add `rig-relay doctor` to show resolved paths and warn about legacy bleed.
