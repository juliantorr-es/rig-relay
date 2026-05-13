# Current Built-In Tool Inventory

> Audit date: 2025-05-13
> Branch: main
> HEAD: 8986750
> See `docs/audits/data/current_builtin_tools.jsonl` for machine-readable records.
> See also: [bash replacement opportunity map](bash-replacement-opportunity-map.md)
> Out-of-scope findings from tool audits are recorded in the [findings registry](../findings/out-of-scope-findings.md).

## Executive Summary

| Metric | Value |
|--------|-------|
| **Total built-in tools found** | 18 |
| **Read-only tools** | 12 (ask_user_question, exit_plan_mode, git_branch, git_diff, git_log, git_ls_files, git_show, git_status, grep, read_file, skill, web_fetch, web_search) |
| **Workspace-mutating tools** | 4 (bash, search_replace, task, write_file) |
| **External/network/provider tools** | 5 (ask_user_question, bash, task, web_fetch, web_search) |
| **Tools with typed artifacts today** | 3 (grep, git_status, task — search, repo-state, and delegation-link artifacts) |
| **Unknown/unclassified tools** | 0 — all 18 have explicit determinism + mutation classes |
| **Biggest annoyance pattern** | No structured evidence fields emitted at tool level — determinism/mutation is declared but not instrumented in tool output, making dogfood session analysis reliant on agent-loop instrumentation alone |
| **Highest-priority hardening target** | `search_replace` — highest wrong-edit risk due to fuzzy matching with no before/after content hash in evidence |

### Classification Summary

- **Determinism**: 1 `deterministic_pure` (todo, exit_plan_mode), 11 `deterministic_repo_state`, 1 `nondeterministic_provider` (task), 4 `nondeterministic_external_io` (bash, webfetch, websearch, ask_user_question)
- **Mutation**: 12 `read_only`, 3 `writes_workspace` (bash, search_replace, write_file), 1 `writes_temp_only` (todo), 1 `nondeterministic_provider` + `writes_workspace` (task)

## Inventory Table

| Tool | Purpose | Determinism | Mutation | External IO | Typed Artifacts | Main Annoyance | Priority | Next Action |
|------|---------|-------------|----------|-------------|-----------------|----------------|----------|-------------|
| `ask_user_question` | Ask user questions with choices | nondeterministic_external_io | read_only | Yes (user) | No | Blocks agent loop | P3 | Add question count + cancel status to evidence |
| `bash` | Run shell commands | nondeterministic_external_io | writes_workspace | Yes (subprocess) | No | Unstructured output, env-sensitive | P0 | Add command SHA256 + env fingerprint to evidence |
| `exit_plan_mode` | Signal plan complete, switch modes | deterministic_pure | read_only | Yes (user) | No | Only usable in plan mode | P3 | Add user decision to evidence |
| `git_branch` | List branches | deterministic_repo_state | read_only | No | No | Variable output format | P1 | Add HEAD hash to evidence |
| `git_diff` | Show changes | deterministic_repo_state | read_only | No | No | Truncation on large diffs | P1 | Add HEAD hash + stat summary to evidence |
| `git_log` | Show commit logs | deterministic_repo_state | read_only | No | No | Format varies | P1 | Add HEAD hash to evidence |
| `git_ls_files` | List tracked files | deterministic_repo_state | read_only | No | No | Unstable order | P1 | Add HEAD hash + file count to evidence |
| `git_show` | Show objects | deterministic_repo_state | read_only | No | No | Large object truncation | P1 | Add ref SHA256 to evidence |
| `git_status` | Show working tree | deterministic_repo_state | read_only | No | **Yes** (git_state) | Output shape varies by args | P1 | Add ignored-file counts when a read-only probe is warranted |
| `grep` | Search files with regex | deterministic_repo_state | read_only | No | **Yes** (search_query, search_result) | Unstable result order | P0 | Sort results by path+line for determinism |
| `read_file` | Read file with line range | deterministic_repo_state | read_only | No | No | Byte-boundary truncation | P2 | Add content SHA256 + line count to evidence |
| `search_replace` | Apply SEARCH/REPLACE edits | deterministic_repo_state | writes_workspace | No | No | Fuzzy matching can apply wrong edits | P0 | Add before/after SHA256 + diff patch to evidence |
| `skill` | Load a skill | deterministic_repo_state | read_only | No | No | Sampled file listing | P2 | Add SHA256 of loaded content to evidence |
| `task` | Delegate to subagent | nondeterministic_provider | writes_workspace | Yes (provider) | Yes (task_session_link) | Child artifact rollup still missing | P1 | Aggregate child artifact manifest hashes into linkage evidence |
| `todo` | Manage todo list | deterministic_pure | writes_temp_only | No | No | Ephemeral in-memory state | P3 | Add state SHA256 to evidence |
| `web_fetch` | Fetch URL content | nondeterministic_external_io | read_only | Yes (network) | No | HTML→MD conversion is lossy | P2 | Add content SHA256 + timestamp to evidence |
| `web_search` | Search web via Mistral | nondeterministic_external_io | read_only | Yes (provider) | No | Provider may not use web_search | P2 | Add query SHA256 + source count to evidence |
| `write_file` | Create/overwrite file | deterministic_repo_state | writes_workspace | No | No | No preview/diff before overwrite | P0 | Add before/after SHA256 + snapshot ref to evidence |

