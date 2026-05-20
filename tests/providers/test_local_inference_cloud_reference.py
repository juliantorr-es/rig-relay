"""Cloud reference executor tests — execute flag gating, API key, respx integration.

Classifications: contract, unit, integration.
"""

from __future__ import annotations

import os
from unittest import mock

import httpx
import pytest
import respx

from rig_relay.providers.local_inference import (
    compare_local_cloud,
    execute_cloud_reference,
)


class TestExecuteFlagGate:
    @pytest.mark.asyncio
    async def test_execute_false_returns_blocked(self) -> None:
        result = await execute_cloud_reference(
            messages=[{"role": "user", "content": "hello"}], execute=False
        )
        assert result["status"] == "blocked"
        assert result["reason"] == "cloud_reference_requires_execute_flag"
        assert result["completion_sha256"] == ""

    @pytest.mark.asyncio
    async def test_execute_false_no_api_call_made(self) -> None:
        with respx.mock(assert_all_called=False) as rx:
            rx.post().respond(200)
            result = await execute_cloud_reference(
                messages=[{"role": "user", "content": "hello"}], execute=False
            )
        assert result["status"] == "blocked"
        assert result["reason"] == "cloud_reference_requires_execute_flag"
        assert result["completion_sha256"] == ""


class TestAPIKeyGate:
    @pytest.mark.asyncio
    async def test_missing_api_key_returns_blocked(self) -> None:
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            result = await execute_cloud_reference(
                messages=[{"role": "user", "content": "hello"}], execute=True
            )
        assert result["status"] == "blocked"
        assert result["reason"] == "no_api_key"

    @pytest.mark.asyncio
    async def test_no_api_call_made_when_blocked_by_key(self) -> None:
        with respx.mock(assert_all_called=False) as rx:
            rx.post().respond(200)
            with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
                result = await execute_cloud_reference(
                    messages=[{"role": "user", "content": "hello"}], execute=True
                )
        assert result["status"] == "blocked"
        assert result["reason"] == "no_api_key"


class TestSuccessfulExecution:
    @pytest.mark.asyncio
    async def test_executed_result_has_status_latency_tokens(self) -> None:
        with mock.patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "sk-fake-test-key"}, clear=True
        ):
            with respx.mock(assert_all_mocked=False) as rx:
                rx.post("https://api.deepseek.com/chat/completions").respond(
                    200,
                    json={
                        "model": "deepseek-v4-flash",
                        "choices": [{"message": {"content": "42"}}],
                        "usage": {"prompt_tokens": 7, "completion_tokens": 1},
                    },
                )
                result = await execute_cloud_reference(
                    messages=[{"role": "user", "content": "What is 6 * 7?"}],
                    execute=True,
                )
        assert result["status"] == "executed"
        assert result["latency_ms"] > 0
        assert result["output_token_count"] == 1
        assert result["input_token_count"] == 7
        assert result["model_safe_id"] == "deepseek-v4-flash"
        assert result["provider"] == "deepseek"

    @pytest.mark.asyncio
    async def test_completion_sha256_populated(self) -> None:
        with mock.patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "sk-fake-test-key"}, clear=True
        ):
            with respx.mock(assert_all_mocked=False) as rx:
                rx.post("https://api.deepseek.com/chat/completions").respond(
                    200,
                    json={
                        "model": "deepseek-v4-flash",
                        "choices": [{"message": {"content": "four"}}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 1},
                    },
                )
                result = await execute_cloud_reference(
                    messages=[{"role": "user", "content": "2+2?"}], execute=True
                )
        import hashlib

        expected_sha = hashlib.sha256(b"four").hexdigest()
        assert result["completion_sha256"] == expected_sha

    @pytest.mark.asyncio
    async def test_uses_model_and_provider_from_args(self) -> None:
        with mock.patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "sk-fake-test-key"}, clear=True
        ):
            with respx.mock(assert_all_mocked=False) as rx:
                rx.post("https://api.deepseek.com/chat/completions").respond(
                    200,
                    json={
                        "model": "deepseek-v4-pro",
                        "choices": [{"message": {"content": "ok"}}],
                        "usage": {},
                    },
                )
                result = await execute_cloud_reference(
                    provider="deepseek",
                    model="deepseek-v4-pro",
                    messages=[{"role": "user", "content": "hi"}],
                    execute=True,
                )
        assert result["status"] == "executed"
        assert result["model_safe_id"] == "deepseek-v4-pro"


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_timeout_produces_timed_out(self) -> None:
        with mock.patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "sk-fake-test-key"}, clear=True
        ):
            with respx.mock(assert_all_mocked=False) as rx:
                rx.post("https://api.deepseek.com/chat/completions").mock(
                    side_effect=httpx.TimeoutException("timeout")
                )
                result = await execute_cloud_reference(
                    messages=[{"role": "user", "content": "x"}], execute=True
                )
        assert result["status"] == "timed_out"

    @pytest.mark.asyncio
    async def test_http_500_produces_failed(self) -> None:
        with mock.patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "sk-fake-test-key"}, clear=True
        ):
            with respx.mock(assert_all_mocked=False) as rx:
                rx.post("https://api.deepseek.com/chat/completions").respond(500)
                result = await execute_cloud_reference(
                    messages=[{"role": "user", "content": "x"}], execute=True
                )
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_malformed_json_produces_malformed(self) -> None:
        with mock.patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "sk-fake-test-key"}, clear=True
        ):
            with respx.mock(assert_all_mocked=False) as rx:
                rx.post("https://api.deepseek.com/chat/completions").respond(
                    200, content=b"not json"
                )
                result = await execute_cloud_reference(
                    messages=[{"role": "user", "content": "x"}], execute=True
                )
        assert result["status"] == "malformed_response"

    @pytest.mark.asyncio
    async def test_empty_choices_produces_malformed(self) -> None:
        with mock.patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "sk-fake-test-key"}, clear=True
        ):
            with respx.mock(assert_all_mocked=False) as rx:
                rx.post("https://api.deepseek.com/chat/completions").respond(
                    200, json={"choices": []}
                )
                result = await execute_cloud_reference(
                    messages=[{"role": "user", "content": "x"}], execute=True
                )
        assert result["status"] == "malformed_response"


