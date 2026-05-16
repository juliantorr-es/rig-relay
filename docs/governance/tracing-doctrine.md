# Tracing Doctrine

Rig Relay tracing is structured runtime evidence, not random logging.

## Tracing vs Logging vs Receipts

| Mechanism | What | When | Where |
|---|---|---|---|
| **Tracing** | Span tree: start/end/event/error | Every operation | `trace_events.jsonl` |
| **Logging** | Human-readable messages | Warnings, errors, info | `vibe.log` |
| **Receipts** | Governed mutation proof | Tool invocations with SHA256 | `.rig/reports/reports.jsonl` |

Tracing answers: what operation happened, where, which parent caused it, how long it took, whether it passed/failed.

## Schema

`rig.trace_event.v1` — JSONL lines, each a self-contained event.

### Fields

| Field | Required | Description |
|---|---|---|
| `schema_version` | Yes | `"rig.trace_event.v1"` |
| `trace_id` | Yes | UUID hex — groups all spans in one trace |
| `span_id` | Yes | UUID hex prefix — unique per span |
| `parent_span_id` | No | Parent span ID for child spans |
| `event_kind` | Yes | `span.start`, `span.end`, `span.event`, `span.error` |
| `name` | Yes | Dotted operation name (e.g., `desktop.bridge.start`) |
| `status` | No | `ok`, `error`, `refused`, `degraded`, `cancelled`, `timed_out`, `skipped` |
| `timestamp` | Yes | ISO 8601 |
| `started_at` | No | When span started |
| `ended_at` | No | When span ended |
| `duration_ms` | No | Wall time in milliseconds |
| `attributes` | No | Safe key-value pairs |
| `error_type` | No | Error class or code |
| `error_message` | No | Redacted error message |
| `receipt_sha256` | No | Links to a governed receipt |

### Event Kinds

- `span.start` — emitted when a span begins
- `span.end` — emitted when a span ends (includes duration, status)
- `span.event` — emitted inside a span (child event)
- `span.error` — emitted on error outside a span

## Redaction Rules

Before writing to JSONL, every trace event is sanitized:

| Contains | Action |
|---|---|
| `token`, `auth_token` | Redacted to `<redacted>` |
| `api_key`, `apikey` | Redacted |
| `password`, `passwd` | Redacted |
| `secret`, `client_secret` | Redacted |
| `authorization`, `auth` | Redacted |
| `cookie` | Redacted |
| `bearer` | Redacted |
| `token_present` | **Allowed** (boolean) |
| `token_length` | **Allowed** (integer) |
| String > 1000 chars | Truncated with marker |
| `bytes` | Summaried as `<bytes len=N>` |
| Nested dicts/lists | Recursively sanitized |
| Unknown objects | Stringified and truncated |

## Default Trace Paths

| Mode | Path |
|---|---|
| Source/Dev | `.build/rig-relay/traces/trace_events.jsonl` |
| Packaged | `~/Library/Application Support/Rig Relay/traces/trace_events.jsonl` |
| Override | `RIG_RELAY_TRACE_PATH` env var |

## Env Vars

| Var | Effect |
|---|---|
| `RIG_RELAY_TRACE=1` | Enable tracing (default) |
| `RIG_RELAY_TRACE=0` | Disable tracing |
| `RIG_RELAY_TRACE_PATH` | Override JSONL path |
| `RIG_RELAY_TRACE_VERBOSE=1` | Include more safe details (future) |

## Hot Paths Instrumented (v0)

| Span/Event | Package |
|---|---|
| `desktop.bridge.start_begin` | `rig_relay/desktop/bridge_server.py` |
| `desktop.websocket.connection_begin` | `rig_relay/desktop/websocket_server.py` |
| `desktop.websocket.auth_ok` | `rig_relay/desktop/websocket_server.py` |
| `runtime.subprocess.execute` | `rig_relay/runtime/supervisor.py` |

## Usage

```python
from rig_relay.tracing import TraceRecorder, get_default_trace_store

store = get_default_trace_store()
recorder = TraceRecorder(store)

with recorder.span("desktop.bridge.start", {"host": "127.0.0.1"}) as span:
    span.event("port_bound", {"port": 9876})
    # ... work ...
# span.end emitted automatically with ok/error status
```

## RuntimeSupervisor Span Contract

`RuntimeSupervisor` now emits a dedicated `runtime.subprocess.execute` span
for each supervised subprocess. The span records safe metadata only:

- executable
- `argv_hash`
- `argv_count`
- `cwd_hash`
- timeout seconds
- lease ID
- lane/workspace identifier when available
- shell usage flag

Child events record subprocess lifecycle milestones:

- `runtime.subprocess.spawn.start`
- `runtime.subprocess.spawn.ok`
- `runtime.subprocess.stdout.chunk`
- `runtime.subprocess.stderr.chunk`
- `runtime.subprocess.timeout`
- `runtime.subprocess.kill`
- `runtime.subprocess.exit`
- `runtime.subprocess.result_classified`

Raw stdout/stderr content, raw argv, and environment values are never emitted.
Only byte counts, hashes, and terminal classification are allowed.

## Runtime Supervisor Result Envelope

Canonical terminal evidence for supervised subprocess execution is carried by
`RuntimeSupervisorResultEnvelope`. The envelope must use the same terminal
classification vocabulary as the `runtime.subprocess.execute` span summary.

Downstream consumers should read the envelope rather than reconstructing
subprocess state from raw process handles or ad hoc status strings. ToolRuntime
and adapter receipts preserve the envelope fields for subprocess-backed tool
calls so trace summaries, receipts, and audit events stay aligned.

## OpenTelemetry Compatibility

The dotted operation names (`desktop.bridge.start`) follow OpenTelemetry semantic conventions. Future exporter can translate Rig JSONL traces to OTel format. No remote exporter in v0 — local-first only.

## See Also

- `docs/audits/runtime/tracing-v0.md` — audit trail of v0 implementation
- `docs/governance/usage-data-doctrine.md` — usage data governance
- `tests/tracing/` — trace model, context, store, recorder, redaction tests
