"""Durable schema-validated append-only evidence ledgers for governed runtime operations.

Writes to typed JSONL ledgers under the project evidence root. Each receipt
is schema-validated and append-only. Content-light: SHA256 hashes only, never
raw prompts, completions, or model output.

Ledgers:
  .build/rig-relay/evidence/runtime_execution_ledger.jsonl   — execution/refusal receipts
  .build/rig-relay/evidence/runtime_lifecycle_ledger.jsonl   — model load/unload events
  .build/rig-relay/evidence/runtime_cache_ledger.jsonl       — cache evidence metrics
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import secrets

from rig_relay.core.logger import logger
from rig_relay.local_inference.runtime._models import (
    CacheEvidenceMetrics,
    ContextPrivacyClass,
    ExecutionStatus,
    LocalInferenceEvidenceReceipt,
    LocalInferenceResponse,
    TaskRefusal,
)


def _evidence_root() -> Path:
    return Path(".build/rig-relay/evidence")


def _ledger_path(name: str) -> Path:
    root = _evidence_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / name


def _append_jsonl(path: Path, record: dict) -> str:
    """Append a JSON record to a ledger file, return the record's receipt-id."""
    line = json.dumps(record, sort_keys=True, default=str)
    with open(path, "a") as f:
        f.write(line + "\n")
    logger.debug(
        "runtime_evidence_written: %s bytes=%d hash=%s",
        path.name,
        len(line),
        _sha256(line)[:12],
    )
    return record.get("receipt_id", record.get("evidence_id", ""))


def emit_execution_receipt(receipt: LocalInferenceEvidenceReceipt) -> str:
    """Write a content-light execution receipt to the durable ledger."""
    record = receipt.model_dump()
    record["_event"] = "rig.relay.runtime.execution_completed"
    record["_written_at"] = _now_iso()
    path = _ledger_path("runtime_execution_ledger.jsonl")
    return _append_jsonl(path, record)


def emit_refusal_receipt(refusal: TaskRefusal, task_id_hash: str) -> str:
    """Write a refusal to the durable ledger as an execution receipt."""
    receipt = LocalInferenceEvidenceReceipt(
        receipt_id=_make_id("refusal"),
        task_id_hash=task_id_hash,
        status=ExecutionStatus.REFUSED,
        refusal_reason=refusal.reason,
        content_light=True,
    )
    record = receipt.model_dump()
    record["_event"] = "rig.relay.runtime.task_refused"
    record["refusal_detail"] = refusal.detail
    record["_written_at"] = _now_iso()
    path = _ledger_path("runtime_execution_ledger.jsonl")
    return _append_jsonl(path, record)


def emit_lifecycle_event(
    event: str, model_id_hash: str, details: dict | None = None
) -> str:
    """Write a model lifecycle event to the lifecycle ledger."""
    receipt_id = _make_id("lifecycle")
    record = {
        "receipt_id": receipt_id,
        "schema_version": "rig.relay.runtime_lifecycle_event.v1",
        "_event": event,
        "model_id_hash": model_id_hash,
        "details": details or {},
        "_written_at": _now_iso(),
        "content_light": True,
    }
    path = _ledger_path("runtime_lifecycle_ledger.jsonl")
    return _append_jsonl(path, record)


def emit_cache_evidence(metrics: CacheEvidenceMetrics) -> str:
    """Write content-light cache performance evidence to the cache ledger."""
    metrics.evidence_id = metrics.evidence_id or _make_id("cache")
    record = metrics.model_dump()
    record["_event"] = "rig.relay.runtime.cache_evidence_recorded"
    record["_written_at"] = _now_iso()
    path = _ledger_path("runtime_cache_ledger.jsonl")
    return _append_jsonl(path, record)


def build_evidence_receipt(
    task_id_hash: str,
    prompt_sha256: str,
    response: LocalInferenceResponse,
    model_id_hash: str,
    latency_ms: int,
    context_privacy_class: ContextPrivacyClass,
) -> LocalInferenceEvidenceReceipt:
    """Build a content-light evidence receipt from a visible response.

    The response contains the actual text (for the UI consumer).
    The receipt contains only SHA256 hashes and metadata (for the ledger).
    """
    import hashlib

    output_sha = (
        hashlib.sha256(response.content.encode()).hexdigest()
        if response.content
        else ""
    )

    return LocalInferenceEvidenceReceipt(
        receipt_id=_make_id("exec"),
        task_id_hash=task_id_hash,
        status=ExecutionStatus.EXECUTED,
        prompt_sha256=prompt_sha256,
        output_sha256=output_sha,
        output_length_chars=len(response.content),
        model_id_hash=model_id_hash,
        latency_ms=latency_ms,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        total_tokens=response.total_tokens,
        time_to_first_token_ms=response.time_to_first_token_ms,
        finish_reason=response.finish_reason,
        cache_hit=response.cache_hit,
        tool_call_count=len(response.tool_call_proposals),
        tool_call_ids=[p.call_id for p in response.tool_call_proposals],
        tool_proposals_routed_to_governance=bool(response.tool_call_proposals),
        context_privacy_class=context_privacy_class,
        created_at=_now_iso(),
    )


def _make_id(prefix: str) -> str:
    return f"{prefix}_{_now_compact()}_{secrets.token_hex(6)}"


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")
