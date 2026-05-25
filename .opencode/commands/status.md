---
description: Summarize repo state before any edit
---

Read @AGENTS.md.

Report current repo state, active branch, short HEAD, dirty files, and any obvious conflict risks.
Treat pre-existing changes as user-owned.
Do not edit files.

To obtain repository state, use the governed custom tools:
- Call `rig_git_status` to get the working tree status.
- Call `rig_git_branch` to check the current branch.
- Call `rig_git_log` with `max_count: 1` or `rig_git_show` with `ref: "HEAD"` to check HEAD.

Do not run raw git status, git branch, or git log shell commands.
