"""Session lifecycle finalize tool — governed agent-callable tool contract.

Wraps finalize_session_storage() in a Pydantic-contract tool with
dry-run-safe defaults, content-light results, and explicit refusal taxonomy.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.evidence.session_lifecycle import (
    SessionRetentionPolicy,
    finalize_session_storage,
)

_SCHEMA_VERSION_REQUEST = "rig.relay.session_lifecycle_finalize_request.v1"
_SCHEMA_VERSION_RESULT = "rig.relay.session_lifecycle_finalize_result.v1"


class SessionLifecycleFinalizeRequest(BaseModel):
    """Request envelope for session_lifecycle_finalize tool.

    All mutation flags default to False. dry_run defaults to True.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION_REQUEST
    session_id: str
    sessions_root: str | None = None
    older_than_days: int = 30
    allow_compaction: bool = False
    allow_prune: bool = False
    write_receipt: bool = True
    reason: str = "session_end"
    dry_run: bool = True


class CompactionDetail(BaseModel):
    """Content-light per-file compaction detail."""

    model_config = ConfigDict(extra="forbid")

    source_path: str
    output_path: str | None = None
    size_bytes_before: int = 0
    size_bytes_after: int = 0
    category: str
    status: str
    reason: str = ""


class ProtectedDetail(BaseModel):
    """Protected file skipped during finalization."""

    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int
    category: str


class RefusalDetail(BaseModel):
    """Refused file with reason."""

    model_config = ConfigDict(extra="forbid")

    path: str
    category: str
    reason: str


class SessionLifecycleFinalizeResult(BaseModel):
    """Content-light result of a session lifecycle finalization.

    Contains counts, paths, hashes, and byte totals. No raw prompts,
    model outputs, stdout/stderr bodies, secrets, or source diffs.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION_RESULT
    status: str
    session_id: str
    scanned_files: int = 0
    total_bytes_before: int = 0
    total_bytes_after: int = 0
    compacted_count: int = 0
    refused_count: int = 0
    prune_candidate_count: int = 0
    deleted_count: int = 0
    compacted_details: list[CompactionDetail] = Field(default_factory=list)
    protected_details: list[ProtectedDetail] = Field(default_factory=list)
    refused_details: list[RefusalDetail] = Field(default_factory=list)
    manifest_path: str | None = None
    receipt_path: str | None = None
    warnings: list[str] = Field(default_factory=list)


def _resolve_sessions_root(session_id: str, sessions_root: str | None) -> Path:
    if sessions_root is not None:
        return Path(sessions_root).expanduser()
    return Path.home() / ".rig" / "sessions" / session_id


class SessionLifecycleFinalizeTool:
    """Governed tool for end-of-session lifecycle finalization.

    Defaults to dry-run. No files are modified unless explicitly
    authorized via allow_compaction/allow_prune and dry_run=False.
    """

    TOOL_NAME = "session_lifecycle_finalize"

    def run(
        self, request: SessionLifecycleFinalizeRequest
    ) -> SessionLifecycleFinalizeResult:
        """Execute session lifecycle finalization.

        Args:
            request: Validated request envelope.

        Returns:
            Content-light result with counts, paths, and status.
        """
        session_root = _resolve_sessions_root(request.session_id, request.sessions_root)

        if not session_root.is_dir():
            return SessionLifecycleFinalizeResult(
                status="refused",
                session_id=request.session_id,
                warnings=[f"Session directory not found: {session_root}"],
            )

        if request.dry_run:
            return self._run_audit_only(request, session_root)

        return self._run_finalize(request, session_root)

    def _run_audit_only(
        self, request: SessionLifecycleFinalizeRequest, session_root: Path
    ) -> SessionLifecycleFinalizeResult:
        """Dry-run: audit only, no file mutations, no receipt written."""
        from rig_relay.evidence.session_lifecycle import audit_sessions_storage

        summary = audit_sessions_storage(session_root)
        compacted_details: list[CompactionDetail] = []

        for candidate in summary.compaction_candidates:
            compacted_details.append(
                CompactionDetail(
                    source_path=str(candidate.path),
                    size_bytes_before=candidate.size_bytes,
                    category=candidate.category.value,
                    status="candidate",
                    reason=getattr(candidate, "reason", "compaction candidate"),
                )
            )

        return SessionLifecycleFinalizeResult(
            status="ok",
            session_id=request.session_id,
            scanned_files=summary.file_count,
            total_bytes_before=summary.total_bytes,
            total_bytes_after=summary.total_bytes,
            compacted_count=len(compacted_details),
            compacted_details=compacted_details,
            warnings=[],
        )

    def _run_finalize(
        self, request: SessionLifecycleFinalizeRequest, session_root: Path
    ) -> SessionLifecycleFinalizeResult:
        """Run finalize with compaction/prune as authorized."""
        policy = SessionRetentionPolicy(older_than_days=request.older_than_days)
        result = finalize_session_storage(
            session_id=request.session_id,
            sessions_root=session_root,
            policy=policy,
            allow_compaction=request.allow_compaction,
            allow_prune=request.allow_prune,
            write_receipt=request.write_receipt,
            reason=request.reason,
        )
        compacted_details = [
            CompactionDetail(
                source_path=str(c.source_path),
                output_path=str(c.output_path) if c.output_path else None,
                size_bytes_before=c.size_bytes_before,
                size_bytes_after=c.size_bytes_after,
                category=c.category.value,
                status=c.status,
                reason=c.reason,
            )
            for c in result.compacted_files
        ]
        protected_details = [
            ProtectedDetail(
                path=str(p.path), size_bytes=p.size_bytes, category=p.category.value
            )
            for p in result.protected_files
        ]
        refused_details = [
            RefusalDetail(path=str(r.path), category=r.category.value, reason=r.reason)
            for r in result.refused_files
        ]
        return SessionLifecycleFinalizeResult(
            status=result.status,
            session_id=result.session_id,
            scanned_files=result.scanned_files,
            total_bytes_before=result.total_bytes_before,
            total_bytes_after=result.total_bytes_after,
            compacted_count=len(result.compacted_files),
            refused_count=len(result.refused_files) + len(result.protected_files),
            prune_candidate_count=len(result.prune_candidates),
            deleted_count=len(result.deleted_files),
            compacted_details=compacted_details,
            protected_details=protected_details,
            refused_details=refused_details,
            manifest_path=str(result.manifest_path) if result.manifest_path else None,
            receipt_path=str(result.receipt_path) if result.receipt_path else None,
            warnings=list(result.warnings),
        )


__all__ = [
    "CompactionDetail",
    "ProtectedDetail",
    "RefusalDetail",
    "SessionLifecycleFinalizeRequest",
    "SessionLifecycleFinalizeResult",
    "SessionLifecycleFinalizeTool",
]
