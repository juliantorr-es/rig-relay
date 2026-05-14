# Validate Blocker Taxonomy

## Goal

`validate` should return structured blockers, not just exit codes.

## Blocker Kinds

### `test_failure`

Meaning:

- one or more tests failed

Typical source:

- `pytest`

### `lint_failure`

Meaning:

- style or static analysis failure

Typical source:

- `ruff check`

### `typecheck_failure`

Meaning:

- pyright or type analysis failure

Typical source:

- `pyright`

### `schema_failure`

Meaning:

- JSON, JSONL, or schema validation failed

Typical source:

- schema validation scripts
- receipt validators

### `governance_failure`

Meaning:

- policy or doctrine mismatch

Typical source:

- governance checks
- retention policy checks

### `dirty_workspace`

Meaning:

- workspace state does not satisfy the profile's dirty policy

Typical source:

- git readiness checks

### `forbidden_mutation`

Meaning:

- a command attempted mutation under a read-only profile

Typical source:

- any check bundle that tries to write

### `timeout`

Meaning:

- profile exceeded allowed time

Typical source:

- long-running pytest or repo scans

### `tool_refusal`

Meaning:

- governed tool refused the command or scope

Typical source:

- path policy
- permission policy

### `missing_dependency`

Meaning:

- required binary or package is unavailable

Typical source:

- `pyright`, `ruff`, `pytest`, schema validators

### `environment_failure`

Meaning:

- environment is misconfigured but command logic is not necessarily wrong

Typical source:

- missing venv, wrong PATH, broken interpreter, invalid locale

### `command_internal_error`

Meaning:

- tool crashed or raised unexpected internal error

Typical source:

- script exception

### `unknown_failure`

Meaning:

- blocker could not be classified safely

Typical source:

- malformed output
- mixed failures

## Mapping Rules

- test runner failure -> `test_failure`
- linter failure -> `lint_failure`
- type checker failure -> `typecheck_failure`
- schema validator failure -> `schema_failure`
- dirty repo gate -> `dirty_workspace`
- permission refusal -> `tool_refusal`
- timeout exit or signal -> `timeout`
- missing binary -> `missing_dependency`
- script exception -> `command_internal_error`

## What the Blocker Taxonomy Should Not Do

- should not store raw stdout
- should not store raw stderr
- should not echo entire command transcripts
- should not hide environment failures inside generic failure

## Blocker Summary Contract

`ValidateResult.blocker_summary` should report counts per blocker kind.

This lets validate answer:

- is this a real code blocker?
- is this a tooling blocker?
- is this a workspace-state blocker?
- is this an environment blocker?

That distinction is the whole point of making validation first-class.
