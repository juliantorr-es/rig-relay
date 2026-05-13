from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from vibe.core.telemetry.context_blocks import (
    ContextAssemblyReport,
    ContextBlock,
    ContextBlockKind,
    ContextBlockStability,
    ContextLayoutPlan,
    classify_block_stability,
    estimate_tokens,
    fingerprint_text,
)
from vibe.core.types import LLMMessage, Role

# Constants for optimization thresholds
HIGH_DYNAMIC_SUFFIX_THRESHOLD = 0.5
LOW_CACHEABILITY_THRESHOLD = 0.8


def plan_context_layout(
    report: ContextAssemblyReport, previous_layout: ContextLayoutPlan | None = None
) -> ContextLayoutPlan:
    """Produce a deterministic layout plan from a context assembly report."""

    # Deterministic block ordering rules:
    # 1. stable/semi-stable cacheable blocks go first (the stable prefix)
    # 2. dynamic blocks go after stable prefix (the dynamic suffix)
    # 3. ephemeral blocks go last (not cacheable)
    # Tie-breakers: stability, kind, source_index, fingerprint, byte_size
    def block_key(b: ContextBlock) -> tuple[int, str, int, str, int]:
        stability_map = {
            ContextBlockStability.STABLE: 0,
            ContextBlockStability.SEMI_STABLE: 1,
            ContextBlockStability.DYNAMIC: 2,
            ContextBlockStability.EPHEMERAL: 3,
        }
        # Use a high sentinel for missing source_index to keep them at the end of their group
        source_idx = b.source_index if b.source_index is not None else 1_000_000
        return (
            stability_map.get(b.stability, 99),
            str(b.kind),
            source_idx,
            b.fingerprint,
            b.byte_size,
        )

    sorted_blocks = sorted(report.blocks, key=block_key)

    stable_prefix_blocks = [
        b
        for b in sorted_blocks
        if b.stability
        in {ContextBlockStability.STABLE, ContextBlockStability.SEMI_STABLE}
        and b.cacheable
    ]
    dynamic_suffix_blocks = [
        b
        for b in sorted_blocks
        if b.stability == ContextBlockStability.DYNAMIC
        or (
            b.stability
            in {ContextBlockStability.STABLE, ContextBlockStability.SEMI_STABLE}
            and not b.cacheable
        )
    ]
    ephemeral_blocks = [
        b for b in sorted_blocks if b.stability == ContextBlockStability.EPHEMERAL
    ]

    stable_prefix_ids = [b.block_id for b in stable_prefix_blocks]
    dynamic_suffix_ids = [b.block_id for b in dynamic_suffix_blocks]
    ephemeral_ids = [b.block_id for b in ephemeral_blocks]

    # Fingerprints must be computed from ordered block fingerprints
    stable_prefix_fp = fingerprint_text(
        "".join(b.fingerprint for b in stable_prefix_blocks)
    )
    dynamic_suffix_fp = fingerprint_text(
        "".join(b.fingerprint for b in dynamic_suffix_blocks)
    )

    stable_prefix_bytes = sum(b.byte_size for b in stable_prefix_blocks)
    dynamic_suffix_bytes = sum(b.byte_size for b in dynamic_suffix_blocks)
    ephemeral_bytes = sum(b.byte_size for b in ephemeral_blocks)

    cache_candidate_bytes = sum(b.byte_size for b in sorted_blocks if b.cacheable)
    total_bytes = sum(b.byte_size for b in sorted_blocks)
    cacheability_ratio = cache_candidate_bytes / total_bytes if total_bytes > 0 else 0.0

    # Prefix stability comparison (using full fingerprints)
    stability_status: Literal["stable", "changed", "unknown"] = "unknown"
    change_reasons = []

    if previous_layout:
        if previous_layout.stable_prefix_fingerprint == stable_prefix_fp:
            stability_status = "stable"
        else:
            stability_status = "changed"
            change_reasons.append("Stable prefix fingerprint changed")
            if len(previous_layout.stable_prefix_block_ids) != len(stable_prefix_ids):
                change_reasons.append("Stable block count changed")

    hints = []
    if stability_status == "changed":
        hints.append("Stable prefix changed; provider cache hit may be lost.")
    if cacheability_ratio < LOW_CACHEABILITY_THRESHOLD:
        hints.append(
            "Low cacheability ratio; consider moving more content to stable blocks."
        )

    return ContextLayoutPlan(
        session_id=report.session_id,
        stable_prefix_block_ids=stable_prefix_ids,
        dynamic_suffix_block_ids=dynamic_suffix_ids,
        ephemeral_block_ids=ephemeral_ids,
        stable_prefix_fingerprint=stable_prefix_fp,
        dynamic_suffix_fingerprint=dynamic_suffix_fp,
        stable_prefix_fingerprint_short=stable_prefix_fp[:16],
        dynamic_suffix_fingerprint_short=dynamic_suffix_fp[:16],
        stable_prefix_bytes=stable_prefix_bytes,
        dynamic_suffix_bytes=dynamic_suffix_bytes,
        ephemeral_bytes=ephemeral_bytes,
        cache_candidate_bytes=cache_candidate_bytes,
        cacheability_ratio=cacheability_ratio,
        prefix_stability_status=stability_status,
        prefix_change_reasons=change_reasons,
        optimization_hints=hints,
    )


