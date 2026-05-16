"""Session storage lifecycle helpers.

Conservative, content-light session audit / compaction / GC helpers for
`~/.rig/sessions`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
from typing import Any


class SessionStorageCategory(StrEnum):
    RECEIPTS = auto()
    CONSENT = auto()
    UPLOAD_RECEIPTS = auto()
    SIGNED_ENVELOPES = auto()
    PROGRESS_EVENTS = auto()
    INTENT_EVENTS = auto()
    VALIDATION_ARTIFACTS = auto()
    MODEL_OBSERVATIONS = auto()
    RAW_TRANSCRIPTS = auto()
    RAW_MODEL_OUTPUTS = auto()
    STDOUT_STDERR = auto()
    DEBUG_DUMPS = auto()
    TEMP_FILES = auto()
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class SessionPruneCandidate:
    path: Path
    size_bytes: int
    category: SessionStorageCategory
    reason: str


@dataclass(frozen=True, slots=True)
class SessionCompactionCandidate:
    path: Path
    size_bytes: int
    category: SessionStorageCategory
    reason: str


@dataclass(frozen=True, slots=True)
class SessionStorageSummary:
    sessions_root: Path
    total_bytes: int
    file_count: int
    category_bytes: dict[SessionStorageCategory, int]
    largest_files: list[dict[str, Any]]
    compaction_candidates: list[SessionCompactionCandidate]
    prune_candidates: list[SessionPruneCandidate]


@dataclass(frozen=True, slots=True)
class ClassifiedArtifact:
    path: Path
    size_bytes: int
    category: SessionStorageCategory


@dataclass(frozen=True, slots=True)
class CompactionResult:
    source_path: Path
    output_path: Path | None
    size_bytes_before: int
    size_bytes_after: int
    category: SessionStorageCategory
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class Refusal:
    path: Path
    category: SessionStorageCategory
    reason: str


@dataclass(frozen=True, slots=True)
class DeletedArtifact:
    path: Path
    size_bytes: int
    category: SessionStorageCategory
    reason: str


@dataclass(frozen=True, slots=True)
class SessionRetentionPolicy:
    allow_prune: bool = False
    max_delete_mb: float = 0.0
    older_than_days: int = 30
    archive_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class SessionLifecycleReceipt:
    schema_version: str
    session_id: str
    reason: str
    created_at: str
    scanned_files: int
    total_bytes_before: int
    total_bytes_after: int
    compacted_count: int
    refused_count: int
    prune_candidate_count: int
    deleted_count: int
    warnings: list[str]
    mission_id: str | None = None
    mission_envelope_sha256: str | None = None
    adr_id: str | None = None
    sprint_id: str | None = None


@dataclass(frozen=True, slots=True)
class SessionLifecycleManifestEntry:
    relative_path: str
    category: SessionStorageCategory
    size_bytes: int
    status: str


@dataclass(frozen=True, slots=True)
class SessionLifecycleManifest:
    schema_version: str
    session_id: str
    reason: str
    created_at: str
    entries: list[SessionLifecycleManifestEntry]
    total_bytes_before: int
    total_bytes_after: int
    projected_reclaimable_bytes: int
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class SessionFinalizeResult:
    session_id: str
    scanned_files: int
    total_bytes_before: int
    total_bytes_after: int
    compacted_files: tuple[CompactionResult, ...]
    protected_files: tuple[ClassifiedArtifact, ...]
    refused_files: tuple[Refusal, ...]
    prune_candidates: tuple[SessionPruneCandidate, ...]
    deleted_files: tuple[DeletedArtifact, ...]
    manifest_path: Path | None
    receipt_path: Path | None
    status: str
    warnings: tuple[str, ...]


@dataclass(slots=True)
class _FinalizeState:
    scanned_files: int
    total_bytes_before: int
    protected_files: list[ClassifiedArtifact]
    refused_files: list[Refusal]
    compacted_files: list[CompactionResult]
    deleted_files: list[DeletedArtifact]
    warnings: list[str]


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
