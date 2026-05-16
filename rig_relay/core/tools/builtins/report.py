"""rig.report — governed structured report tool.

Agents use this to file mission reports, out-of-scope findings, bug
reports, architecture seams, data races, and other discoveries.

rig.get_context is the read side. rig.report is the write side.

Reports are append-only to a local JSONL ledger at .rig/reports/reports.jsonl.
Promotion into canonical findings (docs/findings/) is a separate triage step.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.types import ToolStreamEvent
from rig_relay.reports.report_store import (
    REPORT_KINDS,
    SEVERITY_LEVELS,
    STATUSES,
    compute_report_sha256,
    derive_dedupe_key,
    find_existing_report,
    generate_report_id,
    write_report_to_ledger,
)


class EvidenceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    path: str
    summary: str


class ReportLinks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_report_id: str | None = None
    parent_mission_id: str | None = None
    related_report_ids: list[str] = Field(default_factory=list)


class CreatedBy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = None
    session_id: str | None = None
    lane_id: str | None = None


class ReportArgs(BaseModel):
    """Arguments for rig.report."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        description="Kind of report. See rig.report.v1 schema for valid kinds."
    )
    title: str
    summary: str
    severity: str = Field(default="medium", description="low, medium, high, critical")
    confidence: str = Field(
        default="medium", description="low, medium, high, confirmed"
    )
    scope_relation: str = Field(
        default="out_of_scope_for_current_mission",
        description="in_scope, out_of_scope_for_current_mission, adjacent, regression, pre_existing",
    )
    status: str = Field(default="open")
    affected_paths: list[str] = Field(default_factory=list)
    evidence: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of evidence entries: {kind, path, summary}",
    )
    blockers: list[str] = Field(default_factory=list)
    recommended_next_action: str = ""
    dedupe_key: str | None = Field(
        default=None,
        description="Optional stable dedupe key. Derived from kind+title+paths if not provided.",
    )
    parent_report_id: str | None = None
    parent_mission_id: str | None = None
    related_report_ids: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(
        default_factory=dict, description="Kind-specific detail payload."
    )

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        if v not in REPORT_KINDS:
            valid = ", ".join(sorted(REPORT_KINDS))
            raise ValueError(f"Invalid kind '{v}'. Must be one of: {valid}")
        return v

    @field_validator("severity")
    @classmethod
    def _validate_severity(cls, v: str) -> str:
        if v not in SEVERITY_LEVELS:
            raise ValueError(
                f"Invalid severity '{v}'. Must be one of: {', '.join(sorted(SEVERITY_LEVELS))}"
            )
        return v

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in STATUSES:
            valid = ", ".join(s for s in sorted(STATUSES) if s != "unknown")
            raise ValueError(f"Invalid status '{v}'. Valid statuses: {valid}")
        return v