async def load_latest_layout(session_id: str) -> ContextLayoutPlan | None:
    """Read the latest previous layout JSON for the same session if one exists."""
    report_dir = Path(".rig") / "relay" / "sessions" / session_id / "context"
    if not report_dir.exists():
        return None

    layouts = sorted(
        report_dir.glob("layout_*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not layouts:
        return None

    try:
        content = layouts[0].read_text(encoding="utf-8")
        return ContextLayoutPlan.model_validate_json(content)
    except Exception:
        return None


async def write_layout_plan(plan: ContextLayoutPlan) -> Path:
    """Write the layout plan to the session directory."""
    report_dir = Path(".rig") / "relay" / "sessions" / plan.session_id / "context"
    report_dir.mkdir(parents=True, exist_ok=True)

    path = report_dir / f"layout_{plan.layout_id[:8]}.json"

    # Atomic write with deterministic JSON
    temp_path = path.with_suffix(".tmp")
    try:
        content = plan.model_dump_json(indent=2)
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return path


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
    for i, msg in enumerate(messages):
        if msg.role == Role.system:
            kind = ContextBlockKind.SYSTEM_PROMPT
            stability, cacheable = classify_block_stability(kind)
            content = msg.content or ""
            blocks.append(
                _make_block(kind, stability, cacheable, content, source_index=i)
            )

    if tool_manager_info:
        # If we have tool schema info, record it as a stable block
        schemas = json.dumps(tool_manager_info, sort_keys=True)
        kind = ContextBlockKind.TOOL_SCHEMA
        stability, cacheable = classify_block_stability(kind)
        blocks.append(_make_block(kind, stability, cacheable, schemas, source_index=-1))

    # 2. Conversation & Tool Results
    for i, msg in enumerate(messages):
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
            content += "\n" + json.dumps(
                [tc.model_dump() for tc in msg.tool_calls], sort_keys=True
            )

        blocks.append(_make_block(kind, stability, cacheable, content, source_index=i))

    # 3. Aggregates
    total_bytes = sum(b.byte_size for b in blocks)
    total_tokens = sum(b.estimated_tokens for b in blocks)

    cache_candidate_bytes = sum(b.byte_size for b in blocks if b.cacheable)
    stable_blocks = [b for b in blocks if b.stability in {"stable", "semi_stable"}]
    dynamic_blocks = [b for b in blocks if b.stability not in {"stable", "semi_stable"}]

    stable_prefix_bytes = sum(b.byte_size for b in stable_blocks)
    dynamic_suffix_bytes = sum(b.byte_size for b in dynamic_blocks)

    stable_prefix_fingerprint = fingerprint_text(
        "".join(b.fingerprint for b in stable_blocks)
    )
    dynamic_suffix_fingerprint = fingerprint_text(
        "".join(b.fingerprint for b in dynamic_blocks)
    )

    # Largest blocks
    sorted_blocks = sorted(blocks, key=lambda b: b.byte_size, reverse=True)
    largest_blocks = [
        {"kind": b.kind, "size": b.byte_size, "tokens": b.estimated_tokens}
        for b in sorted_blocks[:5]
    ]

    # Optimization hints
    hints = []
    if dynamic_suffix_bytes > HIGH_DYNAMIC_SUFFIX_THRESHOLD * total_bytes:
        hints.append(
            "High dynamic suffix volume; consider moving stable summaries to the prefix."
        )

    cacheability_ratio = cache_candidate_bytes / total_bytes if total_bytes > 0 else 0.0
    if cacheability_ratio < LOW_CACHEABILITY_THRESHOLD:
        hints.append(
            "Low cacheability; check if large tool results can be artifacted or moved to semi-stable blocks."
        )

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
    kind: ContextBlockKind,
    stability: Any,
    cacheable: bool,
    content: str,
    source_index: int | None = None,
) -> ContextBlock:
    return ContextBlock(
        kind=kind,
        stability=stability,
        cacheable=cacheable,
        content=content,
        byte_size=len(content.encode("utf-8")),
        estimated_tokens=estimate_tokens(content),
        fingerprint=fingerprint_text(content),
        source_index=source_index,
    )
