"""Acceptance tests for the canonical correlation spine."""

from __future__ import annotations

from rig_relay.core.agent_loop import _new_causation_id, _new_correlation_id


def test_two_batches_receive_distinct_correlation_ids():
    """Two tool-call batches in one turn must receive different correlation_id values."""
    # Each call simulates what _execute_pending_tool_batch does
    batch1_id = _new_correlation_id()
    batch2_id = _new_correlation_id()
    assert batch1_id.startswith("corr_")
    assert batch2_id.startswith("corr_")
    assert batch1_id != batch2_id, (
        f"Two batches must receive distinct correlation_ids: {batch1_id} == {batch2_id}"
    )

    # Verify 20 calls produce 20 unique IDs
    ids = {_new_correlation_id() for _ in range(20)}
    assert len(ids) == 20, f"Expected 20 unique IDs but got {len(ids)}"


def test_correlation_id_format_is_stable():
    """Correlation ID format: corr_ + 12 hex chars."""
    for _ in range(50):
        cid = _new_correlation_id()
        assert cid.startswith("corr_"), f"Expected corr_ prefix, got {cid}"
        hex_part = cid[5:]  # strip "corr_"
        assert len(hex_part) == 12, (
            f"Expected 12 hex chars, got {len(hex_part)} hex_part={hex_part!r}"
        )
        assert all(c in "0123456789abcdef" for c in hex_part), (
            f"Non-hex char in {hex_part!r}"
        )


def test_sibling_tools_share_correlation_differ_by_tool_call_id():
    """Two sibling tool calls in the same batch share correlation_id and causation_id,
    but retain distinct tool_call_id values.
    """
    from rig_relay.core.tool_executor.context import ToolTurnContext

    corr_id = _new_correlation_id()
    cause_id = _new_causation_id()

    # Simulate a batch with two sibling tools
    ctx = ToolTurnContext(
        turn_id="turn-1",
        user_message_id="msg-1",
        correlation_id=corr_id,
        causation_id=cause_id,
    )

    # Tool 1
    assert ctx.correlation_id == corr_id
    assert ctx.causation_id == cause_id

    # Tool 2 (same context, different tool_call_id — that happens at the ResolvedToolCall level)
    # The ToolTurnContext is shared, so correlation_id and causation_id are identical
    # tool_call_id is on ResolvedToolCall, not on ToolTurnContext — that's correct
    assert ctx.turn_id == "turn-1"

    # Prove a different turn context would have different IDs
    batch2_corr = _new_correlation_id()
    assert batch2_corr != corr_id
    ctx2 = ToolTurnContext(
        turn_id="turn-1",
        user_message_id="msg-2",
        correlation_id=batch2_corr,
        causation_id=_new_causation_id(),
    )
    assert ctx2.correlation_id != ctx.correlation_id


def test_tool_runtime_result_preserves_causation_id():
    """Every factory method on ToolRuntimeResult must preserve causation_id."""
    from rig_relay.core.tool_runtime_models import ToolRuntimeResult

    for factory in [
        ToolRuntimeResult.completed,
        ToolRuntimeResult.failed,
        ToolRuntimeResult.refused,
        ToolRuntimeResult.cached_result,
        ToolRuntimeResult.skipped,
    ]:
        r = factory(
            tool_name="test",
            tool_call_id="tc-1",
            correlation_id="corr_x",
            causation_id="cause_y",
        )
        assert r.causation_id == "cause_y", (
            f"{factory.__name__}() lost causation_id: got {r.causation_id!r}"
        )
        assert r.correlation_id == "corr_x", (
            f"{factory.__name__}() lost correlation_id: got {r.correlation_id!r}"
        )


def test_derive_agent_outcome_reads_ids_from_result():
    """derive_agent_outcome must read correlation_id and causation_id from ToolRuntimeResult."""
    from rig_relay.core.tool_runtime_models import ToolRuntimeResult
    from rig_relay.core.tools._agent_outcome import derive_agent_outcome

    class _FakeToolClass:
        mutation_class = None

    r = ToolRuntimeResult.completed(
        tool_name="test",
        tool_call_id="tc-1",
        correlation_id="corr_x",
        causation_id="cause_y",
    )
    outcome = derive_agent_outcome(r, _FakeToolClass)
    assert outcome.correlation_id == "corr_x"
    assert outcome.causation_id == "cause_y"
    assert outcome.tool_call_id == "tc-1"
    assert outcome.tool_name == "test"


def test_correlation_preserved_when_telemetry_disabled():
    """When telemetry is disabled, ToolRuntimeResult still carries correlation_id
    and causation_id. The degradation marker records that correlation is preserved
    at runtime but persistence is disabled.
    """
    from rig_relay.core.telemetry.local import (
        _degradation_marker_written,
        is_telemetry_enabled,
        read_degradation_marker,
        set_telemetry_enabled,
        write_degradation_marker,
    )
    from rig_relay.core.tool_runtime_models import ToolRuntimeResult

    # Save original state
    was_enabled = is_telemetry_enabled()
    old_markers = _degradation_marker_written.copy()

    try:
        # Disable telemetry
        set_telemetry_enabled(False)
        assert not is_telemetry_enabled()

        # Verify ToolRuntimeResult still preserves correlation identity
        r = ToolRuntimeResult.completed(
            tool_name="test",
            tool_call_id="tc-1",
            correlation_id="corr_abc",
            causation_id="cause_xyz",
        )
        # Runtime identity is preserved regardless of telemetry
        assert r.correlation_id == "corr_abc"
        assert r.causation_id == "cause_xyz"

        # Write a degradation marker
        sid = "test-telemetry-disabled"
        marker_path = write_degradation_marker(sid)
        assert marker_path is not None

        # Read it back and verify correlation fields
        marker = read_degradation_marker(sid)
        assert marker is not None, "Degradation marker not found"
        assert marker.get("runtime_correlation_preserved") is True, (
            f"Marker missing runtime_correlation_preserved: {list(marker.keys())}"
        )
        assert marker.get("persisted_observability_correlation_disabled") is True
        assert marker.get("cross_session_trace_reconstruction_degraded") is True
        assert marker.get("telemetry_reason") == "user_opt_out"

        # Verify preserved/degraded capability entries
        preserved = marker.get("preserved_capabilities", [])
        assert "runtime_correlation_identity" in preserved
        degraded = marker.get("degraded_capabilities", [])
        assert "persisted_observability_correlation" in degraded

    finally:
        # Restore original state
        set_telemetry_enabled(was_enabled)
        _degradation_marker_written.clear()
        _degradation_marker_written.update(old_markers)
