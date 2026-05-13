# Rig Relay Self-Dogfood Workflow

This document outlines how to use Rig Relay to build and harden Rig Relay, using its own evidence system to identify determinism gaps and tool failures. Rig Relay is the product; providers are interchangeable backends.

Out-of-scope findings discovered during dogfood sessions are recorded in the [findings registry](../findings/out-of-scope-findings.md).

## Operational Workflow

### 1. Starting a Self-Dogfood Session

To use Rig Relay on itself, run it from the root of the Rig Relay repository. By default, evidence will be stored in your global Relay home (`~/.rig/relay`):

```bash
cd rig-relay
rig-relay "Help me implement a new tool determinism check"
```

### 2. Setting Evidence Root for Dogfood

Normal dogfood sessions should use the global Relay home. However, to isolate a test or experiment (e.g., to keep dogfood evidence separate from your main history), use `RIG_RELAY_HOME`:

```bash
RIG_RELAY_HOME=./.dogfood rig-relay "Audit the grep tool for determinism"
```

### 3. Allowed Workflows

- Implementing new features in `vibe/core`.
- Refactoring built-in tools.
- Adding tests.
- Auditing existing sessions.
- Updating documentation.

### 4. Disallowed Workflows

- Mutating `.rig/relay` home directory (unless testing migration).
- Overwriting existing evidence in a way that breaks validation.
- Implementing autonomous merging without human review.
- Creating unstructured artifacts that do not adhere to [Artifact Schema Doctrine](../audits/artifact-schema-doctrine.md).

### 5. Post-Session Validation

After a dogfood session, validate the evidence. If you used the default global home, you don't need to pass `--evidence-root`. If you used an isolated root (e.g., via `RIG_RELAY_HOME=./.dogfood`), point the doctor there:

```bash
rig-relay doctor evidence --evidence-root ./.dogfood --session <SESSION_ID>
```

> [!NOTE]
> When using `RIG_RELAY_HOME=./.dogfood`, the evidence root passed to the doctor is `./.dogfood`.

### 6. Inspecting Tool Determinism

Use the specialized reporter to see how tools behaved:

```bash
rig-relay doctor tool-determinism --evidence-root ./.dogfood --session <SESSION_ID>
```

### 7. Inspecting Tool Reasoning and Latency

Rig Relay records structured reasoning traces for every tool call — latency, byte sizes, determinism class, and observable rationale — without capturing hidden chain-of-thought.

Report with the reasoning tracer:

```bash
rig-relay doctor tool-reasoning --evidence-root ./.dogfood --session <SESSION_ID>
```

JSON output is supported:

```bash
rig-relay doctor tool-reasoning --evidence-root ./.dogfood --session <SESSION_ID> --json
```

The report shows:
- Slowest tool calls (latency candidates)
- Largest inline outputs (token-pressure candidates)
- Largest artifacted outputs
- Calls missing observable rationale
- Retry/error patterns
- Aggregate latency and byte metrics

### 8. Cross-Session Coordination

When multiple Rig Relay sessions are active, use the coordination plane described in [Cross-Session Coordination](../governance/cross-session-coordination.md) to publish claims, leases, heartbeats, artifacts, and conflicts.

Do not coordinate through free-form transcript sharing when a typed coordination update will do.

Coordination events (`coord.*`) are not just operational state — they feed the derived evaluation datasets defined in the [Usage Data Doctrine](../governance/usage-data-doctrine.md). Every path reservation, conflict report, artifact publication, and handoff becomes measurable behavioral evidence for future fleet/delegate orchestration.

## Latency-First Design Principle

Tool-output latency takes priority over model magic. The fastest latency wins come from making tools produce compact, typed, reusable artifacts so the model sees handles + summaries instead of huge raw outputs. Tool content should stay in the dynamic suffix (later in the prompt) so stable prefixes remain cacheable.

## Classification Guidelines

When you find a tool determinism issue:
1. Identify if it's **Model Nondeterminism** (the LLM chose different args) or **Tool Nondeterminism** (the tool gave different output for same args).
2. For Tool Nondeterminism, check if it's due to:
    - Path normalization issues.
    - Filesystem traversal order.
    - Timestamp leakage.
    - Environment variable sensitivity.
