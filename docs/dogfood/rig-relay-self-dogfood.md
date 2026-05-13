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

## Dataset Reports

After dogfood sessions, generate a human-readable dataset summary:

```bash
uv run python scripts/rig_relay_dataset_report.py
```

The report reads coordination events, observability logs, and out-of-scope
findings, and produces `.build/rig-relay/reports/dataset-summary.md` with:

- Session and event counts
- Tool behavior table (success/refused/error by tool name)
- Guard and safety events (dirty-file snapshots, write refusals)
- Coordination breakdown (claims, reservations, conflicts)
- Checkpoint commit/refusal summary
- Provider/model distribution
- Open findings grouped by severity
- Recommended next slices derived from patterns

Reports are content-light and never include raw prompts, model outputs, or
file contents. See the [Usage Data Doctrine](../governance/usage-data-doctrine.md#dataset-reports)
for the full privacy safeguards.

### Dataset Export

After dogfood sessions, export clean derived datasets for machine analysis:

```bash
uv run python scripts/rig_relay_dataset_export.py
```

This produces schema-validated JSONL files under `.build/rig-relay/derived/`:

| Dataset | Rows (current) | Source |
|---------|---------------|--------|
| `cross_session_coordination_dataset.jsonl` | 239 | All `coord.*` events |
| `coordination_conflict_dataset.jsonl` | 0 | Conflicts path |
| `artifact_reuse_dataset.jsonl` | 56 | Artifact publications |
| `checkpoint_eval_dataset.jsonl` | 0 | Checkpoint commits/refusals |
| `tool_failure_patterns_dataset.jsonl` | 81 | Non-success tool calls |
| `provider_task_performance_dataset.jsonl` | 975 | Request accounting events |
| `findings_dataset.jsonl` | 4 | Out-of-scope findings |

These datasets are the machine-readable input to the future marimo interactive
inspector. See the [Usage Data Doctrine](../governance/usage-data-doctrine.md#dataset-exports)
for the full export specification and privacy safeguards.

### Interactive Inspector

After exporting datasets, launch the interactive marimo inspector for
filterable tables, charts, and completeness overviews:

```bash
uv sync --extra inspector
uv run marimo run notebooks/rig_relay_dataset_inspector.py
```

The inspector has 13 reactive view cells: overview stat cards, data quality
metrics, session filters, coordination event breakdowns, conflict analysis,
artifact reuse gap analysis, tool failure patterns, provider performance,
checkpoint stats, findings by severity/kind, file completeness, and about.

The reusable library (`scripts/rig_relay_dataset_inspector_lib.py`) can also
be used directly in Python scripts or tests:

```python
from scripts.rig_relay_dataset_inspector_lib import load_all, compute_summary

datasets = load_all()
summary = compute_summary(datasets)
print(f"Found {summary.total_coordination_rows} coordination events")
```

**Current row counts** (from real data):
- 251 coordination events (69 sessions)
- 59 artifact reuse records
- 81 tool failure records
- 986 provider performance records
- 4 findings (2 high, 2 medium)

See the [Usage Data Doctrine](../governance/usage-data-doctrine.md#interactive-inspector)
for the full inspector specification and privacy safeguards.

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
12.  **Coordination Dataset Row Normalization (Completed 2025-05-17)**: `coord.*` and checkpoint events now emit normalized payload contracts with salted path hashes, content-light fields, and four new evaluation schemas (`rig.relay.cross_session_coordination.v1`, `rig.relay.coordination_conflict.v1`, `rig.relay.artifact_reuse.v1`, `rig.relay.checkpoint_eval.v1`). The coordination event stream is now a real eval substrate for delegate/fleet orchestration analysis.

See the [bash replacement opportunity map](../audits/bash-replacement-opportunity-map.md)
13.  **Review Packet Protocol (Completed 2025-05-18)**: Local review packet creation script (`scripts/rig_relay_create_review_packet.py`) with schema validation, content-light safeguards, 6 review kinds, and 5-file packet layout. JSON Schema at `docs/schemas/rig.relay.review_packet.v1.schema.json`. 14 tests in `tests/coordination/test_review_packet.py`. See the [Review Packet Protocol section in the Usage Data Doctrine](../governance/usage-data-doctrine.md#review-packet-protocol) for the full specification.
14.  **Reviewer Orchestrator Cockpit Protocol (Completed 2025-05-18)**: 4 new JSON Schemas (sprint_cockpit, mission_packet, child_session_result, sprint_aggregate_report) under `docs/schemas/rig.relay.*.v1.schema.json`. Cockpit generator script (`scripts/rig_relay_create_sprint_cockpit.py`) that reads git state, coordination events, dataset report, findings, and checkpoints to produce `.build/rig-relay/cockpit/current_sprint_cockpit.json` and companion Markdown. 18 tests in `tests/coordination/test_sprint_cockpit.py`. See the [Reviewer Orchestrator Doctrine](../governance/reviewer-orchestrator.md) for the protocol specification.
 for the parallel shell-to-typed-tool migration audit.
15.  **Spawn Session Planner (Completed 2025-05-18)**: Dry-run spawn planner (`scripts/rig_relay_spawn_session.py`) with 8 refusal codes, mission packet validation, write overlap detection using `stable_path_key()`, and max-children enforcement. 21 tests in `tests/coordination/test_spawn_session.py`. Schema at `docs/schemas/rig.relay.spawn_plan.v1.schema.json`. See the [Reviewer Orchestrator Doctrine](../governance/reviewer-orchestrator.md) for the planner protocol.
16.  **Current State Pulse (Completed 2025-05-18)**: Live orchestration pulse (`scripts/rig_relay_current_state.py`) that reads coordination sessions/leases/events and derived datasets, then emits a compact, content-light snapshot with per-child risk/heartbeat/reservation info and deterministic recommendations. 15 tests in `tests/coordination/test_current_state.py`. Schema at `docs/schemas/rig.relay.current_state.v1.schema.json`. Also adds `stable_path_key()` to `vibe/core/coordination/_models.py` for cross-process deterministic path comparison, and fixes the spawn planner's overlap detection to use raw paths (not salted export hashes). See the [Reviewer Orchestrator Doctrine](../governance/reviewer-orchestrator.md) for the current state protocol.
17.  **Delegate/Fleet Orchestration Doctrine (Completed 2025-05-18)**: Canonical doctrine document (`docs/governance/delegate-fleet-orchestration.md`) defining delegate, fleet, reviewer/orchestrator, agents-as-tools, handoffs, supervisor graph, stateful orchestration, replay/debug, workspaces, spec-scoped tasks, human oversight, validation stages, and pending work queue. 4 new JSON Schemas: work_item, work_queue, ready_work_plan, parent_convergence_report. Queue planner script (`scripts/rig_relay_queue_plan.py`) with ready/blocked/waiting separation, dependency checking, priority sorting, and write-lease conflict detection. See the [Delegate/Fleet Orchestration Doctrine](../governance/delegate-fleet-orchestration.md).
18.  **Queue Planner Script (Completed 2025-05-18)**: Dry-run ready-work planner (`scripts/rig_relay_queue_plan.py`) that reads a work queue JSON, coordination state, and computes ready/blocked/waiting items with dependency, lease, and priority semantics. 23 tests in `tests/coordination/test_delegate_fleet.py`. Schemas at `docs/schemas/rig.relay.work_item.v1.schema.json`, `docs/schemas/rig.relay.work_queue.v1.schema.json`, `docs/schemas/rig.relay.ready_work_plan.v1.schema.json`, `docs/schemas/rig.relay.parent_convergence_report.v1.schema.json`. See the [Delegate/Fleet Orchestration Doctrine](../governance/delegate-fleet-orchestration.md).
19.  **Schema Validation and Ruff Boundary Hardening (Completed 2025-05-18)**: Schema validation script (`scripts/rig_relay_validate_schemas.py`) that validates all 33 JSON schemas for JSON correctness, Python syntax contamination, and Draft-7 conformance. 12 regression tests in `tests/coordination/test_schema_validation.py` covering all-schemas-parse, no-Python-syntax, forbidden token detection, schema self-validation, and ruff boundary hardening. `pyproject.toml` updated to exclude `docs/schemas/` from Ruff. AGENTS.md updated with hard rule: never run Ruff on `docs/schemas/*.json`. See [AGENTS.md JSON Schema Validation section](../AGENTS.md#json-schema-validation).

## Future Hardening Tracks

1.  **Mutation Evidence Hashing (Completed)**: `write_file` and `search_replace` now emit before/after SHA256 hashes. See [current built-in tools audit](../audits/current-built-in-tools.md).
2.  **Typed File Write/Diff Evidence (Completed)**: `write_file` and `search_replace` now emit structured `file_write` artifact envelopes and diff/patch evidence for write tools. Rollback and semantic placement remain future work.
3.  **Dirty-File Preservation Guard (Completed)**: `DirtyFileGuard` now captures protected dirty files at session start and gates write operations. `write_file` and `search_replace` require `expected_before_sha256` for edits to pre-existing dirty files. Destructive git commands are blocked in `bash`. See [current built-in tools audit](../audits/current-built-in-tools.md).
4.  **Fuzzy Search Hardening (Deferred)**: Audit fuzzy matching behavior in `search_replace` to reduce wrong-edit risk at the matching threshold boundary.
5.  **Semantic Placement (Deferred)**: Audit `semantic_placement` artifacts to ensure edits land in the correct symbols.
6.  **Token Optimization**: Analyze artifact kind density to identify candidates for summarization or deduplication based on [Artifact Schema Doctrine](../audits/artifact-schema-doctrine.md).

## Appendix: Conversation Summaries

Conversation summaries now live in `docs/conversations/` with a canonical naming convention (`YYYY-MM-DD--project--phase-range--topic--kind.md`). See [`docs/conversations/README.md`](../conversations/README.md) for the schema and index.
