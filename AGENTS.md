# AGENTS.md

Conventions for AI agents and humans contributing to **Rig Relay** — a Python 3.12+ CLI coding assistant managed with `uv`.

## Project Instruction Bundle

Read [PROJECT.md](PROJECT.md) after this file. `PROJECT.md` is the canonical product/instruction bundle for desktop-bridge behavior, integration boundaries, and migration debt. This file remains the repo discipline guide for agent workflow, dirty-file handling, and git policy.

## Claim Calibration

Before any agent reports completion, publication, or a green milestone, it MUST run a short claim-adversary pass against the exact status it intends to publish. Treat every noun and adjective in that status as an assertion to falsify. At minimum, attack authority ownership, production-boundary realism, crash/retry or duplicate-effect safety when relevant, canonical evidence reconstruction, remote publication truth, and lane-boundary release safety. If any falsifier succeeds, downgrade the claim or repair the seam before reporting.

## Lane Closure, Freeze, and Deferred-Seam Doctrine

A lane is complete when its explicitly declared boundary is published, production-proven for its stated consumer purpose, reconstructable from governing evidence, and free of defects inside that boundary. Deferred upstream, downstream, cross-lane, UI, transport, or broader capability gaps do not keep the lane open unless they make the released boundary unsafe or its stated claim false.

Before a lane reports completion, it MUST declare the released boundary, the stated consumer purpose, the blocking defects, the deferred seams, and the freeze condition. A claim-adversary pass is boundary-scoped: it attacks the released boundary and its stated consumer purpose only. It MUST NOT expand a lane by requiring unrelated seams unless they invalidate the current claim or make the boundary unsafe to consume.

Once the boundary is remotely verified and survives a final boundary-scoped claim-adversary pass, the lane is frozen pending a named integration milestone. Frozen lanes may reopen only for a concrete defect inside the released boundary, a named integration milestone that consumes or extends it, or a user-directed architectural revision.

## Lane Status Vocabulary

Use only these release dispositions:

- `candidate_local`: implementation exists locally but is not published.
- `published_narrow_release`: the declared boundary is remotely published and safe for its stated purpose; deferred seams remain.
- `blocked_release`: a specific defect inside the declared boundary prevents safe publication or consumption.
- `frozen_pending_integration`: the narrow boundary is published and verified; no further isolated lane work is authorized until a named integration milestone consumes or extends it.

Do not use status identifiers that imply global closure, complete authority, or finished end-to-end integration when the release is intentionally narrow.

## Multiple parallel agents

Multiple agents often work on Rig Relay concurrently. There is no active git worktree mechanism — all agents share the same working tree. When you encounter a file that another agent has modified (dirty file), **never discard their changes**. Preserve all pre-existing modifications exactly. Dirty does not mean forbidden: if the mission needs to touch the file, make your changes **additive** or narrowly scoped to the bug/dead-code seam, and leave unrelated lane work intact. Do not remove, rewrite, or reformat code from other lanes unless the user explicitly asks for a coordinated rewrite. If your required edit would remove or conflict with existing modifications, stop and report the conflict.

## Project layout

`rig_relay/` is the entire product tree:

| Package | Domain |
|---|---|
| `core/` | Engine: agent loop, LLM backends, config, tools, mixins, session lifecycle |
| `acp/` | Agent Client Protocol server and agent loop |
| `cli/` | Entry points, desktop cockpit |
| `desktop/` | Cockpit backend, intents, WebSocket server, projections |
| `context/` | Compiler, symbol indexing, repo index, context observations |
| `ralph/` | Observe-only scanner: projection input, mission candidates, ranking |
| `reports/` | Report store (append-only JSONL), projector, query |
| `analytics/` | DuckDB analytical substrate, bash rows, projection compiler |
| `bash/` | Bash analytics query and projection |
| `providers/` | Model capabilities discovery, provider registry |
| `evidence/` | Receipts, lifecycle, telemetry bundles, Google Drive upload |
| `governance/` | Auth, dirty guard, findings lifecycle |
| `runtime/` | Supervisor, tool invocation |
| `coordination/` | Store, leases, fleet |
| `identity/` | OAuth, consent, token store |
| `extensions/` | IDE extension (vscodium-rig-relay): capability broker, sidecar protocol |

