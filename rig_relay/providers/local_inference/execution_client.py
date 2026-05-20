"""Narrow OpenAI-compatible local chat/completions client.

Sends a single POST /v1/chat/completions to a configured local endpoint.
Content-light: only sends provided prompts, never stores completions raw.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import httpx

from rig_relay.providers.local_inference.models import ExecutionStatusKind


async def execute_chat_completion(
    *,
    endpoint_url: str,
    messages: list[dict[str, str]],
    max_tokens: int = 512,
    temperature: float = 0.0,
    stream: bool = False,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    started = time.monotonic()
    payload: dict[str, Any] = {
        "model": "_manual_execute_",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec)) as client:
            response = await client.post(
                f"{endpoint_url}/v1/chat/completions", json=payload
            )
    except httpx.TimeoutException:
        latency = int((time.monotonic() - started) * 1000)
        return _error_result(
            ExecutionStatusKind.TIMED_OUT, "httpx.TimeoutException", latency
        )
    except httpx.ConnectError as exc:
        latency = int((time.monotonic() - started) * 1000)
        return _error_result(
            ExecutionStatusKind.FAILED, f"ConnectError: {exc}", latency
        )
    except Exception as exc:
        latency = int((time.monotonic() - started) * 1000)
        return _error_result(
            ExecutionStatusKind.FAILED, f"{type(exc).__name__}", latency
        )

    latency = int((time.monotonic() - started) * 1000)

    if response.status_code != 200:
        return _error_result(
            ExecutionStatusKind.FAILED, f"HTTP {response.status_code}", latency
        )

    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return _error_result(
            ExecutionStatusKind.MALFORMED_RESPONSE, "JSONDecodeError", latency
        )

    choices = body.get("choices", [])
    if not choices:
        return _error_result(
            ExecutionStatusKind.MALFORMED_RESPONSE, "empty_choices", latency
        )

    message = choices[0].get("message", {})
    content = message.get("content", "")
    completion_bytes = content.encode("utf-8")
    completion_sha = hashlib.sha256(completion_bytes).hexdigest()
    usage = body.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    return {
        "status": ExecutionStatusKind.EXECUTED.value,
        "latency_ms": latency,
        "completion_sha256": completion_sha,
        "completion_byte_count": len(completion_bytes),
        "output_token_count": output_tokens,
        "input_token_count": input_tokens,
        "model_safe_id": body.get("model", ""),
        "content": content,
    }


def _error_result(
    status: ExecutionStatusKind, error_class: str, latency_ms: int
) -> dict[str, Any]:
    return {
        "status": status.value,
        "latency_ms": latency_ms,
        "error_class": error_class,
        "completion_sha256": "",
        "completion_byte_count": 0,
        "output_token_count": 0,
        "input_token_count": 0,
        "model_safe_id": "",
        "content": "",
    }


__all__ = ["execute_chat_completion"]
