from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rig_relay.evidence._lifecycle_models import (
    ClassifiedArtifact,
    SessionCompactionCandidate,
    SessionFinalizeResult,
    SessionLifecycleReceipt,
    SessionPruneCandidate,
    SessionRetentionPolicy,
    SessionStorageCategory,
    SessionStorageSummary,
    _FinalizeState,
)

DEFAULT_SESSIONS_ROOT = Path.home() / ".rig" / "sessions"
_PROTECTED_CATEGORIES: set[str] = {
    "signed_envelope",
    "receipt",
    "consent",
    "upload_receipt",
}


def default_sessions_root() -> Path:
    return DEFAULT_SESSIONS_ROOT


def _resolve_sessions_root(sessions_root: Path | str | None = None) -> Path:
    if sessions_root is None:
        return default_sessions_root()
    return Path(sessions_root) if isinstance(sessions_root, str) else sessions_root


def _is_protected(path: Path) -> bool:
    for cat in _PROTECTED_CATEGORIES:
        if cat in str(path).lower():
            return True
    return False


def _iter_session_files(root: Path) -> list[Path]:
    """Iterate session files."""
    if not root.is_dir():
        return []
    files: list[Path] = []
    for entry in root.rglob("*"):
        if entry.is_file():
            files.append(entry)
    return files


def _largest_files(root: Path, top_n: int = 10) -> list[tuple[Path, int]]:
    files_with_sizes = []
    for p in _iter_session_files(root):
        try:
            files_with_sizes.append((p, p.stat().st_size))
        except OSError:
            continue
    files_with_sizes.sort(key=lambda x: -x[1])
    return files_with_sizes[:top_n]


def classify_session_file(path: Path) -> SessionStorageCategory:
    name = path.name.lower()
    if "temp" in name or name.endswith(".cache") or name.endswith(".tmp"):
        return SessionStorageCategory.TEMP_FILES
    if "progress_events" in name:
        return SessionStorageCategory.PROGRESS_EVENTS
    if "intent_events" in name:
        return SessionStorageCategory.INTENT_EVENTS
    if "upload_receipt" in name:
        return SessionStorageCategory.UPLOAD_RECEIPTS
    if "receipt" in name:
        return SessionStorageCategory.RECEIPTS
    if "observability" in name or "event_fabric" in name:
        return SessionStorageCategory.OBSERVABILITY
    if "consent" in name:
        return SessionStorageCategory.CONSENT
    if "signed" in name or "envelope" in name:
        return SessionStorageCategory.SIGNED_ENVELOPES
    if "validation" in name:
        return SessionStorageCategory.VALIDATION_ARTIFACTS
    if "model_observation" in name:
        return SessionStorageCategory.MODEL_OBSERVATIONS
    if "trace" in name:
        return SessionStorageCategory.TRACES
    if "transcript" in name:
        return SessionStorageCategory.RAW_TRANSCRIPTS
    if "stdout" in name or "stderr" in name or name.endswith(".log"):
        return SessionStorageCategory.STDOUT_STDERR
    if "debug" in name:
        return SessionStorageCategory.DEBUG_DUMPS
    return SessionStorageCategory.UNKNOWN


def audit_sessions_storage(
    sessions_root: Path | str, top_n: int = 10
) -> SessionStorageSummary:
    root = Path(sessions_root) if isinstance(sessions_root, str) else sessions_root
    total_bytes = 0
    file_count = 0
    category_counts: dict[str, int] = {}
    category_bytes: dict[str, int] = {}
    largest = []
    for p in _iter_session_files(root):
        try:
            size = p.stat().st_size
        except OSError:
            continue
        total_bytes += size
        file_count += 1
        classified = classify_session_file(p)
        k = classified.value
        category_counts[k] = category_counts.get(k, 0) + 1
        category_bytes[k] = category_bytes.get(k, 0) + size
        largest.append((p, size, classified))
    largest.sort(key=lambda x: -x[1])
    top_files = [
        ClassifiedArtifact(path=f, size_bytes=s, category=c)
        for f, s, c in largest[:top_n]
    ]
    return SessionStorageSummary(
        sessions_root=root,
        total_sessions=-1,
        total_bytes=total_bytes,
        file_count=file_count,
        category_counts=category_counts,
        category_bytes=category_bytes,
        top_sessions=top_files,
        timestamp=datetime.now(UTC).isoformat(),
        compaction_candidates=find_session_compaction_candidates(root),
    )


def find_session_prune_candidates(
    sessions_root: Path | str, older_than_days: int = 30
) -> list[SessionPruneCandidate]:
    root = Path(sessions_root) if isinstance(sessions_root, str) else sessions_root
    cutoff = datetime.now(UTC).timestamp() - (older_than_days * 86400)
    protected = {
        SessionStorageCategory.RECEIPTS,
        SessionStorageCategory.CONSENT,
        SessionStorageCategory.UPLOAD_RECEIPTS,
        SessionStorageCategory.SIGNED_ENVELOPES,
    }
    candidates: list[SessionPruneCandidate] = []
    for p in _iter_session_files(root):
        try:
            mtime = p.stat().st_mtime
            size = p.stat().st_size
        except OSError:
            continue
        classified = classify_session_file(p)
        if classified in protected:
            continue
        if mtime < cutoff:
            candidates.append(
                SessionPruneCandidate(
                    path=p,
                    size_bytes=size,
                    category=classified,
                    age_days=older_than_days,
                )
            )
    return candidates