## Detailed Tool Notes

### `bash` — Bash

**What it does**: Runs a shell command with configurable timeout and output cap. Supports allowlist/denylist command patterns. Captures stdout + stderr.

**What it's good for**: One-off system operations, build commands, and when no typed built-in exists.

**What is annoying about it**:
- Output is fully unstructured — the LLM sees raw text that may contain paths, timestamps, environment variables that differ across runs
- Environment injection (`CI=true`, `NO_TTY=1`, `DEBIAN_FRONTEND=noninteractive`) helps stability but is not documented in evidence
- Can mutate git state even though the tool's mutation_class is `writes_workspace` — there's no `mutates_git_state` assertion
- Large outputs get silently truncated
- `SHELL` env var and subprocess encoding are platform-dependent

**Determinism risks**:
- Same command + same repo ≠ same output (time, env, filesystem state)
- No input SHA256 stored — can't prove command was identical across calls
- No output SHA256 stored — can't detect output changes

**Evidence currently available**: None at tool level. Agent-loop instrumentation captures tool_call_completed events but the tool itself emits no evidence artifacts.

**Missing evidence**:
- Command SHA256
- Output SHA256
- Workdir-relative path normalization on output
- Return code structured field
- Command category (read/write/network/git)

**Recommended hardening**:
- Add tree-sitter-bash parsed command list to evidence
- Emit structured evidence with stdout_truncated, stderr_truncated, returncode fields
- Add environment fingerprint (SHELL, platform) to evidence

---

### `grep` — Grep

**What it does**: Searches repository text using ripgrep (preferred) or GNU grep fallback. Handles `.vibeignore` patterns and default exclusions.

**What it's good for**: Fast code search with regex support, backend auto-detection.

**What is annoying about it**:
- Result order is filesystem-traversal-dependent — no `--sort` flag used
- Ripgrep and grep backends produce different output formats
- Truncation at match count AND byte cap can silently lose results
- No fuzzy search support from the model side
- The `use_default_ignore` parameter creates non-determinism when `.gitignore` changes between calls

**Determinism risks**:
- `DETERMINISTIC_REPO_STATE` is correct but fragile — file traversal order is OS-dependent
- Backend auto-detection (rg vs grep) differs by machine
- No sorted output means same repo + same pattern ≠ same result text

**Evidence currently available**: Typed `search_query` and `search_result` artifacts are written to the session artifacts directory, with deterministic ordering and backend/count metadata in the search-result payload.

