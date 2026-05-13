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
from vibe.core.context.assembler import build_context_assembly_report, write_assembly_report
from vibe.core.types import LLMMessage, Role

def test_token_estimate():
    text = "Hello world" # 11 chars
    assert estimate_tokens(text) == 11 // 4

def test_fingerprint_stability():
    text = "stable content"
    f1 = fingerprint_text(text)
    f2 = fingerprint_text(text)
    assert f1 == f2
    assert f1.startswith("sha256:")

def test_classify_block_stability():
    assert classify_block_stability(ContextBlockKind.SYSTEM_PROMPT) == (ContextBlockStability.STABLE, True)
    assert classify_block_stability(ContextBlockKind.TOOL_EXCERPT) == (ContextBlockStability.EPHEMERAL, False)

def test_build_context_assembly_report():
    session_id = "test-session"
    messages = [
        LLMMessage(role=Role.system, content="System prompt"),
        LLMMessage(role=Role.user, content="User question"),
        LLMMessage(role=Role.assistant, content="Assistant thought", tool_calls=[{"id": "c1", "function": {"name": "ls", "arguments": "{}"}}]),
        LLMMessage(role=Role.tool, content="[TRUNCATED] output", tool_call_id="c1", name="ls"),
    ]
    
    report = build_context_assembly_report(
        session_id=session_id,
        messages=messages,
        model="gpt-4",
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
        session_id="session-1",
        messages=[LLMMessage(role=Role.system, content="test")],
    )
    
    import asyncio
    path = asyncio.run(write_assembly_report(report))
    
    assert path.exists()
    content = json.loads(path.read_text())
    assert content["report_id"] == report.report_id
    assert len(content["blocks"]) == 1
