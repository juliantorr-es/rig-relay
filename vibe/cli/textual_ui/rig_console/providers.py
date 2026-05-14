"""Provider protocol and fixture for projection-driven DashboardScreen.

Defines the boundary between Textual UI (projection consumer) and
backend/control-plane (projection producer). Providers are async
seams that return content-light DashboardProjection without exposing
raw logs, file contents, or mutation capabilities.

Rules:
- Provider returns DashboardProjection
- Provider is content-light
- Provider does not mutate state
- Provider may be sync internally but exposed async for future backend integration
"""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Any, Protocol

from git import Repo
from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination.fleet_projection import (
    FleetLeaseSummary,
    FleetProjection,
    build_fleet_projection,
)
from rig_relay.coordination.lease_manager import PathLeaseManager
from rig_relay.coordination.models import CoordinationSession
from rig_relay.desktop.execution_progress import execution_progress_from_runtime_events
from rig_relay.evidence.receipt_index import ToolReceiptIndexRecord, build_receipt_index
from rig_relay.runtime.context_resolver import RuntimeContextResolver
from rig_relay.runtime.runtime_audit_event import RuntimeAuditPersistenceStore
from rig_relay.runtime.runtime_supervisor_projection import (
    RuntimeSupervisorProjection,
    build_runtime_supervisor_projection,
)
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionResult,
    RuntimeToolExecutionRunner,
)
from vibe.cli.textual_ui.rig_console.actions import build_validate_runtime_exec_intent
from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    EvidenceRailProjection,
    SessionPaneProjection,
    build_inspector_projection,
    evidence_rail_from_receipt_index,
)

_PROVIDER_PATH_CAP = 10


class CoordinationDashboardSummary(BaseModel):
    """Read-only summary of coordination state for a session.

    Derived from coordination store JSON files. Empty if unavailable.
    Content-light — no raw payloads, just metadata.
    """

    model_config = ConfigDict(extra="forbid")

    lane_id: str | None = None
    task_title: str | None = None
    last_heartbeat_at: str | None = None
    current_step: str | None = None
    pending_user_action: str | None = None
    session_status: str | None = None
    warnings: list[str] = Field(default_factory=list)


def _read_coordination_summary(
    coordination_root: Path | None, session_id: str
) -> CoordinationDashboardSummary:
    """Read coordination state from coordination store directory.

    Tolerates:
    - missing coordination_root (returns empty summary)
    - missing session file (returns empty summary)
    - malformed JSON (returns empty summary with warning)

    Does not mutate files, crawl directories, or repair leases.
    """
    if coordination_root is None:
        return CoordinationDashboardSummary()

    session_file = coordination_root / "sessions" / f"{session_id}.json"
    if not session_file.is_file():
        return CoordinationDashboardSummary()

    try:
        raw = session_file.read_text(encoding="utf-8")
        data = json.loads(raw)
        session = CoordinationSession.model_validate(data)
    except (json.JSONDecodeError, ValueError, KeyError):
        return CoordinationDashboardSummary(
            warnings=["Malformed coordination session file"]
        )

    return CoordinationDashboardSummary(
        lane_id=session.task_id,
        task_title=None,  # Not directly available from session model
        last_heartbeat_at=session.updated_at,
        current_step=session.status,
        pending_user_action=None,  # Not directly available
        session_status=session.status,
    )


def _git_summary(workspace_root: Path | None) -> tuple[str | None, str | None]:
    if workspace_root is None:
        return None, None
    try:
        repo = Repo(workspace_root, search_parent_directories=True)
    except Exception:
        return None, None
    branch_name: str | None = None
    try:
        branch_name = repo.active_branch.name
    except Exception:
        branch_name = None
    head_sha = repo.head.commit.hexsha[:8] if repo.head.is_valid() else None
    if branch_name and head_sha:
        return f"{branch_name} @{head_sha}", head_sha
    return branch_name, head_sha


class DashboardProjectionProvider(Protocol):
    """Protocol for supplying a dashboard projection to the UI.

    Implementations read from coordination state, receipt indices,
    or other backend stores — but return only a content-light
    DashboardProjection. The UI never reads raw data directly.
    """

    async def dashboard_projection(self) -> DashboardProjection:
        """Return the current dashboard projection.

        Must not mutate files, run tools, or expose raw content.
        """
        ...


class FixtureDashboardProjectionProvider:
    """Fixture provider that returns a fixed DashboardProjection.

    Used for preview/testing. The projection is set once and returned
    on every call. Call set_projection() to swap fixture data.
    """

    def __init__(self, projection: DashboardProjection) -> None:
        self._projection = projection

    async def dashboard_projection(self) -> DashboardProjection:
        """Return the fixed fixture projection."""
        return self._projection

    def set_projection(self, projection: DashboardProjection) -> None:
        """Replace the fixture projection."""
        self._projection = projection


