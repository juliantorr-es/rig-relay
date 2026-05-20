"""Benchmark evidence summarizer — content-light JSONL ingestion.

Consumes BenchmarkSample JSONL files and produces BenchmarkEvidenceSummary.
Never embeds prompts, completions, raw tool outputs, or private data.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import secrets

from rig_relay.providers.local_inference.models import (
    BenchmarkEvidenceSummary,
    BenchmarkSample,
)


def _new_summary_id() -> str:
    return f"bsum_{secrets.token_hex(8)}"


def summarize_benchmark_jsonl(
    jsonl_path: Path, *, runtime_url: str = "", endpoint_sha256: str = ""
) -> BenchmarkEvidenceSummary:
    samples: list[BenchmarkSample] = []
    parse_errors: list[str] = []

    if jsonl_path.is_file():
        for line in jsonl_path.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                samples.append(BenchmarkSample(**data))
            except Exception as exc:
                parse_errors.append(str(exc)[:200])

    if not samples:
        return BenchmarkEvidenceSummary(
            summary_id=_new_summary_id(),
            benchmark_source=str(jsonl_path),
            sample_count=0,
            runtime_url=runtime_url,
            endpoint_sha256=endpoint_sha256,
            evidence_status="missing",
            stale=False,
            redaction_summary="content_light",
            warnings=["No benchmark samples found"] + parse_errors,
        )

    ttfbs = [
        s.time_to_first_token_ms
        for s in samples
        if s.time_to_first_token_ms is not None
    ]
    tok_per_sec = [
        s.tokens_per_sec_decode for s in samples if s.tokens_per_sec_decode is not None
    ]
    durations = [float(s.duration_ms) for s in samples if s.duration_ms > 0]
    errors_total = sum(1 for s in samples if s.status.value != "completed")

    error_classes: Counter[str] = Counter()
    for s in samples:
        if s.error_class:
            error_classes[s.error_class] += 1

    cancellation_count = sum(
        1 for s in samples if s.cancellation_requested_at_ms is not None
    )

    context_buckets: dict[str, int] = {}
    for s in samples:
        if s.prompt_token_count > 0:
            bucket = _context_size_bucket(s.prompt_token_count)
            context_buckets[bucket] = context_buckets.get(bucket, 0) + 1

    stale = False
    measurement_window_start = ""
    measurement_window_end = ""

    return BenchmarkEvidenceSummary(
        summary_id=_new_summary_id(),
        benchmark_source=str(jsonl_path),
        sample_count=len(samples),
        runtime_url=runtime_url,
        endpoint_sha256=endpoint_sha256,
        measurement_window_start=measurement_window_start,
        measurement_window_end=measurement_window_end,
        time_to_first_token_ms_p50=_percentile(ttfbs, 50),
        time_to_first_token_ms_p95=_percentile(ttfbs, 95),
        tokens_per_sec_decode_p50=_percentile(tok_per_sec, 50),
        tokens_per_sec_decode_p95=_percentile(tok_per_sec, 95),
        end_to_end_latency_ms_p50=_percentile(durations, 50),
        end_to_end_latency_ms_p95=_percentile(durations, 95),
        error_count_total=errors_total,
        error_count_by_class=dict(error_classes),
        cancellation_samples=cancellation_count,
        context_size_buckets=context_buckets,
        evidence_status="available",
        stale=stale,
        redaction_summary="content_light",
        warnings=parse_errors,
    )


def _percentile(values: list[float] | list[int], pct: int) -> float | None:
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * pct / 100.0)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


def _context_size_bucket(token_count: int) -> str:
    buckets = [
        (1024, "0-1k"),
        (4096, "1k-4k"),
        (8192, "4k-8k"),
        (16384, "8k-16k"),
        (32768, "16k-32k"),
        (65536, "32k-64k"),
        (131072, "64k-128k"),
    ]
    for threshold, label in buckets:
        if token_count <= threshold:
            return label
    return "128k+"


def validate_benchmark_content_light(jsonl_path: Path) -> list[str]:
    """Scan a benchmark JSONL for potential content leaks. Returns warnings."""
    warnings: list[str] = []
    forbidden_fields = {
        "prompt",
        "completion",
        "raw",
        "content",
        "text",
        "message",
        "input",
        "output",
        "tool_output",
    }
    if not jsonl_path.is_file():
        return warnings
    for i, line in enumerate(
        jsonl_path.read_text(encoding="utf-8").strip().split("\n"), 1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"Line {i}: invalid JSON")
            continue
        for field in forbidden_fields:
            if field in data:
                warnings.append(f"Line {i}: forbidden field '{field}' present")
    return warnings


__all__ = ["summarize_benchmark_jsonl", "validate_benchmark_content_light"]
