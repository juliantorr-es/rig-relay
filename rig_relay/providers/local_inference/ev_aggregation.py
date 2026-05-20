"""Capability evidence aggregation report."""

from __future__ import annotations

from datetime import UTC, datetime
import secrets

from rig_relay.providers.local_inference.models import CapabilityEvidenceReport


def aggregate_rows(
    *, rows: list[dict], now: str | None = None
) -> CapabilityEvidenceReport:
    total = len(rows)
    if total == 0:
        return CapabilityEvidenceReport(
            report_id=f"cer_{secrets.token_hex(8)}",
            generated_at=now or datetime.now(UTC).isoformat(),
        )

    passed = sum(1 for r in rows if r.get("contract_passed", False))
    latencies = sorted(r.get("local_latency_ms", 0) for r in rows)
    tok_per_sec = sorted(r.get("local_tokens_per_sec", 0.0) for r in rows)
    cloud_available = sum(1 for r in rows if r.get("cloud_reference_available", False))
    local_better = sum(
        1 for r in rows if r.get("local_vs_cloud_status", "") == "local_better_latency"
    )
    promotions = sum(
        1
        for r in rows
        if r.get("recommended_route") == "local_first" and r.get("confidence") == "high"
    )
    insufficient = sum(
        1 for r in rows if r.get("recommended_route") == "insufficient_evidence"
    )

    machine_dist: dict[str, int] = {}
    task_dist: dict[str, int] = {}
    for r in rows:
        mc = r.get("machine_class", "unknown")
        machine_dist[mc] = machine_dist.get(mc, 0) + 1
        tp = r.get("task_profile", "unknown")
        task_dist[tp] = task_dist.get(tp, 0) + 1

    return CapabilityEvidenceReport(
        report_id=f"cer_{secrets.token_hex(8)}",
        generated_at=now or datetime.now(UTC).isoformat(),
        total_rows=total,
        rows_by_machine_class=machine_dist,
        rows_by_task_profile=task_dist,
        contract_pass_rate=passed / total,
        local_latency_p50=_pct(latencies, 50),
        local_latency_p95=_pct(latencies, 95),
        local_tokens_per_sec_p50=_pct(tok_per_sec, 50),
        local_tokens_per_sec_p95=_pct(tok_per_sec, 95),
        cloud_reference_coverage=cloud_available / total,
        local_better_latency_rate=local_better / total if cloud_available else 0,
        promotion_candidate_count=promotions,
        insufficient_evidence_count=insufficient,
    )


def _pct(vals: list, p: int) -> float:
    if not vals:
        return 0.0
    idx = min(int(len(vals) * p / 100.0), len(vals) - 1)
    return float(vals[idx])


__all__ = ["aggregate_rows"]
