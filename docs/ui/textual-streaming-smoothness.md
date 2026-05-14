# Textual Streaming Smoothness — Provider Delta Coalescing

## Problem

The Textual chat UI streams provider output into assistant message widgets. The
visible stream can feel laggy or jittery because:

- Provider chunks (LLM token deltas) are very small — often 1–5 characters
- Provider network cadence is uneven — bursts followed by gaps
- Each `AssistantEvent` delta triggers `MarkdownStream.write()`, which causes a
  Textual widget update/repaint
- High-frequency repaints compete with layout, scroll position, and other widget
  updates (spinners, tool call status, header ticks)

The result: UI frames are dropped or jitter because Textual cannot repaint fast
enough for every tiny delta.

## Solution: StreamCoalescer

A lightweight, testable text coalescer that sits between provider deltas and the
streaming message widget.

### Architecture

```
LLM Chunks → AssistantEvent → StreamCoalescer.append(delta)
                                     ↓
                         StreamCoalescer.flush()  ← controlled cadence
                                     ↓
                         StreamingMessageBase.append_content(text)
                                     ↓
                         MarkdownStream.write(text)
```

### Integration Point

`vibe/cli/textual_ui/handlers/event_handler.py`:

- One `StreamCoalescer` instance per active streaming assistant message
- `_handle_assistant_message()` appends deltas to the coalescer, then checks
  if a flush is due via `_flush_coalescer()`
- `finalize_streaming()` force-flushes any remaining text before stopping the
  stream (guarantees no text loss at stream completion)

### Default Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `flush_interval_ms` | 50 | Minimum milliseconds between flushes |
| `max_buffer_chars` | 512 | Flush when buffer exceeds this many chars |
| `flush_on_newline` | True | Flush immediately on newline in any delta |

These defaults balance:
- **Latency**: Text appears within ~50ms of arrival (imperceptible)
- **Repaint reduction**: At most ~20 flushes/second instead of per-delta
- **Responsiveness**: Newlines flush immediately so paragraphs appear promptly

### Coalescer Behavior

- Preserves exact text order (list of strings, joined on flush)
- Never drops text (buffer accumulates until flushed)
- Empty deltas are ignored
- Empty flush returns `""`
- `force_flush()` emits all pending text unconditionally

### What Is Not Coalesced

- **Reasoning events** (`ReasoningEvent`) — streamed directly, not coalesced.
  Reasoning is typically short and often displayed collapsed.
- **Tool call/result events** — structurally separate in the match dispatch.
- **Tool output streams** (`ToolStreamEvent`) — different path via
  `ToolCallMessage.set_stream_message()`.
- **Status events** (`CompactStartEvent/CompactEndEvent`, `HookEvent`) —
  unrelated to assistant text streaming.
- **Receipt emission** — tool receipts and validate receipts are not text
  streams.

### Instrumentation

The coalescer tracks internal counters for diagnosis:

- `total_deltas_received` — number of `append()` calls
- `total_flushes_emitted` — number of flushes that emitted text
- `max_buffer_size_observed` — largest buffer size reached before flush
- `buffer_length` — current pending chars

These are currently internal/test-only. A future debug console could surface
them as `rig.relay.stream_coalescer.stats`.

### Provider Trace Metrics

A `StreamCoalescerMetrics` dataclass provides a content-light snapshot of the
streaming behavior for a single assistant stream. It contains no raw text,
deltas, prompts, or snippets — only numeric counts, ratios, and configuration
parameters.

#### Metric Definitions

| Metric | Type | Description |
|--------|------|-------------|
| `total_deltas_received` | `int` | Number of `append()` calls |
| `total_flushes_emitted` | `int` | Number of flushes that emitted text |
| `total_chars_received` | `int` | Total characters across all deltas |
| `max_buffer_size_observed` | `int` | Peak buffer length before a flush |
| `flush_interval_ms` | `float` | Configured flush interval (ms) |
| `max_buffer_chars` | `int` | Configured max buffer size (chars) |
| `stream_duration_ms` | `float | None` | Wall-clock duration from coalescer creation to snapshot |
| `last_flush_size` | `int` | Characters in the most recent flush |
| `coalescing_ratio` | `float | None` | `flushes / deltas` — lower = better batching. `None` when zero deltas. |
| `average_delta_chars` | `float | None` | `chars / deltas` — mean delta size. `None` when zero deltas. |
| `average_flush_chars` | `float | None` | `chars / flushes` — mean flush batch size. `None` when zero flushes. |

#### Derivation

All derived fields are computed at snapshot time from raw counters.

```
coalescing_ratio    = total_flushes_emitted / total_deltas_received   (if deltas > 0)
average_delta_chars = total_chars_received    / total_deltas_received   (if deltas > 0)
average_flush_chars = total_chars_received    / total_flushes_emitted  (if flushes > 0)
```

