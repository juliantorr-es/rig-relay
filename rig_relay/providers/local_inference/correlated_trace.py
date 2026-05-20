"""Correlated trace events for local/cloud inference evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import CorrelatedTraceEvent


def _new_trace_id() -> str:
    return f"tr_{secrets.token_hex(12)}"


def _new_span_id() -> str:
    return f"sp_{secrets.token_hex(8)}"


def new_correlated_trace(
    *,
    event_type: str,
    parent_span_id: str = "",
    provider_id: str = "",
    runtime_backend_id: str = "",
    model_hash: str = "",
    task_profile: str = "",
    scenario_id: str = "",
    benchmark_run_id: str = "",
    execution_receipt_id: str = "",
    shadow_run_id: str = "",
    proposal_id: str = "",
    routing_decision_id: str = "",
    fallback_decision_id: str = "",
    status: str = "",
    latency_ms: int = 0,
    error_class: str = "",
    now: str | None = None,
) -> CorrelatedTraceEvent:
    return CorrelatedTraceEvent(
        trace_id=_new_trace_id(),
        span_id=_new_span_id(),
        parent_span_id=parent_span_id,
        event_type=event_type,
        provider_id=provider_id,
        runtime_backend_id=runtime_backend_id,
        model_hash=model_hash,
        task_profile=task_profile,
        scenario_id=scenario_id,
        benchmark_run_id=benchmark_run_id,
        execution_receipt_id=execution_receipt_id,
        shadow_run_id=shadow_run_id,
        proposal_id=proposal_id,
        routing_decision_id=routing_decision_id,
        fallback_decision_id=fallback_decision_id,
        status=status,
        latency_ms=latency_ms,
        error_class=error_class,
        timestamp=now or datetime.now(UTC).isoformat(),
    )


__all__ = ["new_correlated_trace"]
