# Tracing v0 — Audit

**Date**: 2026-05-16
**Schema**: `rig.trace_event.v1`

## Implementation Summary

### Core Package (`rig_relay/tracing/`)

| File | Purpose |
|---|---|
| `__init__.py` | Public API exports |
| `models.py` | `RigTraceEvent`, `TraceStatus`, `TraceEventKind` |
| `context.py` | `TraceContext` with contextvars propagation |
| `store.py` | `JSONLTraceStore`, `InMemoryTraceStore`, `NullTraceStore` |
| `recorder.py` | `TraceRecorder` with span context manager |
| `redaction.py` | `sanitize_trace_attributes()` |

### Tests (`tests/tracing/`)

| File | Tests |
|---|---|
| `test_trace_models.py` | 12 tests — serialization, redaction |
| `test_trace_context.py` | 4 tests — propagation, clearing, async |
| `test_trace_store.py` | 5 tests — JSONL, in-memory, null |
| `test_trace_recorder.py` | 7 tests — span start/end, events, errors, nesting |
| **Total** | **28 tests, all passing** |

### Instrumented Hot Paths

| Path | File | Events |
|---|---|---|
| `desktop.bridge.start_begin` | `bridge_server.py` | host, port, tls_enabled |
| `desktop.websocket.connection_begin` | `websocket_server.py` | — |
| `desktop.websocket.auth_ok` | `websocket_server.py` | token_present, token_length |
| `runtime.subprocess.execute` | `supervisor.py` | executable, argv_hash, argv_count, cwd_hash, timeout_seconds, lease_id |

### Sample JSONL Event

```json
{
  "schema_version": "rig.trace_event.v1",
  "trace_id": "a1b2c3d4e5f6...",
  "span_id": "1a2b3c4d5e6f7g8h",
  "event_kind": "span.event",
  "name": "desktop.bridge.start_begin",
  "timestamp": "2026-05-16T00:00:00.000Z",
  "attributes": {
    "host": "127.0.0.1",
    "port": 9876,
    "tls_enabled": false
  }
}
```

### Trace Store Paths

| Mode | Path |
|---|---|
| Source/Dev | `.build/rig-relay/traces/trace_events.jsonl` |
| Packaged | `~/Library/Application Support/Rig Relay/traces/trace_events.jsonl` |

### Redaction Verified

- `token`, `auth_token`, `api_key`, `password`, `secret` → `<redacted>`
- `token_present`, `token_length` → allowed
- Long strings truncated (>1000 chars)
- Bytes summarized
- Nested dicts/lists sanitized recursively
- Serialized output never contains raw auth token

### Skipped Instrumentation

| Path | Reason |
|---|---|
| AgentLoop | Dirty `agent_loop.py` SyntaxError from parallel lane |
| ToolRuntime | Lower priority; can add in follow-up |
| RuntimeSupervisor | Lower priority |
| Validate tool | Lower priority |
| Ralph/orchestrator | Lower priority |

### Validation

| Check | Result |
|---|---|
| Tracing tests (28) | All passing |
| ruff | All checks passed |
| pyright (tracing package) | 0 errors |
| Core imports | Clean |
| Context propagation across async | Verified |
| Nested span parent tracking | Verified |

### RuntimeSupervisor Follow-Up

`RuntimeSupervisor` tracing is now implemented under the same local trace
substrate. The v0 implementation emits a parent
`runtime.subprocess.execute` span plus structured child events for spawn,
output, timeout, kill, exit, and result classification.

The implementation intentionally avoids raw stdout/stderr and raw argv
material in trace payloads. Only hashes, counts, and terminal status data are
recorded.

### RuntimeSupervisor Teardown

`RuntimeSupervisor` now performs deterministic subprocess transport cleanup
through a dedicated finalizer that terminates or waits the process and then
closes the underlying transport. The prior
`PytestUnraisableExceptionWarning` from `BaseSubprocessTransport.__del__`
was caused by subprocess transports surviving past event-loop teardown after
timeout-heavy tests.

Validation of the cleanup path is covered by
`tests/runtime/test_runtime_supervisor_teardown.py`. The runtime supervisor
behavior remains unchanged for success, failure, timeout, cancellation, and
trace payload privacy; the only difference is that subprocess resources are
now closed explicitly before the loop exits.

### RuntimeSupervisor Result Envelope

`SupervisorCommandInvoker` now attaches a canonical
`RuntimeSupervisorResultEnvelope` to each terminal result. The envelope is the
content-light terminal evidence contract for downstream consumers such as
ToolRuntime, validate, desktop diagnostics, and future SubagentRuntime paths.

The envelope classifies outcomes with the same vocabulary used by trace
summary events:

- `completed`
- `failed`
- `timed_out`
- `killed`
- `cancelled`
- `spawn_failed`
- `cleanup_failed`
- `errored`
- `refused`

The envelope stores command and cwd digests, output digests, timing facts,
state projection, and safe evidence metadata only. Raw stdout, raw stderr,
raw argv strings, and raw cwd values remain excluded.
