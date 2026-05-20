from __future__ import annotations

import json

import httpx
import pytest
import respx

from rig_relay.providers.local_inference.execution_client import (
    execute_chat_completion_streaming,
)


def _sse_chunk(content: str) -> bytes:
    return (
        f'data: {{"choices":[{{"delta":{{"content":"{content}"}},"index":0}}]}}\n\n'
    ).encode()


def _sse_bytes(*lines: str) -> bytes:
    return "\n".join(lines).encode("utf-8") + b"\n"


class TestStreamingSSEParsing:
    @pytest.mark.asyncio
    async def test_single_chunk_produces_content(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"hello"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:50001/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:50001",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "executed"
        assert result["ephemeral_content"] == "hello"
        assert result["streaming_chunk_count"] == 1

    @pytest.mark.asyncio
    async def test_multiple_chunks_accumulate_content(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"hello"},"index":0}]}',
            'data: {"choices":[{"delta":{"content":" "},"index":0}]}',
            'data: {"choices":[{"delta":{"content":"world"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:50002/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:50002",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "executed"
        assert result["ephemeral_content"] == "hello world"
        assert result["streaming_chunk_count"] == 3

    @pytest.mark.asyncio
    async def test_chunk_count_tracks_every_json_payload(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"a"},"index":0}]}',
            'data: {"choices":[{"delta":{"content":"b"},"index":0}]}',
            'data: {"choices":[{"delta":{"content":"c"},"index":0}]}',
            'data: {"choices":[{"delta":{"content":"d"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:50003/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:50003",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["streaming_chunk_count"] == 4

    @pytest.mark.asyncio
    async def test_chunks_with_role_delta_are_skipped(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"role":"assistant"},"index":0}]}',
            'data: {"choices":[{"delta":{"content":"ok"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:50004/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:50004",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "executed"
        assert result["ephemeral_content"] == "ok"
        assert result["streaming_chunk_count"] == 2

    @pytest.mark.asyncio
    async def test_null_content_delta_is_skipped(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":null},"index":0}]}',
            'data: {"choices":[{"delta":{"content":"valid"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:50005/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:50005",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "executed"
        assert result["ephemeral_content"] == "valid"

    @pytest.mark.asyncio
    async def test_model_id_extracted_from_chunks(self) -> None:
        sse = _sse_bytes(
            'data: {"model":"test-model-v2","choices":[{"delta":{"content":"hi"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:50006/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:50006",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["model_safe_id"] == "test-model-v2"


class TestStreamingTTFT:
    @pytest.mark.asyncio
    async def test_ttft_positive_when_content_arrives(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"h"},"index":0}]}',
            'data: {"choices":[{"delta":{"content":"i"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:51001/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:51001",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["ttft_ms"] >= 0
        assert result["latency_ms"] >= result["ttft_ms"]

    @pytest.mark.asyncio
    async def test_ttft_zero_on_empty_stream(self) -> None:
        sse = b"data: [DONE]\n"
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:51002/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:51002",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "malformed_response"
        assert result["ttft_ms"] == 0


class TestStreamingCompletions:
    @pytest.mark.asyncio
    async def test_completion_sha256_is_stable(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"hello"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:52001/v1/chat/completions").respond(
                200, content=sse
            )
            r1 = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:52001",
                messages=[{"role": "user", "content": "x"}],
            )
            r2 = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:52001",
                messages=[{"role": "user", "content": "x"}],
            )
        assert r1["completion_sha256"] == r2["completion_sha256"]
        assert r1["completion_sha256"]
        assert len(r1["completion_sha256"]) == 64

    @pytest.mark.asyncio
    async def test_byte_count_matches_content_length(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"abcde"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:52002/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:52002",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["completion_byte_count"] == len(
            result["ephemeral_content"].encode("utf-8")
        )

    @pytest.mark.asyncio
    async def test_usage_extracted_from_final_chunk(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"result"},"index":0}]}',
            'data: {"choices":[{"delta":{},"index":0,"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":2}}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:52003/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:52003",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["input_token_count"] == 10
        assert result["output_token_count"] == 2


class TestStreamingErrorHandling:
    @pytest.mark.asyncio
    async def test_timeout_produces_timed_out_status(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:53001/v1/chat/completions").mock(
                side_effect=httpx.TimeoutException("timed out")
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:53001",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "timed_out"
        assert result["ttft_ms"] == 0
        assert result["streaming_chunk_count"] == 0

    @pytest.mark.asyncio
    async def test_http_error_produces_failed(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:53002/v1/chat/completions").respond(500)
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:53002",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "failed"
        assert result["error_class"] == "HTTP 500"

    @pytest.mark.asyncio
    async def test_malformed_sse_json_does_not_crash(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"good"},"index":0}]}',
            "data: not-valid-json {{{",
            'data: {"choices":[{"delta":{"content":"still-good"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:53003/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:53003",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "executed"
        assert result["ephemeral_content"] == "goodstill-good"
        assert result["streaming_chunk_count"] == 2

    @pytest.mark.asyncio
    async def test_empty_sse_stream_produces_error(self) -> None:
        sse = b""
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:53004/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:53004",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "malformed_response"
        assert result["error_class"] == "empty_sse_stream"

    @pytest.mark.asyncio
    async def test_connect_error_returns_failed(self) -> None:
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:53005/v1/chat/completions").mock(
                side_effect=httpx.ConnectError("refused")
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:53005",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["status"] == "failed"
        assert "ConnectError" in result["error_class"]

    @pytest.mark.asyncio
    async def test_content_light_sha256_not_raw_persisted(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"unique-output-string"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:53006/v1/chat/completions").respond(
                200, content=sse
            )
            result = await execute_chat_completion_streaming(
                endpoint_url="http://127.0.0.1:53006",
                messages=[{"role": "user", "content": "x"}],
            )
        assert result["ephemeral_content"] == "unique-output-string"
        assert result["completion_sha256"]
        assert len(result["completion_sha256"]) == 64
        assert result["completion_byte_count"] == len(b"unique-output-string")


class TestStreamingBenchmarkLoop:
    @pytest.mark.asyncio
    async def test_streaming_loop_populates_ttft(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"hello"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:54001/v1/chat/completions").respond(
                200, content=sse
            )
            from rig_relay.providers.local_inference.benchmark_executor import (
                run_benchmark_loop,
            )

            plan, samples = await run_benchmark_loop(
                endpoint_url="http://127.0.0.1:54001",
                task_profiles=["chat_light"],
                sample_count_per_profile=2,
                timeout_sec=5.0,
                streaming=True,
            )
        assert plan.sample_count == 2
        assert len(samples) == 2
        for s in samples:
            assert s.status == "executed"
            assert s.ttft_ms >= 0
            assert s.completion_sha256

    @pytest.mark.asyncio
    async def test_streaming_loop_content_light(self) -> None:
        sse = _sse_bytes(
            'data: {"choices":[{"delta":{"content":"hello world"},"index":0}]}',
            "data: [DONE]",
        )
        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:54002/v1/chat/completions").respond(
                200, content=sse
            )
            from rig_relay.providers.local_inference.benchmark_executor import (
                run_benchmark_loop,
            )

            plan, samples = await run_benchmark_loop(
                endpoint_url="http://127.0.0.1:54002",
                task_profiles=["chat_light"],
                sample_count_per_profile=1,
                timeout_sec=5.0,
                streaming=True,
            )
        for s in samples:
            data = json.loads(s.model_dump_json())
            assert "hello" not in json.dumps(data).lower()
            assert s.completion_sha256
            assert len(s.completion_sha256) == 64
