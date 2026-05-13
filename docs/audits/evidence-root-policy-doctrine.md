# Audit: Evidence Root Product Semantics and Policy Doctrine
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: e389b446706173ebc5950931994ba4cdb6a7d9f4
Scope: Read-only audit
Owner area: config

## Executive Summary
This doctrine defines where Rig Relay evidence should live. The primary shift is from a "User Global" default to a "Context-Aware" model that prefers Repo-Local storage when working within a project, ensuring evidence is portable with the code it helped create.

## Root Mode Definitions
- **REPO_LOCAL**: `./.rig/relay/`. Preferred for project work.
- **USER_GLOBAL**: `~/.rig/relay/`. Fallback for ad-hoc queries.
- **EXPLICIT_HOME**: Set via `RIG_RELAY_HOME`. Overrides all logic.
- **TEST_TEMP**: Managed by pytest. Isolated from real state.

## Precedence Proposal
1.  **Explicit Environment**: `RIG_RELAY_HOME`.
2.  **Explicit CLI Flag**: `--evidence-root <path>`.
3.  **Implicit Repo-Local**: If CWD or parent contains a `.git` or `.rig/relay` marker.
4.  **Implicit User Global**: Default fallback.

## UX Behavior
- On session start, the CLI should print: `Evidence Root: repo_local (./.rig/relay)`.
- If a user tries to run in a new repo without repo-local evidence, the agent could ask: "Should I initialize repo-local evidence for this project?".

## Warnings/Errors Proposal
- **Warning**: If `REPO_LOCAL` is active but `.gitignore` does not exclude `.rig/relay`.
- **Warning**: If both `REPO_LOCAL` and `USER_GLOBAL` contain active sessions (potential confusion).
- **Error**: If the resolved root is not writable.

## Migration Path
- Add a `rig-relay move-evidence --to-repo` command to help users migrate global history to a specific project.

## CI/Local Doctor Recommendations
- `rig-relay doctor` must report the active root mode and detect "stray" evidence in unexpected locations.
- CI should enforce `TEST_TEMP` mode to avoid polluting runner home directories.

## Future Implementation Backlog
- [ ] Add `--evidence-root-mode` CLI flag (enum: auto, global, local).
- [ ] Implement automatic `.gitignore` injection for `.rig/relay`.
- [ ] Add `root_mode` field to `SESSION_STARTED` event.
