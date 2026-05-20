"""Cloud reference executor — calls a cloud provider's chat/completions API.

Gate-protected. Content-light: SHA256 only for completions, no raw content persisted.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import httpx

from rig_relay.core.config._settings import DEFAULT_PROVIDERS, VibeConfig
from rig_relay.providers.local_inference.models import ExecutionStatusKind


async def execute_cloud_reference(
    *,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    messages: list[dict[str, str]],
    max_tokens: int = 512,
    temperature: float = 0.0,
    timeout_sec: float = 30.0,
    execute: bool = False,
) -> dict[str, Any]:
    if not execute:
        return {
            "status": "blocked",
            "reason": "cloud_reference_requires_execute_flag",
            "latency_ms": 0,
            "completion_sha256": "",
            "completion_byte_count": 0,
            "output_token_count": 0,
            "input_token_count": 0,
            "model_safe_id": "",
            "provider": provider,
        }

    config = _find_provider_config(provider)
    if config is None:
        return _blocked_result(f"provider_not_found:{provider}")

    api_key = os.environ.get(config.api_key_env_var, "")
    if not api_key:
        return _blocked_result("no_api_key")

    api_base = config.api_base.rstrip("/")
    url = f"{api_base}/chat/completions"

    started = time.monotonic()
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec)) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        latency = int((time.monotonic() - started) * 1000)
        return _error_result(
            ExecutionStatusKind.TIMED_OUT,
            "httpx.TimeoutException",
            latency,
            provider,
            model,
        )
    except httpx.ConnectError as exc:
        latency = int((time.monotonic() - started) * 1000)
        return _error_result(
            ExecutionStatusKind.FAILED, f"ConnectError: {exc}", latency, provider, model
        )
    except Exception as exc:
        latency = int((time.monotonic() - started) * 1000)
        return _error_result(
            ExecutionStatusKind.FAILED,
            f"{type(exc).__name__}",
            latency,
            provider,
            model,
        )

    latency = int((time.monotonic() - started) * 1000)

    if response.status_code != 200:
        return _error_result(
            ExecutionStatusKind.FAILED,
            f"HTTP {response.status_code}",
            latency,
            provider,
            model,
        )

    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return _error_result(
            ExecutionStatusKind.MALFORMED_RESPONSE,
            "JSONDecodeError",
            latency,
            provider,
            model,
        )

    choices = body.get("choices", [])
    if not choices:
        return _error_result(
            ExecutionStatusKind.MALFORMED_RESPONSE,
            "empty_choices",
            latency,
            provider,
            model,
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
        "model_safe_id": body.get("model", model),
        "provider": provider,
    }


def _find_provider_config(name: str) -> Any | None:
    for p in DEFAULT_PROVIDERS:
        if p.name == name:
            return p
    try:
        vibe = VibeConfig()
    except Exception:
        return None
    for p in vibe.providers:
        if p.name == name:
            return p
    return None


def _blocked_result(reason: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "reason": reason,
        "latency_ms": 0,
        "completion_sha256": "",
        "completion_byte_count": 0,
        "output_token_count": 0,
        "input_token_count": 0,
        "model_safe_id": "",
        "provider": "",
    }


def _error_result(
    status: ExecutionStatusKind,
    error_class: str,
    latency_ms: int,
    provider: str,
    model: str,
) -> dict[str, Any]:
    return {
        "status": status.value,
        "latency_ms": latency_ms,
        "error_class": error_class,
        "completion_sha256": "",
        "completion_byte_count": 0,
        "output_token_count": 0,
        "input_token_count": 0,
        "model_safe_id": model,
        "provider": provider,
    }


__all__ = ["execute_cloud_reference"]
