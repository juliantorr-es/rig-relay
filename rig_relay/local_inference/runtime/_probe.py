"""Runtime discovery and enriched capability probing.

Discovers local runtimes by probing endpoints. Supports OMLX's enriched
endpoint layout (health, api/status, embeddings, rerank, anthropic messages)
in addition to the OpenAI-compatible minimum.

OMLX-informed: route discovery patterns (/health, /v1/models, /v1/chat/completions,
/v1/embeddings, /v1/rerank, /v1/messages, /api/status) adapted from OMLX
server.py endpoint layout (Apache 2.0, oMLX contributors).
"""

from __future__ import annotations

from datetime import UTC
import time

import httpx

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._models import (
    EnrichedRuntimeCapabilities,
    ModelInventoryEntry,
    ModelTypeClass,
    RuntimeHealth,
    RuntimeIdentity,
    RuntimeLifecycleState,
)


async def discover_runtime(
    endpoint_url: str, runtime_kind: str = "unknown", timeout_seconds: float = 10.0
) -> RuntimeIdentity:
    """Discover runtime identity from a configured endpoint URL.

    Probes the endpoint for version, platform, protocol, and capability
    surface. Returns RuntimeIdentity with discovered facts. Never exposes
    raw endpoint internals beyond what is needed for capability reporting.
    """
    identity = RuntimeIdentity(runtime_kind=runtime_kind, endpoint_url=endpoint_url)
    url = endpoint_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(f"{url}/health")
            if response.status_code == _HTTP_OK:
                data = response.json() if response.text else {}
                identity.runtime_version = str(data.get("version", ""))
                identity.platform_class = str(data.get("platform", "unknown"))

            status_response = await client.get(f"{url}/api/status")
            if status_response.status_code == _HTTP_OK:
                data = status_response.json() if status_response.text else {}
                if not identity.runtime_version:
                    identity.runtime_version = str(
                        data.get("version", data.get("omlx_version", ""))
                    )
                identity.display_name = str(data.get("name", data.get("server", "")))

    except httpx.TransportError:
        logger.debug("Runtime endpoint unreachable during discovery: %s", endpoint_url)
    except Exception:
        logger.debug("Runtime discovery error for %s", endpoint_url, exc_info=True)

    return identity


async def probe_runtime_health(
    endpoint_url: str, timeout_seconds: float = 10.0
) -> RuntimeHealth:
    """Probe runtime health: liveness, reachability, enriched status.

    Tries /health first, then /api/status for enriched (OMLX-specific)
    memory, model count, GPU availability, and uptime data.
    """
    health = RuntimeHealth()
    url = endpoint_url.rstrip("/")

    try:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(f"{url}/health")
            elapsed = (time.monotonic() - start) * 1000

            health.reachable = response.status_code == _HTTP_OK
            health.health_endpoint_status = str(response.status_code)
            health.health_latency_ms = int(elapsed)
            health.probed_at = _now_iso()

            if health.reachable:
                status_response = await client.get(f"{url}/api/status")
                if status_response.status_code == _HTTP_OK:
                    data = status_response.json() if status_response.text else {}
                    health.uptime_seconds = data.get("uptime_seconds")
                    mem = data.get("memory", data.get("memory_usage", {}))
                    if isinstance(mem, dict):
                        health.memory_usage_mb = mem.get(
                            "used_mb", mem.get("current_mb")
                        )
                    health.gpu_available = bool(
                        data.get("gpu_available", data.get("metal_available", False))
                    )
                    models = data.get("models", data.get("loaded_models", []))
                    health.active_model_count = (
                        len(models) if isinstance(models, list) else 0
                    )

        health.state = (
            RuntimeLifecycleState.HEALTHY
            if health.reachable
            else RuntimeLifecycleState.UNREACHABLE
        )
    except TimeoutError:
        health.state = RuntimeLifecycleState.UNREACHABLE
        health.warnings.append("health_probe_timed_out")
    except httpx.TransportError:
        health.state = RuntimeLifecycleState.UNREACHABLE
        health.warnings.append("health_probe_transport_error")
    except Exception:
        health.state = RuntimeLifecycleState.ERROR
        health.warnings.append("health_probe_unexpected_error")

    return health


