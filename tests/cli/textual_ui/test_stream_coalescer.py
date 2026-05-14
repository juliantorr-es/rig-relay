from __future__ import annotations

import asyncio
import time

from vibe.cli.textual_ui.stream_coalescer import StreamCoalescer


class TestAppend:
    def test_empty_delta_ignored(self) -> None:
        c = StreamCoalescer()
        c.append("")
        assert c.is_empty

    def test_single_delta_buffered(self) -> None:
        c = StreamCoalescer()
        c.append("hello")
        assert c.buffer_length == 5
        assert not c.is_empty

    def test_multiple_deltas_accumulate(self) -> None:
        c = StreamCoalescer()
        c.append("a")
        c.append("b")
        c.append("c")
        assert c.buffer_length == 3


class TestFlushOrder:
    def test_preserves_order_across_many_deltas(self) -> None:
        c = StreamCoalescer(max_buffer_chars=9999, flush_interval_ms=9999)
        deltas = ["the ", "quick ", "brown ", "fox ", "jumps"]
        for d in deltas:
            c.append(d)
        text = c.force_flush()
        assert text == "the quick brown fox jumps"

    def test_no_text_lost_across_multiple_flushes(self) -> None:
        c = StreamCoalescer(max_buffer_chars=10, flush_interval_ms=9999)
        c.append("hello ")
        c.append("world ")
        flush1 = c.flush()  # buffer > 10 chars
        assert flush1 == "hello world "
        c.append("and ")
        c.append("beyond")
        flush2 = c.force_flush()
        assert flush2 == "and beyond"

    def test_force_flush_emits_all_pending(self) -> None:
        c = StreamCoalescer()
        c.append("pending text")
        text = c.force_flush()
        assert text == "pending text"
        assert c.is_empty

    def test_force_flush_empty_returns_empty(self) -> None:
        c = StreamCoalescer()
        text = c.force_flush()
        assert text == ""


class TestTimeFlush:
    def test_flush_by_time_interval(self) -> None:
        c = StreamCoalescer(flush_interval_ms=50)
        c.append("hello")
        # Immediately after append, should_flush returns False (not enough time)
        assert not c.should_flush()
        # Advance time past interval
        future = time.perf_counter() + 0.1
        assert c.should_flush(now=future)
        text = c.flush(now=future)
        assert text == "hello"
        assert c.is_empty

    def test_empty_flush_returns_empty(self) -> None:
        c = StreamCoalescer()
        assert c.flush() == ""
        assert c.force_flush() == ""

    def test_no_premature_flush(self) -> None:
        c = StreamCoalescer(flush_interval_ms=9999, max_buffer_chars=9999)
        c.append("small")
        assert not c.should_flush()


class TestMaxCharsFlush:
    def test_flush_by_max_chars(self) -> None:
        c = StreamCoalescer(max_buffer_chars=10, flush_interval_ms=9999)
        c.append("1234567890")
        assert c.should_flush()
        text = c.flush()
        assert text == "1234567890"

    def test_no_flush_below_threshold(self) -> None:
        c = StreamCoalescer(max_buffer_chars=100, flush_interval_ms=9999)
        c.append("small")
        assert not c.should_flush()


class TestNewlineFlush:
    def test_flush_on_newline(self) -> None:
        c = StreamCoalescer(
            max_buffer_chars=9999, flush_interval_ms=9999, flush_on_newline=True
        )
        c.append("hello\n")
        assert c.should_flush()
        text = c.flush()
        assert text == "hello\n"

    def test_newline_in_middle_of_delta(self) -> None:
        c = StreamCoalescer(
            max_buffer_chars=9999, flush_interval_ms=9999, flush_on_newline=True
        )
        c.append("line1\nline2")
        assert c.should_flush()
        text = c.flush()
        assert text == "line1\nline2"

    def test_newline_flush_disabled(self) -> None:
        c = StreamCoalescer(
            max_buffer_chars=9999, flush_interval_ms=9999, flush_on_newline=False
        )
        c.append("hello\n")
        assert not c.should_flush()


class TestFinalCompletion:
    def test_no_text_lost_across_final_completion(self) -> None:
        c = StreamCoalescer(max_buffer_chars=9999, flush_interval_ms=9999)
        parts = ["building ", "up ", "text ", "for ", "final ", "flush"]
        for p in parts:
            c.append(p)
        final = c.force_flush()
        assert final == "building up text for final flush"
        assert c.is_empty


class TestReset:
    def test_reset_clears_state(self) -> None:
        c = StreamCoalescer()
        c.append("data")
        c.reset()
        assert c.is_empty
        assert c.buffer_length == 0
        assert c.total_deltas_received == 0
        assert c.total_flushes_emitted == 0
        assert c.max_buffer_size_observed == 0