**Missing evidence**:
- Query-side include/exclude globs still come from tool defaults rather than explicit user args
- `absolute_offset`/`submatch_*` remain unavailable from the current line-oriented grep backend

**Recommended hardening**:
- Keep path/line ordering normalized in artifact evidence and preserve it across backend fallbacks (P0)
- Add richer offsets/submatch spans if/when the grep backend exposes them without changing command behavior

---

### `read_file` — ReadFile

**What it does**: Reads a text file from a specific line range, capped by `max_read_bytes`. Uses anyio for async I/O and safe encoding detection.

**What it's good for**: Bounded file reads for code review and context gathering.

**What is annoying about it**:
- Truncation at byte boundary, not line boundary — can produce partial last line
- No symbol context or semantic framing of the content being read
- AGENTS.md injection (`get_result_extra`) changes the output the LLM sees vs the raw file content, which is a feature but makes pure determinism claims harder
- No content hash means repeated reads of the same file can't be deduplicated at the evidence level

**Determinism risks**:
- `DETERMINISTIC_REPO_STATE` is correct for file content
- But AGENTS.md injection varies with what AGENTS.md files exist along the path

**Evidence currently available**: None at tool level.

**Missing evidence**:
- Content SHA256
- Line count structured field
- Truncation flag as structured field
- AGENTS.md injection flag

**Recommended hardening**:
- Add content SHA256 to `ReadFileResult`
- Emit evidence with content_hash, line_count, was_truncated

---

### `search_replace` — SearchReplace

**What it does**: Applies SEARCH/REPLACE blocks with fuzzy matching support to edit files. Supports code-fenced and bare blocks.

**What it's good for**: Making targeted edits without reading the full file.

**What is annoying about it**:
- Fuzzy matching can apply the wrong edit silently — the "closest" match may not be the intended one
- SEARCH block matching is fragile (whitespace, trailing newlines)
- No diff preview before applying
- On partial application, some blocks succeed and others fail, leaving file in inconsistent state
- No rollback mechanism if edits go wrong
- Context display in errors is valuable but adds tokens

**Determinism risks**:
- `DETERMINISTIC_REPO_STATE` — same SEARCH/REPLACE on same file state produces same result
- But fuzzy matching introduces non-determinism at the matching threshold boundary

**Evidence currently available**:
- `before_file_sha256: dict[str, str]` — SHA256 of file bytes before edits, keyed by repo-relative path
- `after_file_sha256: dict[str, str]` — SHA256 of file bytes after edits
- `changed_files: list[str]` — files with non-zero line changes
- `total_block_count`, `blocks_applied` (already present), `failed_block_count`

**Missing evidence** (deferred):
- Structured diff/patch artifact (deferred)
- Per-block apply details (deferred)
- Fuzzy match placement hardening (deferred)

**Implemented hardening (2025-05-17)**:
- Added `before_file_sha256`, `after_file_sha256`, `changed_files`, `failed_block_count`, `total_block_count` to `SearchReplaceResult`

---

### `git_*` — Git tools (status, diff, log, branch, show, ls_files)

**What they do**: Read-only Git operations with structured args models and unified error handling.

**What they're good for**: Repository state inspection without shell escape.

**What is annoying about them**:
- All six are in one file but registered as separate tools
- Output format varies by flags (short vs porcelain, oneline vs full)
- Only `git_status` currently emits a typed evidence artifact
- No structured result for the other git tools yet beyond raw output and truncation flags
- Wrong-edit risk is low since they're read-only, but the git tools themselves track `READ_ONLY` even though `bash` can do git write operations

**Determinism risks**:
- `DETERMINISTIC_REPO_STATE` is correct
- But without HEAD hash in evidence, two calls on different commits look the same in the determinism log

**Evidence currently available**: Typed `git_state` artifact for `git_status`, with branch, HEAD, dirty-file counts, upstream counts when available, and a deterministic state hash.

