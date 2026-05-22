from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class SessionStorageCategory(StrEnum):
    OBSERVABILITY = "observability"
    INTENT_EVENTS = "intent_events"
    RECEIPTS = "receipts"
    CONSENT = "consent"
    SIGNED_ENVELOPES = "signed_envelopes"
    UPLOAD_RECEIPTS = "upload_receipts"
    TRACES = "traces"
    PROGRESS_EVENTS = "progress_events"
    VALIDATION_ARTIFACTS = "validation_artifacts"
    MODEL_OBSERVATIONS = "model_observations"
    RAW_TRANSCRIPTS = "raw_transcripts"
    STDOUT_STDERR = "stdout_stderr"
    DEBUG_DUMPS = "debug_dumps"
    TEMP_FILES = "temp_files"
    UNKNOWN = "unknown"
    OTHER = "other"


@dataclass(slots=True)
class ClassifiedArtifact:
    path: Path
    size_bytes: int
    category: SessionStorageCategory


@dataclass(slots=True)
class SessionPruneCandidate:
    path: Path
    size_bytes: int
    category: SessionStorageCategory
    age_days: int = 0


@dataclass(slots=True)
class SessionCompactionCandidate:
    path: Path
    size_bytes: int
    category: SessionStorageCategory


@dataclass(slots=True)
class SessionStorageSummary:
    sessions_root: Path
    total_sessions: int
    total_bytes: int
    file_count: int
    category_counts: dict[str, int]
    top_sessions: list[ClassifiedArtifact]
    timestamp: str
    category_bytes: dict[str, int] = field(default_factory=dict)
    compaction_candidates: list[SessionCompactionCandidate] = field(
        default_factory=list
    )


@dataclass(slots=True)
class CompactionResult:
    candidates: int = 0
    compacted: int = 0
    format: str = "parquet"


@dataclass(slots=True)
class DeletedArtifact:
    path: str
    size_bytes: int


@dataclass(slots=True)
class Refusal:
    path: str
    reason: str


@dataclass(slots=True)
class SessionFinalizeResult:
    session_id: str
    receipts_count: int = 0
    lifecycle_manifest_path: Path | str | None = None
    scanned_files: int = 0
    total_bytes_before: int = 0
    total_bytes_after: int = 0
    compacted_files: tuple[str, ...] | list[str] = field(default_factory=tuple)
    protected_files: tuple[str, ...] | list[str] = field(default_factory=tuple)
    refused_files: tuple[str, ...] | list[str] = field(default_factory=tuple)
    prune_candidates: tuple[str, ...] | list[str] = field(default_factory=tuple)
    deleted_files: tuple[str, ...] | list[str] = field(default_factory=tuple)
    manifest_path: Path | str | None = None
    receipt_path: Path | str | None = None
    status: str = "ok"
    warnings: tuple[str, ...] | list[str] = field(default_factory=tuple)


@dataclass(slots=True)
class SessionLifecycleManifestEntry:
    session_id: str
    finalized_at: str
    receipt_path: str | None = None


@dataclass(slots=True)
class SessionLifecycleManifest:
    entries: list[SessionLifecycleManifestEntry] = field(default_factory=list)


@dataclass(slots=True)
class SessionLifecycleReceipt:
    session_id: str
    finalized_at: str
    category_counts: dict[str, int] = field(default_factory=dict)
    reason: str = ""
    scanned_files: int = 0
    total_bytes_before: int = 0
    total_bytes_after: int = 0
    compacted_count: int = 0
    refused_count: int = 0
    prune_candidate_count: int = 0
    deleted_count: int = 0
    warnings: list[str] = field(default_factory=list)
    schema_version: str = "rig.relay.session_lifecycle_receipt.v1"
    created_at: str = ""
    mission_id: str | None = None
    adr_id: str | None = None
    sprint_id: str | None = None


@dataclass(slots=True, frozen=True)
class SessionRetentionPolicy:
    older_than_days: int = 30
    max_age_days: int = 90
    max_total_bytes: int = 1_073_741_824
    max_delete_mb: float = 256.0
    allow_prune: bool = False
    archive_dir: Path | str | None = None
    protected_categories: tuple[str, ...] = (
        "signed_envelopes",
        "receipts",
        "consent",
        "upload_receipts",
    )


@dataclass(slots=False)
class _FinalizeState:
    session_id: str
    receipts_count: int = 0
    manifest_path: str | None = None
    scanned_files: int = 0
    total_bytes_before: int = 0
    protected_files: list[str] = field(default_factory=list)
    refused_files: list[str] = field(default_factory=list)
    compacted_files: list[dict] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


__all__ = [
    "ClassifiedArtifact",
    "CompactionResult",
    "DeletedArtifact",
    "Refusal",
    "SessionCompactionCandidate",
    "SessionFinalizeResult",
    "SessionLifecycleManifest",
    "SessionLifecycleManifestEntry",
    "SessionLifecycleReceipt",
    "SessionPruneCandidate",
    "SessionRetentionPolicy",
    "SessionStorageCategory",
    "SessionStorageSummary",
    "_FinalizeState",
]
