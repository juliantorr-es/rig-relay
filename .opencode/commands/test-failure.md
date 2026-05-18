---
description: Narrow a failing test or type check
---

Read @AGENTS.md and @pyproject.toml.

Pick the narrowest relevant `uv run pytest`, `uv run pyright`, or `uv run ruff check` command for the symptom.
Focus on the first failure only.
Do not expand scope until that failure is understood.

Return:

1. Exact command run
2. First failure
3. Smallest file scope
4. Recommended follow-up
