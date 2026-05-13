# Audit: Evidence Root Product Semantics and Policy Doctrine
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: e389b446706173ebc5950931994ba4cdb6a7d9f4
Scope: Read-only audit
Owner area: config

## Executive Summary
This doctrine defines where Rig Relay evidence should live. The primary policy is to use the **User Global** Relay home (`~/.rig/relay`) by default for all normal dogfood and operational work. This ensures a centralized, durable control plane for session history.

Repo-Local evidence (`./.rig/relay`) is supported and useful for deterministic tests, smoke fixtures, isolated experiments, and explicit exports, but it is not the recommended default for project work.

Current implementation note:
- root defaults remain `user_global`
- root mode is observable in session-start telemetry
- repo-local validation is supported as a selected root via `--evidence-root`

## Root Mode Definitions
- **USER_GLOBAL**: `~/.rig/relay/`. **Default and preferred** for normal work.
- **REPO_LOCAL**: `./.rig/relay/`. Reserved for **test/debug/export** mode only.
- **EXPLICIT_HOME**: Set via `RIG_RELAY_HOME`. Overrides all logic.
- **TEST_TEMP**: Managed by pytest. Isolated from real state.

## Precedence Doctrine (Current Runtime)
1.  **Explicit Environment**: `RIG_RELAY_HOME`.
2.  **User Global**: Default fallback (canonical home).
3.  **Legacy Fallback**: `~/.rig-relay`, `~/.vibe`, etc. (only if allowed).

Note: `--evidence-root <path>` in `doctor evidence` overrides discovery for validation tasks but does not change the runtime recording root.

## UX Behavior
- On session start, the CLI should print: `Evidence Root: user_global (~/.rig/relay)`.
- If a user intentionally wants to isolate a project, they should use `export RIG_RELAY_HOME=./.rig/relay`.

## Warnings/Errors Proposal
- **Warning**: If `REPO_LOCAL` is active but `.gitignore` does not exclude `.rig/relay`.
- **Warning**: If both `REPO_LOCAL` and `USER_GLOBAL` contain active sessions (potential confusion).
- **Error**: If the resolved root is not writable.

## Migration Path
- Add a `rig-relay move-evidence --to-global` command to help users consolidate isolated repo-local history into their central global home.

## CI/Local Doctor Recommendations
- `rig-relay doctor` must report the active root mode and detect "stray" evidence in unexpected locations.
- CI should enforce `TEST_TEMP` mode to avoid polluting runner home directories.

## Future Implementation Backlog
- [ ] Add `--evidence-root-mode` CLI flag (enum: auto, global, local).
- [ ] Implement automatic `.gitignore` injection for `.rig/relay`.
- [ ] Add `root_mode` field to `SESSION_STARTED` event.