Tests live in `tests/` with test doubles in `tests/stubs/`. Fixtures for contract tests live in `tests/fixtures/`.

## Commands

Always go through `uv` — never invoke bare `python` or `pip`.

- `uv run rig-relay` — launch the Desktop Cockpit (primary surface).
- `uv run rig-relay-acp` — launch the ACP server.
- `uv run rig-relay --help` / `uv run rig-relay-acp --help` — show flags.
- `uv run pytest` — full suite (parallel via `pytest-xdist`).
- `uv run pyright` — strict type check.
- `uv run ruff check --fix .` and `uv run ruff format .` — run both after every code change and report the files modified.
- Useful uv basics: `uv sync`, `uv add <pkg>`, `uv remove <pkg>`.

### CLI tools for file operations

Prefer these over raw `find`/`grep`/`sed`:

- **`rg`** (ripgrep) — fast recursive search: `rg PATTERN [PATH]`
- **`fd`** — fast file find: `fd -e py PATTERN` (vs `find -name`)
- **`sd`** — better `sed`: `sd 'BEFORE' 'AFTER' FILE` (no BSD sed quirks)
- **`sg`** (ast-grep) — AST-aware structural search: `sg -p 'async def $NAME($$$)'`
- **`bat`** — `cat` with syntax highlighting: `bat file.py`
- **`jq`** — JSON query: `jq '.key' file.json`
- **`yq`** — TOML/YAML query: `yq '.project.scripts' pyproject.toml`
- **`hyperfine`** — benchmark commands: `hyperfine 'uv run pytest -n auto' --warmup 2`
- **`difft`** (difftastic) — AST-aware diff: `difft --color always file1.py file2.py`
- **`watchexec`** — auto-run on file change: `watchexec -e py 'uv run pytest -x'`
- **`just`** — command runner (like Make but simpler): `just <recipe>`
- **`eza`** — modern `ls`: `eza --tree --git --icons`

## Module conventions

- `__init__.py` exposes the public API via an explicit `__all__`.
- Private modules are prefixed with `_` (e.g. `_settings.py`, `_config.py`).
- Pydantic models live in `models.py`; configuration in `_settings.py` / `_config.py`.
- Abstract interfaces use the `_port.py` suffix (hexagonal-style ports).
- Tests mirror the source layout; test doubles in `tests/stubs/` are named `Fake*`.

### AgentLoop mixin pattern

The AgentLoop class (`rig_relay/core/agent_loop.py`) delegates responsibility domains to private mixins in `rig_relay/core/_*.py`. Mixins access `self.*` attributes freely (config, messages, stats, backend, tool_manager, telemetry_client, etc.) — they rely on AgentLoop's MRO for attribute resolution. This is intentional; pyright validates them in context of AgentLoop, not in isolation.

**When to extract**: a group of related methods that share a coherent responsibility and don't cross-cut the core orchestration loop (LLM turns, tool execution). The method stays in AgentLoop if it *is* the loop.

Existing mixins:

| Mixin | File | Responsibility |
|---|---|---|
| `LLMCallMixin` | `_llm_call.py` | LLM completion and streaming |
| `ToolResponseMixin` | `_tool_response.py` | Tool response recording and telemetry |
| `PatchGatingMixin` | `_patch_gating.py` | Patch proposal gating for mutation tools |
| `InitHelpersMixin` | `_agent_init.py` | Subsystem construction during init |
| `SessionLifecycleMixin` | `_session_lifecycle.py` | Message history cleanup, session reset, fork |
| `GovernanceMixin` | `_governance.py` | Approval callbacks, tool permissions, session rules |
| `TelemetryMixin` | `_telemetry.py` | Session lifecycle telemetry and context observations |
| `ContextEnvelopeMixin` | `_context_envelope.py` | Context envelope construction and assembly telemetry |
| `MiddlewareMetadataMixin` | `_middleware_metadata.py` | Middleware pipeline setup, result handling, backend metadata |

