# Tool Determinism Inventory

This document tracks the determinism and mutation characteristics of Rig Relay built-in tools. All tool evidence and artifacts must adhere to the [Artifact Schema Doctrine](../audits/artifact-schema-doctrine.md).

See also the [bash replacement opportunity map](bash-replacement-opportunity-map.md) for shell-to-typed-tool migration priorities.

## Reasoning Traces

Rig Relay records **observable reasoning traces** for every tool call, not raw hidden chain-of-thought. See `docs/schemas/rig.relay.artifact.tool_reasoning_trace.v1.schema.json`.

Trace records include:
- Latency (ms) per tool call
- Input/output byte sizes
- Output kind (inline vs artifacted vs error)
- Determinism and mutation class
- Observable rationale summaries (empty when provider does not expose them)

These traces power the `rig-relay doctor tool-reasoning` report for identifying latency bottlenecks and token-pressure candidates.

## Inventory

| Tool Name | Module | Determinism Class | Mutation Class | Input Normalization | Output Normalization | Evidence Coverage |
|-----------|--------|-------------------|----------------|---------------------|----------------------|-------------------|
| `read_file` | `builtins.read_file` | `deterministic_repo_state` | `read_only` | High (Path normalization) | High (UTF-8, line range) | Full |
| `write_file` | `builtins.write_file` | `deterministic_repo_state` | `writes_workspace` | High | High | Full (before/after SHA256, creation/overwrite flags, parent dirs) |
| `grep` | `builtins.grep` | `deterministic_repo_state` | `read_only` | High | Medium (Recursive order) | Full (typed search_query/search_result with backend/count/order evidence) |
| `bash` | `builtins.bash` | `nondeterministic_external_io` | `writes_workspace` | Low | Low | Full |
| `git` | `builtins.git` | `deterministic_repo_state` | `read_only` | Medium | Medium | Full |
| `websearch` | `builtins.websearch` | `nondeterministic_external_io` | `read_only` | High | Low (Provider dependent) | Full |
| `webfetch` | `builtins.webfetch` | `nondeterministic_external_io` | `read_only` | High | Low | Full |
| `ask_user_question` | `builtins.ask_user_question` | `nondeterministic_external_io` | `read_only` | N/A | N/A | Full |
| `search_replace` | `builtins.search_replace` | `deterministic_repo_state` | `writes_workspace` | High | High | Full (before/after per-file SHA256, block counts, changed files) |
| `skill` | `builtins.skill` | `deterministic_repo_state` | `read_only` | High | Medium | Full |
| `task` | `builtins.task` | `nondeterministic_provider` | `writes_workspace` | Medium | Low | Full |
| `todo` | `builtins.todo` | `deterministic_pure` | `writes_temp_only` | High | High | Full |
| `exit_plan_mode` | `builtins.exit_plan_mode` | `deterministic_pure` | `read_only` | N/A | N/A | Full |

## Determinism Classes

- `deterministic_pure`: Output depends only on inputs (e.g. math).
- `deterministic_repo_state`: Output depends on inputs and the current repository files/state.
- `deterministic_env_sensitive`: Output depends on environment variables.
- `deterministic_time_sensitive`: Output depends on current time/date.
- `nondeterministic_provider`: Output depends on external LLM/AI provider.
- `nondeterministic_external_io`: Output depends on external network or non-repo filesystem.
- `unknown`: Classification pending.

## Mutation Classes

- `read_only`: No side effects.
- `writes_workspace`: Modifies files in the user's working directory.
- `writes_evidence_only`: Only modifies Rig Relay telemetry/evidence logs.
- `writes_temp_only`: Only modifies temporary files.
- `mutates_git_state`: Modifies the Git repository (index, commits, etc.).
- `external_side_effect`: Modifies external systems (API calls, etc.).
- `unknown`: Classification pending.