3. Open a "Tool Hardening" mission to address the gap.

## Determinism Goal

Tool execution should become deterministic given:
- Same normalized input.
- Same repository snapshot.
- Same environment contract.
## Tool Hardening Backlog (Prioritized)

Based on initial evidence collection, the following areas are prioritized for tool hardening:

1.  **Mutation Evidence Hashes (Completed 2025-05-17)**: `write_file` and `search_replace` now emit before/after SHA256 content hashes, creation/overwrite flags, block counts, and changed file lists. See `WriteFileResult` and `SearchReplaceResult`.
2.  **Typed File Write/Diff Artifacts (Completed 2025-05-13)**: `write_file` and `search_replace` now emit structured `file_write` artifact envelopes with unified diff evidence, byte/line counts, and changed-line ranges. Rollback and semantic placement remain deferred.
3.  **Dirty-File Preservation Guard (Completed 2025-05-18)**: `DirtyFileGuard` captures protected dirty files at session start via `git status --porcelain=v1`. `write_file` and `search_replace` now require `expected_before_sha256` for edits to pre-existing dirty files. Destructive git commands (`restore`, `reset`, `clean`, `stash`) are blocked in `bash`. Fields exposed through ACP/tool schemas.
4.  **Typed Search Results (Completed 2026-05-13)**: `grep` now emits typed search query and search result artifacts with deterministic ordering, backend, counts, truncation flags, and result-set hashes.
5.  **Path Normalization (High)**: Ensure all file-based tools (`read_file`, `write_file`, `grep`, `search_replace`) use absolute, canonicalized paths in evidence, even if models pass relative paths.
6.  **Bash Output Filtering (Medium)**: Scrub environment-specific details (paths, usernames) from `bash` tool output to improve cache hit rates.
7.  **Git State Capture (Medium)**: `git_status` now emits typed repo-state evidence. Extend the remaining git tools with comparable structured artifacts.
8.  **Task Session Linkage (Low)**: `task` now emits a typed `task_session_link` artifact with parent/child IDs, provider/options metadata, scope metadata, and child manifest hashes when available. The fleet path now returns a read-only aggregated report with child summaries for non-overlapping specs. The remaining gap is child-artifact rollup.
9.  **Fleet Validation (Low)**: `task` now accepts read-only `TaskFleetSpec` packets and returns a validation report that flags path overlaps before scheduling. The scheduler itself is still deferred.
10.  **Traversal Determinism (Low)**: Enforce sorted file listing in `grep` and `read_file` (when reading directories) to prevent OS-level nondeterminism.
11.  **Thinking Delegation Boundary (Low)**: Keep thinking-mode delegation opt-in and provider-scoped; default task runs should remain non-thinking.

See the [bash replacement opportunity map](../audits/bash-replacement-opportunity-map.md) for the parallel shell-to-typed-tool migration audit.

## Future Hardening Tracks

1.  **Mutation Evidence Hashing (Completed)**: `write_file` and `search_replace` now emit before/after SHA256 hashes. See [current built-in tools audit](../audits/current-built-in-tools.md).
2.  **Typed File Write/Diff Evidence (Completed)**: `write_file` and `search_replace` now emit structured `file_write` artifact envelopes and diff/patch evidence for write tools. Rollback and semantic placement remain future work.
3.  **Dirty-File Preservation Guard (Completed)**: `DirtyFileGuard` now captures protected dirty files at session start and gates write operations. `write_file` and `search_replace` require `expected_before_sha256` for edits to pre-existing dirty files. Destructive git commands are blocked in `bash`. See [current built-in tools audit](../audits/current-built-in-tools.md).
4.  **Fuzzy Search Hardening (Deferred)**: Audit fuzzy matching behavior in `search_replace` to reduce wrong-edit risk at the matching threshold boundary.
5.  **Semantic Placement (Deferred)**: Audit `semantic_placement` artifacts to ensure edits land in the correct symbols.
6.  **Token Optimization**: Analyze artifact kind density to identify candidates for summarization or deduplication based on [Artifact Schema Doctrine](../audits/artifact-schema-doctrine.md).
