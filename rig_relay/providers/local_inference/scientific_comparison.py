"""Scientific local-vs-cloud comparison report. Content-light."""

from __future__ import annotations

from datetime import UTC, datetime
import secrets
from typing import Any

from rig_relay.providers.local_inference.models import ScientificComparisonReport


def compare_local_cloud(
    *,
    task_profile: str = "",
    scenario_id: str = "",
    local_provider_id: str = "",
    cloud_provider_id: str = "",
    local_model_hash: str = "",
    cloud_model_hash: str = "",
    local_contract_result: str = "",
    cloud_contract_result: str = "",
    local_ttft_ms: int = 0,
    cloud_ttft_ms: int = 0,
    local_latency_ms: int = 0,
    cloud_latency_ms: int = 0,
    local_tokens_per_sec: float = 0.0,
    cloud_tokens_per_sec: float = 0.0,
    local_error_rate: float = 0.0,
    cloud_error_rate: float = 0.0,
    cloud_reference_available: bool = False,
    cloud_reference_result: dict[str, Any] | None = None,
    now: str | None = None,
) -> ScientificComparisonReport:
    if cloud_reference_result is not None:
        cloud_reference_available = True
        _ingest_cloud_result = _inject_cloud_fields(
            cloud_reference_result,
            cloud_latency_ms,
            cloud_tokens_per_sec,
            cloud_ttft_ms,
        )
        cloud_latency_ms = _ingest_cloud_result[0]
        cloud_tokens_per_sec = _ingest_cloud_result[1]
        cloud_ttft_ms = _ingest_cloud_result[2]

    report = ScientificComparisonReport(
        report_id=f"scr_{secrets.token_hex(8)}",
        generated_at=now or datetime.now(UTC).isoformat(),
        task_profile=task_profile,
        scenario_id=scenario_id,
        local_provider_id=local_provider_id,
        cloud_provider_id=cloud_provider_id,
        local_model_hash=local_model_hash,
        cloud_model_hash=cloud_model_hash,
        local_contract_result=local_contract_result,
        cloud_contract_result=cloud_contract_result,
        local_ttft_ms=local_ttft_ms,
        cloud_ttft_ms=cloud_ttft_ms,
        local_latency_ms=local_latency_ms,
        cloud_latency_ms=cloud_latency_ms,
        local_tokens_per_sec=local_tokens_per_sec,
        cloud_tokens_per_sec=cloud_tokens_per_sec,
        local_error_rate=local_error_rate,
        cloud_error_rate=cloud_error_rate,
        cloud_reference_available=cloud_reference_available,
    )
    if not cloud_reference_available:
        report.comparison_status = "cloud_reference_missing"
    elif local_contract_result == "passed" and cloud_contract_result != "passed":
        report.comparison_status = "local_contract_passed"
    elif local_latency_ms < cloud_latency_ms:
        report.comparison_status = "local_better_latency"
    else:
        report.comparison_status = "cloud_better_latency"
    report.local_privacy_score = 1.0
    return report


def _inject_cloud_fields(
    cloud_result: dict[str, Any],
    current_latency: int,
    current_tps: float,
    current_ttft: int,
) -> tuple[int, float, int]:
    latency = cloud_result.get("latency_ms", current_latency)
    output_tokens = cloud_result.get("output_token_count", 0)
    tps = (output_tokens / (latency / 1000)) if latency > 0 else current_tps
    return latency, tps, current_ttft


__all__ = ["compare_local_cloud"]
