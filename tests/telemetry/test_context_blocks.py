from __future__ import annotations

import json

from vibe.core.context.assembler import (
    build_context_assembly_report,
    plan_context_layout,
    write_assembly_report,
)
from vibe.core.telemetry.context_blocks import (
    ContextAssemblyReport,
    ContextBlockKind,
    ContextBlockStability,
    classify_block_stability,
    estimate_tokens,
    fingerprint_text,
)
from vibe.core.types import LLMMessage, Role


def test_token_estimate():
    text = "Hello world"  # 11 chars
    assert estimate_tokens(text) == 11 // 4


def test_fingerprint_stability():
    text = "stable content"
    f1 = fingerprint_text(text)
    f2 = fingerprint_text(text)
    assert f1 == f2
    assert f1.startswith("sha256:")
    assert len(f1) > 16  # Full fingerprint


def test_classify_block_stability():
    assert classify_block_stability(ContextBlockKind.SYSTEM_PROMPT) == (
        ContextBlockStability.STABLE,
        True,
    )
    assert classify_block_stability(ContextBlockKind.TOOL_EXCERPT) == (
        ContextBlockStability.EPHEMERAL,
        False,
    )


def test_build_context_assembly_report():
    session_id = "test-session"
    messages = [
        LLMMessage(role=Role.system, content="System prompt"),
        LLMMessage(role=Role.user, content="User question"),
        LLMMessage(
            role=Role.assistant,
            content="Assistant thought",
            tool_calls=[{"id": "c1", "function": {"name": "ls", "arguments": "{}"}}],
        ),
        LLMMessage(
            role=Role.tool, content="[TRUNCATED] output", tool_call_id="c1", name="ls"
        ),
    ]

    report = build_context_assembly_report(
        session_id=session_id, messages=messages, model="gpt-4"
    )

    assert report.session_id == session_id
    assert report.total_bytes > 0
    assert len(report.blocks) >= 4

    # Check block kinds
    kinds = [b.kind for b in report.blocks]
    assert ContextBlockKind.SYSTEM_PROMPT in kinds
    assert ContextBlockKind.CONVERSATION_TAIL in kinds
    assert ContextBlockKind.ARTIFACT_REFERENCE in kinds

    # Verify source_index
    for b in report.blocks:
        assert b.source_index is not None


def test_write_assembly_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    report = build_context_assembly_report(
        session_id="session-1", messages=[LLMMessage(role=Role.system, content="test")]
    )

    import asyncio

    path = asyncio.run(write_assembly_report(report))

    assert path.exists()
    content = json.loads(path.read_text())
    assert content["report_id"] == report.report_id
    assert len(content["blocks"]) == 1


def test_plan_context_layout_prefix_stability():
    session_id = "layout-test"

    # Base report
    report1 = build_context_assembly_report(
        session_id=session_id,
        messages=[
            LLMMessage(role=Role.system, content="System Instruction"),
            LLMMessage(role=Role.user, content="Dynamic Q1"),
        ],
    )
    plan1 = plan_context_layout(report1)
    fp1 = plan1.stable_prefix_fingerprint
    assert len(fp1) == 71  # sha256: + 64 chars

    # Change user content (dynamic suffix), stable prefix MUST NOT change
    report2 = build_context_assembly_report(
        session_id=session_id,
        messages=[
            LLMMessage(role=Role.system, content="System Instruction"),
            LLMMessage(role=Role.user, content="Different dynamic question"),
        ],
    )
    plan2 = plan_context_layout(report2, previous_layout=plan1)
    assert plan2.stable_prefix_fingerprint == fp1
    assert plan2.prefix_stability_status == "stable"

    # Change system content, stable prefix MUST change
    report3 = build_context_assembly_report(
        session_id=session_id,
        messages=[LLMMessage(role=Role.system, content="Changed Instruction")],
    )
    plan3 = plan_context_layout(report3, previous_layout=plan2)
    assert plan3.stable_prefix_fingerprint != fp1
    assert plan3.prefix_stability_status == "changed"


def test_deterministic_layout_across_shuffled_inputs():
    session_id = "shuffled-test"

    msg_system = LLMMessage(role=Role.system, content="System")
    msg_user = LLMMessage(role=Role.user, content="User")

    report1 = build_context_assembly_report(
        session_id=session_id, messages=[msg_system, msg_user]
    )
    plan1 = plan_context_layout(report1)

    # Shuffle input blocks in a manual report construction to test planner sorting
    report2 = build_context_assembly_report(
        session_id=session_id, messages=[msg_system, msg_user]
    )
    # Force out-of-order blocks in the report
    report2.blocks = list(reversed(report1.blocks))

    plan2 = plan_context_layout(report2)

    # Fingerprints and block order must match regardless of input list order
    assert plan1.stable_prefix_fingerprint == plan2.stable_prefix_fingerprint
    assert plan1.dynamic_suffix_fingerprint == plan2.dynamic_suffix_fingerprint
    assert plan1.stable_prefix_block_ids == plan2.stable_prefix_block_ids


def test_prefix_stability_with_different_block_ids():
    """Identical content must produce identical prefix fingerprint even if block IDs differ."""
    session_id = "uuid-test"

    report1 = build_context_assembly_report(
        session_id=session_id, messages=[LLMMessage(role=Role.system, content="System")]
    )
    plan1 = plan_context_layout(report1)

    report2 = build_context_assembly_report(
        session_id=session_id, messages=[LLMMessage(role=Role.system, content="System")]
    )
    # Ensure block IDs are different
    for b1, b2 in zip(report1.blocks, report2.blocks, strict=True):
        b2.block_id = "different-uuid"
        assert b1.block_id != b2.block_id

    plan2 = plan_context_layout(report2)
    assert plan1.stable_prefix_fingerprint == plan2.stable_prefix_fingerprint


def test_deterministic_sorting_by_source_index():
    """Verify that source_index is used for ordering when stability and kind match."""
    from vibe.core.telemetry.context_blocks import ContextBlock

    b1 = ContextBlock(
        kind=ContextBlockKind.SYSTEM_PROMPT,
        stability=ContextBlockStability.STABLE,
        cacheable=True,
        content="First",
        source_index=0,
    )
    b2 = ContextBlock(
        kind=ContextBlockKind.SYSTEM_PROMPT,
        stability=ContextBlockStability.STABLE,
        cacheable=True,
        content="Second",
        source_index=1,
    )

    report = ContextAssemblyReport(
        session_id="sort-test",
        blocks=[b2, b1],  # Out of order
        total_bytes=0,
        total_estimated_tokens=0,
        stable_prefix_bytes=0,
        dynamic_suffix_bytes=0,
        cache_candidate_bytes=0,
        largest_blocks=[],
        optimization_hints=[],
    )

    plan = plan_context_layout(report)
    # b1 (source_index 0) must come before b2 (source_index 1)
    assert plan.stable_prefix_block_ids == [b1.block_id, b2.block_id]


def test_observability_event_privacy():
    """Ensure that the layout plan does not include full block content."""
    report = build_context_assembly_report(
        session_id="privacy-test",
        messages=[LLMMessage(role=Role.system, content="SECRET_KEY_12345")],
    )
    plan = plan_context_layout(report)

    # Convert to dict as it would be serialized for telemetry
    data = plan.model_dump()
    dumped = json.dumps(data)

    assert "SECRET_KEY_12345" not in dumped
    # Fingerprint should be present but not the content
    assert plan.stable_prefix_fingerprint.startswith("sha256:")
