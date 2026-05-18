---
description: Classify a Rig Relay failure before patching
---

Read @AGENTS.md and @pyproject.toml.

Classify the failure as runtime, test fixture, config, dependency, or environment drift before any code change.
If the cause is unclear, gather one more focused signal, then stop and name the blocker.
Do not propose a fix until the root cause is named.

Return:

1. Failure class
2. Ownership
3. Most likely root cause
4. Smallest next check
