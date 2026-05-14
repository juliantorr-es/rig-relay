# RuntimeSupervisor Architecture

The **RuntimeSupervisor** is the relay-native subprocess execution engine. It supersedes the Rig domain's `runtime_supervisor.py` and `runtime_stream.py` with a lease-gated, streaming-first design.

## Core Contract

```python
supervisor = RuntimeSupervisor(lease_store=store)
async for event in supervisor.execute(lease):
    # handle event
```

- **Input**: An active `ExecutionLease` containing an `ExecutionRequest` with `argv: list[str]`.
- **Output**: An `AsyncIterator[RuntimeStreamEvent]` — status updates, output chunks, and a terminal event.
- **No shell**: `asyncio.create_subprocess_exec(*argv)` — no shell wrapping, no shell string parsing.

## Stream Event Lifecycle

```
STATUS(starting) → STATUS(running) → [chunks* | heartbeats* | warnings*] → COMPLETION | FAILURE
```

| Phase | Events | Description |
|-------|--------|-------------|
| Validation | `FAILURE` (blocked) | Lease inactive/expired, cwd missing, invalid request |
| Spawn | `STATUS(starting)` | Emitted before `create_subprocess_exec` |
| Running | `STATUS(running)` | Emitted after process starts |
| Drain | `STDOUT_CHUNK` / `STDERR_CHUNK` | Bounded concurrent stream draining |
| Heartbeat | `HEARTBEAT` | Periodic liveness signal during execution |
| Stall | `WARNING` (stall_detected) | Non-fatal warning when no output for threshold |
| Terminal | `COMPLETION` (succeeded/failed) | Content-light — hashes + byte counts |
| Terminal | `FAILURE` (timed_out/cancelled) | Content-light — no raw output |

## Bounded Output

- `max_stdout_bytes`: 65,536 default (configurable)
- `max_stderr_bytes`: 65,536 default (configurable)
- `chunk_size`: 4,096 bytes per read
- SHA256 hashing continues past the cap for accurate summaries
- `chunk_text` is set to `None` (not emitted) after truncation
- Terminal events carry `*_truncated` flags and final byte counts

## Timeout and Cancellation

Both use the same termination pattern:

1. `process.terminate()` (SIGTERM on Unix)
2. Wait 5 seconds for graceful shutdown
3. `process.kill()` (SIGKILL on Unix)
4. Wait for final exit

Timeout produces a `FAILURE` event with `status=timed_out`.
Cancellation produces a `FAILURE` event with `status=cancelled`.

## Lease Integration

- Supervisor checks `lease.status == ACTIVE` before execution
- Validates `expires_at` against current UTC time
- Calls `lease_store.release(lease_id)` on terminal events
- Refuses execution without an active, non-expired lease

## Content-Light Design

Terminal events (`COMPLETION`, `FAILURE`) carry only:

- SHA256 hashes of stdout/stderr
- Total byte counts (before and regardless of truncation)
- Truncation flags
- Exit code and duration in milliseconds

Raw output text is only present in intermediate `RuntimeOutputChunkEvent` objects,
never in terminal summaries.

## Deferred Features

1. **Dry-run mode** — Not implemented. Would validate lease and environment without
   actually spawning the subprocess.
2. **Watchable filesystem backend** for lease coordination — currently uses
   `ExecutionLeaseStore` with file-backed persistence.

## Porting Notes

- **Rig source**: `rig/domain/runtime_supervisor.py` (deprecated), `rig/domain/runtime_stream.py`
- **Porting status**: Reimplemented with relay-native vocabulary
- **Key adaptations**:
  - Pydantic `BaseModel` with `extra="forbid"` instead of frozen dataclasses
  - Discriminated union `RuntimeStreamEvent` for type-safe event handling
  - `ExecutionLease` gate instead of internal process lifecycle tracking
  - No forbidden-command lists (governance is deferred)
  - Simplified: no `RuntimeProvider` integration, no event store persistence


## Governance Gate

The `RuntimeSupervisor` can optionally evaluate governance policy before spawning a subprocess.

### Integration

```python
supervisor = RuntimeSupervisor(
    lease_store=store,
    governance_engine=GovernanceEngine(),
    allow_mutation=False,
    allow_network=False,
)
```

### Constructor Args

| Arg | Default | Description |
|-----|---------|-------------|
| `governance_engine` | `None` | Optional `GovernanceEngine` instance. If `None`, no governance check is performed. |
| `provider_trust_tier` | `EXECUTOR_CANDIDATE` | Default trust tier passed to governance evaluation. |
| `provider_status` | `AVAILABLE` | Default provider status passed to governance evaluation. |
| `allow_mutation` | `False` | Whether mutation capabilities are allowed. If `False` and mutation capabilities are requested, governance returns `REQUIRES_REVIEW`. |
| `allow_network` | `False` | Whether network capabilities are allowed. If `False` and network capabilities are requested, governance returns `REQUIRES_REVIEW`. |
| `dirty_policy_satisfied` | `True` | Whether the dirty-file policy is satisfied for this execution. |

### Behavior

- `decision == allowed` → execution proceeds normally.
- `decision == requires_review` → emits `RuntimeFailureEvent` with `status=blocked`, `error_kind="requires_review"`. No subprocess created. Lease is released.
- `decision == blocked` → emits `RuntimeFailureEvent` with `status=blocked`, `error_kind="governance_blocked"`. No subprocess created. Lease is released.
- `decision == not_applicable` → only proceeds if no `requested_capabilities` are present; otherwise blocks defensively.
- Governance is evaluated **after** lease validation and cwd resolution, but **before** spawning the subprocess and emitting the STARTING status event.