def find_session_compaction_candidates(
    sessions_root: Path | str,
) -> list[SessionCompactionCandidate]:
    root = Path(sessions_root) if isinstance(sessions_root, str) else sessions_root
    compaction_eligible = {
        SessionStorageCategory.INTENT_EVENTS,
        SessionStorageCategory.PROGRESS_EVENTS,
        SessionStorageCategory.VALIDATION_ARTIFACTS,
        SessionStorageCategory.MODEL_OBSERVATIONS,
    }
    candidates: list[SessionCompactionCandidate] = []
    for p in _iter_session_files(root):
        try:
            size = p.stat().st_size
        except OSError:
            continue
        classified = classify_session_file(p)
        if classified not in compaction_eligible:
            continue
        if p.suffix == ".jsonl":
            candidates.append(
                SessionCompactionCandidate(path=p, size_bytes=size, category=classified)
            )
    return candidates


def finalize_session_storage(
    *,
    session_id: str,
    sessions_root: Path,
    policy: SessionRetentionPolicy,
    allow_compaction: bool = True,
    allow_prune: bool = False,
    write_receipt: bool = True,
    reason: str = "session_end",
    mission_envelope: object | None = None,
) -> SessionFinalizeResult:
    session_root = sessions_root.expanduser()
    files = _iter_session_files(session_root)
    state = _FinalizeState(session_id=session_id, scanned_files=len(files))

    total_bytes_before = 0
    protected: list[str] = []
    refused: list[str] = []
    for p in files:
        try:
            size = p.stat().st_size
        except OSError:
            refused.append(str(p))
            continue
        total_bytes_before += size
        if _is_protected(p):
            protected.append(str(p))

    state.total_bytes_before = total_bytes_before
    state.protected_files = protected
    state.refused_files = refused

    prune_candidates = find_session_prune_candidates(
        session_root, older_than_days=policy.older_than_days
    )
    compaction_candidates = (
        find_session_compaction_candidates(session_root) if allow_compaction else []
    )

    receipt_path = None
    total_bytes_after = total_bytes_before
    compacted_count = 0
    deleted_count = 0

    if allow_prune and prune_candidates and not state.protected_files:
        for c in prune_candidates[:10]:
            try:
                c.path.unlink(missing_ok=True)
                deleted_count += 1
                total_bytes_after -= c.size_bytes
            except OSError:
                state.warnings.append(f"Failed to delete {c.path}")

    if allow_compaction and compaction_candidates:
        for c in compaction_candidates[:10]:
            state.compacted_files.append({
                "path": str(c.path),
                "size_bytes": c.size_bytes,
            })
            compacted_count += 1

    if write_receipt:
        mission_id = None
        envelope_fingerprint = None
        if mission_envelope is not None:
            mission_id = getattr(mission_envelope, "mission_id", None)
            envelope_fingerprint = getattr(mission_envelope, "fingerprint", None)

        receipt = SessionLifecycleReceipt(
            session_id=session_id,
            reason=reason,
            finalized_at=datetime.now(UTC).isoformat(),
            category_counts=audit_sessions_storage(session_root).category_counts,
            scanned_files=state.scanned_files,
            total_bytes_before=total_bytes_before,
            total_bytes_after=total_bytes_after,
            compacted_count=compacted_count,
            refused_count=len(refused),
            prune_candidate_count=len(prune_candidates),
            deleted_count=deleted_count,
            warnings=list(state.warnings),
            mission_id=mission_id,
        )
        receipt_path = _write_lifecycle_receipt(
            session_root, receipt, envelope_fingerprint
        )

    return SessionFinalizeResult(
        session_id=session_id,
        receipts_count=1 if receipt_path else 0,
        lifecycle_manifest_path=str(receipt_path) if receipt_path else None,
        scanned_files=state.scanned_files,
        total_bytes_before=total_bytes_before,
        total_bytes_after=total_bytes_after,
        compacted_files=tuple(c["path"] for c in state.compacted_files),
        protected_files=tuple(protected),
        refused_files=tuple(refused),
        prune_candidates=tuple(str(c.path) for c in prune_candidates),
        deleted_files=tuple(state.deleted_files),
        manifest_path=receipt_path,
        receipt_path=receipt_path,
        status="ok" if not state.warnings else "partial",
        warnings=tuple(state.warnings),
    )


def _write_lifecycle_receipt(
    root: Path, receipt: SessionLifecycleReceipt, fingerprint: str | None = None
) -> Path:
    import json

    receipt_dir = root / "finalize"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = receipt_dir / f"lifecycle_receipt_{ts}.json"
    data = {
        "schema_version": receipt.schema_version,
        "session_id": receipt.session_id,
        "finalized_at": receipt.finalized_at,
        "reason": receipt.reason,
        "scanned_files": receipt.scanned_files,
        "total_bytes_before": receipt.total_bytes_before,
        "total_bytes_after": receipt.total_bytes_after,
        "compacted_count": receipt.compacted_count,
        "refused_count": receipt.refused_count,
        "prune_candidate_count": receipt.prune_candidate_count,
        "deleted_count": receipt.deleted_count,
        "warnings": receipt.warnings,
        "category_counts": receipt.category_counts,
    }
    if receipt.mission_id:
        data["mission_id"] = receipt.mission_id
    if receipt.adr_id:
        data["adr_id"] = receipt.adr_id
    if receipt.sprint_id:
        data["sprint_id"] = receipt.sprint_id
    if fingerprint:
        data["mission_envelope_sha256"] = fingerprint
    if not receipt.adr_id:
        data["adr_id"] = None
    if not receipt.sprint_id:
        data["sprint_id"] = None
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return path


__all__ = [
    "_is_protected",
    "_iter_session_files",
    "_largest_files",
    "_resolve_sessions_root",
    "audit_sessions_storage",
    "classify_session_file",
    "default_sessions_root",
    "finalize_session_storage",
    "find_session_compaction_candidates",
    "find_session_prune_candidates",
]
