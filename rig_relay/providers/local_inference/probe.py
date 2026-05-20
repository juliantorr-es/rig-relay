"""OpenAI-compatible local endpoint capability probe.

Probes a local inference endpoint for capabilities via standard OpenAI-compatible
endpoints. Dry-run mode returns simulated probe data without network calls.
Content-light: never records prompts, completions, or secrets.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import secrets
import time
from typing import Any

from rig_relay.providers.local_inference.models import (
    CapabilityProbeCapabilities,
    CapabilityProbeResult,
    CapabilityStatus,
    HealthSummary,
    LocalRuntimeKind,
    ProbeError,
)


def _new_probe_id() -> str:
    return f"probe_{secrets.token_hex(8)}"


async def probe_local_endpoint(
    base_url: str, *, timeout_sec: float = 30.0, dry_run: bool = False
) -> CapabilityProbeResult:
    probe_id = _new_probe_id()
    started = time.monotonic()
    errors: list[ProbeError] = []
    warnings: list[str] = []
    capabilities = CapabilityProbeCapabilities()
    health = HealthSummary()
    reachable = False
    engine = LocalRuntimeKind.UNKNOWN

    if dry_run:
        reachable = True
        engine = LocalRuntimeKind.LLAMA_CPP
        capabilities.chat_completions = CapabilityStatus.SUPPORTED
        capabilities.completions = CapabilityStatus.SUPPORTED
        capabilities.models_list = CapabilityStatus.SUPPORTED
        capabilities.health_endpoint = CapabilityStatus.SUPPORTED
        capabilities.streaming = CapabilityStatus.SUPPORTED
        capabilities.tool_calling = CapabilityStatus.SUPPORTED
        capabilities.structured_json_output = CapabilityStatus.SUPPORTED
        health.status = "ok"
        health.model_count = 1
        health.active_model_id_hash = hashlib.sha256(b"dry-run-model").hexdigest()
    else:
        import httpx

        normalized_url = base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_sec), follow_redirects=True
            ) as client:
                await _probe_health(client, normalized_url, capabilities, health)
                reachable = True

                await _probe_models(client, normalized_url, capabilities)
                await _probe_chat_completions(
                    client, normalized_url, capabilities, engine
                )
                await _probe_streaming(client, normalized_url, capabilities)
        except httpx.ConnectError as exc:
            errors.append(
                ProbeError(
                    probe_target=normalized_url,
                    error_class="ConnectError",
                    error_safe_message=str(exc)[:200],
                )
            )
            reachable = False
        except httpx.TimeoutException as exc:
            errors.append(
                ProbeError(
                    probe_target=normalized_url,
                    error_class="TimeoutException",
                    error_safe_message=str(exc)[:200],
                )
            )
        except Exception as exc:
            errors.append(
                ProbeError(
                    probe_target=normalized_url,
                    error_class=type(exc).__name__,
                    error_safe_message=str(exc)[:200],
                )
            )

    duration_ms = int((time.monotonic() - started) * 1000)
    return CapabilityProbeResult(
        probe_id=probe_id,
        runtime_url=base_url,
        runtime_engine=engine,
        probed_at=datetime.now(UTC).isoformat(),
        probe_duration_ms=duration_ms,
        reachable=reachable,
        capabilities=capabilities,
        health_summary=health,
        errors=errors,
        warnings=warnings,
    )


async def _probe_health(
    client: Any,
    base_url: str,
    capabilities: CapabilityProbeCapabilities,
    health: HealthSummary,
) -> None:
    health_paths = ["/health", "/v1/health"]
    for path in health_paths:
        try:
            resp = await client.get(f"{base_url}{path}")
            if resp.status_code == 200:
                capabilities.health_endpoint = CapabilityStatus.SUPPORTED
                data = resp.json()
                if isinstance(data, dict):
                    health.status = str(data.get("status", "unknown"))
                return
        except Exception:
            continue
    capabilities.health_endpoint = CapabilityStatus.UNSUPPORTED


async def _probe_models(
    client: Any, base_url: str, capabilities: CapabilityProbeCapabilities
) -> None:
    try:
        resp = await client.get(f"{base_url}/v1/models")
        if resp.status_code == 200:
            capabilities.models_list = CapabilityStatus.SUPPORTED
        elif resp.status_code == 404:
            capabilities.models_list = CapabilityStatus.UNSUPPORTED
        else:
            capabilities.models_list = CapabilityStatus.ERROR
    except Exception:
        capabilities.models_list = CapabilityStatus.ERROR


async def _probe_chat_completions(
    client: Any,
    base_url: str,
    capabilities: CapabilityProbeCapabilities,
    engine: LocalRuntimeKind,
) -> None:
    smoke_prompt = "Respond with exactly the word: ok"
    payload: dict[str, Any] = {
        "model": "_probe_",
        "messages": [{"role": "user", "content": smoke_prompt}],
        "max_tokens": 2,
        "temperature": 0,
    }
    try:
        resp = await client.post(f"{base_url}/v1/chat/completions", json=payload)
        if resp.status_code == 200:
            try:
                json.loads(resp.text)
            except Exception:
                capabilities.chat_completions = CapabilityStatus.ERROR
                return
            capabilities.chat_completions = CapabilityStatus.SUPPORTED
        elif resp.status_code == 404:
            capabilities.chat_completions = CapabilityStatus.UNSUPPORTED
        else:
            capabilities.chat_completions = CapabilityStatus.ERROR
    except Exception:
        capabilities.chat_completions = CapabilityStatus.ERROR

    tool_payload: dict[str, Any] = {
        "model": "_probe_",
        "messages": [{"role": "user", "content": "What is 1+1?"}],
        "max_tokens": 10,
        "temperature": 0,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add two numbers",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "required": ["a", "b"],
                    },
                },
            }
        ],
    }
    try:
        resp = await client.post(f"{base_url}/v1/chat/completions", json=tool_payload)
        data = resp.json()
        if resp.status_code == 200:
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message", {})
            if msg.get("tool_calls"):
                capabilities.tool_calling = CapabilityStatus.SUPPORTED
            else:
                capabilities.tool_calling = CapabilityStatus.PARTIAL
        else:
            capabilities.tool_calling = CapabilityStatus.UNSUPPORTED
    except Exception:
        capabilities.tool_calling = CapabilityStatus.ERROR

    json_payload: dict[str, Any] = {
        "model": "_probe_",
        "messages": [{"role": "user", "content": 'Output: {"x": 1}'}],
        "max_tokens": 20,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = await client.post(f"{base_url}/v1/chat/completions", json=json_payload)
        if resp.status_code == 200:
            capabilities.structured_json_output = CapabilityStatus.SUPPORTED
        else:
            capabilities.structured_json_output = CapabilityStatus.UNSUPPORTED
    except Exception:
        capabilities.structured_json_output = CapabilityStatus.ERROR


async def _probe_streaming(
    client: Any, base_url: str, capabilities: CapabilityProbeCapabilities
) -> None:
    payload: dict[str, Any] = {
        "model": "_probe_",
        "messages": [{"role": "user", "content": "Say hello"}],
        "max_tokens": 5,
        "temperature": 0,
        "stream": True,
    }
    try:
        async with client.stream(
            "POST", f"{base_url}/v1/chat/completions", json=payload
        ) as response:
            if response.status_code == 200:
                capabilities.streaming = CapabilityStatus.SUPPORTED
            else:
                capabilities.streaming = CapabilityStatus.PARTIAL
    except Exception:
        capabilities.streaming = CapabilityStatus.ERROR


__all__ = ["probe_local_endpoint"]