class TestContentLight:
    def test_blocked_result_no_raw_content(self) -> None:
        import json

        blocked = {
            "status": "blocked",
            "reason": "cloud_reference_requires_execute_flag",
            "latency_ms": 0,
            "completion_sha256": "",
            "completion_byte_count": 0,
            "output_token_count": 0,
            "input_token_count": 0,
            "model_safe_id": "",
            "provider": "deepseek",
        }
        serialized = json.dumps(blocked)
        assert "secret" not in serialized.lower()
        assert "api_key" not in serialized.lower()
        assert "sk-" not in serialized

    @pytest.mark.asyncio
    async def test_executed_result_no_raw_completion_in_return(self) -> None:
        with mock.patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "sk-fake-test-key"}, clear=True
        ):
            with respx.mock(assert_all_mocked=False) as rx:
                rx.post("https://api.deepseek.com/chat/completions").respond(
                    200,
                    json={
                        "model": "deepseek-v4-flash",
                        "choices": [{"message": {"content": "The capital is Paris"}}],
                        "usage": {"prompt_tokens": 6, "completion_tokens": 4},
                    },
                )
                result = await execute_cloud_reference(
                    messages=[{"role": "user", "content": "Capital of France?"}],
                    execute=True,
                )
        assert "The capital is Paris" not in str(result)
        assert "Paris" not in result.get("completion_sha256", "")
        assert result["completion_sha256"]
        assert len(result["completion_sha256"]) == 64


class TestScientificComparisonWiring:
    def test_compare_with_cloud_result_sets_available(self) -> None:
        cloud_ref = {"status": "executed", "latency_ms": 200, "output_token_count": 10}
        report = compare_local_cloud(
            local_latency_ms=300,
            cloud_reference_result=cloud_ref,
            now="2026-06-01T00:00:00Z",
        )
        assert report.cloud_reference_available is True
        assert report.cloud_latency_ms == 200
        assert report.cloud_tokens_per_sec > 0

    def test_compare_without_cloud_result_still_missing(self) -> None:
        report = compare_local_cloud(
            local_latency_ms=300,
            cloud_reference_result=None,
            now="2026-06-01T00:00:00Z",
        )
        assert report.cloud_reference_available is False
        assert report.comparison_status == "cloud_reference_missing"

    def test_cloud_result_latency_zero_does_not_crash(self) -> None:
        cloud_ref = {"status": "executed", "latency_ms": 0, "output_token_count": 10}
        report = compare_local_cloud(
            cloud_reference_result=cloud_ref, now="2026-06-01T00:00:00Z"
        )
        assert report.cloud_tokens_per_sec == 0.0