## Active Lease Conflict Detection

`ExecutionLeaseStore.acquire()` enforces exclusivity for active leases targeting the same worktree or workspace.

### Behavior

| Scenario | Result |
|----------|--------|
| Active lease exists for same `worktree_path` | `status="refused"`, `error_kind="active_worktree_lease_exists"` |
| Active lease exists for same `workspace_id` (no worktree_path) | `status="refused"`, `error_kind="active_workspace_lease_exists"` |
| Released lease for same worktree_path | New lease granted |
| Expired lease for same worktree_path | New lease granted (after expiry check) |
| Different worktree_path | Both leases coexist |
| `enforce_exclusive_worktree=False` | Overrides exclusivity; same worktree allowed |

Expired leases are detected by comparing `expires_at` against the current UTC time. Leases in terminal states (`RELEASED`, `EXPIRED`, `CANCELLED`, `FAILED`) do not block new acquisitions.

## Heartbeat Emission

The `RuntimeSupervisor` emits periodic `RuntimeHeartbeatEvent` events while the subprocess is running.

### Behavior

- Heartbeat interval is configured via `heartbeat_interval_ms` constructor arg (default: `1000`).
- If `heartbeat_interval_ms <= 0`, heartbeat emission is fully disabled.
- Heartbeat events contain `elapsed_ms` (milliseconds since process start) and correct `lease_id`/`request_id`.
- Heartbeats are emitted in the poll loop alongside process-wait, so they do not block stdout/stderr draining.
- Heartbeats stop after the process exits (completion, failure, timeout, or cancellation).
- The terminal event is always the last event yielded (never a heartbeat).

### Constructor Args

| Arg | Default | Description |
|-----|---------|-------------|
| `heartbeat_interval_ms` | `1000` | Interval between heartbeat events in ms. `<= 0` disables heartbeats. |

## Stall Detection

The `RuntimeSupervisor` can detect stalled output and emit `RuntimeWarningEvent` with `warning_kind="stall_detected"`.

### Behavior

- Stall detection is disabled unless `stall_warning_after_ms` is set (default: `None`).
- When enabled, the supervisor tracks `last_output_at` timestamps updated by drain tasks on each chunk.
- If no output (stdout or stderr) has been received for `stall_warning_after_ms` while the process is still running, a `RuntimeWarningEvent` is emitted.
- Stall warnings are rate-limited to at most one per `stall_warning_after_ms` window to avoid spam.
- Stall warnings do **not** terminate the process by default (`terminate_on_stall=False`).
- If `terminate_on_stall=True` and `stall_terminate_after_ms` is set, the process is terminated (SIGTERM → SIGKILL) after exceeding the hard stall threshold, producing a `RuntimeFailureEvent` with `status=timed_out`.
- If output resumes, the stall timer resets on the next chunk.

### Constructor Args

| Arg | Default | Description |
|-----|---------|-------------|
| `stall_warning_after_ms` | `None` | If set, emit stall warning after no output for this many ms. `None` disables. |
| `stall_check_interval_ms` | `1000` | How often to check for stall in the poll loop. |
| `terminate_on_stall` | `False` | If `True`, terminate the process on hard stall (warning-only by default). |
| `stall_terminate_after_ms` | `None` | If set with `terminate_on_stall=True`, hard stall threshold before terminate/kill. |


## Projection Integration

Execution stream events are consumed by the UI via the
[ExecutionProgressProjection](execution-progress-projection.md) read model.
See that design doc for the aggregation contract and projection-integrity
relationship.

## Audit Integration (P3b)

The `RuntimeSupervisor` supports optional audit trail integration. When
configured, terminal execution events produce a `ReceiptEnvelope` and
`AuditEvent` appended to the `AuditTrailStore`.

### Constructor Args

- ``audit_trail_store: AuditTrailStore | None = None`` — If provided,
  terminal events are audited automatically.
- ``audit_actor: ReceiptActor | None = None`` — Optional actor identity
  for the audit trail. Defaults to a ``runtime`` kind actor.

### Behavior

1. After the terminal event (``RuntimeCompletionEvent`` or
   ``RuntimeFailureEvent``) is yielded, the supervisor builds a
   content-light ``ReceiptEnvelope`` with:
   - Actor from ``audit_actor`` or a runtime default
   - Subject as ``RUNTIME_INVOCATION`` with lease/request context
   - Input as execution request reference (request SHA256)
   - Output as terminal status, stdout/stderr hashes and byte counts
   - Evidence as SHA256 hash of the terminal event itself
   - Decision as completed/failed/refused mapping
2. An ``AuditEvent`` with ``action=EXECUTION_COMPLETED`` is appended
   to the store via ``AuditTrailStore.append_audit_event()``.
3. If envelope build or audit append fails, a
   ``RuntimeWarningEvent(warning_kind="audit_append_failed")`` is
   yielded and the terminal event is still delivered.

### Scope

- **Terminal-event-only**: Only ``EXECUTION_COMPLETED`` audit events
  are emitted. ``EXECUTION_REQUESTED`` and ``EXECUTION_STARTED`` are
  not emitted in this slice.
- **Content-light**: No raw stdout, stderr, file contents, diffs,
  snippets, or secrets in envelopes or audit events.
- **No signing**: Audit events are not cryptographically signed or
  tamper-proof. Append-only guarantees are best-effort (fsync per
  append).
- **Failure-safe**: Audit failures never cascade to the terminal
  event or the stream. A warning is emitted instead.

## What Remains Deferred

The following features from the original P2b spec remain deferred:

1. **Dry-run mode** — Not implemented. Would validate lease and environment without spawning.