## Python style

- Prefer `match` / `case` over long `if` / `elif` chains.
- Use the walrus operator `:=` only when it shortens code and improves clarity.
- Be a never-nester: early returns and guard clauses over nested blocks.
- Modern type hints only: built-in generics (`list`, `dict`) and `|` unions. Never import `Optional`, `Union`, `Dict`, `List` from `typing`.
- Use `pathlib.Path` (and `anyio.Path` in async paths) instead of `os.path`.
- Use f-strings, comprehensions, and context managers; follow PEP 8.
- Enums: `StrEnum` / `IntEnum` with `auto()` and UPPERCASE members. For type-mixing, the mix-in type comes before `Enum` in the bases. Add methods or `@property` rather than parallel lookup tables.
- Write declarative, minimalist code: express intent, drop boilerplate.
- Never call a private method from outside its class.
- Avoid comments and docstrings, except for when there's a hard to spot corner case.

## Typing & imports

- Pyright is strict and gates CI; fix types at the source.
- No relative imports — `ban-relative-imports = "all"`. Always `from rig_relay.core.x import …`.
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

### Canonical tools

Two governed, receipt-backed tools form the read/write boundary for agent observations:

- **`rig.get_context`** — read-side. 5 modes (map, packet, handoff, collision, symbols). Returns repo topology, subsystem map, active work lanes, collision warnings, `do_not_touch` list. Agents should call this first before planning or editing.
- **`rig.report`** — write-side. 14 report kinds. Append-only to `.rig/reports/reports.jsonl`. Produces separate `report_sha256` (payload hash) and `event_sha256` (write envelope hash). Reports are raw observations; canonical findings (`docs/findings/out-of-scope-findings.jsonl`) are never mutated by raw agent observations. Ralph reads report projections, not the canonical findings ledger.

### General tool rules

- Subclass `BaseTool` from `rig_relay/core/tools/base.py` with a Pydantic args model and a `BaseToolConfig` generic parameter.
- Implement `async def run(args, ctx: InvokeContext)` and yield events progressively.
- Raise `ToolError` for user-facing failures; raise `ToolPermissionError` for authorization failures.
- Declare permission with `ToolPermission` (`ALWAYS` / `ASK` / `NEVER`); honor it consistently.

### Tool hardening

All built-in tools must pass through security guards. When adding a new tool or modifying `BashTool`, ensure:

- **Environment scrubbing**: `sanitize_env_for_subprocess()` strips 28 sensitive env vars (`ENV_BLOCKLIST`) before any subprocess.
- **Binary rejection**: `is_likely_binary()` header heuristic and `BINARY_EXTENSIONS` block binary reads. `MAX_TEXT_FILE_BYTES` (10 MB) caps read size.
- **Symlink protection**: `resolve_safe_path()` resolves symlinks and rejects traversal outside workspace.
- **Bash rerouting**: `reroute.py` detects `cat`/`head`/`tail` → `read_file`, `grep` → `grep` tool, `git status` → `git_status` tool. Bash rerouting is transparent to the agent — it hijacks the bash call before subprocess execution and checks the target tool's permission first.
- **Bash pattern detection**: `detect_dangerous_bash_patterns()` blocks command substitution, inline code execution, backslash-escaped paths, and env var injection.
- **Sensitive path blocking**: `_SENSITIVE_READ_PATTERNS` prevents reading identity/token files via bash.

## Logging & errors