async def probe_runtime_models(
    endpoint_url: str, timeout_seconds: float = 10.0
) -> list[ModelInventoryEntry]:
    """Probe model inventory from runtime's /v1/models endpoint.

    Returns content-light ModelInventoryEntry list with safe model
    identifiers (SHA256 hashes), capability classes, and load status.
    Never exposes raw model paths or download metadata.
    """
    url = endpoint_url.rstrip("/")
    models: list[ModelInventoryEntry] = []

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(f"{url}/v1/models")
            if response.status_code != _HTTP_OK:
                return models

            data = response.json()
            model_list = data.get("data", data.get("models", []))
            if isinstance(model_list, list):
                for m in model_list:
                    if not isinstance(m, dict):
                        continue

                    model_id = str(m.get("id", ""))
                    if not model_id:
                        continue

                    entry = ModelInventoryEntry(
                        model_id_hash=_hash_model_id(model_id),
                        display_name_safe=_sanitize_model_name(model_id),
                        model_type=_classify_model_type(model_id, m),
                        is_loaded=bool(m.get("loaded", m.get("available", True))),
                        capabilities=_extract_capabilities(m),
                    )
                    models.append(entry)

            status_response = await client.get(f"{url}/v1/models/status")
            if status_response.status_code == _HTTP_OK:
                status_data = status_response.json()
                model_statuses = status_data.get("data", status_data.get("models", []))
                if isinstance(model_statuses, list):
                    _merge_model_status(models, model_statuses)

    except httpx.TransportError:
        logger.debug("Runtime model probe transport error: %s", endpoint_url)
    except Exception:
        logger.debug("Runtime model probe error: %s", endpoint_url, exc_info=True)

    return models


async def probe_enriched_capabilities(
    endpoint_url: str, timeout_seconds: float = 10.0
) -> EnrichedRuntimeCapabilities:
    """Probe enriched capabilities beyond the OpenAI-compatible minimum.

    OMLX-informed: targets embeddings, rerank, anthropic messages, api/status,
    and cache metrics endpoints based on OMLX server.py route layout.
    """
    caps = EnrichedRuntimeCapabilities()
    url = endpoint_url.rstrip("/")

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        endpoints = [
            ("health_endpoint", "GET", f"{url}/health"),
            ("api_status", "GET", f"{url}/api/status"),
            ("models_list", "GET", f"{url}/v1/models"),
            ("chat_completions", "GET", f"{url}/v1/models"),
            ("embeddings", "POST", f"{url}/v1/embeddings"),
            ("reranking", "POST", f"{url}/v1/rerank"),
            ("anthropic_messages", "POST", f"{url}/v1/messages"),
            ("cache_metrics", "GET", f"{url}/api/cache/stats"),
        ]

        for attr, method, endpoint in endpoints:
            try:
                if method == "GET":
                    response = await client.get(endpoint)
                else:
                    response = await client.head(endpoint)
                setattr(
                    caps,
                    attr,
                    "supported"
                    if response.status_code < _HTTP_OK * 3
                    else "unsupported",
                )
            except Exception:
                setattr(caps, attr, "unsupported")

    return caps


def _hash_model_id(model_id: str) -> str:
    import hashlib

    return hashlib.sha256(model_id.encode()).hexdigest()[:16]


def _sanitize_model_name(model_id: str) -> str:
    parts = model_id.rsplit("/", 1)
    return parts[-1] if len(parts) > 1 else model_id


def _classify_model_type(model_id: str, entry: dict) -> ModelTypeClass:
    lower = model_id.lower() + " " + str(entry.get("object", "")).lower()
    if any(
        k in lower
        for k in (
            "vlm",
            "vision",
            "gemma3",
            "llava",
            "pixtral",
            "phi4mm",
            "qwen2_vl",
            "qwen2.5-vl",
            "qwen3_vl",
        )
    ):
        return ModelTypeClass.VLM
    if any(
        k in lower for k in ("embed", "bge", "e5", "stella", "jina-embed", "colqwen")
    ):
        return ModelTypeClass.EMBEDDING
    if any(k in lower for k in ("rerank", "bge-reranker", "jina-rerank")):
        return ModelTypeClass.RERANKER
    if any(k in lower for k in ("whisper", "wav2vec", "qwen3-asr", "stt")):
        return ModelTypeClass.AUDIO_STT
    if any(k in lower for k in ("tts", "kokoro", "qwen3-tts")):
        return ModelTypeClass.AUDIO_TTS
    return ModelTypeClass.LLM


def _extract_capabilities(entry: dict) -> list[str]:
    caps: list[str] = []
    owned = str(entry.get("owned_by", "")).lower()
    obj = str(entry.get("object", "")).lower()
    if "tool" in owned or "tool_use" in obj:
        caps.append("tool_calling")
    if "json" in owned or "structured" in obj:
        caps.append("structured_output")
    return caps


def _merge_model_status(
    models: list[ModelInventoryEntry], statuses: list[dict]
) -> None:
    for s in statuses:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id", ""))
        for m in models:
            if m.model_id_hash == _hash_model_id(sid):
                m.is_loaded = bool(s.get("loaded", m.is_loaded))
                if "size_gb" in s:
                    m.estimated_size_gb = float(s["size_gb"])
                break


_HTTP_OK = 200


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(tz=UTC).isoformat()
