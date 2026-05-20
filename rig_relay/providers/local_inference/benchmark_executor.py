"""Benchmark execution loop — dry-run safe, fake-endpoint testable.

Runs execute_chat_completion() across task profiles and synthetic prompts.
Measures TTFT, latency, tokens/sec. Writes CapacityBenchmarkSample JSONL.
Content-light: SHA256-only, never persists raw prompts or completions.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import secrets

from rig_relay.providers.local_inference.execution_client import (
    execute_chat_completion,
    execute_chat_completion_streaming,
)
from rig_relay.providers.local_inference.models import (
    CapacityBenchmarkPlan,
    CapacityBenchmarkSample,
)

BENCHMARK_PROMPTS: dict[str, list[dict[str, str]]] = {
    "chat_light": [
        {"role": "user", "content": "Respond with exactly one word: hello"},
        {"role": "user", "content": "What is 2+2? Answer with only the number."},
        {"role": "user", "content": "Say the word 'ok' and nothing else."},
        {
            "role": "user",
            "content": "In one word, what color is the sky on a clear day?",
        },
        {"role": "user", "content": "Reply with just the letter A."},
    ],
    "structured_json": [
        {"role": "user", "content": 'Output exactly: {"answer": 2, "status": "ok"}'},
        {"role": "user", "content": 'Respond with JSON: {"x":1,"y":2}'},
        {
            "role": "user",
            "content": 'Output a JSON object with keys "name" and "value".',
        },
        {"role": "user", "content": 'Return: {"valid": true, "count": 0}'},
        {"role": "user", "content": 'Produce: {"items": [], "total": 0}'},
    ],
    "tool_planning": [
        {"role": "user", "content": "What is 5+3? Use a calculator if needed."},
        {"role": "user", "content": "Search for the current time."},
        {"role": "user", "content": "Read the file /tmp/test.txt if it exists."},
        {"role": "user", "content": "List files in the current directory."},
        {"role": "user", "content": "Run the command 'echo hello'."},
    ],
    "code_review_light": [
        {"role": "user", "content": "Is this Python valid? `x = lambda a: a + 1`"},
        {"role": "user", "content": "What does `len([])` return?"},
        {"role": "user", "content": "Fix: `if x = 5: print(x)`"},
        {"role": "user", "content": "Explain `import os` in one sentence."},
        {"role": "user", "content": "What does `dict.get('key', 0)` do?"},
    ],
}


def build_prompt_fixtures() -> dict[str, list[dict[str, str]]]:
    return {k: list(v) for k, v in BENCHMARK_PROMPTS.items()}


def _new_plan_id() -> str:
    return f"cbp_{secrets.token_hex(8)}"


async def run_benchmark_loop(
    *,
    endpoint_url: str,
    task_profiles: list[str] | None = None,
    sample_count_per_profile: int = 3,
    output_jsonl_path: Path | None = None,
    max_tokens: int = 128,
    temperature: float = 0.0,
    timeout_sec: float = 10.0,
    streaming: bool = False,
) -> tuple[CapacityBenchmarkPlan, list[CapacityBenchmarkSample]]:
    plan_id = _new_plan_id()
    profiles = task_profiles or list(BENCHMARK_PROMPTS.keys())
    plan = CapacityBenchmarkPlan(
        plan_id=plan_id,
        generated_at=datetime.now(UTC).isoformat(),
        mode="local_endpoint_live",
        endpoint_url=endpoint_url,
        task_profiles=profiles,
        sample_count=0,
        dimensions=["ttft", "latency", "tokens_per_sec", "error_rate"],
    )

    samples: list[CapacityBenchmarkSample] = []
    for profile in profiles:
        prompts = BENCHMARK_PROMPTS.get(profile, [])
        for i in range(min(sample_count_per_profile, len(prompts))):
            msg = prompts[i]
            prompt_text = msg["content"]
            prompt_sha = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

            try:
                if streaming:
                    result = await execute_chat_completion_streaming(
                        endpoint_url=endpoint_url,
                        messages=[msg],
                        max_tokens=max_tokens,
                        temperature=temperature,
                        timeout_sec=timeout_sec,
                    )
                else:
                    result = await execute_chat_completion(
                        endpoint_url=endpoint_url,
                        messages=[msg],
                        max_tokens=max_tokens,
                        temperature=temperature,
                        timeout_sec=timeout_sec,
                    )
            except Exception as exc:
                result = {
                    "status": "failed",
                    "latency_ms": 0,
                    "ttft_ms": 0,
                    "error_class": type(exc).__name__,
                    "completion_sha256": "",
                    "ephemeral_content": "",
                    "output_token_count": 0,
                    "input_token_count": 0,
                    "streaming_chunk_count": 0,
                }

            sample = CapacityBenchmarkSample(
                sample_id=f"cbs_{secrets.token_hex(8)}",
                plan_id=plan_id,
                trace_id=f"tr_{secrets.token_hex(8)}",
                mode="local_endpoint_live",
                task_profile=profile,
                prompt_sha256=prompt_sha,
                completion_sha256=result["completion_sha256"],
                ttft_ms=result.get("ttft_ms", 0),
                latency_ms=result["latency_ms"],
                tokens_per_sec=(
                    result["output_token_count"] / (result["latency_ms"] / 1000.0)
                    if result["latency_ms"] > 0 and result["output_token_count"] > 0
                    else 0.0
                ),
                input_token_count=result["input_token_count"],
                output_token_count=result["output_token_count"],
                error_class=result.get("error_class", ""),
                status=result["status"],
            )
            samples.append(sample)

    plan.sample_count = len(samples)

    if output_jsonl_path:
        output_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_jsonl_path, "a", encoding="utf-8") as f:
            for s in samples:
                f.write(s.model_dump_json() + "\n")

    return plan, samples


async def run_benchmark_concurrent(
    *,
    endpoint_url: str,
    concurrency: int = 3,
    task_profile: str = "chat_light",
    sample_count: int = 5,
    max_tokens: int = 128,
    temperature: float = 0.0,
    timeout_sec: float = 10.0,
) -> tuple[CapacityBenchmarkPlan, list[CapacityBenchmarkSample]]:
    plan_id = _new_plan_id()
    plan = CapacityBenchmarkPlan(
        plan_id=plan_id,
        generated_at=datetime.now(UTC).isoformat(),
        mode="local_endpoint_live",
        endpoint_url=endpoint_url,
        task_profiles=[task_profile],
        sample_count=0,
        dimensions=["ttft", "latency", "tokens_per_sec", "error_rate"],
    )

    prompts = BENCHMARK_PROMPTS.get(task_profile, BENCHMARK_PROMPTS["chat_light"])
    samples: list[CapacityBenchmarkSample] = []

    async def _single_request(index: int) -> None:
        msg = prompts[index % len(prompts)]
        prompt_text = msg["content"]
        prompt_sha = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

        try:
            result = await execute_chat_completion(
                endpoint_url=endpoint_url,
                messages=[msg],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_sec=timeout_sec,
            )
        except Exception as exc:
            result = {
                "status": "failed",
                "latency_ms": 0,
                "error_class": type(exc).__name__,
                "completion_sha256": "",
                "ephemeral_content": "",
                "output_token_count": 0,
                "input_token_count": 0,
            }

        sample = CapacityBenchmarkSample(
            sample_id=f"cbs_{secrets.token_hex(8)}",
            plan_id=plan_id,
            trace_id=f"tr_{secrets.token_hex(8)}",
            mode="local_endpoint_live",
            task_profile=task_profile,
            prompt_sha256=prompt_sha,
            completion_sha256=result["completion_sha256"],
            ttft_ms=0,
            latency_ms=result["latency_ms"],
            tokens_per_sec=(
                result["output_token_count"] / (result["latency_ms"] / 1000.0)
                if result["latency_ms"] > 0 and result["output_token_count"] > 0
                else 0.0
            ),
            input_token_count=result["input_token_count"],
            output_token_count=result["output_token_count"],
            concurrency_level=concurrency,
            error_class=result.get("error_class", ""),
            status=result["status"],
        )
        samples.append(sample)

    tasks = [
        asyncio.create_task(_single_request(i))
        for i in range(min(sample_count, len(prompts)))
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, BaseException):
            sample = CapacityBenchmarkSample(
                sample_id=f"cbs_{secrets.token_hex(8)}",
                plan_id=plan_id,
                trace_id=f"tr_{secrets.token_hex(8)}",
                mode="local_endpoint_live",
                task_profile=task_profile,
                prompt_sha256="",
                completion_sha256="",
                ttft_ms=0,
                latency_ms=0,
                tokens_per_sec=0.0,
                input_token_count=0,
                output_token_count=0,
                concurrency_level=concurrency,
                error_class=type(r).__name__,
                status="failed",
            )
            samples.append(sample)

    plan.sample_count = len(samples)
    return plan, samples


def run_benchmark_sync(
    *,
    endpoint_url: str,
    task_profiles: list[str] | None = None,
    sample_count_per_profile: int = 3,
    output_jsonl_path: Path | None = None,
) -> tuple[CapacityBenchmarkPlan, list[CapacityBenchmarkSample]]:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    run_benchmark_loop(
                        endpoint_url=endpoint_url,
                        task_profiles=task_profiles,
                        sample_count_per_profile=sample_count_per_profile,
                        output_jsonl_path=output_jsonl_path,
                    ),
                )
                return future.result(timeout=300)
        return asyncio.run(
            run_benchmark_loop(
                endpoint_url=endpoint_url,
                task_profiles=task_profiles,
                sample_count_per_profile=sample_count_per_profile,
                output_jsonl_path=output_jsonl_path,
            )
        )
    except Exception:
        plan = CapacityBenchmarkPlan(
            plan_id=_new_plan_id(),
            generated_at=datetime.now(UTC).isoformat(),
            mode="local_endpoint_live",
            endpoint_url=endpoint_url,
            blocked_reasons=["benchmark_execution_failed"],
        )
        return plan, []


__all__ = [
    "BENCHMARK_PROMPTS",
    "build_prompt_fixtures",
    "run_benchmark_concurrent",
    "run_benchmark_loop",
    "run_benchmark_sync",
]
