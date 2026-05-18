---
description: Summarize repo state before any edit
---

Read @AGENTS.md.

Report current repo state, active branch, short HEAD, dirty files, and any obvious conflict risks.
Treat pre-existing changes as user-owned.
Do not edit files.

Current repo state:

!git status --short --branch

Branch:

!git branch --show-current

HEAD:

!git rev-parse --short HEAD
