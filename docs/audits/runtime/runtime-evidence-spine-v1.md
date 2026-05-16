# Runtime Evidence Spine v1

## Trace Semantics

### Parent/Child Span Model
- `span.start` + `span.end` = one span
- `span.event` = event attached to active span (parent_span_id == span_id)
- Child spans get `parent_span_id` = parent's `span_id`
- Sibling spans share `trace_id` but have different `span_id`

### Trace Tree Example
```
tool_runtime.execute_one (trace_id=t1, span_id=s1)
  │
  ├── tool_runtime.cache_check (span.event, span_id=s1)
  │
  └── runtime.subprocess.execute (trace_id=t1, span_id=s2, parent_span_id=s1)
```

## RuntimeSupervisor Trace Privacy

### Safe Attributes
- `executable`: argv[0] only
- `argv_hash`: sha256 of joined argv (first 16 chars)
- `argv_count`: len(argv)
- `cwd_hash`: sha256 of cwd path (first 16 chars)
- `cwd_kind`: repo | worktree | temp | app_support | unknown
- `timeout_seconds`, `exit_code`, `status`, `duration_ms`
- `stdout_bytes`, `stderr_bytes` (never raw content)

### Redaction Proof
- Raw CWD path with username/project never appears
- Raw argv secrets never appear
- Raw stdout/stderr content never appears

## Validate Tracing v0 (deferred)
Validate profile execution tracing deferred to next pass. Current check execution goes through `validate_runner._run_check()` which uses `create_subprocess_exec`. Instrumentation will be added when validate state machine transitions are stable.

## Desktop Trace Correlation
- Bridge probe ladder already emits structured events
- Frontend event recorder exists
- DesktopBridgeStateMachine transitions are traceable
- /healthz exposes bridge_state, transition_count

## Test Diagnostics Helper
`tests/helpers/probe_report.py` — ProbeReport with structured check recording and safe assertions. Used for golden-path protocol tests. Emits no secrets.

## Duplicate Test Audit
Scanned 5954 tests across 327 test files:
- 1 exact body duplicate group
- 34 normalized AST duplicate groups
- 618 assert-shape duplicate groups

Output: `docs/audits/test-suite/duplicate_test_audit.*`

## Validate/Agent Command Doctrine
1. `uv run pytest -m smoke --maxfail=1 -q` — pulse check
2. `uv run pytest -m "not slow and not integration..."` — fast default (4885 tests)
3. Full suite explicit only
4. Agents must not run broad pytest loops when focused validation exists
5. Duplicate tests should become parametrized behavior tables
6. Raw output/secrets never belong in traces or diagnostics