A `coalescing_ratio` of `0.2` means 1 flush per 5 deltas — 80% reduction
in UI updates compared to per-delta rendering.

#### Privacy Boundary

The metrics snapshot is content-light by construction:

- **No raw assistant content** — no text, no snippets, no characters from the
  model output are included
- **No deltas** — individual `append()` arguments are not stored or exposed
- **No prompts** — user or system prompts are never tracked
- **No hashes of model text** — SHA256 or other content-derived hashes are
  not computed or stored
- **No path or file information** — only configuration and counter values
- **Configuration values** (`flush_interval_ms`, `max_buffer_chars`) are
  fixed at construction time and reveal no private data

The `StreamCoalescerMetrics` dataclass is annotated as such and has no fields
that can carry raw text. The `get_metrics_snapshot()` method is the only
access point — it returns a frozen snapshot, not a live reference to internal
buffers.

#### Telemetry Integration

The metrics snapshot is currently **test-only**. In `EventHandler.finalize_streaming()`,
after the final `force_flush()`, a commented-out capture is present:

```python
# metrics = self._coalescer.get_metrics_snapshot()
# logger.debug("stream_coalescer_metrics: %s", metrics)
```

To activate, uncomment these lines and ensure `logger` is imported from
`vibe.core.logger`. The `logger.debug()` call is failure-safe (never raises),
content-light, and logs to `~/.vibe/logs/vibe.log` at `LOG_LEVEL=DEBUG`.

If richer telemetry is desired (e.g., structured events in observability JSONL),
define a new `EventName` in `vibe/core/telemetry/constants.py` following the
`rig.relay.<domain>.<verb>` convention, and create a schema file at
`docs/schemas/rig.relay.stream_coalescer_metrics.v1.schema.json`.

## Risks and Tuning

### Risk: Flush delay on sparse deltas

If deltas arrive less frequently than `flush_interval_ms`, the coalescer delays
each flush by up to `flush_interval_ms` (~50ms). This is intentional — sparse
deltas don't cause jitter, so the flush cadence is imperceptible.

Worst case: a single delta arrives, wait 50ms, then display it. This is
undetectable in practice (50ms < human perception threshold of ~100ms for
text rendering).

### Risk: Flush delay on final delta

If the last delta before stream completion is small and no newline is present,
it stays in the buffer until `finalize_streaming()` force-flushes it. The
force-flush happens when the next event arrives (tool call, user message,
etc.), which is typically <100ms after the last delta.

### Risk: Reasoning stream interleaving

When `_handle_assistant_message()` runs, it stops any active reasoning stream
first. This includes force-flushing any coalesced text via `finalize_streaming()`.
The reasoning stream itself is not coalesced — it uses direct `append_content()`.

## Tuning Knobs

Configure by creating `StreamCoalescer` with different parameters:

```python
# More aggressive: flush every 33ms (~30fps), max 256 chars
coalescer = StreamCoalescer(
    flush_interval_ms=33,
    max_buffer_chars=256,
    flush_on_newline=True,
)

# Less aggressive: flush every 100ms (~10fps), max 1024 chars
coalescer = StreamCoalescer(
    flush_interval_ms=100,
    max_buffer_chars=1024,
    flush_on_newline=True,
)
```

The default 50ms/512 chars should work for most providers. Increase
`flush_interval_ms` if the UI still feels jittery (fewer repaints).
Decrease `max_buffer_chars` for more responsive display of long code blocks.

## Files Changed

| File | Change |
|------|--------|
| `vibe/cli/textual_ui/stream_coalescer.py` | **New** — StreamCoalescer class + StreamCoalescerMetrics dataclass + get_metrics_snapshot() |
| `vibe/cli/textual_ui/handlers/event_handler.py` | **Modified** — integrated coalescer into `_handle_assistant_message`, `_flush_coalescer`, `finalize_streaming`; metrics snapshot capture (commented out) in `finalize_streaming` |
| `tests/cli/textual_ui/test_stream_coalescer.py` | **New/Modified** — 36 tests (21 unit + 8 integration + 7 metrics) |

## Unit Tests

| Test Group | Count | What It Verifies |
|------------|-------|-----------------|
| `TestAppend` | 3 | Empty delta, single delta, multiple deltas |
| `TestFlushOrder` | 4 | Order preservation, no text loss across flushes, force flush, empty force flush |
| `TestTimeFlush` | 3 | Flush after interval, empty flush, no premature flush |
| `TestMaxCharsFlush` | 2 | Flush at threshold, no flush below threshold |
| `TestNewlineFlush` | 3 | Newline triggers flush, newline in middle, disabled |
| `TestFinalCompletion` | 1 | No text lost across final force flush |
| `TestReset` | 1 | Reset clears all state and counters |
| `TestInstrumentation` | 4 | Delta counter, flush counter, max buffer, after force flush |
| `TestMetrics` | 7 | Metrics snapshot, coalescing_ratio, zero-delta safety, stream_duration, no raw text, last_flush_size, non-destructive |
| **Subtotal** | **28** | |