- Use `from rig_relay.core.logger import logger` — stdlib `logging` with `StructuredLogFormatter`, not `structlog`.
- Configure via env: `LOG_LEVEL` (default `WARNING`), `LOG_MAX_BYTES`. Logs land in `~/.vibe/logs/vibe.log`.
- Pass variables as `%s` positional args, not f-string interpolation: prefer `logger.error("Failed to fetch url=%s", url)` over `logger.error(f"Failed to fetch {url}")`. This defers formatting to the logging framework (only formats if the message is emitted) and keeps messages grep-friendly.
- Define module-local exception hierarchies. Always chain with `raise NewError(...) from e`. Rich exceptions expose a `_fmt()` helper for human-readable output.

## File I/O

- Prefer `rig_relay.core.utils.io.read_safe` / `read_safe_async` / `decode_safe` over raw `Path.read_text()`, `Path.read_bytes().decode()`, or `open()`.
- They return `ReadSafeResult(text, encoding)` and try UTF-8, then BOM detection, then locale, then `charset_normalizer` lazily.
- Pass `raise_on_error=True` only when callers must distinguish corrupt files from valid ones; the default replaces undecodable bytes with U+FFFD.

## Tests

- Stack: `pytest` + `pytest-asyncio` + `pytest-textual-snapshot` + `respx`.
- Mark async tests with `@pytest.mark.asyncio`. Mock outbound HTTP with `respx`.
- Rely on autouse fixtures in `tests/conftest.py` for filesystem and home-dir isolation.
- No docstrings on test functions, methods, or classes — descriptive names like `test_create_user_returns_403_when_unauthorized` carry the intent. Pytest displays docstrings instead of node IDs when present, which hurts.
- Tests are exempt from the `ANN` and `PLR` ruff rules (see `per-file-ignores`).

## Git

- Never use `git commit --amend`, `git push --force`, or `git push --force-with-lease`.
- Always create new commits and push with a plain `git push`.
- If a push is rejected due to upstream changes, rebase onto the updated remote branch — never merge and never force-push.
- **Agent checkpoint commits**: Agents may create local checkpoint commits for session-owned files using the `checkpoint` tool to preserve proven work. Once a lane's release summary is published and a named milestone grants publication authorization, the checkpointed slice must be pushed for remote review. Agents may NOT push, amend, rebase, merge, reset, clean, or commit files outside their mission scope. See `docs/governance/cross-session-coordination.md`.
- Direct `git commit` and `git add` via bash are blocked. Use the `checkpoint` tool instead.
- **Stash**: `git stash` is only permitted for temporary testing with immediate `git stash pop`. Never use stash to discard or hide changes from parallel agent lanes.

## Checkpoint Publication And Review

- Local checkpoint commits are the mechanism for preserving proven, mission-owned work sets.
- Publishing a checkpointed commit is separate from authoring it; publication is only allowed after the release summary is published and a named milestone grants explicit review authorization.
- Only the released or narrowly published slice should be pushed for review. Do not use the publication step to widen the lane or bundle unrelated work.
- Review tooling may inspect the published checkpointed slice, but broader integration work remains deferred unless the released boundary is unsafe or false.

## Release Summary

Every final mission report must include a concise but explanatory summary that says:

- what changed;
- which choices were made and why;
- what codebase research was performed;
- what external sources were consulted, if any;
- how that research led to the conclusion.

Keep the summary short enough to scan, but not so short that it hides the reasoning behind the release. If no external research was needed, say so explicitly.

## Dirty-file preservation

- Any modified, staged, or untracked file that exists before the current mission is PROTECTED. These files contain user-owned or prior-agent-owned changes.
- Before editing, inspect repository state with `git_status`. Dirty files are not yours to freely rewrite.
- When a mission requires editing a protected file:
  - Read it first. Identify existing modified regions.
  - Apply only the mission-required delta. Preserve unrelated edits exactly.
  - Make changes **additive** whenever possible — add new code; avoid removing or rewriting code from parallel lanes.
  - If the work is a bug fix or dead-code deletion, it is acceptable to touch only the broken or dead region on a dirty file as long as the change remains narrow and does not erase other lanes' work.
  - Prefer `search_replace` with targeted SEARCH/REPLACE blocks over `write_file`.
  - For `write_file` on a protected file, set `allow_overwrite_protected=true` and provide `expected_before_sha256`.
  - For `search_replace` on a protected file, provide `expected_before_sha256`.
  - Never run formatters over the whole file unless the mission explicitly requires it.