class ReportResult(BaseModel):
    """Result from rig.report.

    Contains the report payload hash (report_sha256), the event write
    hash (event_sha256), and separate counts for the raw report ledger
    vs. the canonical findings registry.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    report_id: str
    dedupe_status: str = "new"
    report_sha256: str = ""
    event_sha256: str = ""
    ledger_path: str = ""
    report_ledger_count: int | None = None
    open_raw_report_count: int | None = None
    open_finding_count: int | None = None
    stale_finding_count: int | None = None


class ReportToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class ReportState(BaseToolState):
    pass


class Report(
    BaseTool[ReportArgs, ReportResult, ReportToolConfig, ReportState],
    ToolUIData[ReportArgs, ReportResult],
):
    description: ClassVar[str] = (
        "File a structured report: mission report, out-of-scope finding, "
        "bug report, architecture seam, data race, or other discovery. "
        "Reports are append-only to a local JSONL ledger. "
        "This is the write-side counterpart to rig.get_context."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.NONDETERMINISTIC_EXTERNAL_IO
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.WRITES_EVIDENCE_ONLY

    @classmethod
    def format_call_display(cls, args: ReportArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"Report: {args.kind} — {args.title[:60]}")

    @classmethod
    def get_result_display(cls, event: Any) -> ToolResultDisplay:
        if not isinstance(event.result, ReportResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        return ToolResultDisplay(
            success=True,
            message=f"Report {event.result.report_id}: {event.result.dedupe_status}",
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Filing report"

    async def run(
        self, args: ReportArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | ReportResult, None]:
        try:
            report_id = generate_report_id()
            dedupe_key = args.dedupe_key or derive_dedupe_key({
                "kind": args.kind,
                "title": args.title,
                "affected_paths": args.affected_paths,
            })

            # Check for duplicate
            existing = find_existing_report(dedupe_key)
            if existing is not None:
                explicit_key = args.dedupe_key is not None
                yield ReportResult(
                    ok=True,
                    report_id=existing.get("report_id", report_id),
                    dedupe_status="duplicate_exact"
                    if explicit_key
                    else "duplicate_candidate",
                    report_sha256=compute_report_sha256(existing),
                    event_sha256=compute_report_sha256(existing),
                    ledger_path=str(existing.get("_ledger_path", "")),
                )
                return

            # Build the report envelope
            report = {
                "schema_version": "rig.report.v1",
                "report_id": report_id,
                "created_at": datetime.now(UTC).isoformat(),
                "created_by": {
                    "agent_id": getattr(ctx, "agent_id", None),
                    "session_id": getattr(ctx, "session_id", None),
                },
                "kind": args.kind,
                "title": args.title,
                "summary": args.summary,
                "severity": args.severity,
                "confidence": args.confidence,
                "scope_relation": args.scope_relation,
                "status": args.status,
                "affected_paths": args.affected_paths,
                "evidence": args.evidence,
                "blockers": args.blockers,
                "recommended_next_action": args.recommended_next_action,
                "dedupe_key": dedupe_key,
                "links": {
                    "parent_report_id": args.parent_report_id,
                    "parent_mission_id": args.parent_mission_id,
                    "related_report_ids": args.related_report_ids,
                },
                "details": args.details,
            }

            # Persist
            report_sha256 = compute_report_sha256(report)
            event_envelope = {
                **report,
                "_write_event": "report.created",
                "_report_sha256": report_sha256,
            }
            event_sha256 = compute_report_sha256(event_envelope)
            ledger_path = write_report_to_ledger(report)

            # Compute separate counts
            counts = _compute_report_counts(ledger_path)

            yield ReportResult(
                ok=True,
                report_id=report_id,
                dedupe_status="new",
                report_sha256=report_sha256,
                event_sha256=event_sha256,
                ledger_path=str(ledger_path),
                report_ledger_count=counts["report_ledger_count"],
                open_raw_report_count=counts["open_raw_report_count"],
                open_finding_count=counts["open_finding_count"],
                stale_finding_count=counts["stale_finding_count"],
            )

        except Exception as e:
            raise ToolError(f"report failed: {e}") from e


def _compute_report_counts(ledger_path: Path) -> dict[str, int | None]:
    """Compute separate counts for raw reports and canonical findings.

    Returns:
        dict with: report_ledger_count, open_raw_report_count,
        open_finding_count, stale_finding_count.
        Canonical finding counts may be None if the findings lifecycle
        module is unavailable.
    """
    import json as _json

    report_ledger_count = 0
    open_raw = 0
    open_finding_count: int | None = None
    stale_finding_count: int | None = None

    try:
        if ledger_path.is_file():
            with open(ledger_path) as _f:
                for _line in _f:
                    if _line.strip():
                        report_ledger_count += 1
                        try:
                            _r = _json.loads(_line)
                            if _r.get("status") == "open":
                                open_raw += 1
                        except _json.JSONDecodeError:
                            pass

        from rig_relay.governance.findings_lifecycle import compute_findings_summary

        _fs = compute_findings_summary()
        open_finding_count = _fs.get("by_status", {}).get("open", 0)
        stale_finding_count = len(_fs.get("stale_findings", []))
    except Exception:
        pass

    return {
        "report_ledger_count": report_ledger_count,
        "open_raw_report_count": open_raw,
        "open_finding_count": open_finding_count,
        "stale_finding_count": stale_finding_count,
    }
