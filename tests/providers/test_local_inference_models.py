"""Contract and unit tests for local inference models, schemas, and dry-run probe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.providers.local_inference import (
    BenchmarkRun,
    CapabilityStatus,
    LocalRuntimeKind,
    ProbeStatus,
    RoutingConfidence,
    TaskProfile,
    TaskType,
    build_benchmark_sample,
    probe_local_endpoint,
    select_runtime,
    write_sample_to_jsonl,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"


class TestSchemaValidation:
    def test_capability_probe_schema_exists(self) -> None:
        schema_path = (
            SCHEMA_DIR / "rig.local_inference.runtime_capability_probe.v1.schema.json"
        )
        assert schema_path.exists()

    def test_capability_probe_schema_valid_json(self) -> None:
        schema_path = (
            SCHEMA_DIR / "rig.local_inference.runtime_capability_probe.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["$id"].endswith("runtime_capability_probe.v1")

    def test_benchmark_run_schema_exists(self) -> None:
        schema_path = SCHEMA_DIR / "rig.local_inference.benchmark_run.v1.schema.json"
        assert schema_path.exists()

    def test_benchmark_sample_schema_exists(self) -> None:
        schema_path = SCHEMA_DIR / "rig.local_inference.benchmark_sample.v1.schema.json"
        assert schema_path.exists()

    def test_routing_decision_schema_exists(self) -> None:
        schema_path = SCHEMA_DIR / "rig.local_inference.routing_decision.v1.schema.json"
        assert schema_path.exists()

    def test_evaluation_report_schema_exists(self) -> None:
        schema_path = (
            SCHEMA_DIR / "rig.local_inference_runtime_evaluation.v1.schema.json"
        )
        assert schema_path.exists()


class TestCapabilityProbeDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_probe_returns_reachable(self) -> None:
        result = await probe_local_endpoint("http://localhost:8080", dry_run=True)
        assert result.reachable is True
        assert result.runtime_engine == LocalRuntimeKind.LLAMA_CPP
        assert result.capabilities.chat_completions == CapabilityStatus.SUPPORTED
        assert result.capabilities.streaming == CapabilityStatus.SUPPORTED
        assert result.probe_id.startswith("probe_")
        assert result.probe_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_dry_run_probe_has_no_errors(self) -> None:
        result = await probe_local_endpoint("http://localhost:8080", dry_run=True)
        assert result.errors == []
        assert result.health_summary.status == "ok"

    @pytest.mark.asyncio
    async def test_probe_result_validates_against_schema(self) -> None:
        import jsonschema

        result = await probe_local_endpoint("http://localhost:8080", dry_run=True)
        data = json.loads(result.model_dump_json())
        schema_path = (
            SCHEMA_DIR / "rig.local_inference.runtime_capability_probe.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)


class TestBenchmarkSampleWriter:
    def test_build_benchmark_sample_hash_only(self) -> None:
        sample = build_benchmark_sample(
            run_id="bench_test",
            prompt_text="What is 1+1?",
            completion_text="2",
            prompt_token_count=5,
            completion_token_count=1,
        )
        assert sample.sample_id.startswith("sample_")
        assert sample.prompt_sha256
        assert len(sample.prompt_sha256) == 64
        assert sample.completion_sha256
        assert len(sample.completion_sha256) == 64
        assert sample.prompt_token_count == 5
        assert sample.completion_token_count == 1
        assert sample.status == ProbeStatus.COMPLETED

    def test_build_benchmark_sample_content_light(self) -> None:
        sample = build_benchmark_sample(run_id="bench_test", prompt_text="What is 1+1?")
        data = json.loads(sample.model_dump_json())
        assert "prompt_text" not in data
        assert "completion_text" not in data
        assert "What is 1+1?" not in json.dumps(data)

    def test_write_and_read_jsonl(self, tmp_path: Path) -> None:
        sample = build_benchmark_sample(
            run_id="bench_test",
            prompt_text="test prompt",
            completion_text="test completion",
            prompt_token_count=3,
            completion_token_count=2,
        )
        path = tmp_path / "samples.jsonl"
        write_sample_to_jsonl(sample, path)
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["sample_id"] == sample.sample_id
        assert parsed["prompt_sha256"] == sample.prompt_sha256

    def test_sample_validates_against_schema(self) -> None:
        import jsonschema

        sample = build_benchmark_sample(
            run_id="bench_test", prompt_text="test", completion_text="result"
        )
        data = json.loads(sample.model_dump_json())
        schema_path = SCHEMA_DIR / "rig.local_inference.benchmark_sample.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)


class TestBenchmarkRunModel:
    def test_benchmark_run_validates_against_schema(self) -> None:
        import jsonschema

        run = BenchmarkRun(
            run_id="bench_test001",
            runtime_url="http://localhost:8080",
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:01:00Z",
            duration_ms=60000,
            sample_count=100,
        )
        data = json.loads(run.model_dump_json())
        schema_path = SCHEMA_DIR / "rig.local_inference.benchmark_run.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)


class TestRoutingDecision:
    def test_dry_run_returns_fallback(self) -> None:
        result = select_runtime(
            probed_runtimes=[], task_profile=TaskProfile(), dry_run=True
        )
        assert result.confidence == RoutingConfidence.FALLBACK
        assert "dry-run" in result.decision_rationale.lower()

    def test_empty_probes_returns_fallback(self) -> None:
        result = select_runtime(
            probed_runtimes=[], task_profile=TaskProfile(), dry_run=False
        )
        assert result.confidence == RoutingConfidence.FALLBACK

    @pytest.mark.asyncio
    async def test_routing_with_probed_runtimes(self) -> None:
        probe = await probe_local_endpoint("http://localhost:8080", dry_run=True)
        result = select_runtime(
            probed_runtimes=[probe],
            task_profile=TaskProfile(task_type=TaskType.CHAT, tool_call_required=False),
            dry_run=False,
        )
        assert result.selected_runtime_url == "http://localhost:8080"
        assert result.selected_runtime_engine == "llama_cpp"

    def test_routing_decision_validates_against_schema(self) -> None:
        import jsonschema

        result = select_runtime(
            probed_runtimes=[], task_profile=TaskProfile(), dry_run=True
        )
        data = json.loads(result.model_dump_json())
        schema_path = SCHEMA_DIR / "rig.local_inference.routing_decision.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)


class TestBenchmarkSampleContentLight:
    def test_no_raw_prompt_in_sample(self) -> None:
        sample = build_benchmark_sample(
            run_id="bench_test",
            prompt_text="sensitive user prompt",
            completion_text="sensitive model output",
        )
        data = json.loads(sample.model_dump_json())
        assert "sensitive" not in json.dumps(data)
        assert "user prompt" not in json.dumps(data)
        assert "model output" not in json.dumps(data)

    def test_sample_has_required_fields(self) -> None:
        sample = build_benchmark_sample(run_id="bench_test", prompt_text="test")
        data = json.loads(sample.model_dump_json())
        for field in [
            "schema_version",
            "sample_id",
            "run_id",
            "prompt_sha256",
            "prompt_token_count",
            "status",
            "duration_ms",
        ]:
            assert field in data, f"Missing required field: {field}"

    def test_sample_no_extra_fields(self) -> None:
        sample = build_benchmark_sample(
            run_id="bench_test", prompt_text="test", duration_ms=100
        )
        data = json.loads(sample.model_dump_json())
        forbidden = {"prompt_text", "completion_text", "raw", "content"}
        for field in forbidden:
            assert field not in data, f"Content field leaked: {field}"