- Never use `git restore`, `git checkout` (for undo), `git reset`, or `git clean` to discard changes to protected files.
- If a required edit overlaps unknown existing edits, stop and report a structured conflict.
- The final report must distinguish: pre-existing dirty files, files changed by this mission, files skipped, and files with conflicts.

## Ralph: observe-only scanner

Ralph (`rig_relay/ralph/`) is an observe-only scanner that consumes projections from `.rig/reports/indexes/` and `.rig/analytics/bash/indexes/`, ranks candidates (findings, diagnostics, bash replacement candidates, bash risk patterns), and produces mission candidates. Ralph **never mutates** files — it is read-only.

Key components:
- `scanner.py` — `scan_projections()` drives the scan, reads projection JSON, ranks candidates.
- `models.py` — `CandidateKind`, `ScanInput`, `RankedCandidate`, `MissionCandidate`, `ScoreComponents`, `RalphScanResult`.
- `__init__.py` — public API (`scan_projections`, `build_ralph_panel`).

When adding analytics domains, register new `CandidateKind` values, add projection paths to `_load_projection_findings()`, and wire bash/domain kind detection in `_to_candidate()`.

## IDE extension: governed capability broker

The VSCodium extension (`extensions/vscodium-rig-relay/`) is a thin host — it handles IDE APIs and UI only. All durable policy and orchestration lives in the Python sidecar (`rig_relay/cli/ide_sidecar.py`).

The canonical capability manifest (`etc/rig.ide.capability_manifest.v1.json`) is the single authority for all 42 IDE capabilities. Both the TypeScript capability broker and Python sidecar derive from it. Validator: `scripts/rig_relay_validate_ide_manifest.py`.

Protocol docs:
- `docs/protocols/ide-sidecar-ipc.md` — sidecar IPC protocol
- `docs/protocols/ide-capability-map.md` — generated capability map
- `docs/schemas/rig.ide.capability_manifest.v1.schema.json`
- `docs/schemas/rig.ide.capability_receipt.v1.schema.json`
- `docs/schemas/rig.ide.sidecar.message.v1.schema.json`

Contract tests: `tests/fixtures/ide_sidecar/` (8 golden fixtures) and `tests/ide_sidecar/test_sidecar_protocol_fixtures.py` (18 tests).

## Usage data

- Rig Relay emits structured workflow observability data to `~/.rig/relay/sessions/<session_id>/observability.jsonl`. See `docs/governance/usage-data-doctrine.md` for the full governance doctrine.
- **Do not emit raw file contents, secrets, or private code** into observability events. Use SHA256 hashes for everything content-derived.
- **Dirty file snapshots, refusals, files_read, and tests_run** are currently in-memory only. When touching the guard or tool execution path, prefer emitting these as `rig.relay.guard.dirty_snapshot_captured`, `rig.relay.guard.refused_write`, `rig.relay.tool.files_read`, and `rig.relay.tool.tests_run` events.
- New telemetry events: add the event name to `EventName` in `rig_relay/core/telemetry/constants.py`. Follow the `rig.relay.<domain>.<verb>` naming convention.
- New artifacts: subclass the pattern in `rig_relay/core/telemetry/artifacts.py`. Register the artifact kind in the `ArtifactEnvelope` model.
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
- Suggest updates to the README.md file according to feature changes or additions.
- Keep the builtin Vibe Skill (`rig_relay/core/skills/builtins/vibe.py`) up-to-date. It documents the CLI's features, such as args, flags, config options and persistence, commands, built-in agents, file discovery logic.

## JSON Schema Validation

