"""Session lifecycle — split into sub-modules for maintainability."""

from __future__ import annotations

from rig_relay.evidence._lifecycle_funcs import (
    _is_protected,
    _iter_session_files,
    _largest_files,
    _resolve_sessions_root,
    audit_sessions_storage,
    classify_session_file,
    default_sessions_root,
    finalize_session_storage,
    find_session_compaction_candidates,
    find_session_prune_candidates,
)
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
