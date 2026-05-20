from __future__ import annotations

import asyncio
import hashlib
import json
import secrets

import httpx
import pytest
import respx

from rig_relay.providers.local_inference.benchmark_executor import (
    run_benchmark_concurrent,
)
from rig_relay.providers.local_inference.models import CapacityBenchmarkSample

_ENDPOINT = "http://127.0.0.1:19865"


def _fake_completion_json(content: str = "hello") -> dict[str, object]:
    return {
        "model": "test",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": len(content.split())},
    }


class TestRunBenchmarkConcurrent:
    @pytest.mark.asyncio
    async def test_concurrent_requests_all_succeed(self) -> None:
        call_times: list[float] = []

        def _side_effect(request: httpx.Request) -> httpx.Response:
            call_times.append(asyncio.get_event_loop().time())
            msg = json.loads(request.content)["messages"][0]["content"]
            return httpx.Response(
                200,
                json={
                    "model": "test",
                    "choices": [{"message": {"content": f"echo: {msg[:20]}"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                },
            )

        with respx.mock(assert_all_mocked=False) as mock:
            mock.post(f"{_ENDPOINT}/v1/chat/completions").mock(side_effect=_side_effect)

            plan, samples = await run_benchmark_concurrent(
                endpoint_url=_ENDPOINT,
                concurrency=3,
                task_profile="chat_light",
                sample_count=3,
                timeout_sec=5.0,
            )

        assert plan.sample_count == 3
        assert len(samples) == 3
        for s in samples:
            assert s.status == "executed"
            assert s.prompt_sha256
            assert len(s.prompt_sha256) == 64
            assert s.completion_sha256
            assert len(s.completion_sha256) == 64
            assert s.concurrency_level == 3
            assert s.latency_ms > 0

    @pytest.mark.asyncio
    async def test_all_samples_have_concurrency_level(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post(f"{_ENDPOINT}/v1/chat/completions").respond(
                200, json=_fake_completion_json("ok")
            )

            plan, samples = await run_benchmark_concurrent(
                endpoint_url=_ENDPOINT,
                concurrency=5,
                task_profile="chat_light",
                sample_count=5,
                timeout_sec=5.0,
            )

        assert len(samples) == 5
        for s in samples:
            assert s.concurrency_level == 5

    @pytest.mark.asyncio
    async def test_no_interleaved_corrupted_responses(self) -> None:
        received_contents: list[str] = []

        def _side_effect(request: httpx.Request) -> httpx.Response:
            msg = json.loads(request.content)["messages"][0]["content"]
            received_contents.append(msg)
            return httpx.Response(
                200,
                json={
                    "model": "test",
                    "choices": [{"message": {"content": f"r: {msg[:10]}"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                },
            )

        with respx.mock(assert_all_mocked=False) as mock:
            mock.post(f"{_ENDPOINT}/v1/chat/completions").mock(side_effect=_side_effect)

            plan, samples = await run_benchmark_concurrent(
                endpoint_url=_ENDPOINT,
                concurrency=3,
                task_profile="chat_light",
                sample_count=3,
                timeout_sec=5.0,
            )

        assert len(samples) == 3
        assert len(received_contents) == 3
        for s in samples:
            assert s.status == "executed"
            assert s.completion_sha256
            assert len(s.completion_sha256) == 64

    @pytest.mark.asyncio
    async def test_one_failing_request_does_not_crash_gather(self) -> None:
        call_count = 0

        def _side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return httpx.Response(500, json={"error": "internal"})
            return httpx.Response(
                200,
                json={
                    "model": "test",
                    "choices": [{"message": {"content": "good"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                },
            )

        with respx.mock(assert_all_mocked=False) as mock:
            mock.post(f"{_ENDPOINT}/v1/chat/completions").mock(side_effect=_side_effect)

            plan, samples = await run_benchmark_concurrent(
                endpoint_url=_ENDPOINT,
                concurrency=3,
                task_profile="chat_light",
                sample_count=3,
                timeout_sec=5.0,
            )

        assert len(samples) == 3
        succeeded = [s for s in samples if s.status == "executed"]
        failed = [s for s in samples if s.status == "failed"]
        assert len(succeeded) == 2
        assert len(failed) == 1
        assert failed[0].error_class
        for s in succeeded:
            assert s.completion_sha256
            assert len(s.completion_sha256) == 64
        for s in samples:
            assert s.concurrency_level == 3

    @pytest.mark.asyncio
    async def test_exception_in_task_captured_gracefully(self) -> None:
        call_count = 0

        def _side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise httpx.ConnectError("refused")
            return httpx.Response(
                200,
                json={
                    "model": "test",
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                },
            )

        with respx.mock(assert_all_mocked=False) as mock:
            mock.post(f"{_ENDPOINT}/v1/chat/completions").mock(side_effect=_side_effect)

            plan, samples = await run_benchmark_concurrent(
                endpoint_url=_ENDPOINT, concurrency=3, sample_count=3, timeout_sec=5.0
            )

        assert len(samples) == 3
        succeeded = [s for s in samples if s.status == "executed"]
        assert len(succeeded) == 2
        for s in samples:
            assert s.concurrency_level == 3

    def test_sample_model_includes_concurrency_level(self) -> None:
        sample = CapacityBenchmarkSample(
            sample_id=f"cbs_{secrets.token_hex(8)}",
            plan_id=f"cbp_{secrets.token_hex(8)}",
            trace_id=f"tr_{secrets.token_hex(8)}",
            mode="local_endpoint_live",
            task_profile="chat_light",
            prompt_sha256=hashlib.sha256(b"test").hexdigest(),
            completion_sha256=hashlib.sha256(b"hello").hexdigest(),
            ttft_ms=10,
            latency_ms=50,
            tokens_per_sec=20.0,
            input_token_count=5,
            output_token_count=1,
            concurrency_level=7,
            status="executed",
        )
        data = json.loads(sample.model_dump_json())
        assert data["concurrency_level"] == 7

    def test_content_light_sha256_only_no_raw_content(self) -> None:
        sample = CapacityBenchmarkSample(
            sample_id=f"cbs_{secrets.token_hex(8)}",
            plan_id=f"cbp_{secrets.token_hex(8)}",
            trace_id=f"tr_{secrets.token_hex(8)}",
            mode="local_endpoint_live",
            task_profile="chat_light",
            prompt_sha256=hashlib.sha256(b"prompt").hexdigest(),
            completion_sha256=hashlib.sha256(b"completion").hexdigest(),
            ttft_ms=5,
            latency_ms=30,
            tokens_per_sec=33.3,
            input_token_count=4,
            output_token_count=1,
            concurrency_level=3,
            status="executed",
        )
        data_str = sample.model_dump_json()
        assert "hello" not in data_str.lower()
        parsed = json.loads(data_str)
        assert len(parsed["prompt_sha256"]) == 64
        assert len(parsed["completion_sha256"]) == 64
