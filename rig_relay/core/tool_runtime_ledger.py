"""ToolRuntime result ledger — explicit sink for tool execution outcomes.

Separates result recording (AgentLoop concern: "here is the result")
from result aggregation (projection concern: "what happened across all
tools?"). The sink protocol allows swapping the in-memory ledger for
a durable event ledger, analytics adapter, or debug exporter later
without changing AgentLoop.

Current: InMemoryToolRuntimeResultLedger.
Future: DurableToolRuntimeResultLedger, AnalyticsToolRuntimeSink.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.tool_runtime_models import ToolRuntimeResult, ToolRuntimeStatus


class ToolRuntimeLedgerEntry(BaseModel):
    """A single tool execution outcome."""

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

    @classmethod
    def from_result(cls, result: ToolRuntimeResult) -> ToolRuntimeLedgerEntry:
        """Build an entry from a ToolRuntimeResult."""
        return cls(
            tool_name=result.tool_name,
            tool_call_id=result.tool_call_id,
            status=result.status.value,
            cache_status=result.cache_status.value,
            refusal_code=(
                result.refusal.refusal_code.value if result.refusal else None
            ),
            degraded_capabilities=list(result.degraded_capabilities),
            duration_ms=result.duration_ms,
        )


class ToolRuntimeSummary(BaseModel):
    """Aggregated summary of recent ToolRuntime outcomes.

    Schema: rig.ui.tool_runtime_summary.v1
    Content-light: counts, statuses, refs. No raw tool outputs.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ui.tool_runtime_summary.v1"
    generated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    recent_results: list[ToolRuntimeLedgerEntry] = Field(default_factory=list)
    total_executions: int = 0
    completed_count: int = 0
    cached_count: int = 0
    refused_count: int = 0
    failed_count: int = 0
    degraded_count: int = 0
    skipped_count: int = 0
    refusal_counts: dict[str, int] = Field(default_factory=dict)
    degradation_counts: dict[str, int] = Field(default_factory=dict)
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    cache_write_failed_count: int = 0
    approval_required_count: int = 0
    approval_denied_count: int = 0
    latest_receipt_refs: list[str] = Field(default_factory=list)
    latest_context_observation_status: str = ""


class ToolRuntimeResultSink(Protocol):
    """Protocol for recording ToolRuntime outcomes.

    AgentLoop calls ``record(result)`` after each tool execution.
    The sink decides what to do: store in memory, write to disk,
    feed to analytics, etc.
    """

    def record(self, result: ToolRuntimeResult) -> None: ...


class InMemoryToolRuntimeResultLedger:
    """In-memory ledger implementing ToolRuntimeResultSink.

    Stores entries in a process-local list. Provides ``build_summary()``
    for the desktop projection builder.
    """

    def __init__(self) -> None:
        self._entries: list[ToolRuntimeLedgerEntry] = []

    def record(self, result: ToolRuntimeResult) -> None:
        """Record a ToolRuntimeResult in the in-memory ledger."""
        entry = ToolRuntimeLedgerEntry.from_result(result)
        self._entries.append(entry)

    def build_summary(self, max_recent: int = 10) -> ToolRuntimeSummary:
        """Build an aggregate summary from recorded entries."""
        entries = list(self._entries)

        status_counts: dict[str, int] = {}
        refusal_counts: dict[str, int] = {}
        degradation_counts: dict[str, int] = {}
        cache_hit = 0
        cache_miss = 0
        cache_write_failed = 0
        approval_denied = 0

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
                degradation_counts[cap] = (
                    degradation_counts.get(cap, 0) + 1
                )

        return ToolRuntimeSummary(
            recent_results=entries[-max_recent:],
            total_executions=len(entries),
            completed_count=status_counts.get(
                ToolRuntimeStatus.COMPLETED.value, 0
            ),
            cached_count=status_counts.get(
                ToolRuntimeStatus.CACHED.value, 0
            ),
            refused_count=status_counts.get(
                ToolRuntimeStatus.REFUSED.value, 0
            ),
            failed_count=status_counts.get(
                ToolRuntimeStatus.FAILED.value, 0
            ),
            degraded_count=status_counts.get(
                ToolRuntimeStatus.DEGRADED.value, 0
            ),
            skipped_count=status_counts.get(
                ToolRuntimeStatus.SKIPPED.value, 0
            ),
            refusal_counts=refusal_counts,
            degradation_counts=degradation_counts,
            cache_hit_count=cache_hit,
            cache_miss_count=cache_miss,
            cache_write_failed_count=cache_write_failed,
            approval_denied_count=approval_denied,
        )

    def reset(self) -> None:
        """Clear the ledger (for tests or session reset)."""
        self._entries.clear()

    @property
    def entry_count(self) -> int:
        return len(self._entries)


# ── Session-level singleton (temporary bridge) ──────────────────
# _active_ledger is a session-local desktop projection bridge.
# NOT a durable analytics store. Reset between sessions/forks.
# Future: SessionToolRuntimeLedger keyed by session_id.

_active_ledger: InMemoryToolRuntimeResultLedger | None = None


def get_active_ledger() -> InMemoryToolRuntimeResultLedger:
    """Return the active session ledger, creating one if needed."""
    global _active_ledger
    if _active_ledger is None:
        _active_ledger = InMemoryToolRuntimeResultLedger()
    return _active_ledger


def set_active_ledger(ledger: InMemoryToolRuntimeResultLedger) -> None:
    """Set the active session ledger (called by AgentLoop on init)."""
    global _active_ledger
    _active_ledger = ledger


def reset_active_ledger() -> None:
    """Reset the active ledger (called on session close/fork).

    Prevents cross-session result leakage.
    """
    global _active_ledger
    if _active_ledger is not None:
        _active_ledger.reset()
    _active_ledger = None
