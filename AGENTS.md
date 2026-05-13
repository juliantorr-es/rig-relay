# AGENTS.md

Conventions for AI agents and humans contributing to **Rig Relay** — a Python 3.12+ CLI coding assistant managed with `uv`.

Layout: `vibe/core` is the engine (agent loop, tools, LLM backends, config); `vibe/cli` is the Textual TUI; `vibe/acp` bridges to the Agent Client Protocol; `vibe/setup` runs first-run wizards. Tests live in `tests/` with autouse fixtures in `conftest.py` and test doubles in `tests/stubs/`.

## Commands

Always go through `uv` — never invoke bare `python` or `pip`.

- `uv run vibe` / `uv run vibe-acp` — the two entry points.
- `uv run pytest` — full suite (parallel via `pytest-xdist`).
- `uv run pyright` — strict type check.
- `uv run ruff check --fix .` and `uv run ruff format .` — run both after every code change and report the files modified.
- `uv run pre-commit run --all-files` — full lint pass. Install once with `uv tool install pre-commit && uv run pre-commit install`.
- Useful uv basics: `uv sync --all-extras`, `uv add <pkg>`, `uv remove <pkg>`.

## Project layout & module conventions

- `__init__.py` exposes the public API via an explicit `__all__`.
- Private modules are prefixed with `_` (e.g. `_settings.py`, `_config.py`).
- Pydantic models live in `models.py`; configuration in `_settings.py` / `_config.py`.
- Abstract interfaces use the `_port.py` suffix (hexagonal-style ports).
- Tests mirror the source layout; test doubles in `tests/stubs/` are named `Fake*`.

## Python style

- Prefer `match` / `case` over long `if` / `elif` chains.
- Use the walrus operator `:=` only when it shortens code and improves clarity.
- Be a never-nester: early returns and guard clauses over nested blocks.
- Modern type hints only: built-in generics (`list`, `dict`) and `|` unions. Never import `Optional`, `Union`, `Dict`, `List` from `typing`.
- Use `pathlib.Path` (and `anyio.Path` in async paths) instead of `os.path`.
- Use f-strings, comprehensions, and context managers; follow PEP 8.
- Enums: `StrEnum` / `IntEnum` with `auto()` and UPPERCASE members. For type-mixing, the mix-in type comes before `Enum` in the bases. Add methods or `@property` rather than parallel lookup tables.
- Write declarative, minimalist code: express intent, drop boilerplate.
- Never call a private method from outside of it's class
- Avoid comments and docstrings, except for when there's a hard to spot corner case

## Typing & imports

- Pyright is strict and gates CI; fix types at the source.
- No relative imports — `ban-relative-imports = "all"`. Always `from vibe.core.x import …`.
- No inline `# type: ignore` or `# noqa`. Fix with refined signatures (TypeVar, Protocol), `isinstance` guards, `typing.cast` when control flow guarantees the type, or a small typed wrapper at the boundary.

## Pydantic

- Parse external data via `model_validate`, `field_validator`, or `model_validator(mode="before")` — never ad-hoc `getattr` / `hasattr` walks or custom `from_sdk` constructors.
- Set `ConfigDict(extra=…)` explicitly. Use `validation_alias` (or field aliases) for kebab-case TOML keys.
- Discriminated unions (e.g. MCP `transport`): use sibling final classes plus a shared base/mixin, and compose with `Annotated[Union[...], Field(discriminator=...)]`. Never narrow the discriminator field in a subclass — it violates LSP and pyright will reject it.
- Document `Raises:` only for exceptions the function actually raises (or that propagate from public API calls). Don't list speculative built-ins.

## Async

- `asyncio` is the orchestration runtime in the agent loop and tool execution. Use `asyncio.create_task` + queues for concurrent work, not blanket `gather`.
- Use `anyio.Path` for file I/O on async paths.
- Streaming surfaces return `AsyncGenerator[Event, None]`, not coroutines.
- HTTP via `httpx.AsyncClient`; mock with `respx` in tests.

## Tools

- Subclass `BaseTool` from `vibe/core/tools/base.py` with a Pydantic args model and a `BaseToolConfig` generic parameter.
- Implement `async def run(args, ctx: InvokeContext)` and yield events progressively.
- Raise `ToolError` for user-facing failures; raise `ToolPermissionError` for authorization failures.
- Declare permission with `ToolPermission` (`ALWAYS` / `ASK` / `NEVER`); honor it consistently.

## Logging & errors

- Use `from vibe.core.logger import logger` — stdlib `logging` with `StructuredLogFormatter`, not `structlog`.
- Configure via env: `LOG_LEVEL` (default `WARNING`), `LOG_MAX_BYTES`. Logs land in `~/.vibe/logs/vibe.log`.
- Pass variables as `%s` positional args, not f-string interpolation: prefer `logger.error("Failed to fetch url=%s", url)` over `logger.error(f"Failed to fetch {url}")`. This defers formatting to the logging framework (only formats if the message is emitted) and keeps messages grep-friendly.
- Define module-local exception hierarchies. Always chain with `raise NewError(...) from e`. Rich exceptions expose a `_fmt()` helper for human-readable output.

## File I/O

- Prefer `vibe.core.utils.io.read_safe` / `read_safe_async` / `decode_safe` over raw `Path.read_text()`, `Path.read_bytes().decode()`, or `open()`.
- They return `ReadSafeResult(text, encoding)` and try UTF-8, then BOM detection, then locale, then `charset_normalizer` lazily.
- Pass `raise_on_error=True` only when callers must distinguish corrupt files from valid ones; the default replaces undecodable bytes with U+FFFD.

