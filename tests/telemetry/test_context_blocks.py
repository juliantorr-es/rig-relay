from __future__ import annotations

import json
from pathlib import Path
from vibe.core.telemetry.context_blocks import (
    ContextBlock,
    ContextBlockKind,
    ContextBlockStability,
    classify_block_stability,
    estimate_tokens,
    fingerprint_text,
)
from vibe.core.context.assembler import (
    build_context_assembly_report,
    write_assembly_report,
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

    # Verify stable prefix vs dynamic suffix
    assert report.stable_prefix_bytes > 0
    assert report.dynamic_suffix_bytes > 0
    assert report.stable_prefix_fingerprint.startswith("sha256:")


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

def test_plan_context_layout():
    session_id = "layout-test"
    report = build_context_assembly_report(
        session_id=session_id,
        messages=[
            LLMMessage(role=Role.system, content="System"),
            LLMMessage(role=Role.user, content="Dynamic User Msg"),
        ],
    )
    
    plan = plan_context_layout(report)
    assert plan.session_id == session_id
    assert plan.prefix_stability_status == "unknown"
    assert len(plan.stable_prefix_block_ids) == 1 # System prompt
    assert len(plan.dynamic_suffix_block_ids) == 1 # User msg
    
    # Deterministic fingerprint check
    fp1 = plan.stable_prefix_fingerprint
    
    # Change dynamic content, stable prefix should remain same
    report2 = build_context_assembly_report(
        session_id=session_id,
        messages=[
            LLMMessage(role=Role.system, content="System"),
            LLMMessage(role=Role.user, content="Different Dynamic Msg"),
        ],
    )
    plan2 = plan_context_layout(report2, previous_layout=plan)
    assert plan2.stable_prefix_fingerprint == fp1
    assert plan2.prefix_stability_status == "stable"
    
    # Change system content, stable prefix should change
    report3 = build_context_assembly_report(
        session_id=session_id,
        messages=[
            LLMMessage(role=Role.system, content="Changed System"),
        ],
    )
    plan3 = plan_context_layout(report3, previous_layout=plan2)
    assert plan3.stable_prefix_fingerprint != fp1
    assert plan3.prefix_stability_status == "changed"

def test_deterministic_block_ordering():
    from vibe.core.telemetry.context_blocks import ContextBlock, ContextBlockStability
    session_id = "order-test"
    
    b_stable = ContextBlock(kind=ContextBlockKind.SYSTEM_PROMPT, stability=ContextBlockStability.STABLE, cacheable=True, content="A", byte_size=1, estimated_tokens=1, fingerprint="fA")
    b_dynamic = ContextBlock(kind=ContextBlockKind.CONVERSATION_TAIL, stability=ContextBlockStability.DYNAMIC, cacheable=False, content="B", byte_size=1, estimated_tokens=1, fingerprint="fB")
    
    from vibe.core.telemetry.context_blocks import ContextAssemblyReport
    report = ContextAssemblyReport(
        session_id=session_id,
        blocks=[b_dynamic, b_stable], # Out of order
        stable_prefix_fingerprint="",
        dynamic_suffix_fingerprint="",
        total_bytes=2,
        total_estimated_tokens=2,
        stable_prefix_bytes=1,
        dynamic_suffix_bytes=1,
        cache_candidate_bytes=1,
        largest_blocks=[],
        optimization_hints=[],
    )
    
    plan = plan_context_layout(report)
    # Stable should be first
    assert plan.stable_prefix_block_ids[0] == b_stable.block_id
    assert plan.dynamic_suffix_block_ids[0] == b_dynamic.block_id
