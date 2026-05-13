from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vibe.core.telemetry.artifacts import get_artifact_dir
from vibe.core.telemetry.context_blocks import (
    ContextAssemblyReport,
    ContextBlock,
    ContextBlockKind,
    classify_block_stability,
    estimate_tokens,
    fingerprint_text,
)
from vibe.core.types import LLMMessage, Role


def build_context_assembly_report(
    session_id: str,
    messages: list[LLMMessage],
    model: str | None = None,
    entrypoint: str | None = None,
    tool_manager_info: dict[str, Any] | None = None,
) -> ContextAssemblyReport:
    """Build an observational context assembly report from the current message list.
    
    This function does NOT modify the messages. It only reports on how they would
    be structured into blocks.
    """
    blocks: list[ContextBlock] = []
    
    # 1. System Prompt & Tool Schemas
    for msg in messages:
        if msg.role == Role.system:
            kind = ContextBlockKind.SYSTEM_PROMPT
            stability, cacheable = classify_block_stability(kind)
            content = msg.content or ""
            blocks.append(_make_block(kind, stability, cacheable, content))
            
    if tool_manager_info:
        # If we have tool schema info, record it as a stable block
        schemas = json.dumps(tool_manager_info, sort_keys=True)
        kind = ContextBlockKind.TOOL_SCHEMA
        stability, cacheable = classify_block_stability(kind)
        blocks.append(_make_block(kind, stability, cacheable, schemas))

    # 2. Conversation & Tool Results
    artifact_root = get_artifact_dir(session_id)
    
    for msg in messages:
        if msg.role == Role.system:
            continue
            
        kind = ContextBlockKind.CONVERSATION_TAIL
        if msg.role == Role.tool:
            kind = ContextBlockKind.TOOL_EXCERPT
            # Check for artifact references in the content
            if "[TRUNCATED]" in (msg.content or ""):
                kind = ContextBlockKind.ARTIFACT_REFERENCE
        
        stability, cacheable = classify_block_stability(kind)
        content = msg.content or ""
        
        # Add tool calls info if present (from assistant role)
        if msg.tool_calls:
            content += "\n" + json.dumps([tc.model_dump() for tc in msg.tool_calls], sort_keys=True)
            
        blocks.append(_make_block(kind, stability, cacheable, content))

    # 3. Aggregates
    total_bytes = sum(b.byte_size for b in blocks)
    total_tokens = sum(b.estimated_tokens for b in blocks)
    
    stable_blocks = [b for b in blocks if b.stability in ("stable", "semi_stable")]
    dynamic_blocks = [b for b in blocks if b.stability not in ("stable", "semi_stable")]
    
    stable_prefix_bytes = sum(b.byte_size for b in stable_blocks)
    dynamic_suffix_bytes = sum(b.byte_size for b in dynamic_blocks)
    cache_candidate_bytes = sum(b.byte_size for b in blocks if b.cacheable)
    
    stable_prefix_fingerprint = fingerprint_text("".join(b.fingerprint for b in stable_blocks))
    dynamic_suffix_fingerprint = fingerprint_text("".join(b.fingerprint for b in dynamic_blocks))
    
    # Largest blocks
    sorted_blocks = sorted(blocks, key=lambda b: b.byte_size, reverse=True)
    largest_blocks = [
        {"kind": b.kind, "size": b.byte_size, "tokens": b.estimated_tokens}
        for b in sorted_blocks[:5]
    ]
    
    # Optimization hints
    hints = []
    if dynamic_suffix_bytes > 0.5 * total_bytes:
        hints.append("High dynamic suffix volume; consider moving stable summaries to the prefix.")
    if cache_candidate_bytes < 0.8 * total_bytes:
        hints.append("Low cacheability; check if large tool results can be artifacted or moved to semi-stable blocks.")

    return ContextAssemblyReport(
        session_id=session_id,
        entrypoint=entrypoint,
        model=model,
        blocks=blocks,
        stable_prefix_fingerprint=stable_prefix_fingerprint,
        dynamic_suffix_fingerprint=dynamic_suffix_fingerprint,
        total_bytes=total_bytes,
        total_estimated_tokens=total_tokens,
        stable_prefix_bytes=stable_prefix_bytes,
        dynamic_suffix_bytes=dynamic_suffix_bytes,
        cache_candidate_bytes=cache_candidate_bytes,
        largest_blocks=largest_blocks,
        optimization_hints=hints,
    )


def _make_block(
    kind: ContextBlockKind, stability: Any, cacheable: bool, content: str
) -> ContextBlock:
    return ContextBlock(
        kind=kind,
        stability=stability,
        cacheable=cacheable,
        content=content,
        byte_size=len(content.encode("utf-8")),
        estimated_tokens=estimate_tokens(content),
        fingerprint=fingerprint_text(content),
    )


async def write_assembly_report(report: ContextAssemblyReport) -> Path:
    """Write the full context assembly report to the session directory."""
    report_dir = Path(".rig") / "relay" / "sessions" / report.session_id / "context"
    report_dir.mkdir(parents=True, exist_ok=True)
    
    path = report_dir / f"assembly_{report.report_id[:8]}.json"
    
    # Atomic write with deterministic JSON
    temp_path = path.with_suffix(".tmp")
    try:
        content = report.model_dump_json(indent=2)
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
            
    return path