class TestInstrumentation:
    def test_deltas_received_incremented(self) -> None:
        c = StreamCoalescer()
        c.append("a")
        c.append("b")
        assert c.total_deltas_received == 2

    def test_flushes_emitted_incremented(self) -> None:
        c = StreamCoalescer(max_buffer_chars=5, flush_interval_ms=9999)
        c.append("12345")
        c.flush()
        assert c.total_flushes_emitted == 1

    def test_max_buffer_size_observed(self) -> None:
        c = StreamCoalescer(max_buffer_chars=9999, flush_interval_ms=9999)
        c.append("small")
        assert c.max_buffer_size_observed == 5
        c.append(" and then larger text")
        assert c.max_buffer_size_observed == 26  # 5 + 24

    def test_instrumentation_after_force_flush(self) -> None:
        c = StreamCoalescer()
        c.append("hello")
        c.append(" world")
        assert c.total_deltas_received == 2
        c.force_flush()
        assert c.total_flushes_emitted == 1
        assert c.is_empty


class FakeAppendCounter:
    """Test double that mimics StreamingMessageBase.append_content() for coalescer
    integration testing. Records call count and accumulated text.
    """

    def __init__(self) -> None:
        self.append_calls: int = 0
        self.accumulated_text: str = ""

    async def append_content(self, content: str) -> None:
        if not content:
            return
        self.append_calls += 1
        self.accumulated_text += content


class TestEventBoundary:
    """Integration-ish tests simulating the EventHandler → coalescer → widget path.

    Simulates what _handle_assistant_message() + _flush_coalescer() do:
    StreamCoalescer.append(delta) → flush() → append_content(text).
    """

    def test_many_tiny_deltas_produce_fewer_append_calls(self) -> None:
        """100 one-char deltas should produce far fewer than 100 append calls."""
        coalescer = StreamCoalescer(max_buffer_chars=512, flush_interval_ms=50)
        counter = FakeAppendCounter()

        # Simulate 100 tiny deltas (no flush triggers yet — buffer < 512, no newline)
        for _ in range(100):
            coalescer.append("a")

        # Time-based flush
        future = time.perf_counter() + 1.0
        text = coalescer.flush(now=future)
        if text:
            asyncio.run(counter.append_content(text))

        assert counter.append_calls == 1
        assert counter.accumulated_text == "a" * 100
        assert coalescer.total_deltas_received == 100
        assert coalescer.total_flushes_emitted == 1

    def test_final_text_equals_original_full_message(self) -> None:
        """50 varying-length deltas, force-flushed, must reproduce the full text."""
        coalescer = StreamCoalescer(max_buffer_chars=9999, flush_interval_ms=9999)
        counter = FakeAppendCounter()
        parts = [
            "The ",
            "quick ",
            "brown ",
            "fox ",
            "jumps ",
            "over ",
            "the ",
            "lazy ",
            "dog. ",
            "It ",
            "was ",
            "a ",
            "dark ",
            "and ",
            "stormy ",
            "night. ",
            "Lorem ",
            "ipsum ",
            "dolor ",
            "sit ",
            "amet, ",
            "consectetur ",
            "adipiscing ",
            "elit, ",
            "sed ",
            "do ",
            "eiusmod ",
            "tempor ",
            "incididunt ",
            "ut ",
            "labore ",
            "et ",
            "dolore ",
            "magna ",
            "aliqua. ",
            "Ut ",
            "enim ",
            "ad ",
            "minim ",
            "veniam, ",
            "quis ",
            "nostrud ",
            "exercitation ",
            "ullamco ",
            "laboris ",
            "nisi ",
            "ut ",
            "aliquip ",
            "ex ",
            "ea ",
            "commodo ",
            "consequat.",
        ]
        expected = "".join(parts)

        for p in parts:
            coalescer.append(p)
        text = coalescer.force_flush()
        import asyncio

        asyncio.run(counter.append_content(text))

        assert counter.accumulated_text == expected
        assert len(counter.accumulated_text) == len(expected)

    def test_force_flush_emits_pending_text(self) -> None:
        """Small pending delta must be emitted by force_flush(), not lost."""
        coalescer = StreamCoalescer(max_buffer_chars=9999, flush_interval_ms=9999)
        coalescer.append("pending delta")
        text = coalescer.force_flush()
        assert text == "pending delta"
        assert coalescer.is_empty

    def test_newline_triggers_prompt_flush(self) -> None:
        """Delta containing newline triggers flush even when other thresholds unmet."""
        coalescer = StreamCoalescer(max_buffer_chars=9999, flush_interval_ms=9999)
        coalescer.append("line one\n")
        assert coalescer.should_flush()
        text = coalescer.flush()
        assert text == "line one\n"
        assert coalescer.is_empty

    def test_max_buffer_chars_triggers_flush(self) -> None:
        """When buffer exceeds max_buffer_chars, flush must fire."""
        coalescer = StreamCoalescer(max_buffer_chars=10, flush_interval_ms=9999)
        coalescer.append("1234567890")
        assert coalescer.should_flush()
        text = coalescer.flush()
        assert text == "1234567890"
        assert coalescer.is_empty

    def test_no_empty_append_calls_emitted(self) -> None:
        """flush() returning '' must never result in an append_content('') call."""
        coalescer = StreamCoalescer(max_buffer_chars=9999, flush_interval_ms=9999)
        counter = FakeAppendCounter()

        # Append small delta, should_flush is False
        coalescer.append("hello")
        text = coalescer.flush()  # time not advanced, no flush due
        assert text == ""
        # Simulate guard: only call append_content if text is truthy
        if text:
            asyncio.run(counter.append_content(text))
        assert counter.append_calls == 0

        # Force flush should emit the text
        text = coalescer.force_flush()
        assert text == "hello"
        if text:
            asyncio.run(counter.append_content(text))
        assert counter.append_calls == 1

    def test_coalescer_counters_during_integration(self) -> None:
        """Verify counters reflect actual deltas and flushes during integration scenario."""
        coalescer = StreamCoalescer(max_buffer_chars=20, flush_interval_ms=9999)
        deltas = ["one ", "two ", "three ", "four ", "five "]

        for d in deltas:
            coalescer.append(d)

        assert coalescer.total_deltas_received == 5
        # Buffer should be > 20 chars: "one two three four five " = 26 chars
        assert coalescer.max_buffer_size_observed == 24
        assert coalescer.buffer_length == 24

        # Flush by max_buffer_chars
        text = coalescer.flush()
        assert text == "one two three four five "
        assert coalescer.total_flushes_emitted == 1
        assert coalescer.is_empty

    def test_empty_delta_does_not_increment_counters(self) -> None:
        """append('') must be a no-op for all counters."""
        coalescer = StreamCoalescer()
        coalescer.append("")
        assert coalescer.total_deltas_received == 0
        assert coalescer.total_flushes_emitted == 0
        assert coalescer.max_buffer_size_observed == 0
        assert coalescer.is_empty