**Missing evidence**:
- Ignored-file counts without an extra read-only probe
- Structured evidence for `git_diff`, `git_log`, `git_branch`, `git_show`, and `git_ls_files`

**Recommended hardening**:
- Add typed per-tool evidence for the remaining git read-only surfaces

---

### `task` — Task (subagent delegation)

**What it does**: Delegates a task to a subagent (default: `explore`) for independent execution in its own AgentLoop, with an explicit provider/options envelope when callers need it.

**What it's good for**: Parallel exploration, research, or isolated work that doesn't need user interaction.

**What is annoying about it**:
- Subagent can make arbitrary tool calls including file writes and git mutations
- No way to observe or audit the subagent's tool calls from the parent session
- Error propagation is lossy — just `[Subagent error: {e}]`
- No evidence shard capture from subagent — subagent tool calls are invisible in the parent evidence
- Subagent writes files in the workspace without those writes being tracked in parent evidence
- `writes_workspace` mutation class is correct but the scope of writes is completely opaque
- Thinking-mode delegation is opt-in and should stay off by default for normal deterministic workflows

**Determinism risks**:
- `NONDETERMINISTIC_PROVIDER` — subagent uses an LLM, outputs are inherently non-deterministic
- But the lack of subagent call evidence means we can't even measure how non-deterministic

**Evidence currently available**: Task results now record provider, model, thinking request state, tool-access/result-compression policy, a deterministic task-result hash, a typed `task_session_link` artifact with parent/child IDs, scope metadata, and manifest hashes when available, plus a read-only fleet report that validates overlaps, schedules non-overlapping children in parallel, and returns child summaries.

**Missing evidence**:
- Subagent tool call evidence shard references
- Subagent workspace delta (files created/modified)
- Subagent message count and completion status
- Explicit attachment of task metadata to the parent evidence stream
- Child artifact manifest rollup for parent audit summaries
- Typed task packets for scope/policy validation
- Read-only fleet reports for parallel planning and parallel child execution
- Cross-session coordination primitives for claims, leases, artifacts, and conflicts

**Recommended hardening**:
- Link subagent session UUID in parent evidence
- Capture subagent tool-call evidence shards with parent session reference
- Add after-task file diff to detect workspace mutations
- Add task-level evidence for provider/options selection when delegation is thinking-enabled
- Add coordination-plane evidence so sessions can publish claims, leases, and handoffs in real time

---

### `web_fetch` — WebFetch

**What it does**: Fetches URL content, converts HTML to Markdown, handles bot detection with honest-UA fallback.

**What it's good for**: Reading documentation, blog posts, and web content.

**What is annoying about it**:
- HTML→Markdown conversion is lossy — tables, code blocks, and structure can degrade
- Content changes between fetches — no caching
- Bot detection (Cloudflare challenge) can cause inconsistent results
- Large page truncation loses context
- User-Agent header is configurable but default is a Chrome UA string

**Determinism risks**:
- `NONDETERMINISTIC_EXTERNAL_IO` — same URL ≠ same content over time
- Content-Type header determines whether HTML→MD conversion runs, so a server changing its Content-Type changes tool output

**Evidence currently available**: None at tool level.

**Missing evidence**:
- Content SHA256
- Fetch timestamp
- HTTP status code
- Content-Type used for conversion decision

**Recommended hardening**:
- Add content_sha256, fetch_timestamp, http_status to evidence

---

### `web_search` — WebSearch

**What it does**: Searches the web via Mistral API with web_search tool integration.

**What it's good for**: Current events, documentation lookups, fact-checking.

**What is annoying about it**:
- Requires `MISTRAL_API_KEY` env var — not available defaults
- The Mistral model may or may not actually call the web_search tool (depends on provider)
- No caching — same query costs tokens every time
- Results vary by time and location
- Source attribution is fragile (ToolReferenceChunk may be empty)

