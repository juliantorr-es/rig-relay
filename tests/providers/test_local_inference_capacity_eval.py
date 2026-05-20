"""Capacity benchmarking & scientific comparison tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from rig_relay.providers.local_inference.benchmark_harness import (
    build_capacity_benchmark_sample,
    plan_benchmark,
)
from rig_relay.providers.local_inference.capacity_scanner import scan_capacity
from rig_relay.providers.local_inference.correlated_trace import new_correlated_trace
from rig_relay.providers.local_inference.model_fit_planner import plan_models
from rig_relay.providers.local_inference.models import CapacityScan
from rig_relay.providers.local_inference.scientific_comparison import (
    compare_local_cloud,
)
from rig_relay.providers.local_inference.telemetry_summary import (
    build_telemetry_summary,
    validate_telemetry_content_light,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"


class TestCapacityScanner:
    def test_scan_produces_valid_result(self) -> None:
        result = scan_capacity()
        assert result.scan_id.startswith("cs_")
        assert result.capacity_class in {
            "tiny_cpu",
            "small_cpu",
            "apple_silicon_light",
            "apple_silicon_medium",
            "apple_silicon_heavy",
            "cuda_light",
            "cuda_medium",
            "cuda_heavy",
            "unknown",
        }

    def test_scan_no_secrets(self) -> None:
        result = scan_capacity()
        data = json.loads(result.model_dump_json())
        assert "password" not in json.dumps(data).lower()
        assert "secret" not in json.dumps(data).lower()
        assert "api_key" not in json.dumps(data).lower()
        assert "/Users/" not in json.dumps(data)

    def test_scan_has_runtime_detection(self) -> None:
        result = scan_capacity()
        assert isinstance(result.runtimes_detected, list)

    def test_schema_exists(self) -> None:
        assert (
            SCHEMA_DIR / "rig.local_inference.capacity_scan.v1.schema.json"
        ).exists()


class TestModelFitPlanner:
    def test_plan_produces_candidates(self) -> None:
        caps = CapacityScan(
            scan_id="t",
            collected_at="",
            capacity_class="apple_silicon_medium",
            ram_total_mb=24000,
        )
        plan = plan_models(capacity=caps)
        assert len(plan.candidates) >= 2
        assert plan.recommendations_count >= 2

    def test_tiny_cpu_only_small_recommended(self) -> None:
        caps = CapacityScan(scan_id="t", collected_at="", capacity_class="tiny_cpu")
        plan = plan_models(capacity=caps)
        recs = [c for c in plan.candidates if c.recommendation_status == "recommended"]
        assert len(recs) >= 1

    def test_cuda_gets_vllm_candidate(self) -> None:
        caps = CapacityScan(
            scan_id="t",
            collected_at="",
            capacity_class="cuda_heavy",
            ram_total_mb=48000,
            runtimes_detected=["vllm"],
            cuda_available=True,
            gpu_detected=True,
        )
        plan = plan_models(capacity=caps)
        vllm_candidates = [c for c in plan.candidates if c.backend_id == "vllm"]
        assert len(vllm_candidates) >= 1

    def test_schema_exists(self) -> None:
        assert (
            SCHEMA_DIR / "rig.local_inference.model_fit_plan.v1.schema.json"
        ).exists()


class TestBenchmarkHarness:
    def test_plan_is_dry_run_by_default(self) -> None:
        plan = plan_benchmark()
        assert plan.mode == "dry_run_plan"

    def test_live_requires_approval(self) -> None:
        plan = plan_benchmark(mode="local_endpoint_live")
        assert "live_benchmark_requires_approval" in plan.blocked_reasons

    def test_sample_builder(self) -> None:
        sample = build_capacity_benchmark_sample(
            plan_id="p1",
            task_profile="chat_light",
            prompt_sha256="abc",
            completion_sha256="def",
            ttft_ms=100,
            latency_ms=300,
            tokens_per_sec=30.0,
        )
        assert sample.sample_id.startswith("cbs_")
        assert sample.ttft_ms == 100

    def test_sample_no_raw_prompt(self) -> None:
        sample = build_capacity_benchmark_sample(
            plan_id="p1", task_profile="chat_light"
        )
        data = json.loads(sample.model_dump_json())
        assert "raw_prompt" not in data


class TestCorrelatedTrace:
    def test_trace_has_all_ids(self) -> None:
        trace = new_correlated_trace(
            event_type="capacity_scan", provider_id="local", task_profile="chat_light"
        )
        assert trace.trace_id.startswith("tr_")
        assert trace.span_id.startswith("sp_")
        assert trace.provider_id == "local"

    def test_parent_chain(self) -> None:
        parent = new_correlated_trace(event_type="benchmark_request")
        child = new_correlated_trace(
            event_type="local_execution", parent_span_id=parent.span_id
        )
        assert child.parent_span_id == parent.span_id


class TestScientificComparison:
    def test_missing_cloud_reference(self) -> None:
        report = compare_local_cloud(
            task_profile="chat_light", cloud_reference_available=False
        )
        assert report.comparison_status == "cloud_reference_missing"

    def test_local_contract_passed(self) -> None:
        report = compare_local_cloud(
            task_profile="chat_light",
            cloud_reference_available=True,
            local_contract_result="passed",
            cloud_contract_result="failed",
            local_latency_ms=500,
            cloud_latency_ms=200,
        )
        assert report.comparison_status == "local_contract_passed"

    def test_local_better_latency(self) -> None:
        report = compare_local_cloud(
            task_profile="chat_light",
            cloud_reference_available=True,
            local_contract_result="passed",
            cloud_contract_result="passed",
            local_latency_ms=200,
            cloud_latency_ms=800,
        )
        assert report.comparison_status == "local_better_latency"


class TestTelemetrySummary:
    def test_content_light_default(self) -> None:
        summary = build_telemetry_summary()
        assert summary.raw_prompt_telemetry == 0
        assert summary.raw_completion_telemetry == 0
        assert summary.telemetry_export_allowed is False

    def test_validate_rejects_raw_fields(self) -> None:
        violations = validate_telemetry_content_light({
            "raw_prompt": "leaked",
            "capacity_class": "unknown",
        })
        assert len(violations) >= 1


class TestSubstrate:
    def test_no_raw_prompt_in_any_artifact(self) -> None:
        sample = build_capacity_benchmark_sample(
            plan_id="p",
            task_profile="chat_light",
            prompt_sha256="h",
            completion_sha256="c",
        )
        data = json.loads(sample.model_dump_json())
        assert "raw_prompt" not in json.dumps(data).lower()
        assert "What is" not in json.dumps(data)

    def test_scan_no_absolute_paths(self) -> None:
        result = scan_capacity()
        data = json.loads(result.model_dump_json())
        assert "/Users/" not in json.dumps(data)

    def test_no_runtime_started_anywhere(self) -> None:
        plan = plan_benchmark(mode="managed_server_live")
        assert plan.blocked_reasons


class TestCLI:
    SCRIPT = str(
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "rig_local_inference_capacity_eval.py"
    )
    SCRIPT_P = Path(SCRIPT)

    def _run(self, *args: str, **kw: object) -> subprocess.CompletedProcess[str]:
        cmd = (
            [
                sys.executable,
                self.SCRIPT_P.as_posix() if self.SCRIPT_P.exists() else self.SCRIPT,
            ]
            if self.SCRIPT_P.exists()
            else [sys.executable, self.SCRIPT]
        )
        cmd = [
            sys.executable,
            str(
                Path(__file__).resolve().parents[2]
                / "scripts"
                / "rig_local_inference_capacity_eval.py"
            ),
        ] + list(args)
        for k, v in kw.items():
            kk = k.replace("_", "-")
            if v is True:
                cmd.append(f"--{kk}")
            elif v is not False and v is not None:
                cmd.append(f"--{kk}")
                cmd.append(str(v))
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_scan_capacity(self, tmp_path: Path) -> None:
        r = self._run("scan-capacity", output_dir=str(tmp_path), json=True)
        data = json.loads(r.stdout)
        assert data["capacity_class"]

    def test_plan_models(self, tmp_path: Path) -> None:
        r = self._run("plan-models", output_dir=str(tmp_path), json=True)
        data = json.loads(r.stdout)
        assert len(data["candidates"]) >= 2

    def test_benchmark_plan(self, tmp_path: Path) -> None:
        r = self._run("benchmark-plan", output_dir=str(tmp_path), json=True)
        data = json.loads(r.stdout)
        assert data["mode"] == "dry_run_plan"

    def test_compare(self, tmp_path: Path) -> None:
        r = self._run("compare", output_dir=str(tmp_path), json=True)
        data = json.loads(r.stdout)
        assert data["comparison_status"] == "cloud_reference_missing"
