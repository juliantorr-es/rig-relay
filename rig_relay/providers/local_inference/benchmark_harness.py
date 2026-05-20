"""Capacity benchmark harness — plan-only by default. Content-light samples."""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import (
    CapacityBenchmarkPlan,
    CapacityBenchmarkSample,
)


def _new_plan_id() -> str:
    return f"cbp_{secrets.token_hex(8)}"


def _new_sample_id() -> str:
    return f"cbs_{secrets.token_hex(8)}"


def plan_benchmark(
    *,
    mode: str = "dry_run_plan",
    endpoint_url: str = "",
    backend_id: str = "",
    task_profiles: list[str] | None = None,
    approval: bool = False,
    now: str | None = None,
) -> CapacityBenchmarkPlan:
    plan = CapacityBenchmarkPlan(
        plan_id=_new_plan_id(),
        generated_at=now or datetime.now(UTC).isoformat(),
        mode=mode,
        endpoint_url=endpoint_url,
        backend_id=backend_id,
        task_profiles=task_profiles or [],
        sample_count=0,
        dimensions=["ttft", "latency", "tokens_per_sec", "error_rate"],
    )
    if mode not in {"dry_run_plan", "fake_endpoint"} and not approval:
        plan.blocked_reasons.append("live_benchmark_requires_approval")
        plan.approval_required = True
    return plan


def build_capacity_benchmark_sample(
    *,
    plan_id: str,
    task_profile: str,
    prompt_sha256: str = "",
    trace_id: str = "",
    mode: str = "",
    ttft_ms: int = 0,
    latency_ms: int = 0,
    tokens_per_sec: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    completion_sha256: str = "",
    error_class: str = "",
    status: str = "completed",
    contract_result: str = "",
    memory_mb: int = 0,
) -> CapacityBenchmarkSample:
    return CapacityBenchmarkSample(
        sample_id=_new_sample_id(),
        plan_id=plan_id,
        trace_id=trace_id,
        mode=mode,
        task_profile=task_profile,
        prompt_sha256=prompt_sha256,
        completion_sha256=completion_sha256,
        ttft_ms=ttft_ms,
        latency_ms=latency_ms,
        tokens_per_sec=tokens_per_sec,
        input_token_count=input_tokens,
        output_token_count=output_tokens,
        error_class=error_class,
        status=status,
        contract_result=contract_result,
        memory_peak_mb=memory_mb,
    )


__all__ = ["build_capacity_benchmark_sample", "plan_benchmark"]