class TestMetrics:
    """Metrics snapshot correctness and content-light guarantee."""

    def test_metrics_snapshot_contains_expected_counts(self) -> None:
        c = StreamCoalescer(max_buffer_chars=10, flush_interval_ms=9999)
        c.append("hello ")
        c.append("world! ")
        c.append("test")
        c.flush()  # buffer > 10 chars triggers flush

        snapshot = c.get_metrics_snapshot()
        assert snapshot.total_deltas_received == 3
        assert snapshot.total_flushes_emitted == 1
        assert snapshot.total_chars_received == 17  # len("hello world! test") = 6+7+4
        assert snapshot.max_buffer_size_observed == 17
        assert snapshot.last_flush_size == 17
        assert snapshot.flush_interval_ms == 9999
        assert snapshot.max_buffer_chars == 10

    def test_metrics_snapshot_coalescing_ratio(self) -> None:
        c = StreamCoalescer(max_buffer_chars=20, flush_interval_ms=9999)
        for _ in range(5):
            c.append("data ")
        c.flush()
        snapshot = c.get_metrics_snapshot()
        assert snapshot.total_deltas_received == 5
        assert snapshot.total_flushes_emitted == 1
        assert snapshot.coalescing_ratio == 0.2  # 1/5

    def test_coalescing_ratio_zero_deltas(self) -> None:
        c = StreamCoalescer()
        snapshot = c.get_metrics_snapshot()
        assert snapshot.total_deltas_received == 0
        assert snapshot.total_flushes_emitted == 0
        assert snapshot.coalescing_ratio is None
        assert snapshot.average_delta_chars is None
        assert snapshot.average_flush_chars is None

    def test_metrics_snapshot_stream_duration(self) -> None:
        c = StreamCoalescer()
        c.append("test")
        import time

        time.sleep(0.01)  # Ensure measurable elapsed time
        snapshot = c.get_metrics_snapshot()
        assert snapshot.stream_duration_ms is not None
        assert snapshot.stream_duration_ms > 0

    def test_metrics_snapshot_no_raw_text(self) -> None:
        c = StreamCoalescer()
        c.append("sensitive content")
        snapshot = c.get_metrics_snapshot()
        import json

        dumped = json.dumps(snapshot.__dict__)
        assert "sensitive" not in dumped
        assert "content" not in dumped  # field name allowed, but no raw text valued
        assert isinstance(snapshot.total_deltas_received, int)

    def test_metrics_snapshot_last_flush_size_updated_on_force_flush(self) -> None:
        c = StreamCoalescer()
        c.append("pending text")
        size_before = c.last_flush_size
        assert size_before == 0  # no flush yet
        c.force_flush()
        assert c.last_flush_size == 12  # len("pending text")
        snapshot = c.get_metrics_snapshot()
        assert snapshot.last_flush_size == 12

    def test_metrics_snapshot_non_destructive(self) -> None:
        c = StreamCoalescer(max_buffer_chars=9999, flush_interval_ms=9999)
        c.append("hello")
        c.append(" world")
        snapshot1 = c.get_metrics_snapshot()
        assert snapshot1.total_deltas_received == 2
        # Snapshot should not alter state
        assert c.total_deltas_received == 2
        assert c.buffer_length == 11
        snapshot2 = c.get_metrics_snapshot()
        assert snapshot2.total_deltas_received == 2  # unchanged
