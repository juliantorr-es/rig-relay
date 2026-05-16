"""Session storage lifecycle helpers.

Conservative, content-light session audit / compaction / GC helpers for
`~/.rig/sessions`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.evidence._lifecycle_models import (
    ClassifiedArtifact,
    CompactionResult,
    DeletedArtifact,
    Refusal,
    SessionCompactionCandidate,
    SessionFinalizeResult,
    SessionLifecycleManifest,
    SessionLifecycleManifestEntry,
    SessionLifecycleReceipt,
    SessionPruneCandidate,
    SessionRetentionPolicy,
    SessionStorageCategory,
    SessionStorageSummary,
    _FinalizeState,
)
from rig_relay.governance.mission_envelope import MissionEnvelope


def default_sessions_root() -> Path:
    return Path.home() / ".rig" / "sessions"

    scanned_files: int
    total_bytes_before: int
    protected_files: list[ClassifiedArtifact]
    refused_files: list[Refusal]
    compacted_files: list[CompactionResult]
    deleted_files: list[DeletedArtifact]
    warnings: list[str]


_PROTECTED_NAMES = (
    "receipt",
    "consent",
    "upload_receipt",
    "signed_local_action_envelope",
    "signed_envelope",
    "active",
    "pinned",
)

_CATEGORY_RULES: tuple[tuple[SessionStorageCategory, tuple[str, ...], bool], ...] = (
    (SessionStorageCategory.UPLOAD_RECEIPTS, ("upload", "receipt"), True),
    (SessionStorageCategory.RECEIPTS, ("receipt", "receipts"), False),
    (SessionStorageCategory.CONSENT, ("consent",), False),
    (SessionStorageCategory.SIGNED_ENVELOPES, ("signed", "envelope"), False),
    (SessionStorageCategory.PROGRESS_EVENTS, ("progress",), False),
    (SessionStorageCategory.INTENT_EVENTS, ("intent",), False),
    (SessionStorageCategory.VALIDATION_ARTIFACTS, ("validation", "refinement"), False),
    (SessionStorageCategory.MODEL_OBSERVATIONS, ("observation", "model"), False),
    (SessionStorageCategory.STDOUT_STDERR, ("stdout", "stderr", "shell"), False),
    (SessionStorageCategory.DEBUG_DUMPS, ("debug", "dump"), False),
)


def _resolve_sessions_root(root: Path | None) -> Path:
    if root is not None:
        return root.expanduser()
    return default_sessions_root()


def classify_session_file(path: Path) -> SessionStorageCategory:
    name = path.name.lower()
    suffix = path.suffix.lower()

    if "transcript" in name:
        return SessionStorageCategory.RAW_TRANSCRIPTS
    if suffix == ".jsonl" and ("output" in name or "message" in name):
        return SessionStorageCategory.RAW_MODEL_OUTPUTS
    if name.startswith("tmp") or "cache" in name or suffix in {".tmp", ".temp"}:
        return SessionStorageCategory.TEMP_FILES
    for category, tokens, require_all in _CATEGORY_RULES:
        matched = (
            all(token in name for token in tokens)
            if require_all
            else any(token in name for token in tokens)
        )
        if matched:
            return category
    if suffix in {".jsonl", ".json", ".ndjson"}:
        return SessionStorageCategory.INTENT_EVENTS
    return SessionStorageCategory.UNKNOWN


def _is_protected(path: Path, sessions_root: Path) -> bool:
    name = path.name.lower()
    if any(token in name for token in _PROTECTED_NAMES):
        return True
    if name in {"active", "current", "pinned"}:
        return True
    if (sessions_root / "active").exists() and path.is_relative_to(
        sessions_root / "active"
    ):
        return True
    if (sessions_root / "pinned").exists() and path.is_relative_to(
        sessions_root / "pinned"
    ):
        return True
    return False


def _iter_session_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [path for path in root.rglob("*") if path.is_file()]


def _largest_files(files: list[Path], limit: int = 20) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in files:
        try:
            size_bytes = path.stat().st_size
        except OSError:
            continue
        records.append({
            "path": str(path),
            "size_bytes": size_bytes,
            "category": classify_session_file(path).value,
        })
    records.sort(key=lambda item: item["size_bytes"], reverse=True)
    return records[:limit]


def find_session_prune_candidates(
    sessions_root: Path | None = None, *, older_than_days: int = 30
) -> list[SessionPruneCandidate]:
    root = _resolve_sessions_root(sessions_root)
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    candidates: list[SessionPruneCandidate] = []
    for path in _iter_session_files(root):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            size = path.stat().st_size
        except OSError:
            continue
        if mtime > cutoff:
            continue
        category = classify_session_file(path)
        if category in {
            SessionStorageCategory.RECEIPTS,
            SessionStorageCategory.CONSENT,
            SessionStorageCategory.UPLOAD_RECEIPTS,
            SessionStorageCategory.SIGNED_ENVELOPES,
        }:
            continue
        if _is_protected(path, root):
            continue
        if category in {
            SessionStorageCategory.RAW_TRANSCRIPTS,
            SessionStorageCategory.RAW_MODEL_OUTPUTS,
            SessionStorageCategory.STDOUT_STDERR,
            SessionStorageCategory.DEBUG_DUMPS,
            SessionStorageCategory.TEMP_FILES,
            SessionStorageCategory.UNKNOWN,
        }:
            candidates.append(
                SessionPruneCandidate(
                    path=path,
                    size_bytes=size,
                    category=category,
                    reason="age-based prune candidate",
                )
            )
    candidates.sort(key=lambda item: item.size_bytes, reverse=True)
    return candidates


def find_session_compaction_candidates(
    sessions_root: Path | None = None,
) -> list[SessionCompactionCandidate]:
    root = _resolve_sessions_root(sessions_root)
    candidates: list[SessionCompactionCandidate] = []
    for path in _iter_session_files(root):
        category = classify_session_file(path)
        if category not in {
            SessionStorageCategory.INTENT_EVENTS,
            SessionStorageCategory.PROGRESS_EVENTS,
            SessionStorageCategory.VALIDATION_ARTIFACTS,
            SessionStorageCategory.MODEL_OBSERVATIONS,
        }:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if _is_protected(path, root):
            continue
        candidates.append(
            SessionCompactionCandidate(
                path=path,
                size_bytes=size,
                category=category,
                reason="jsonl rollup candidate",
            )
        )
    candidates.sort(key=lambda item: item.size_bytes, reverse=True)
    return candidates


def audit_sessions_storage(
    sessions_root: Path | None = None, *, top_n: int = 20
) -> SessionStorageSummary:
    root = _resolve_sessions_root(sessions_root)
    files = _iter_session_files(root)
    category_bytes: dict[SessionStorageCategory, int] = {
        category: 0 for category in SessionStorageCategory
    }
    total_bytes = 0
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total_bytes += size
        category_bytes[classify_session_file(path)] += size
    return SessionStorageSummary(
        sessions_root=root,
        total_bytes=total_bytes,
        file_count=len(files),
        category_bytes=category_bytes,
        largest_files=_largest_files(files, limit=top_n),
        compaction_candidates=find_session_compaction_candidates(root),
        prune_candidates=find_session_prune_candidates(root),
    )


def write_jsonl_gz(source: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        source.open("rt", encoding="utf-8") as src,
        gzip.open(output_path, "wt", encoding="utf-8") as dst,
    ):
        for line in src:
            if line.strip():
                dst.write(line)


def _category_status(category: SessionStorageCategory) -> str:
    if category in {
        SessionStorageCategory.RECEIPTS,
        SessionStorageCategory.CONSENT,
        SessionStorageCategory.UPLOAD_RECEIPTS,
        SessionStorageCategory.SIGNED_ENVELOPES,
    }:
        return "protected"
    if category in {
        SessionStorageCategory.INTENT_EVENTS,
        SessionStorageCategory.PROGRESS_EVENTS,
        SessionStorageCategory.VALIDATION_ARTIFACTS,
        SessionStorageCategory.MODEL_OBSERVATIONS,
    }:
        return "compacted"
    return "retained"


def build_session_lifecycle_manifest(
    session_root: Path,
    *,
    session_id: str,
    reason: str,
    projected_reclaimable_bytes: int,
    warnings: list[str] | None = None,
) -> SessionLifecycleManifest:
    files = _iter_session_files(session_root)
    entries: list[SessionLifecycleManifestEntry] = []
    total_bytes = 0
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        category = classify_session_file(path)
        total_bytes += size
        entries.append(
            SessionLifecycleManifestEntry(
                relative_path=path.relative_to(session_root).as_posix(),
                category=category,
                size_bytes=size,
                status=_category_status(category),
            )
        )
    entries.sort(key=lambda item: item.relative_path)
    return SessionLifecycleManifest(
        schema_version="rig.relay.session_lifecycle_manifest.v1",
        session_id=session_id,
        reason=reason,
        created_at=datetime.now(UTC).isoformat(),
        entries=entries,
        total_bytes_before=total_bytes,
        total_bytes_after=total_bytes,
        projected_reclaimable_bytes=projected_reclaimable_bytes,
        warnings=list(warnings or []),
    )


def write_session_lifecycle_manifest(
    session_root: Path,
    *,
    session_id: str,
    reason: str,
    projected_reclaimable_bytes: int,
    warnings: list[str] | None = None,
) -> Path:
    manifest = build_session_lifecycle_manifest(
        session_root,
        session_id=session_id,
        reason=reason,
        projected_reclaimable_bytes=projected_reclaimable_bytes,
        warnings=warnings,
    )
    payload = {
        "schema_version": manifest.schema_version,
        "session_id": manifest.session_id,
        "reason": manifest.reason,
        "created_at": manifest.created_at,
        "entries": [
            {
                "relative_path": entry.relative_path,
                "category": entry.category.value,
                "size_bytes": entry.size_bytes,
                "status": entry.status,
            }
            for entry in manifest.entries
        ],
        "total_bytes_before": manifest.total_bytes_before,
        "total_bytes_after": manifest.total_bytes_after,
        "projected_reclaimable_bytes": manifest.projected_reclaimable_bytes,
        "warnings": manifest.warnings,
    }
    path = session_root / "session_lifecycle_manifest.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temp.replace(path)
    return path


def write_session_lifecycle_receipt(
    session_root: Path, receipt: SessionLifecycleReceipt
) -> Path:
    payload = {
        "schema_version": receipt.schema_version,
        "session_id": receipt.session_id,
        "reason": receipt.reason,
        "created_at": receipt.created_at,
        "mission_id": receipt.mission_id,
        "mission_envelope_sha256": receipt.mission_envelope_sha256,
        "adr_id": receipt.adr_id,
        "sprint_id": receipt.sprint_id,
        "scanned_files": receipt.scanned_files,
        "total_bytes_before": receipt.total_bytes_before,
        "total_bytes_after": receipt.total_bytes_after,
        "compacted_count": receipt.compacted_count,
        "refused_count": receipt.refused_count,
        "prune_candidate_count": receipt.prune_candidate_count,
        "deleted_count": receipt.deleted_count,
        "warnings": receipt.warnings,
    }
    path = session_root / "session_lifecycle_receipt.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temp.replace(path)
    return path


def _compact_text_log(source: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        source.open("rt", encoding="utf-8") as src,
        gzip.open(output_path, "wt", encoding="utf-8") as dst,
    ):
        for line in src:
            stripped = line.rstrip("\n")
            if not stripped:
                continue
            payload = {
                "line_sha256": "sha256:"
                + hashlib.sha256(stripped.encode("utf-8")).hexdigest(),
                "line_length": len(stripped),
            }
            dst.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _is_current_session_marker(path: Path) -> bool:
    return path.name.lower().startswith("active") or path.name.lower().startswith(
        "pinned"
    )


def _session_finalize_result(
    *,
    session_id: str,
    state: _FinalizeState,
    prune_candidates: tuple[SessionPruneCandidate, ...],
    manifest_path: Path,
    receipt_path: Path | None,
    total_bytes_after: int,
) -> SessionFinalizeResult:
    if state.refused_files or state.protected_files:
        status = (
            "partial" if state.compacted_files or state.deleted_files else "refused"
        )
    elif state.warnings:
        status = "partial"
    else:
        status = "ok"
    return SessionFinalizeResult(
        session_id=session_id,
        scanned_files=state.scanned_files,
        total_bytes_before=state.total_bytes_before,
        total_bytes_after=total_bytes_after,
        compacted_files=tuple(state.compacted_files),
        protected_files=tuple(state.protected_files),
        refused_files=tuple(state.refused_files),
        prune_candidates=prune_candidates,
        deleted_files=tuple(state.deleted_files),
        manifest_path=manifest_path,
        receipt_path=receipt_path,
        status=status,
        warnings=tuple(state.warnings),
    )


def _apply_session_finalize_compaction(
    *,
    session_root: Path,
    path: Path,
    size: int,
    category: SessionStorageCategory,
    state: _FinalizeState,
) -> None:
    relative = path.relative_to(session_root).as_posix().replace("/", "__")
    output_path = session_root / "lifecycle" / "rollups" / f"{relative}.jsonl.gz"
    try:
        if path.suffix.lower() == ".jsonl":
            write_jsonl_gz(path, output_path)
        else:
            _compact_text_log(path, output_path)
        after = output_path.stat().st_size
        state.compacted_files.append(
            CompactionResult(
                source_path=path,
                output_path=output_path,
                size_bytes_before=size,
                size_bytes_after=after,
                category=category,
                status="compacted",
                reason="session finalize compaction",
            )
        )
    except OSError as err:
        state.warnings.append(f"compaction failed for {path}: {err}")
        state.refused_files.append(
            Refusal(path=path, category=category, reason="compaction failed")
        )


def _record_marker_refusals(
    session_root: Path, files: list[Path], state: _FinalizeState
) -> None:
    if (session_root / "active").exists() or any(
        path.name.lower().startswith("active") for path in files
    ):
        state.refused_files.append(
            Refusal(
                path=session_root / "active",
                category=SessionStorageCategory.UNKNOWN,
                reason="active session marker present",
            )
        )
    if (session_root / "pinned").exists() or any(
        path.name.lower().startswith("pinned") for path in files
    ):
        state.refused_files.append(
            Refusal(
                path=session_root / "pinned",
                category=SessionStorageCategory.UNKNOWN,
                reason="pinned session marker present",
            )
        )


def _walk_finalize_files(
    *,
    session_root: Path,
    files: list[Path],
    policy: SessionRetentionPolicy,
    allow_compaction: bool,
    allow_prune: bool,
    state: _FinalizeState,
) -> None:
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        state.total_bytes_before += size
        category = classify_session_file(path)
        artifact = ClassifiedArtifact(path=path, size_bytes=size, category=category)
        if _is_protected(path, session_root):
            state.protected_files.append(artifact)
            continue
        if allow_compaction and category in {
            SessionStorageCategory.INTENT_EVENTS,
            SessionStorageCategory.PROGRESS_EVENTS,
            SessionStorageCategory.VALIDATION_ARTIFACTS,
            SessionStorageCategory.MODEL_OBSERVATIONS,
            SessionStorageCategory.STDOUT_STDERR,
        }:
            _apply_session_finalize_compaction(
                session_root=session_root,
                path=path,
                size=size,
                category=category,
                state=state,
            )
            continue
        if allow_prune and category in {
            SessionStorageCategory.RAW_TRANSCRIPTS,
            SessionStorageCategory.RAW_MODEL_OUTPUTS,
            SessionStorageCategory.STDOUT_STDERR,
            SessionStorageCategory.DEBUG_DUMPS,
            SessionStorageCategory.TEMP_FILES,
            SessionStorageCategory.UNKNOWN,
        }:
            _record_prune_candidate(session_root, path, size, category, policy, state)


def _record_prune_candidate(
    session_root: Path,
    path: Path,
    size: int,
    category: SessionStorageCategory,
    policy: SessionRetentionPolicy,
    state: _FinalizeState,
) -> None:
    if _is_protected(path, session_root):
        state.refused_files.append(
            Refusal(path=path, category=category, reason="protected")
        )
        return
    if any(
        candidate.path == path
        for candidate in find_session_prune_candidates(
            session_root, older_than_days=policy.older_than_days
        )
    ):
        state.deleted_files.append(
            DeletedArtifact(
                path=path, size_bytes=size, category=category, reason="prune candidate"
            )
        )


def finalize_session_storage(
    *,
    session_id: str,
    sessions_root: Path,
    policy: SessionRetentionPolicy,
    mission_envelope: MissionEnvelope | None = None,
    allow_compaction: bool = True,
    allow_prune: bool = False,
    write_receipt: bool = True,
    reason: str = "session_end",
) -> SessionFinalizeResult:
    session_root = sessions_root.expanduser()
    files = _iter_session_files(session_root)
    state = _FinalizeState(
        scanned_files=len(files),
        total_bytes_before=0,
        protected_files=[],
        refused_files=[],
        compacted_files=[],
        deleted_files=[],
        warnings=[],
    )
    _record_marker_refusals(session_root, files, state)
    _walk_finalize_files(
        session_root=session_root,
        files=files,
        policy=policy,
        allow_compaction=allow_compaction,
        allow_prune=allow_prune,
        state=state,
    )
    prune_candidates = tuple(
        find_session_prune_candidates(
            session_root, older_than_days=policy.older_than_days
        )
    )
    total_bytes_after = state.total_bytes_before - sum(
        result.size_bytes_before - result.size_bytes_after
        for result in state.compacted_files
    )
    manifest_path = write_session_lifecycle_manifest(
        session_root,
        session_id=session_id,
        reason=reason,
        projected_reclaimable_bytes=sum(
            candidate.size_bytes for candidate in prune_candidates
        ),
        warnings=state.warnings,
    )
    receipt_path = None
    if write_receipt:
        receipt = SessionLifecycleReceipt(
            schema_version="rig.relay.session_lifecycle_receipt.v1",
            session_id=session_id,
            reason=reason,
            created_at=datetime.now(UTC).isoformat(),
            mission_id=mission_envelope.mission_id if mission_envelope else None,
            mission_envelope_sha256=(
                mission_envelope.fingerprint if mission_envelope else None
            ),
            adr_id=mission_envelope.adr_id if mission_envelope else None,
            sprint_id=mission_envelope.sprint_id if mission_envelope else None,
            scanned_files=state.scanned_files,
            total_bytes_before=state.total_bytes_before,
            total_bytes_after=total_bytes_after,
            compacted_count=len(state.compacted_files),
            refused_count=len(state.refused_files) + len(state.protected_files),
            prune_candidate_count=len(prune_candidates),
            deleted_count=len(state.deleted_files),
            warnings=list(state.warnings),
        )
        receipt_path = write_session_lifecycle_receipt(session_root, receipt)
    return _session_finalize_result(
        session_id=session_id,
        state=state,
        prune_candidates=prune_candidates,
        manifest_path=manifest_path,
        receipt_path=receipt_path,
        total_bytes_after=total_bytes_after,
    )