class RuntimeDashboardProjectionProvider:
    """Read-only provider that builds DashboardProjection from local evidence.

    Uses the existing receipt index builder (build_receipt_index) to read
    session observability JSONL. Builds EvidenceRailProjection via the
    existing adapter (evidence_rail_from_receipt_index), and populates
    SessionPaneProjection from available receipt metadata.

    Rules:
    - Does not mutate files, run tools, or expose raw content
    - Tolerates missing session paths gracefully (returns empty projection)
    - Does not parse raw observability payloads in widget/screen code
    - All content goes through projection models with extra="forbid"
    """

    def __init__(
        self,
        session_id: str = "unknown",
        session_path: Path | None = None,
        workspace_root: Path | None = None,
        max_evidence_items: int = 20,
        coordination_root: Path | None = None,
        session_root: Path | None = None,
        audit_root: Path | None = None,
        lane_id: str | None = None,
        task_title: str | None = None,
        runtime_events: Sequence[Any] | None = None,
    ) -> None:
        self._session_id = session_id
        self._session_path = session_path
        self._workspace_root = workspace_root
        self._max_evidence_items = max_evidence_items
        self._coordination_root = coordination_root
        self._session_root = session_root
        self._audit_root = audit_root
        self._lane_id = lane_id
        self._task_title = task_title
        self._runtime_events = runtime_events
        self._validate_runner: RuntimeToolExecutionRunner | None = None

    async def dashboard_projection(self) -> DashboardProjection:
        """Build a DashboardProjection from available local evidence.

        Returns a clean empty projection if the session path does
        not exist or cannot be read. If runtime_events were provided
        at construction, aggregates them into execution_progress.
        """
        path: str | Path = (
            self._session_path if self._session_path is not None else self._session_id
        )
        records, errors = build_receipt_index(path)
        supervisor = self._build_supervisor_projection()

        evidence = evidence_rail_from_receipt_index(
            records, self._session_id, max_items=self._max_evidence_items
        )

        session = self._build_session(records, evidence)
        footer = self._build_footer(errors, evidence)
        inspector = build_inspector_projection(session, evidence, supervisor)

        execution_progress = None
        if self._runtime_events is not None:
            execution_progress = execution_progress_from_runtime_events(
                self._runtime_events
            )

        fleet = self._build_fleet_projection()

        return DashboardProjection(
            title="Rig Console",
            subtitle=f"Session {self._session_id[:12]}",
            session=session,
            evidence=evidence,
            safety_state="read-only",
            footer_hint=footer,
            backlog_items=[],
            execution_progress=execution_progress,
            inspector=inspector,
            fleet=fleet,
        )

    def _build_session(
        self, records: list[ToolReceiptIndexRecord], evidence: EvidenceRailProjection
    ) -> SessionPaneProjection:
        """Build a SessionPaneProjection from receipt records and coordination state.

        Populates fields from:
        - Receipt metadata (validate_status, latest_receipt_kind, changed_paths)
        - Coordination store (lane_id, last_heartbeat_at, current_step)
        - Explicit constructor inputs (lane_id, task_title)
        - workspace_root (worktree_path)

        Unknown fields remain None/default. Missing coordination state
        is tolerated silently.
        """
        # Latest validate status from most recent validate receipt
        validate_status: str | None = None
        latest_receipt_kind: str | None = None

        sorted_records = sorted(
            records, key=lambda r: r.captured_at or "", reverse=True
        )

        for record in sorted_records:
            if record.tool_name == "validate" and record.status:
                validate_status = record.status
                if latest_receipt_kind is None:
                    latest_receipt_kind = "validate"
            if latest_receipt_kind is None:
                latest_receipt_kind = record.tool_name

        # Deduplicated changed paths from evidence items
        seen: set[str] = set()
        changed_paths: list[str] = []
        for item in evidence.items:
            if item.path and item.path not in seen:
                seen.add(item.path)
                changed_paths.append(item.path)
                if len(changed_paths) >= _PROVIDER_PATH_CAP:
                    break

        status = "active" if records else "idle"

        # Read coordination state
        coord = _read_coordination_summary(self._coordination_root, self._session_id)

        # Prefer explicit constructor inputs over coordination-derived
        lane_id = self._lane_id or coord.lane_id
        task_title = self._task_title or coord.task_title
        last_heartbeat_at = coord.last_heartbeat_at
        current_step = coord.current_step or "No active session data"

        branch_name, _ = _git_summary(self._workspace_root)
        return SessionPaneProjection(
            session_id=self._session_id,
            lane_id=lane_id,
            task_title=task_title,
            status=status,
            branch_name=branch_name,
            worktree_path=(str(self._workspace_root) if self._workspace_root else None),
            last_heartbeat_at=last_heartbeat_at,
            current_step=current_step,
            validate_status=validate_status,
            blocker_summary={},
            receipt_count=evidence.receipt_count,
            latest_receipt_kind=latest_receipt_kind,
            changed_paths=changed_paths,
            pending_user_action=None,
        )

    def _build_supervisor_projection(self) -> RuntimeSupervisorProjection | None:
        store = self._audit_store()
        if store is None:
            return None
        return build_runtime_supervisor_projection(store)

    def _audit_store(self) -> RuntimeAuditPersistenceStore | None:
        audit_root = self._audit_root
        if audit_root is None:
            return None
        path = (
            audit_root
            if audit_root.suffix == ".jsonl"
            else audit_root / "observability.jsonl"
        )
        return RuntimeAuditPersistenceStore(path)

    def _runner(self) -> RuntimeToolExecutionRunner | None:
        store = self._audit_store()
        if store is None:
            return None
        if self._validate_runner is None:
            self._validate_runner = RuntimeToolExecutionRunner(audit_store=store)
        return self._validate_runner

    async def run_validate(
        self, projection: DashboardProjection
    ) -> RuntimeToolExecutionResult:
        """Run governed validate via runtime_exec and return the execution result."""
        if self._workspace_root is None or self._audit_root is None:
            return RuntimeToolExecutionResult(
                status="refused",
                intent_id="validate-unavailable",
                tool_name=RuntimeToolName.RUNTIME_EXEC.value,
                error_kind="missing_runtime_roots",
                refusal_reason="workspace_root and audit_root are required for validate",
            )

        runner = self._runner()
        if runner is None:
            return RuntimeToolExecutionResult(
                status="refused",
                intent_id="validate-unavailable",
                tool_name=RuntimeToolName.RUNTIME_EXEC.value,
                error_kind="missing_audit_store",
                refusal_reason="audit store is required for validate",
            )

        task_id = (
            projection.session.task_title
            or projection.session.current_step
            or "validate"
        )
        resolver = RuntimeContextResolver(
            repo_root=self._workspace_root, session_root=self._session_path
        )
        resolution = resolver.resolve_for_intent(
            "validate",
            session_id=projection.session.session_id,
            task_id=task_id,
            paths=projection.session.changed_paths or None,
            require_worktree=False,
        )

        if resolution.status != "resolved":
            return RuntimeToolExecutionResult(
                status="blocked",
                intent_id="validate-unavailable",
                tool_name=RuntimeToolName.RUNTIME_EXEC.value,
                error_kind=resolution.error_kind or "context_unresolved",
                refusal_reason=resolution.refusal_reason,
            )

        intent = build_validate_runtime_exec_intent(
            intent_id=f"validate-{projection.session.session_id}",
            session_id=projection.session.session_id,
            task_id=task_id,
            changed_paths=projection.session.changed_paths[:5],
        )
        return await runner.execute_runtime_exec(intent, resolution)

    def _build_footer(self, errors: list[str], evidence: EvidenceRailProjection) -> str:
        """Build a concise footer hint string."""
        parts: list[str] = ["Read-only evidence provider"]
        if errors:
            parts.append(f"({len(errors)} read errors)")
        return "  ".join(parts)

    def _build_fleet_projection(self) -> FleetProjection | None:
        """Build a FleetProjection from available coordination data.

        Phase 0: reads path leases from PathLeaseManager when
        coordination_root is set. All other subsystems (queue,
        agents, blockers, patches) return empty defaults.

        Never crashes — returns None when coordination_root is
        unavailable or lease reading fails.
        """
        if self._coordination_root is None:
            return None

        try:
            path_manager = PathLeaseManager(self._coordination_root)
            leases = path_manager.query_active_leases()
        except Exception:
            leases = []

        lease_summary = FleetLeaseSummary(
            total_active=len(leases),
            exclusive_write=sum(1 for l in leases if l.mode == "write"),
            shared_read=sum(1 for l in leases if l.mode == "read"),
            path_count=sum(len(l.paths) for l in leases),
        )

        return build_fleet_projection(
            coordination_root=self._coordination_root, leases=lease_summary
        )


__all__ = [
    "DashboardProjectionProvider",
    "FixtureDashboardProjectionProvider",
    "RuntimeDashboardProjectionProvider",
]
