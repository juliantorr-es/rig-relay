"""ToolRuntime projection — exposes ToolRuntime outcomes for desktop UI.

Lightweight in-memory ledger + summary builder. No persistence yet —
each session accumulates results and the projection builds from
current in-memory state. Future: move to a durable event ledger and
let the analytics compiler consume it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeCacheStatus,
    ToolRuntimeStatus,
)


class ToolRuntimeLedgerEntry(BaseModel):
    """A single tool execution outcome written by AgentLoop after
    each tool call completes via ToolRuntime.
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: str = ""
    tool_call_id: str = ""
    status: str = ""
    cache_status: str = ""
    refusal_code: str | None = None
    degraded_capabilities: list[str] = Field(default_factory=list)
    duration_ms: float | None = None
    recorded_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


class ToolRuntimeSummary(BaseModel):
    """Aggregated summary of recent ToolRuntime outcomes.

    This is the projection model surfaced to the desktop UI.
    All fields are content-light: counts, statuses, refs.
    No raw tool outputs or secrets.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ui.tool_runtime_summary.v1"
    generated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    # ── Recent results (last 10) ────────────────────────────────────
    recent_results: list[ToolRuntimeLedgerEntry] = Field(default_factory=list)

    # ── Status counts ───────────────────────────────────────────────
    total_executions: int = 0
    completed_count: int = 0
    cached_count: int = 0
    refused_count: int = 0
    failed_count: int = 0
    degraded_count: int = 0
    skipped_count: int = 0

    # ── Refusal breakdown ───────────────────────────────────────────
    refusal_counts: dict[str, int] = Field(default_factory=dict)

    # ── Degradation breakdown ───────────────────────────────────────
    degradation_counts: dict[str, int] = Field(default_factory=dict)

    # ── Cache ───────────────────────────────────────────────────────
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    cache_write_failed_count: int = 0

    # ── Approval ────────────────────────────────────────────────────
    approval_required_count: int = 0
    approval_denied_count: int = 0

    # ── Receipt ─────────────────────────────────────────────────────
    latest_receipt_refs: list[str] = Field(default_factory=list)
    latest_context_observation_status: str = ""


# ── Global in-memory ledger (per-process, per-session) ──────────────

_ledger: list[ToolRuntimeLedgerEntry] = []


def record_tool_outcome(
    tool_name: str,
    tool_call_id: str,
    status: ToolRuntimeStatus,
    cache_status: ToolRuntimeCacheStatus = ToolRuntimeCacheStatus.NOT_APPLICABLE,
    refusal_code: RefusalCode | None = None,
    degraded_capabilities: list[str] | None = None,
    duration_ms: float | None = None,
) -> None:
    """Record a tool execution outcome in the in-memory ledger."""
    entry = ToolRuntimeLedgerEntry(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        status=status.value,
        cache_status=cache_status.value,
        refusal_code=refusal_code.value if refusal_code else None,
        degraded_capabilities=degraded_capabilities or [],
        duration_ms=duration_ms,
    )
    _ledger.append(entry)


def build_summary(max_recent: int = 10) -> ToolRuntimeSummary:
    """Build a ToolRuntimeSummary from the current in-memory ledger."""
    entries = list(_ledger)

    status_counts: dict[str, int] = {}
    refusal_counts: dict[str, int] = {}
    degradation_counts: dict[str, int] = {}
    cache_hit = 0
    cache_miss = 0
    cache_write_failed = 0
    approval_denied = 0
    latest_receipts: list[str] = []
    latest_obs = ""

    for e in entries:
        status_counts[e.status] = status_counts.get(e.status, 0) + 1

        if e.cache_status == "hit":
            cache_hit += 1
        elif e.cache_status == "miss":
            cache_miss += 1
        elif e.cache_status == "write_failed":
            cache_write_failed += 1

        if e.refusal_code:
            refusal_counts[e.refusal_code] = (
                refusal_counts.get(e.refusal_code, 0) + 1
            )
            if "approval" in e.refusal_code:
                approval_denied += 1

        for cap in e.degraded_capabilities:
            degradation_counts[cap] = degradation_counts.get(cap, 0) + 1

    # Approval required = count of refused with approval_denied
    # In future, track approval_required separately from the approval callback

    return ToolRuntimeSummary(
        recent_results=entries[-max_recent:],
        total_executions=len(entries),
        completed_count=status_counts.get("completed", 0),
        cached_count=status_counts.get("cached", 0),
        refused_count=status_counts.get("refused", 0),
        failed_count=status_counts.get("failed", 0),
        degraded_count=status_counts.get("degraded", 0),
        skipped_count=status_counts.get("skipped", 0),
        refusal_counts=refusal_counts,
        degradation_counts=degradation_counts,
        cache_hit_count=cache_hit,
        cache_miss_count=cache_miss,
        cache_write_failed_count=cache_write_failed,
        approval_denied_count=approval_denied,
        latest_receipt_refs=latest_receipts,
        latest_context_observation_status=latest_obs,
    )


def reset_ledger() -> None:
    """Clear the in-memory ledger (for tests or session reset)."""
    _ledger.clear()
