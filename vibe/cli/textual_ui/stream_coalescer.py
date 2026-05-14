from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass
class StreamCoalescerMetrics:
    """Content-light streaming metrics for a single assistant stream.

    Contains no raw assistant content, deltas, prompts, or snippets.
    Only numeric counts, ratios, and configuration parameters.
    """

    total_deltas_received: int = 0
    total_flushes_emitted: int = 0
    total_chars_received: int = 0
    max_buffer_size_observed: int = 0
    flush_interval_ms: float = 50
    max_buffer_chars: int = 512
    stream_duration_ms: float | None = None
    last_flush_size: int = 0
    coalescing_ratio: float | None = None
    average_delta_chars: float | None = None
    average_flush_chars: float | None = None


class StreamCoalescer:
    """Coalesces small text deltas into larger batches for UI-friendly flushing.

    Flush triggers (any of):
    - elapsed time >= flush_interval_ms since last flush
    - buffer length >= max_buffer_chars
    - delta contains newline (if flush_on_newline is True)
    - force_flush() called (stream completion/interruption)

    Rules:
    - Preserves exact text order.
    - Never drops text.
    - Empty flush returns "".
    - Final force_flush emits all pending text.
    """

    def __init__(
        self,
        flush_interval_ms: float = 50,
        max_buffer_chars: int = 512,
        flush_on_newline: bool = True,
    ) -> None:
        self._flush_interval_ms = flush_interval_ms
        self._max_buffer_chars = max_buffer_chars
        self._flush_on_newline = flush_on_newline
        self._buffer: list[str] = []
        self._buffer_len = 0
        self._last_flush_time = time.perf_counter()
        self._total_deltas_received = 0
        self._total_flushes_emitted = 0
        self._max_buffer_size_observed = 0
        self._total_chars_received = 0
        self._last_flush_size = 0
        self._stream_start_time = time.perf_counter()

    def append(self, delta: str) -> None:
        """Add a text delta to the buffer."""
        if not delta:
            return
        self._buffer.append(delta)
        chars = len(delta)
        self._buffer_len += chars
        self._total_chars_received += chars
        self._total_deltas_received += 1
        self._max_buffer_size_observed = max(
            self._max_buffer_size_observed, self._buffer_len
        )

    def should_flush(self, now: float | None = None) -> bool:
        """Return True if flush should happen based on configured triggers."""
        if not self._buffer:
            return False

        if now is None:
            now = time.perf_counter()

        elapsed_ms = (now - self._last_flush_time) * 1000
        if elapsed_ms >= self._flush_interval_ms:
            return True

        if self._buffer_len >= self._max_buffer_chars:
            return True

        if self._flush_on_newline:
            for part in self._buffer:
                if "\n" in part:
                    return True

        return False

    def flush(self, now: float | None = None) -> str:
        """Flush accumulated text if should_flush returns True.

        Returns accumulated text, or "" if no flush is due.
        """
        if not self.should_flush(now):
            return ""
        return self._do_flush()

    def force_flush(self) -> str:
        """Flush all accumulated text immediately regardless of triggers."""
        return self._do_flush()

    def _do_flush(self) -> str:
        if not self._buffer:
            return ""
        result = "".join(self._buffer)
        self._buffer = []
        self._buffer_len = 0
        self._last_flush_time = time.perf_counter()
        self._total_flushes_emitted += 1
        self._last_flush_size = len(result)
        return result

    def reset(self) -> None:
        """Clear buffer and reset counters. Text in buffer is lost."""
        self._buffer = []
        self._buffer_len = 0
        self._last_flush_time = time.perf_counter()
        self._total_deltas_received = 0
        self._total_flushes_emitted = 0
        self._max_buffer_size_observed = 0
        self._total_chars_received = 0
        self._last_flush_size = 0
        self._stream_start_time = time.perf_counter()

    @property
    def buffer_length(self) -> int:
        return self._buffer_len

    @property
    def is_empty(self) -> bool:
        return self._buffer_len == 0

    @property
    def total_deltas_received(self) -> int:
        return self._total_deltas_received

    @property
    def total_flushes_emitted(self) -> int:
        return self._total_flushes_emitted

    @property
    def max_buffer_size_observed(self) -> int:
        return self._max_buffer_size_observed

    @property
    def total_chars_received(self) -> int:
        return self._total_chars_received

    @property
    def last_flush_size(self) -> int:
        return self._last_flush_size

    def get_metrics_snapshot(self) -> StreamCoalescerMetrics:
        """Return a content-light metrics snapshot for the current stream.

        The snapshot contains only numeric counts, ratios, and
        configuration parameters. No raw text, deltas, prompts, or
        snippets are included.
        """
        deltas = self._total_deltas_received
        flushes = self._total_flushes_emitted
        chars = self._total_chars_received
        elapsed = time.perf_counter() - self._stream_start_time
        stream_duration_ms = elapsed * 1000

        return StreamCoalescerMetrics(
            total_deltas_received=deltas,
            total_flushes_emitted=flushes,
            total_chars_received=chars,
            max_buffer_size_observed=self._max_buffer_size_observed,
            flush_interval_ms=self._flush_interval_ms,
            max_buffer_chars=self._max_buffer_chars,
            stream_duration_ms=stream_duration_ms,
            last_flush_size=self._last_flush_size,
            coalescing_ratio=(flushes / deltas) if deltas > 0 else None,
            average_delta_chars=(chars / deltas) if deltas > 0 else None,
            average_flush_chars=(chars / flushes) if flushes > 0 else None,
        )