**Determinism risks**:
- `NONDETERMINISTIC_EXTERNAL_IO` — results vary by time, provider state, model version
- Provider model choice affects whether web search is even used
- No query SHA256 to compare across calls

**Evidence currently available**: None at tool level.

**Missing evidence**:
- Query SHA256
- Source count and list
- Provider response time
- Whether web_search tool was actually invoked by the model

**Recommended hardening**:
- Add query_sha256, source_count, response_time to evidence

---

### `write_file` — WriteFile

**What it does**: Creates or overwrites a UTF-8 file with configurable parent directory creation. Requires `overwrite=True` for existing files.

**What it's good for**: Writing new files and safe overwrites.

**What is annoying about it**:
- The `overwrite` safety is a boolean gate — once set, no additional safety net
- No diff/preview — the tool just writes without showing what changed
- No rollback on write errors
- Silently creates parent directories (`create_parent_dirs` defaults to True)
- Byte limit silently rejects writes over `max_write_bytes` with no preview of what was lost

**Determinism risks**:
- `DETERMINISTIC_REPO_STATE` — same write on same repo state = same outcome
- But parent directory creation changes filesystem state even on "canceled" writes (because `_prepare_and_validate_path` creates dirs before `_write_file`)

**Evidence currently available**:
- `before_sha256` (``sha256:`` hex of file bytes before write, or ``None`` for new files)
- `after_sha256` (``sha256:`` hex of file bytes after write)
- `created_file` / `overwrote_existing_file` flags
- `parent_dirs_created` flag
- `bytes_written` count
- Typed `file_write` envelope artifact with unified diff, byte/line counts, and changed-line ranges

**Missing evidence** (deferred):
- Rollback capability (deferred)
- Semantic placement evidence (deferred)
- Fuzzy-match placement hardening for `search_replace` (deferred)

**Implemented hardening (2025-05-17)**:
- Added `before_sha256`, `after_sha256`, `created_file`, `overwrote_existing_file`, `parent_dirs_created` to `WriteFileResult`
- Added typed `file_write` artifact emission for `write_file` and `search_replace`
- Added `expected_before_sha256` and `allow_overwrite_protected` safety fields to `WriteFileArgs` and `SearchReplaceArgs`
- Added `DirtyFileGuard` runtime — captures protected dirty files at session start via `git status --porcelain=v1`, gates write operations on dirty files, blocks destructive git commands (`restore`, `reset`, `clean`, `stash`) in bash

---

### `skill` — Skill

**What it does**: Loads a skill by name, returning its content with sampled file listing. Low-risk, no mutations.

**Notable**: The only tool with `resolve_permission` returning `ALWAYS` unconditionally.

---

### `todo` — Todo

**What it does**: In-memory todo list with read/write actions. `deterministic_pure` + `writes_temp_only`. Ephemeral — lost on process exit.

---

### `ask_user_question` — AskUserQuestion

**What it does**: Presents questions with 2-4 choices plus optional free-text input. Requires interactive UI callback.

---

### `exit_plan_mode` — ExitPlanMode

**What it does**: Asks user to confirm switching from plan to implementation mode. Only usable in plan mode agent profile.

---

## Annoyance Ranking

Ranked by composite score of risk, frequency, token waste, and wrong-edit potential:

| Rank | Tool | Risk Score | High Risk? | High Frequency? | Token Waste? | Wrong Edit? | Easiest to Harden? | Blockers for Autonomy |
|------|------|------------|-----------|---------------|-------------|------------|-------------------|----------------------|
| 1 | `search_replace` | Critical | Yes (fuzzy wrong edits) | High | High | Yes | Medium | **Biggest wrong-edit risk** |
| 2 | `bash` | Critical | Yes (unstructured, env-sensitive) | High | High | Yes | Hard | Uncontrolled mutations |
| 3 | `write_file` | High | Yes (no preview) | High | Medium | Yes | Easy | No before/after diff |
| 4 | `task` | High | Yes (opaque subagent) | Medium | High | Yes | Medium | No subagent observability |
| 5 | `grep` | High | No (read-only) | High | Medium | No | **Easy** | Result ordering unstable |
| 6 | `web_search` | Medium | No | Medium | High | No | Medium | Provider dependency |
| 7 | `web_fetch` | Medium | No | Medium | Medium | No | Medium | Content volatility |
| 8 | `git_diff` | Medium | No | High | Medium | No | **Easy** | Missing HEAD hash |
| 9 | `read_file` | Low | No | High | Low | No | **Easy** | Missing content hash |
| 10 | `git_status` | Low | No | High | Low | No | **Easy** | Missing HEAD hash |