- **Never run `ruff check` or `ruff format` on `docs/schemas/*.json`.** JSON schema files must be validated as JSON with Python's `json` module and as JSON Schema with `jsonschema` (if available), not formatted as Python code. Ruff is a Python linter/formatter; running it on JSON schema files corrupts them by injecting Python syntax.
- Use `scripts/rig_relay_validate_schemas.py` to validate all schemas: `uv run python scripts/rig_relay_validate_schemas.py`.
- `pyproject.toml` excludes `docs/schemas/` from Ruff's scope.
- Schema files must always start with `{` and contain no Python syntax (no `from __future__ import annotations`, `import`, `def`, `class`, `# ruff:`, etc.).
- The regression test `test_no_schema_contains_python_syntax` in `tests/coordination/test_schema_validation.py` automatically detects Python contamination.
- When a request describes a recurring implementation pattern, govern it as a JSON code schema under `docs/json/code_schemas/` and add the canonical schema definition under `docs/schemas/`.
- Check the relevant code schemas before editing implementation files when a task matches a known pattern, and keep the schema authority metadata explicit.

## Conversation Summary Naming

Conversation summaries belong in `docs/conversations/`.
Use this filename pattern:
`YYYY-MM-DD--project--phase-range--topic--kind.md`
Examples:
- `2026-05-13--rig-relay--phase-a-j--orchestration-dataset-control-plane--summary.md`
- `2026-05-14--rig-relay--phase-k--spawn-executor-preflight--handoff.md`
- `2026-05-14--rig-relay--no-phase--checkpoint-refusal-staged-files--incident.md`
Rules:
- Use lowercase kebab-case.
- Use double hyphens between filename fields.
- Use single hyphens inside each field.
- Keep topic to 3–8 words.
- Do not use spaces.
- Do not use vague names like `summary.md`, `notes.md`, or `conversation.md`.
- Add every saved summary to `docs/conversations/README.md`.
- Do not store conversation summaries in `docs/audits/` unless they are converted into an audit.
- Do not store conversation summaries in `docs/dogfood/` unless they are converted into a dogfood proof.
- Validate filenames with the test in `tests/docs/test_conversation_summary_names.py`.

## Reports, audits, roadmaps, and evidence artifacts

Agents must not write mission reports, audit reports, roadmaps, release-candidate reports, final reports, evidence inventories, test inventories, blocker lists, validation ledgers, handoff reports, or phase-convergence reports as new Markdown files.

Markdown is allowed only for explicitly canonical human-facing files listed in this document's allowed Markdown exceptions. `AGENTS.md` may remain Markdown because it is an instruction file. `README.md`, legal notices, security policy, changelog, and code-of-conduct files may remain Markdown or plain text where GitHub or legal conventions require them. Markdown is not an evidence container.

When a mission needs to persist a report, create or update a structured artifact instead:

- Use `.json` for a single report object, roadmap object, audit object, validation summary, inventory, or manifest.
- Use `.jsonl` for append-only event streams, findings ledgers, blocker ledgers, deleted-test ledgers, hardened-test ledgers, coordination ledgers, telemetry/redaction ledgers, and repeated observations.
- Use `.csv` only for tabular exports intended for analysis or release-gate review.

Canonical locations:

- `docs/json/` — durable documentation objects, roadmaps, audit summaries, phase plans, doctrine companions, inventories, and migration manifests.
- `docs/findings/*.jsonl` — append-only out-of-scope findings and debt registries.
- `.build/rig-relay/` or `.build/rig/` — ephemeral local run evidence, validation outputs, generated projections, and non-committed work products.
- `docs/schemas/` — JSON Schema authority for any durable structured artifact kind.

If no schema exists for the report kind, add or extend a schema first. Do not fall back to Markdown because a schema is missing. The absence of a schema means the mission includes schema creation or the report must remain ephemeral and clearly identified as non-canonical.

Final responses in chat may use Markdown for readability, but any persisted final report must also be written as JSON, JSONL, or CSV. A chat-formatted Markdown summary is not a substitute for the canonical artifact.

Required persisted final report shape:

