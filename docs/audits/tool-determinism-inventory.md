# Tool Determinism Inventory

This document tracks the determinism and mutation characteristics of Rig Relay built-in tools.

## Inventory

| Tool Name | Module | Determinism Class | Mutation Class | Input Normalization | Output Normalization | Evidence Coverage |
|-----------|--------|-------------------|----------------|---------------------|----------------------|-------------------|
| `read_file` | `builtins.read_file` | `deterministic_repo_state` | `read_only` | High (Path normalization) | High (UTF-8, line range) | Partial |
| `write_file` | `builtins.write_file` | `deterministic_repo_state` | `writes_workspace` | High | High | Partial |
| `grep` | `builtins.grep` | `deterministic_repo_state` | `read_only` | High | Medium (Recursive order) | Partial |
| `bash` | `builtins.bash` | `nondeterministic_external_io` | `writes_workspace` | Low | Low | Low |
| `git` | `builtins.git` | `deterministic_repo_state` | `mutates_git_state` | Medium | Medium | Low |
| `websearch` | `builtins.websearch` | `nondeterministic_external_io` | `read_only` | High | Low (Provider dependent) | Low |
| `webfetch` | `builtins.webfetch` | `nondeterministic_external_io` | `read_only` | High | Low | Low |
| `ask_user_question` | `builtins.ask_user_question` | `nondeterministic_external_io` | `read_only` | N/A | N/A | Low |

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