## Tests

- Stack: `pytest` + `pytest-asyncio` + `pytest-textual-snapshot` + `respx`.
- Mark async tests with `@pytest.mark.asyncio`. Mock outbound HTTP with `respx`.
- Rely on the autouse fixtures in `tests/conftest.py` (`config_dir`, `tmp_working_directory`) for filesystem and home-dir isolation.
- No docstrings on test functions, methods, or classes — descriptive names like `test_create_user_returns_403_when_unauthorized` carry the intent. Pytest displays docstrings instead of node IDs when present, which hurts.
- Tests are exempt from the `ANN` and `PLR` ruff rules (see `per-file-ignores`).

## Git

- Never use `git commit --amend`, `git push --force`, or `git push --force-with-lease`.
- Always create new commits and push with a plain `git push`.
- If a push is rejected due to upstream changes, rebase onto the updated remote branch — never merge and never force-push.
- **Agent checkpoint commits**: Agents may create local checkpoint commits for session-owned files using the `checkpoint` tool. Agents may NOT push, amend, rebase, merge, reset, clean, stash, restore, or commit files outside their mission scope. Only the user pushes. See `docs/governance/cross-session-coordination.md`.
- Direct `git commit` and `git add` via bash are blocked. Use the `checkpoint` tool instead.

## Dirty-file preservation

- Any modified, staged, or untracked file that exists before the current mission is PROTECTED. These files contain user-owned or prior-agent-owned changes.
- Before editing, inspect repository state with `git_status`. Dirty files are not yours to freely rewrite.
- When a mission requires editing a protected file:
  - Read it first. Identify existing modified regions.
  - Apply only the mission-required delta. Preserve unrelated edits exactly.
  - Prefer `search_replace` with targeted SEARCH/REPLACE blocks over `write_file`.
  - For `write_file` on a protected file, set `allow_overwrite_protected=true` and provide `expected_before_sha256`.
  - For `search_replace` on a protected file, provide `expected_before_sha256`.
  - Never run formatters over the whole file unless the mission explicitly requires it.
- Never use `git restore`, `git checkout` (for undo), `git reset`, `git clean`, or `git stash` to discard changes to protected files.
- If a required edit overlaps unknown existing edits, stop and report a structured conflict.
- The final report must distinguish: pre-existing dirty files, files changed by this mission, files skipped, and files with conflicts.

## Editor tip

In Cursor / Pyright, the "Add import" quick fix is missing — use the workspace snippets `acpschema`, `acphelpers`, `vibetypes`, `vibeconfig` to insert the import line, then rename the symbol.

## Usage data

- Rig Relay emits structured workflow observability data to `~/.rig/relay/sessions/<session_id>/observability.jsonl`. See `docs/governance/usage-data-doctrine.md` for the full governance doctrine.
- **Do not emit raw file contents, secrets, or private code** into observability events. Use SHA256 hashes for everything content-derived.
- **Dirty file snapshots, refusals, files_read, and tests_run** are currently in-memory only. When touching the guard or tool execution path, prefer emitting these as `rig.relay.guard.dirty_snapshot_captured`, `rig.relay.guard.refused_write`, `rig.relay.tool.files_read`, and `rig.relay.tool.tests_run` events.
- New telemetry events: add the event name to `EventName` in `vibe/core/telemetry/constants.py`. Follow the `rig.relay.<domain>.<verb>` naming convention.
- New artifacts: subclass the pattern in `vibe/core/telemetry/artifacts.py`. Register the artifact kind in the `ArtifactEnvelope` model.
- Schemas for derived eval datasets live in `docs/schemas/rig.relay.*.v1.schema.json`. Alignment between source fields and schema fields is governed by the usage data doctrine.
- **Never feed raw usage data back into agent prompts.** Compile into small decision artifacts (see doctrine for derived dataset list).
- Export and remote telemetry are opt-in only. Default is local-first.
- **Cross-session coordination** uses typed state, not chat transcripts. See `docs/governance/cross-session-coordination.md`. Emit `coord.*` events for task claims, path reservations, heartbeats, artifacts, conflicts, handoffs, and compact projections.
- **Coordination events are evaluation data.** Every `coord.*` event feeds the derived datasets defined in the usage data doctrine (`cross_session_coordination_dataset.jsonl`, `coordination_conflict_dataset.jsonl`, `artifact_reuse_dataset.jsonl`).
- Coordination is local-first (file-backed under `.build/rig-relay/coordination/`). Watchable backends are future and opt-in.

## Out-of-scope findings

When an agent discovers important debt, design gaps, or best-practice violations outside the current mission scope, it must NOT fix them opportunistically. Instead:

- Append a structured finding to `docs/findings/out-of-scope-findings.jsonl`.
- When useful, add or update the corresponding Markdown index in `docs/findings/out-of-scope-findings.md`.
- Findings must include affected files, language/subsystem, why it matters, best-practice anchor, and a recommended future slice.
- The JSONL registry is append-only — never edit or remove existing rows.
- Every final mission report should include an "Out-of-scope findings recorded" section linking to the registry.
- See `docs/findings/language-practices/python.md` for Python-specific best-practice anchors used by findings (PEP 8, Ruff PLR rules, Diátaxis).

## Autoimprovement

- Suggest to add new rules to AGENTS.md based on user input or PR comments, when a change request could be generalized as a rule.
- Suggest updates to the README.md file according to feature changes or additions
- Keep the builtin Vibe Skill (`vibe/core/skills/builtins/vibe.py`) up-to-date. It documents the CLI's features, such as args, flags, config options and persistence, commands, built-in agents, file discovery logic.
