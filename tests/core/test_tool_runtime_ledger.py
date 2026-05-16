"""Tests for ToolRuntime result ledger."""

from __future__ import annotations

import json

from rig_relay.core.tool_runtime_ledger import (
    InMemoryToolRuntimeResultLedger,
    ToolRuntimeLedgerEntry,
    get_active_ledger,
    set_active_ledger,
)
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeApprovalStatus,
    ToolRuntimeCacheStatus,
    ToolRuntimeRefusal,
    ToolRuntimeResult,
    ToolRuntimeStatus,
)


def _completed_result(tool_name: str = "read_file", duration_ms: float = 2.0) -> ToolRuntimeResult:
    return ToolRuntimeResult.completed(
        tool_name=tool_name,
        tool_call_id="c1",
        provider_tool_response={"output": "ok"},
        cache_status=ToolRuntimeCacheStatus.HIT,
        duration_ms=duration_ms,
    )


def _refused_result() -> ToolRuntimeResult:
    return ToolRuntimeResult.refused(
        tool_name="bash",
        tool_call_id="c2",
        refusal=ToolRuntimeRefusal(
            refusal_code=RefusalCode.APPROVAL_DENIED,
            message="User denied",
            recoverable=True,
        ),
        approval_status=ToolRuntimeApprovalStatus.DENIED,
    )


def _degraded_result() -> ToolRuntimeResult:
    return ToolRuntimeResult(
        status=ToolRuntimeStatus.DEGRADED,
        tool_name="search_replace",
        tool_call_id="c3",
        cache_status=ToolRuntimeCacheStatus.WRITE_FAILED,
        approval_status=ToolRuntimeApprovalStatus.APPROVED,
        degraded_capabilities=["cache_write_failed"],
        duration_ms=12.3,
    )


def _failed_result() -> ToolRuntimeResult:
    return ToolRuntimeResult.failed(
        tool_name="bash",
        tool_call_id="c4",
        error_kind="tool_invocation_failed",
        error_message="command not found",
    )


class TestLedgerEntry:
    def test_from_result_completed(self):
        entry = ToolRuntimeLedgerEntry.from_result(_completed_result())
        assert entry.status == "completed"
        assert entry.cache_status == "hit"
        assert entry.tool_name == "read_file"
        assert entry.duration_ms == 2.0
        assert entry.refusal_code is None

    def test_from_result_refused(self):
        entry = ToolRuntimeLedgerEntry.from_result(_refused_result())
        assert entry.status == "refused"
        assert entry.refusal_code == "approval_denied"

    def test_from_result_degraded(self):
        entry = ToolRuntimeLedgerEntry.from_result(_degraded_result())
        assert entry.status == "degraded"
        assert "cache_write_failed" in entry.degraded_capabilities

    def test_from_result_failed(self):
        entry = ToolRuntimeLedgerEntry.from_result(_failed_result())
        assert entry.status == "failed"


class TestLedgerRecords:
    def test_record_completed(self):
        ledger = InMemoryToolRuntimeResultLedger()
        ledger.record(_completed_result())
        assert ledger.entry_count == 1

    def test_record_multiple(self):
        ledger = InMemoryToolRuntimeResultLedger()
        ledger.record(_completed_result())
        ledger.record(_refused_result())
        ledger.record(_degraded_result())
        ledger.record(_failed_result())
        assert ledger.entry_count == 4

    def test_reset_clears_all(self):
        ledger = InMemoryToolRuntimeResultLedger()
        ledger.record(_completed_result())
        ledger.record(_refused_result())
        ledger.reset()
        assert ledger.entry_count == 0


