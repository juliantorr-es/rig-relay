from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import pytest

from rig_relay.providers.local_inference.duckdb_projection import (
    HAS_DUCKDB,
    compute_benchmark_summary_from_jsonl,
    compute_evidence_dataset_summary,
)
from rig_relay.providers.local_inference.energy_measurement import (
    measure_power_estimate,
)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    text = "\n".join(json.dumps(r) for r in records) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


class TestDuckDBBenchmarkSummary:
    @pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not available")
    def test_percentiles_from_jsonl(self, tmp_path: Path) -> None:
        records = [
            {
                "sample_id": "a",
                "plan_id": "p1",
                "task_profile": "chat",
                "status": "completed",
                "error_class": "",
                "latency_ms": 100,
                "ttft_ms": 30,
                "tokens_per_sec": 50.0,
            },
            {
                "sample_id": "b",
                "plan_id": "p1",
                "task_profile": "chat",
                "status": "failed",
                "error_class": "timeout",
                "latency_ms": 300,
                "ttft_ms": 90,
                "tokens_per_sec": 30.0,
            },
            {
                "sample_id": "c",
                "plan_id": "p1",
                "task_profile": "tool_use",
                "status": "completed",
                "error_class": "",
                "latency_ms": 200,
                "ttft_ms": 60,
                "tokens_per_sec": 40.0,
            },
        ]
        path = _write_jsonl(tmp_path / "bench.jsonl", records)

        result = compute_benchmark_summary_from_jsonl(path)

        assert result["sample_count"] == 3
        assert result["latency_ms_p50"] == 200.0
        assert result["latency_ms_p95"] == 300.0
        assert result["ttft_ms_p50"] == 60.0
        assert result["ttft_ms_p95"] == 90.0
        assert result["tokens_per_sec_p50"] == 40.0
        assert result["tokens_per_sec_p95"] == 50.0

        assert result["count_by_status"] == {"completed": 2, "failed": 1}
        assert result["count_by_error_class"] == {"timeout": 1}
        assert result["count_by_task_profile"] == {"chat": 2, "tool_use": 1}

    def test_missing_duckdb_returns_error_dict(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            "rig_relay.providers.local_inference.duckdb_projection.HAS_DUCKDB", False
        )
        result = compute_benchmark_summary_from_jsonl(Path("/nonexistent.jsonl"))
        assert "error" in result
        assert "DuckDB" in result["error"]
        assert result["sample_count"] == 0

    def test_empty_jsonl_returns_zeros(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")

        result = compute_benchmark_summary_from_jsonl(path)
        assert result["sample_count"] == 0

    def test_missing_file_returns_zeros(self) -> None:
        result = compute_benchmark_summary_from_jsonl(Path("/nonexistent.jsonl"))
        assert result["sample_count"] == 0

    @pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not available")
    def test_no_raw_prompts_in_output(self, tmp_path: Path) -> None:
        records = [
            {
                "sample_id": "a",
                "plan_id": "p1",
                "task_profile": "chat",
                "status": "completed",
                "error_class": "",
                "latency_ms": 100,
                "ttft_ms": 30,
                "tokens_per_sec": 50.0,
            }
        ]
        path = _write_jsonl(tmp_path / "bench.jsonl", records)
        result = compute_benchmark_summary_from_jsonl(path)
        result_str = json.dumps(result)
        assert "prompt_sha256" not in result_str.lower()
        assert "completion" not in result_str.lower()
        assert "raw" not in result_str.lower()


class TestDuckDBEvidenceSummary:
    @pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not available")
    def test_percentiles_from_jsonl(self, tmp_path: Path) -> None:
        records = [
            {
                "evidence_id": "e1",
                "task_profile": "chat",
                "machine_class": "apple_silicon_light",
                "recommended_route": "local_first",
                "contract_passed": True,
                "local_latency_ms": 150,
                "local_ttft_ms": 40,
                "local_tokens_per_sec": 55.0,
            },
            {
                "evidence_id": "e2",
                "task_profile": "tool_use",
                "machine_class": "apple_silicon_light",
                "recommended_route": "cloud_escalation",
                "contract_passed": False,
                "local_latency_ms": 350,
                "local_ttft_ms": 100,
                "local_tokens_per_sec": 25.0,
            },
            {
                "evidence_id": "e3",
                "task_profile": "chat",
                "machine_class": "cuda_light",
                "recommended_route": "local_first",
                "contract_passed": True,
                "local_latency_ms": 200,
                "local_ttft_ms": 60,
                "local_tokens_per_sec": 40.0,
            },
        ]
        path = _write_jsonl(tmp_path / "evidence.jsonl", records)

        result = compute_evidence_dataset_summary(path)

        assert result["sample_count"] == 3
        assert result["local_latency_ms_p50"] == 200.0
        assert result["local_latency_ms_p95"] == 350.0
        assert result["local_ttft_ms_p50"] == 60.0
        assert result["local_ttft_ms_p95"] == 100.0
        assert result["local_tokens_per_sec_p50"] == 40.0
        assert result["local_tokens_per_sec_p95"] == 55.0

        assert result["count_by_task_profile"] == {"chat": 2, "tool_use": 1}
        assert result["count_by_machine_class"] == {
            "apple_silicon_light": 2,
            "cuda_light": 1,
        }
        assert result["count_by_recommended_route"] == {
            "local_first": 2,
            "cloud_escalation": 1,
        }
        assert result["contract_pass_rate"] == pytest.approx(2.0 / 3.0)

    def test_missing_duckdb_returns_error_dict(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            "rig_relay.providers.local_inference.duckdb_projection.HAS_DUCKDB", False
        )
        result = compute_evidence_dataset_summary(Path("/nonexistent.jsonl"))
        assert "error" in result
        assert result["sample_count"] == 0

    def test_empty_jsonl_returns_zeros(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        result = compute_evidence_dataset_summary(path)
        assert result["sample_count"] == 0

    @pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB not available")
    def test_no_raw_prompts_in_output(self, tmp_path: Path) -> None:
        records = [
            {
                "evidence_id": "e1",
                "task_profile": "chat",
                "machine_class": "cuda_light",
                "recommended_route": "local_first",
                "contract_passed": True,
                "local_latency_ms": 150,
                "local_ttft_ms": 40,
                "local_tokens_per_sec": 55.0,
            }
        ]
        path = _write_jsonl(tmp_path / "ev.jsonl", records)
        result = compute_evidence_dataset_summary(path)
        result_str = json.dumps(result)
        assert "completion" not in result_str.lower()
        assert "prompt" not in result_str.lower()
        assert "raw" not in result_str.lower()


class TestEnergyMeasurement:
    def test_returns_valid_shape(self) -> None:
        result = measure_power_estimate()
        assert "power_estimate_watts" in result
        assert "thermal_state" in result
        assert "platform" in result
        assert isinstance(result["platform"], str)
        assert result["power_estimate_watts"] is None or isinstance(
            result["power_estimate_watts"], float
        )
        assert isinstance(result["thermal_state"], str)

    def test_no_sensitive_data(self) -> None:
        result = measure_power_estimate()
        result_str = json.dumps(result).lower()
        assert "serial" not in result_str
        assert "battery" not in result_str
        assert "health" not in result_str
        assert "user" not in result_str
        assert "password" not in result_str
        assert "token" not in result_str
        assert "key" not in result_str

    def test_content_light_no_raw_files(self) -> None:
        result = measure_power_estimate()
        result_str = json.dumps(result)
        assert "prompt" not in result_str.lower()
        assert "completion" not in result_str.lower()
        assert "raw" not in result_str.lower()

    def test_platform_is_nonempty(self) -> None:
        result = measure_power_estimate()
        assert len(result["platform"]) > 0

    def test_power_estimate_watts_null_on_non_linux(self) -> None:
        result = measure_power_estimate()
        if sys.platform != "linux":
            assert result["power_estimate_watts"] is None