- summary
- branch
- head_before
- head_after
- dirty_state_before
- dirty_state_after
- files_changed
- files_created
- files_deleted
- tests_run
- tests_intentionally_skipped
- test_classifications
- evidence_artifacts
- schema_validation_results
- telemetry_and_redaction_implications
- dependency_changes
- completed_work
- intentionally_deferred_work
- discovered_out_of_scope_risks
- remaining_seams

When an agent finds an existing Markdown report in a directory where structured artifacts are required, it must not add more Markdown beside it. It must either migrate that content into the canonical structured format as part of the mission, or record a structured out-of-scope finding explaining the migration slice needed. Do not delete old Markdown reports until the migration rules below are satisfied.

Forbidden examples:

- `docs/audits/some-audit.md`
- `docs/audits/release-candidate-convergence-spine.md`
- `docs/reports/final-report.md`
- `docs/roadmaps/phase-1-plan.md`
- `docs/proofs/validation-proof.md`
- `mission-report.md`
- `handoff.md`

Preferred examples:

- `docs/json/audits/release_candidate_convergence_spine.v1.json`
- `docs/json/roadmaps/release_candidate_5_phase_roadmap.v1.json`
- `docs/json/testing/test_inventory.v1.json`
- `docs/json/testing/test_classification.v1.jsonl`
- `docs/findings/out-of-scope-findings.jsonl`
- `.build/rig-relay/evidence/validation_run.v1.json`

Every final mission report must explicitly list any Markdown file it created or modified. For each Markdown file, the report must state which allowed exception authorizes it. If there is no allowed exception, the mission is incomplete.

## Documentation Policy — Canonical JSON Artifacts

New project documentation and persisted mission outputs must be written as **canonical JSON artifacts** using the `rig.documentation.page.v1` schema or another repo-local schema for that artifact kind, unless the file is an explicitly allowed Markdown/legal/interface exception.

### Allowed Markdown exceptions
- `AGENTS.md` — agent instructions are conventionally Markdown
- `README.md` — GitHub landing page
- `CONTRIBUTING.md` — contribution UI
- `CONTRIBUTOR_LICENSE_AGREEMENT.md` — legal
- `LICENSE` — must remain plain license text, not JSON
- `ATTRIBUTION.md` — human-readable attribution (JSON companion required)
- `UPSTREAM.md` — upstream attribution and lineage
- `THIRD_PARTY_NOTICES.md` — third-party license notices
- `CHANGELOG.md` — if release tooling requires it
- `SECURITY.md` — if present
- `CODE_OF_CONDUCT.md` — if present

### Migration rules
Old Markdown docs must not be deleted until:
- a JSON replacement exists,
- the JSON replacement validates against a schema,
- the static renderer renders it,
- the migration manifest maps `old_path` to `new_path`,
- references are updated,
- tests pass,
- the deletion is listed in the final report.

Agents must not create new Markdown docs for plans, audits, architecture notes, proofs, reports, roadmaps, or task records. Create new documentation as `.json`, `.jsonl`, or `.csv` artifacts that follow the repo-local schema or tabular convention for the document kind. If no schema exists, add or extend a schema first before writing the doc.

### Static site rendering
The documentation site is rendered locally by `scripts/render_static_docs.py`. The generated static site is committed under `docs/` and published via GitHub Pages from the main branch `/docs` folder. No custom GitHub Actions workflow is required.

Canonical source: `docs/json/`, `docs/schemas/`
Generated site: `docs/index.html`, `docs/pages/`, `docs/assets/`, `docs/search-index.json`, `docs/render-manifest.json`

### Migration manifest
A migration manifest must exist at: `docs/json/documentation_migration_manifest.v1.json`

Fields: `schema_version`, `generated_at`, `policy`, `migrations[]` (each with `old_path`, `new_path`, `status`: pending\|migrated\|deleted\|retained_exception, `reason`, `content_sha256_old`, `content_sha256_new`, `references_updated`, `review_notes`).