## Hardening Priority Map

| Priority | Count | Tools |
|----------|-------|-------|
| **P0** | 4 | bash, grep, search_replace, write_file |
| **P1** | 7 | git_branch, git_diff, git_log, git_ls_files, git_show, git_status, task |
| **P2** | 4 | read_file, skill, web_fetch, web_search |
| **P3** | 3 | ask_user_question, exit_plan_mode, todo |

### P0 Rationale

- **search_replace**: Fuzzy matching can silently corrupt files. Now protected by `expected_before_sha256` guard — edits to pre-existing dirty files require a hash match. Still the highest wrong-edit risk tool in the inventory.
- **write_file**: Can overwrite works without traceability. Now protected by `allow_overwrite_protected` + `expected_before_sha256` guard — whole-file overwrites of dirty files are refused by default.
- **grep**: Already has typed artifact support but unstable result ordering undermines determinism. Sorting results is a trivial fix.
- **bash**: Highest blast radius — uncontrolled mutations, no evidence trail. Hardest to harden fully but partial evidence (SHA256, command parse) is low-hanging fruit.

### P1 Rationale

- **git tools**: All share the same missing HEAD hash pattern. Adding it is a one-line change per tool that dramatically improves evidence traceability.
- **task**: Subagent isolation is architecturally complex, but session linkage and child manifest hashes are now available; the remaining gap is rollup quality.

### P2 Rationale

- **read_file**: Low risk, but content SHA256 is cheap and useful for cache dedup.
- **web_fetch / web_search**: External IO tools are inherently non-deterministic, but adding evidence fields improves auditability.
- **skill**: Low usage frequency, low risk.

### P3 Rationale

- **ask_user_question, exit_plan_mode, todo**: UX polish tools. Low risk, low frequency, or ephemeral. Not worth hardening before higher priorities.

## Recommended Next Implementation Slice

**Slice: Typed `file_write` artifact and diff/patch evidence**

**Why this slice**:

1. **Completes the mutation evidence chain**: Before/after hashes tell us *that* a file changed. Typed artifacts tell us *how* — structured diff patches for search_replace, file_write envelopes for write_file.
2. **Enables autonomous promotion gates**: Diff evidence is needed to decide whether an edit is safe to auto-approve.
3. **Prerequisite for rollback**: Before/after hashes are present now; diff patches complete the rollback story.

**Deferred from this slice**:
- Semantic placement artifacts
- Full autonomous merging

---

## Cross-Links

- Existing inventory: [`docs/audits/tool-determinism-inventory.md`](./tool-determinism-inventory.md) — add cross-reference
- JSONL data: [`docs/audits/data/current_builtin_tools.jsonl`](./data/current_builtin_tools.jsonl)
- Self-dogfood docs: [`docs/dogfood/rig-relay-self-dogfood.md`](../dogfood/rig-relay-self-dogfood.md)
- Tool contracts: [`vibe/core/telemetry/tool_contract.py`](../../vibe/core/telemetry/tool_contract.py)
- Artifact schemas: [`docs/audits/artifact-schema-doctrine.md`](./artifact-schema-doctrine.md)
- Governance: [Cross-Session Coordination](../governance/cross-session-coordination.md), [Usage Data Doctrine](../governance/usage-data-doctrine.md)