class TestSummary:
    def test_summary_counts(self):
        ledger = InMemoryToolRuntimeResultLedger()
        ledger.record(_completed_result())
        ledger.record(_completed_result(tool_name="grep", duration_ms=1.0))
        ledger.record(_refused_result())
        ledger.record(_degraded_result())
        ledger.record(_failed_result())

        s = ledger.build_summary()
        assert s.total_executions == 5
        assert s.completed_count == 2
        assert s.refused_count == 1
        assert s.degraded_count == 1
        assert s.failed_count == 1

    def test_summary_cache_counts(self):
        ledger = InMemoryToolRuntimeResultLedger()
        ledger.record(_completed_result())  # cache=hit
        ledger.record(ToolRuntimeResult.completed(
            tool_name="grep",
            tool_call_id="c5",
            cache_status=ToolRuntimeCacheStatus.MISS,
        ))
        ledger.record(_degraded_result())  # cache=write_failed

        s = ledger.build_summary()
        assert s.cache_hit_count == 1
        assert s.cache_miss_count == 1
        assert s.cache_write_failed_count == 1

    def test_summary_refusal_breakdown(self):
        ledger = InMemoryToolRuntimeResultLedger()
        ledger.record(_refused_result())
        s = ledger.build_summary()
        assert s.refusal_counts == {"approval_denied": 1}
        assert s.approval_denied_count == 1

    def test_summary_degradation_breakdown(self):
        ledger = InMemoryToolRuntimeResultLedger()
        ledger.record(_degraded_result())
        s = ledger.build_summary()
        assert s.degradation_counts == {"cache_write_failed": 1}

    def test_recent_results_capped(self):
        ledger = InMemoryToolRuntimeResultLedger()
        for i in range(15):
            ledger.record(_completed_result(
                tool_name=f"tool_{i}", duration_ms=float(i)
            ))
        s = ledger.build_summary(max_recent=10)
        assert len(s.recent_results) == 10
        assert s.recent_results[-1].tool_name == "tool_14"

    def test_summary_is_json_safe(self):
        ledger = InMemoryToolRuntimeResultLedger()
        ledger.record(_completed_result())
        ledger.record(_refused_result())
        s = ledger.build_summary()
        d = s.model_dump(mode="json")
        json.dumps(d)


class TestSingletonAccess:
    def test_get_active_creates_default(self):
        set_active_ledger(None)
        # Reset global
        import rig_relay.core.tool_runtime_ledger as mod
        mod._active_ledger = None
        ledger = get_active_ledger()
        assert ledger is not None
        assert isinstance(ledger, InMemoryToolRuntimeResultLedger)

    def test_set_and_get_active(self):
        ledger = InMemoryToolRuntimeResultLedger()
        ledger.record(_completed_result())
        set_active_ledger(ledger)
        assert get_active_ledger() is ledger
        assert get_active_ledger().entry_count == 1


class TestArchitectureBoundaries:
    def test_ledger_does_not_import_forbidden_modules(self):
        import ast
        from pathlib import Path

        forbidden = (
            "rig_relay.desktop",
            "rig_relay.ralph",
            "rig_relay.scripts",
            "rig_relay.analytics",
            "rig_relay.reports.query",
            "rig_relay.bash.query",
            "duckdb",
        )
        path = (
            Path(__file__).resolve().parent.parent.parent
            / "rig_relay" / "core" / "tool_runtime_ledger.py"
        )
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for f in forbidden:
                        assert not alias.name.startswith(f), (
                            f"ledger imports {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                for f in forbidden:
                    assert not node.module.startswith(f), (
                        f"ledger imports {node.module}"
                    )


def test_ledger_reset_clears_entries():
    from rig_relay.core.tool_runtime_ledger import (
        InMemoryToolRuntimeResultLedger,
        set_active_ledger,
        get_active_ledger,
        reset_active_ledger,
    )
    from rig_relay.core.tool_runtime_models import ToolRuntimeResult, ToolRuntimeStatus, ToolRuntimeCacheStatus

    ledger = InMemoryToolRuntimeResultLedger()
    set_active_ledger(ledger)

    result = ToolRuntimeResult(
        tool_name="test_tool", tool_call_id="tc-1",
        status=ToolRuntimeStatus.COMPLETED,
        cache_status=ToolRuntimeCacheStatus.MISS,
    )
    ledger.record(result)
    assert ledger.entry_count == 1

    summary = ledger.build_summary()
    assert summary.total_executions == 1

    reset_active_ledger()
    new_ledger = get_active_ledger()
    assert new_ledger.entry_count == 0

    summary2 = new_ledger.build_summary()
    assert summary2.total_executions == 0


def test_cross_session_no_leakage():
    from rig_relay.core.tool_runtime_ledger import (
        set_active_ledger,
        get_active_ledger,
        reset_active_ledger,
    )
    from rig_relay.core.tool_runtime_models import ToolRuntimeResult, ToolRuntimeStatus, ToolRuntimeCacheStatus

    reset_active_ledger()
    ledger1 = get_active_ledger()
    result = ToolRuntimeResult(
        tool_name="session_a", tool_call_id="a-1",
        status=ToolRuntimeStatus.COMPLETED,
        cache_status=ToolRuntimeCacheStatus.MISS,
    )
    ledger1.record(result)
    assert ledger1.entry_count == 1

    reset_active_ledger()
    ledger2 = get_active_ledger()
    assert ledger2.entry_count == 0
    assert ledger2.build_summary().total_executions == 0


def test_singleton_documented_as_temporary():
    source = open("rig_relay/core/tool_runtime_ledger.py").read()
    assert "temporary bridge" in source or "not a durable" in source.lower()
    assert "reset_active_ledger" in source
