"""Benchmark sample writer — content-light, SHA256-based.

Writes BenchmarkSample objects. Never records raw prompts or completions.
Callers provide SHA256 hashes and token counts; this module only stores them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import secrets

from rig_relay.providers.local_inference.models import BenchmarkSample, ProbeStatus


def _new_sample_id() -> str:
    return f"sample_{secrets.token_hex(8)}"


def build_benchmark_sample(
    *,
    run_id: str,
    prompt_text: str,
    completion_text: str = "",
    prompt_token_count: int = 0,
    completion_token_count: int = 0,
    tool_calls_count: int = 0,
    status: ProbeStatus = ProbeStatus.COMPLETED,
    duration_ms: int = 0,
    time_to_first_token_ms: float | None = None,
    tokens_per_sec_decode: float | None = None,
    streaming_chunk_count: int | None = None,
    streaming_chunk_interval_ms_p50: float | None = None,
    tool_call_correct: bool | None = None,
    structured_output_complies: bool | None = None,
    temperature_zero_deterministic: bool | None = None,
    cancellation_requested_at_ms: int | None = None,
    cancellation_effective_ms: int | None = None,
    error_class: str | None = None,
    error_safe_message: str | None = None,
    server_reported_tokens_match: bool | None = None,
    token_accounting_discrepancy: str | None = None,
) -> BenchmarkSample:
    return BenchmarkSample(
        sample_id=_new_sample_id(),
        run_id=run_id,
        prompt_sha256=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        prompt_token_count=prompt_token_count,
        completion_sha256=hashlib.sha256(completion_text.encode("utf-8")).hexdigest()
        if completion_text
        else "",
        completion_token_count=completion_token_count,
        tool_calls_count=tool_calls_count,
        status=status,
        duration_ms=duration_ms,
        time_to_first_token_ms=time_to_first_token_ms,
        tokens_per_sec_decode=tokens_per_sec_decode,
        streaming_chunk_count=streaming_chunk_count,
        streaming_chunk_interval_ms_p50=streaming_chunk_interval_ms_p50,
        tool_call_correct=tool_call_correct,
        structured_output_complies=structured_output_complies,
        temperature_zero_deterministic=temperature_zero_deterministic,
        cancellation_requested_at_ms=cancellation_requested_at_ms,
        cancellation_effective_ms=cancellation_effective_ms,
        error_class=error_class,
        error_safe_message=error_safe_message,
        server_reported_tokens_match=server_reported_tokens_match,
        token_accounting_discrepancy=token_accounting_discrepancy,
    )


def write_sample_to_jsonl(sample: BenchmarkSample, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(sample.model_dump_json() + "\n")


def compute_prompt_sha256(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


__all__ = ["build_benchmark_sample", "compute_prompt_sha256", "write_sample_to_jsonl"]
