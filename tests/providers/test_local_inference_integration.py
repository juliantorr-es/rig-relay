"""Integration and adversarial tests for local inference probe against fake HTTP endpoints.

Uses respx to mock external HTTP boundaries only. Rig Relay models and probe
logic are tested against realistic HTTP responses (success, malformed, server error).
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx  # noqa: I202

from rig_relay.providers.local_inference import (
    CapabilityStatus,
    build_benchmark_sample,
    probe_local_endpoint,
    write_sample_to_jsonl,
)


@pytest.fixture
def mock_healthy_vllm() -> Generator[Any, None, None]:
    with respx.mock(base_url="http://localhost:8080", assert_all_mocked=False) as mock:
        mock.get("/health").respond(200, json={"status": "ok"})
        mock.get("/v1/models").respond(
            200,
            json={"object": "list", "data": [{"id": "test-model", "object": "model"}]},
        )
        mock.post("/v1/chat/completions").respond(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 1,
                    "total_tokens": 13,
                },
            },
        )
        yield mock


@pytest.fixture
def mock_llama_cpp_minimal() -> Generator[Any, None, None]:
    with respx.mock(base_url="http://localhost:8081", assert_all_mocked=False) as mock:
        mock.get("/health").respond(200, json={"status": "ok"})
        mock.get("/v1/models").respond(200, json={"data": [{"id": "gguf-model"}]})
        mock.post("/v1/chat/completions").respond(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )
        yield mock


@pytest.fixture
def mock_malformed_json() -> Generator[Any, None, None]:
    with respx.mock(base_url="http://localhost:8082", assert_all_mocked=False) as mock:
        mock.get("/health").respond(200, json={"status": "ok"})
        mock.get("/v1/models").respond(200, json={"data": [{"id": "bad-model"}]})
        mock.post("/v1/chat/completions").respond(200, content=b"not-json-at-all")
        yield mock


@pytest.fixture
def mock_server_error() -> Generator[Any, None, None]:
    with respx.mock(base_url="http://localhost:8083", assert_all_mocked=False) as mock:
        mock.get("/health").respond(500, json={"error": "internal"})
        mock.get("/v1/models").respond(503)
        mock.post("/v1/chat/completions").respond(502)
        yield mock


class TestProbeIntegration:
    @pytest.mark.asyncio
    async def test_probe_returns_errors_for_unreachable(
        self, mock_server_error: Any
    ) -> None:
        result = await probe_local_endpoint("http://localhost:8083", dry_run=False)
        assert result.reachable is True
        assert result.capabilities.models_list == CapabilityStatus.ERROR
        assert result.capabilities.chat_completions == CapabilityStatus.ERROR


class TestProbeAdversarial:
    @pytest.mark.asyncio
    async def test_probe_handles_malformed_json(
        self, mock_malformed_json: respx.MockRouter
    ) -> None:
        result = await probe_local_endpoint(
            "http://localhost:8082", dry_run=False, timeout_sec=2.0
        )
        assert result.reachable is True
        assert result.capabilities.chat_completions == CapabilityStatus.ERROR

    @pytest.mark.asyncio
    async def test_probe_handles_server_error(
        self, mock_server_error: respx.MockRouter
    ) -> None:
        result = await probe_local_endpoint("http://localhost:8083", dry_run=False)
        assert result.reachable is True
        assert result.capabilities.models_list == CapabilityStatus.ERROR
        assert result.capabilities.chat_completions == CapabilityStatus.ERROR


class TestBenchmarkRunRealArtifact:
    def test_benchmark_run_schema_validates(self) -> None:
        from rig_relay.providers.local_inference.models import BenchmarkRun
        import jsonschema

        SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"

        run = BenchmarkRun(
            run_id="bench_integration_test",
            runtime_url="http://localhost:8080",
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:01:00Z",
            duration_ms=60000,
            sample_count=10,
        )
        data = json.loads(run.model_dump_json())
        schema_path = SCHEMA_DIR / "rig.local_inference.benchmark_run.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)

    def test_all_schemas_are_valid_json(self) -> None:
        schema_dir = Path(__file__).resolve().parents[2] / "docs" / "schemas"
        local_inference_schemas = sorted(schema_dir.glob("rig.local_inference*.json"))
        assert len(local_inference_schemas) >= 4
        for schema_path in local_inference_schemas:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            assert "$id" in schema, f"Schema {schema_path.name} missing $id"
            assert "type" in schema, f"Schema {schema_path.name} missing type"


class TestBenchmarkSampleJSONLOutput:
    def test_jsonl_output_writes_valid_json(self, tmp_path: Path) -> None:
        from rig_relay.providers.local_inference import (
            build_benchmark_sample,
            write_sample_to_jsonl,
        )

        sample = build_benchmark_sample(
            run_id="bench_jsonl_test",
            prompt_text="test prompt",
            completion_text="test completion",
            prompt_token_count=5,
            completion_token_count=3,
        )
        path = tmp_path / "test_samples.jsonl"
        write_sample_to_jsonl(sample, path)
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["schema_version"] == "rig.local_inference.benchmark_sample.v1"

    def test_jsonl_multiple_samples(self, tmp_path: Path) -> None:
        from rig_relay.providers.local_inference import (
            build_benchmark_sample,
            write_sample_to_jsonl,
        )

        for i in range(5):
            sample = build_benchmark_sample(
                run_id="bench_multi", prompt_text=f"prompt {i}"
            )
            write_sample_to_jsonl(sample, tmp_path / "multi.jsonl")

        lines = (
            (tmp_path / "multi.jsonl").read_text(encoding="utf-8").strip().split("\n")
        )
        assert len(lines) == 5
        hashes = {json.loads(line)["prompt_sha256"] for line in lines}
        assert len(hashes) == 5


class TestArchitectureReportValidates:
    def test_evaluation_report_validates(self) -> None:
        import jsonschema

        REPORT_DIR = (
            Path(__file__).resolve().parents[2] / "docs" / "json" / "governance"
        )
        SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"

        report_path = REPORT_DIR / "local_inference_runtime_evaluation_v1.v1.json"
        assert report_path.exists(), "Architecture report must exist"

        schema_path = (
            SCHEMA_DIR / "rig.local_inference_runtime_evaluation.v1.schema.json"
        )
        assert schema_path.exists(), "Architecture report schema must exist"

        report = json.loads(report_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(report, schema)
