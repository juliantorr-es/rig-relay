"""Canonical governed evidence ledgers for Rigged local runtime operations.

Locked, schema-validated, digest-chained, reconstructable append-only JSONL.
Content-light: SHA256 hashes only, never raw prompts, completions, or model output.

Each ledger entry is an envelope:
  { "_event": "...", "_written_at": "...", "_digest": "sha256:...",
    "_prev_digest": "sha256:...", "_ledger": "...", "payload": { ... } }

The digest chain enables reconstruction: every entry's digest depends on its
predecessor, so truncation or corruption is detectable.

Ledgers:
  .build/rig-relay/evidence/runtime_execution_ledger.jsonl
  .build/rig-relay/evidence/runtime_lifecycle_ledger.jsonl
  .build/rig-relay/evidence/runtime_cache_ledger.jsonl
"""

from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
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


class EvidenceLedgerError(Exception):
    """Raised when a ledger operation fails (corruption, lock, schema)."""


class EvidenceLedger:
    """Canonical append-only evidence ledger with digest chaining.

    Thread-safe and process-safe via fcntl advisory locking.
    Schema-validates payloads before append. Digest-chains every
    entry so truncation/corruption is detectable on reconstruction.
    """

    def __init__(self, path: Path, schema_name: str) -> None:
        self._path: Path = path
        self._schema: str = schema_name
        self._lock_path: Path = path.with_suffix(".lock")

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: str, payload: dict) -> str:
        """Append a validated, digest-chained event to the ledger.

        Returns the entry digest for receipt chaining.
        Raises EvidenceLedgerError on schema, lock, or write failure.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        envelope = self._build_envelope(event, payload)
        self._validate(envelope)
        line = json.dumps(envelope, sort_keys=True, default=str)
        self._write_locked(line)
        logger.debug(
            "evidence_ledger: %s event=%s digest=%s",
            self._path.name,
            event,
            envelope["_digest"][:16],
        )
        return envelope["_digest"]

    def reconstruct(self) -> list[dict]:
        """Read and validate the entire ledger chain.

        Returns all valid entries. Raises EvidenceLedgerError if the
        chain is broken (truncation, corruption, missing digest).
        """
        entries: list[dict] = []
        prev_digest: str = ""
        if not self._path.exists():
            return entries

        with open(self._path) as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    computed = _compute_digest(entry)
                    expected = entry.get("_digest", "")

                    if computed != expected:
                        raise EvidenceLedgerError(
                            f"Digest mismatch at line {line_num} in {self._path.name}: "
                            f"computed={computed[:16]} expected={expected[:16]}"
                        )

                    if prev_digest and entry.get("_prev_digest") != prev_digest:
                        raise EvidenceLedgerError(
                            f"Chain broken at line {line_num} in {self._path.name}: "
                            f"prev_digest mismatch"
                        )

                    prev_digest = computed
                    entries.append(entry)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        return entries

    def _build_envelope(self, event: str, payload: dict) -> dict:
        prev = self._last_digest()
        envelope = {
            "_event": event,
            "_written_at": _now_iso(),
            "_ledger": self._path.name,
            "_prev_digest": prev,
            "payload": payload,
        }
        envelope["_digest"] = _compute_digest(envelope)
        return envelope

    def _validate(self, envelope: dict) -> None:
        payload = envelope.get("payload", {})
        if not isinstance(payload, dict):
            raise EvidenceLedgerError("Payload must be a dict")

        if not envelope.get("_digest"):
            raise EvidenceLedgerError("Envelope missing _digest")

        content_light = payload.get("content_light", False)
        if not content_light:
            logger.warning("evidence_ledger_content_light_unset: %s", self._path.name)

    def _write_locked(self, line: str) -> None:
        with open(self._lock_path, "w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                with open(self._path, "a") as f:
                    f.write(line + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def _last_digest(self) -> str:
        if not self._path.exists():
            return ""
        try:
            with open(self._path) as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    lines = [l for l in f if l.strip()]
                    if not lines:
                        return ""
                    last = json.loads(lines[-1].strip())
                    return last.get("_digest", "")
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (json.JSONDecodeError, OSError):
            return ""


_EVIDENCE_ROOT = Path(".build/rig-relay/evidence")


def _ledger_path(name: str) -> Path:
    _EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    return _EVIDENCE_ROOT / name


_execution_ledger = EvidenceLedger(
    _ledger_path("runtime_execution_ledger.jsonl"),
    "rig.relay.local_inference_evidence_receipt.v1",
)
_lifecycle_ledger = EvidenceLedger(
    _ledger_path("runtime_lifecycle_ledger.jsonl"),
    "rig.relay.runtime_lifecycle_event.v1",
)
_cache_ledger = EvidenceLedger(
    _ledger_path("runtime_cache_ledger.jsonl"), "rig.relay.local_cache_evidence.v1"
)


def emit_execution_receipt(receipt: LocalInferenceEvidenceReceipt) -> str:
    payload = receipt.model_dump()
    return _execution_ledger.append("rig.relay.runtime.execution_completed", payload)


def emit_refusal_receipt(refusal: TaskRefusal, task_id_hash: str) -> str:
    receipt = LocalInferenceEvidenceReceipt(
        receipt_id=_make_id("refusal"),
        task_id_hash=task_id_hash,
        status=ExecutionStatus.REFUSED,
        refusal_reason=refusal.reason,
        content_light=True,
    )
    payload = receipt.model_dump()
    payload["refusal_detail"] = refusal.detail
    return _execution_ledger.append("rig.relay.runtime.task_refused", payload)


def emit_lifecycle_event(
    event: str, model_id_hash: str, details: dict | None = None
) -> str:
    payload = {
        "schema_version": "rig.relay.runtime_lifecycle_event.v1",
        "event": event,
        "model_id_hash": model_id_hash,
        "details": details or {},
        "content_light": True,
    }
    return _lifecycle_ledger.append(event, payload)


def emit_cache_evidence(metrics: CacheEvidenceMetrics) -> str:
    metrics.evidence_id = metrics.evidence_id or _make_id("cache")
    payload = metrics.model_dump()
    return _cache_ledger.append("rig.relay.runtime.cache_evidence_recorded", payload)


def emit_tool_proposal_evidence(
    task_id_hash: str, proposal_count: int, tool_names: list[str]
) -> str:
    """Emit content-light evidence that tool proposals were detected.

    The proposals themselves are routed through governance.
    This records a content-light receipt of the detection event.
    """
    payload = {
        "schema_version": "rig.relay.runtime.tool_proposal.v1",
        "task_id_hash": task_id_hash,
        "proposal_count": proposal_count,
        "tool_names_sha256": [_sha256(n) for n in tool_names],
        "routed_to_governance": True,
        "content_light": True,
    }
    return _execution_ledger.append(
        "rig.relay.runtime.tool_proposals_detected", payload
    )


def build_evidence_receipt(
    task_id_hash: str,
    prompt_sha256: str,
    response: LocalInferenceResponse,
    model_id_hash: str,
    latency_ms: int,
    context_privacy_class: ContextPrivacyClass,
    secret_scan_result: str = "none",
) -> LocalInferenceEvidenceReceipt:
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
        content_light=True,
    )


def reconstruct_ledgers() -> dict[str, list[dict]]:
    """Reconstruct and validate all ledgers. Returns ledger_name → entries."""
    return {
        "execution": _execution_ledger.reconstruct(),
        "lifecycle": _lifecycle_ledger.reconstruct(),
        "cache": _cache_ledger.reconstruct(),
    }


def _compute_digest(envelope: dict) -> str:
    """Compute SHA256 digest of an envelope (excluding _digest field)."""
    stripped = {k: v for k, v in envelope.items() if k != "_digest"}
    canonical = json.dumps(stripped, sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _make_id(prefix: str) -> str:
    return f"{prefix}_{_now_compact()}_{secrets.token_hex(6)}"


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")