## Integration Tests (TestEventBoundary)

These tests simulate the EventHandler -> coalescer -> widget data path using
`FakeAppendCounter`, a lightweight double that records `append_content()` call
count and accumulated text — no Textual app required.

| Test | What It Verifies |
|------|-----------------|
| `test_many_tiny_deltas_produce_fewer_append_calls` | 100 one-char deltas produce 1 append call (not 100) |
| `test_final_text_equals_original_full_message` | Force-flushed 50 deltas preserve exact full text |
| `test_force_flush_emits_pending_text` | Pending delta emitted by force_flush, nothing lost |
| `test_newline_triggers_prompt_flush` | Newline in delta triggers immediate flush |
| `test_max_buffer_chars_triggers_flush` | Buffer exceeding max_buffer_chars triggers flush |
| `test_no_empty_append_calls_emitted` | flush() returning '' is never passed to append_content |
| `test_coalescer_counters_during_integration` | total_deltas_received, total_flushes_emitted, max_buffer_size_observed reflect real counts |
| `test_empty_delta_does_not_increment_counters` | append('') is a no-op for all counters |

**Flush-count reduction evidence:** In `test_many_tiny_deltas_produce_fewer_append_calls`,
100 deltas produce exactly 1 flush. Without coalescing, each delta would
trigger a separate `append_content()` call and Textual repaint. The coalescer
reduces widget update calls by 99% in this scenario.

**Final-text preservation:** In `test_final_text_equals_original_full_message`,
50 varying-length deltas (totalling 373 chars) are force-flushed in a single
batch. The accumulated text matches the concatenated parts exactly — no dropped
or reordered characters.

**Metrics/counters:** `StreamCoalescer` exposes four debug properties:
- `total_deltas_received` — number of `append()` calls
- `total_flushes_emitted` — number of flushes that emitted text
- `max_buffer_size_observed` — peak buffer length before flush
- `buffer_length` — current pending characters

These are test-only. A future debug console could surface them as
`rig.relay.stream_coalescer.stats`.

**Why tool output is not coalesced:** Tool output streams (`ToolStreamEvent`)
and structured events (`ToolCallEvent`, `ToolResultEvent`, `CompactEvent`,
`HookEvent`) are dispatched through separate `match` arms in `EventHandler`.
Only `AssistantEvent` deltas pass through the coalescer. This is by design:
tool output has different latency requirements (user expects immediate
visibility of tool progress), and structured events are not text streams.

**Test boundary:** `FakeAppendCounter` records call count and accumulated
text. The integration tests exercise the coalescer/flush/append pipeline
without requiring a Textual application mount. This keeps tests fast,
deterministic, and free of UI dependencies.

Existing streaming message buffer tests (22) and hook handler tests (3) all
pass — no regressions.

## Remaining Risk

- **Provider/network cadence still determines upstream latency.** The coalescer
  can only smooth the display cadence, not the network round-trip.
- **Reasoning events are not coalesced.** If reasoning deltas are also tiny,
  a similar coalescer could be added for `ReasoningEvent`.
- **The `FakeAppendCounter` test double does not test Textual widget rendering.**
  A full-widget integration test (mounting `AssistantMessage` in a test driver)
  would provide end-to-end coverage but requires the Textual test framework.
- **Instrumentation counters and metrics are test-only.** The `get_metrics_snapshot()`
  call in `finalize_streaming()` is commented out. Activate by uncommenting
  and importing `logger` from `vibe.core.logger`.
- **Metrics are not yet connected to observability JSONL.** A future slice should
  define a `rig.relay.stream_coalescer.metrics` event and schema if structured
  telemetry is preferred over debug logging.

## Recommended Next Slices

1. **Performance benchmarking:** Activate the metrics snapshot in `finalize_streaming()`
   and collect traces from real provider sessions. Compare `coalescing_ratio` and
   `average_flush_chars` across providers (OpenAI, Anthropic, DeepSeek) to tune
   `flush_interval_ms` and `max_buffer_chars` per provider.
2. **Debug console integration:** Surface coalescer instrumentation counters and
   metrics in the Rig Console evidence rail as a debug/telemetry widget.
3. **Observability JSONL integration:** Define `rig.relay.stream_coalescer.metrics`
   event in `EventName` and a corresponding JSON Schema for structured telemetry
   at `docs/schemas/rig.relay.stream_coalescer_metrics.v1.schema.json`.
4. **Reasoning event coalescing** (optional): If reasoning deltas also arrive
   as tiny chunks, add a second `StreamCoalescer` for the reasoning path.
