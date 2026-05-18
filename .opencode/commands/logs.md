---
description: Inspect local logs and runtime evidence
---

Read @AGENTS.md.

Inspect the most recent useful lines in `~/.vibe/logs/vibe.log` and any relevant `.build/rig-relay/` evidence.
Pull out only the lines that explain the failure.
Keep private data out of the summary.

Recent log tail:

!tail -n 200 ~/.vibe/logs/vibe.log
