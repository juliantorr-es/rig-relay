"""Content-light evidence emission for governed local runtime operations.

All evidence is hash-heavy and content-light: SHA256 hashes for content-derived
references, never raw prompts, completions, model output, or file contents.

Follows the usage data doctrine retention classes:
  - Evidence-retained: hashes, counts, statuses, timing, metadata
  - Locally retained: raw output bodies (never exported)
  - Exportable after redaction: anonymized aggregate metrics
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._models import (
    CacheEvidenceMetrics,
    EnrichedRuntimeCapabilities,
    ExecutionOutcome,
    ModelInventoryEntry,
    RuntimeHealth,
    RuntimeIdentity,
    TaskRefusal,
)


def emit_probe_evidence(
    runtime_identity: RuntimeIdentity,
    health: RuntimeHealth,
    models: list[ModelInventoryEntry],
    capabilities: EnrichedRuntimeCapabilities,
) -> str:
    """Emit content-light evidence for a runtime probe cycle."""
    evidence_id = _make_evidence_id("probe")
    payload = {
        "evidence_id": evidence_id,
        "schema_version": "rig.relay.local_runtime_probe_evidence.v1",
        "timestamp": _now_iso(),
        "runtime": {
            "kind": runtime_identity.runtime_kind,
            "version": runtime_identity.runtime_version,
            "platform_class": runtime_identity.platform_class,
            "endpoint_url_sha256": _sha256(runtime_identity.endpoint_url),
        },
        "health": {
            "state": health.state,
            "reachable": health.reachable,
            "health_latency_ms": health.health_latency_ms,
            "active_model_count": health.active_model_count,
            "gpu_available": health.gpu_available,
        },
        "model_count": len(models),
        "model_capability_summary": _model_capability_summary(models),
        "capability_classes": _capability_summary(capabilities),
        "content_light": True,
    }
    _log_evidence("rig.relay.runtime.probe_completed", payload)
    return evidence_id


def emit_execution_evidence(outcome: ExecutionOutcome) -> str:
    """Emit content-light evidence for a governed execution."""
    evidence_id = _make_evidence_id("exec")
    payload = {
        "evidence_id": evidence_id,
        "schema_version": "rig.relay.local_runtime_execution_evidence.v1",
        "timestamp": _now_iso(),
        "outcome": outcome.model_dump(),
        "content_light": True,
    }
    _log_evidence("rig.relay.runtime.execution_completed", payload)
    return evidence_id


def emit_cache_evidence(metrics: CacheEvidenceMetrics) -> str:
    """Emit content-light local cache performance evidence.

    Local KV cache evidence is distinct from cloud-provider cache evidence
    per W1 Principle 4. Never contains raw prompt text, generated text,
    or model output.
    """
    evidence_id = _make_evidence_id("cache")
    payload = {
        "evidence_id": evidence_id,
        "schema_version": metrics.schema_version,
        "timestamp": _now_iso(),
        "runtime_kind": metrics.runtime_kind,
        "cache_hit_rate_recent": metrics.cache_hit_rate_recent,
        "cache_hit_rate_medium": metrics.cache_hit_rate_medium,
        "cache_hit_rate_aggregate": metrics.cache_hit_rate_aggregate,
        "gpu_cache_blocks_total": metrics.gpu_cache_blocks_total,
        "gpu_cache_blocks_used": metrics.gpu_cache_blocks_used,
        "ssd_cache_size_mb": metrics.ssd_cache_size_mb,
        "prefix_cache_entries": metrics.prefix_cache_entries,
        "content_light": True,
    }
    _log_evidence("rig.relay.runtime.cache_evidence_recorded", payload)
    return evidence_id


def emit_refusal_evidence(refusal: TaskRefusal, task_id_hash: str) -> str:
    """Emit content-light refusal evidence."""
    evidence_id = _make_evidence_id("ref")
    payload = {
        "evidence_id": evidence_id,
        "schema_version": "rig.relay.local_runtime_refusal_evidence.v1",
        "timestamp": _now_iso(),
        "task_id_hash": task_id_hash,
        "refusal_reason": refusal.reason,
        "detail": refusal.detail,
        "content_light": True,
    }
    _log_evidence("rig.relay.runtime.task_refused", payload)
    return evidence_id


def _log_evidence(event_name: str, payload: dict) -> None:
    serialized = json.dumps(payload)
    logger.debug("runtime_evidence: %s %s", event_name, _sha256(serialized)[:8])


def _model_capability_summary(models: list[ModelInventoryEntry]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for m in models:
        summary[m.model_type] = summary.get(m.model_type, 0) + 1
    summary["loaded_count"] = sum(1 for m in models if m.is_loaded)
    summary["pinned_count"] = sum(1 for m in models if m.is_pinned)
    return summary


def _capability_summary(caps: EnrichedRuntimeCapabilities) -> dict[str, str]:
    return {
        k: v
        for k, v in caps.model_dump().items()
        if v != "not_tested" and not k.startswith("_")
    }


def _make_evidence_id(prefix: str) -> str:
    return f"{prefix}_{_now_compact()}_{_random_hex(6)}"


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def _random_hex(length: int) -> str:
    import secrets

    return secrets.token_hex(length)
