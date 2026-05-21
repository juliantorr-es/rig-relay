"""Execution loop tests — model download, benchmark runner, prompt fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.providers.local_inference.benchmark_executor import (
    BENCHMARK_PROMPTS,
    build_prompt_fixtures,
)
from rig_relay.providers.local_inference.model_download_executor import (
    execute_model_download,
)


class TestModelDownloadExecutor:
    def test_blocked_by_default(self) -> None:
        plan = execute_model_download(backend_id="ollama", model_id="llama3")
        assert plan.download_executed is False
        assert any("backend_not_enabled" in r for r in plan.blocked_reasons)

    def test_unknown_backend_blocks(self) -> None:
        plan = execute_model_download(backend_id="nonexistent", model_id="x")
        assert "unknown_backend" in plan.blocked_reasons[0]

    def test_plan_only_without_execute(self) -> None:
        plan = execute_model_download(
            backend_id="ollama", model_id="llama3", execute=False
        )
        assert plan.download_executed is False
        assert (
            "backend_not_enabled" in plan.blocked_reasons
            or "execute_flag_not_set" in plan.blocked_reasons
        )
        assert plan.command_hash

    def test_command_hash_is_populated(self) -> None:
        plan = execute_model_download(backend_id="ollama", model_id="llama3")
        assert plan.command_hash
        assert len(plan.command_hash) == 64

    def test_model_id_hash_stable(self) -> None:
        p1 = execute_model_download(backend_id="ollama", model_id="llama3")
        p2 = execute_model_download(backend_id="ollama", model_id="llama3")
        assert p1.model_id_hash == p2.model_id_hash

    def test_no_backend_template_blocks(self) -> None:
        plan = execute_model_download(
            backend_id="custom_openai_compatible", model_id="x"
        )
        assert "no_pull_command_template" in plan.blocked_reasons

    def test_real_download_blocked_in_test(self) -> None:
        plan = execute_model_download(
            backend_id="ollama", model_id="llama3", execute=False
        )
        assert plan.download_executed is False


class TestBenchmarkPrompts:
    def test_four_profiles_have_prompts(self) -> None:
        fixtures = build_prompt_fixtures()
        assert "chat_light" in fixtures
        assert "structured_json" in fixtures
        assert "tool_planning" in fixtures
        assert "code_review_light" in fixtures

    def test_five_prompts_per_profile(self) -> None:
        for profile, prompts in BENCHMARK_PROMPTS.items():
            assert len(prompts) == 5, f"{profile} has {len(prompts)} prompts"

    def test_all_prompts_are_synthetic_safe(self) -> None:
        for prompts in BENCHMARK_PROMPTS.values():
            for msg in prompts:
                content = msg["content"]
                assert content
                assert len(content) < 500

    def test_prompts_are_dicts_with_role_and_content(self) -> None:
        for prompts in BENCHMARK_PROMPTS.values():
            for msg in prompts:
                assert "role" in msg
                assert "content" in msg
                assert msg["role"] == "user"

    def test_structured_json_prompts_contain_json(self) -> None:
        fixtures = BENCHMARK_PROMPTS["structured_json"]
        for msg in fixtures:
            has_json = any(kw in msg["content"].lower() for kw in {"json", "{", "}"})
            assert has_json, f"Missing JSON keywords in: {msg['content']}"


class TestBenchmarkLoopFakeEndpoint:
    @pytest.mark.asyncio
    async def test_loop_produces_samples(self) -> None:
        import respx

        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:19998/v1/chat/completions").respond(
                200,
                json={
                    "model": "test",
                    "choices": [{"message": {"content": "hello"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 1},
                },
            )
            from rig_relay.providers.local_inference.benchmark_executor import (
                run_benchmark_loop,
            )

            plan, samples = await run_benchmark_loop(
                endpoint_url="http://127.0.0.1:19998",
                task_profiles=["chat_light"],
                sample_count_per_profile=2,
                timeout_sec=5.0,
            )
            assert plan.sample_count == 2
            assert len(samples) == 2
            for s in samples:
                assert s.prompt_sha256
                assert s.status == "executed"

    @pytest.mark.asyncio
    async def test_loop_writes_jsonl(self, tmp_path: Path) -> None:
        import respx

        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:19999/v1/chat/completions").respond(
                200,
                json={
                    "model": "test",
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                },
            )
            from rig_relay.providers.local_inference.benchmark_executor import (
                run_benchmark_loop,
            )

            jsonl_path = tmp_path / "samples.jsonl"
            await run_benchmark_loop(
                endpoint_url="http://127.0.0.1:19999",
                task_profiles=["chat_light"],
                sample_count_per_profile=2,
                output_jsonl_path=jsonl_path,
                timeout_sec=5.0,
            )
            assert jsonl_path.is_file()
            lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_loop_content_light(self) -> None:
        import respx

        with respx.mock(assert_all_mocked=False) as mock:
            mock.post("http://127.0.0.1:28888/v1/chat/completions").respond(
                200,
                json={
                    "model": "test",
                    "choices": [{"message": {"content": "hello world"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                },
            )
            from rig_relay.providers.local_inference.benchmark_executor import (
                run_benchmark_loop,
            )

            plan, samples = await run_benchmark_loop(
                endpoint_url="http://127.0.0.1:28888",
                task_profiles=["chat_light"],
                sample_count_per_profile=1,
                timeout_sec=5.0,
            )
            for s in samples:
                data = json.loads(s.model_dump_json())
                assert "hello" not in json.dumps(data).lower()
                assert s.completion_sha256
                assert len(s.completion_sha256) == 64
