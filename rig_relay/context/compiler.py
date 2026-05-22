"""Context compiler — the core logic for rig.get_context.

Takes a ContextRequest, builds a ContextPacket by composing repo_map,
work_map, and optional receipt/symbol scans. Produces structured output,
hash-stable receipts, and content-light metadata.

This is the front door for the rig.get_context built-in tool.

The ``execute()`` function delegates to ``ContextRuntime`` from
``rig_relay.compiler.context.runtime`` for mode dispatch. The
function signature is preserved for backward compatibility.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from rig_relay.compiler.context.runtime import ContextRuntime
from rig_relay.context.models import (
    ContextEnvelopeReceipt,
    ContextPacket,
    ContextReceipt,
    ContextRequest,
    PathRecommendation,
)
from rig_relay.context.renderer import ContextRenderer
from rig_relay.context.repo_index import RepoContextIndex
from rig_relay.context.repo_map import build_repo_info
from rig_relay.context.warnings import (
    ContextWarningCode,
    build_warning,
    exception_class_name,
)
from rig_relay.context.work_map import build_active_work
from rig_relay.tracing.golden_path import build_golden_path_event
from rig_relay.tracing.store import get_default_trace_store


def _emit_context_trace(
    event_type: str, *, session_id: str = "", payload: dict[str, Any] | None = None
) -> None:
    """Emit a content-light context assembly trace event. Non-fatal on error."""
    try:
        store = get_default_trace_store()
        event = build_golden_path_event(
            event_type=event_type,
            correlation={"session_id": session_id},
            payload=payload or {},
        )
        store.write(event)
    except Exception:
        pass


# Singleton ContextRuntime (lazy, for backward-compatible module-level execute)
_runtime: ContextRuntime | None = None


def _get_runtime() -> ContextRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ContextRuntime()
    return _runtime


class ContextCompiler:
    """Builds prompt envelopes from workspace state for the agent loop.

    Constructs a ContextEnvelopeReceipt with a rendered system prompt
    containing repo topology, dirty state, collision warnings, and
    relevant receipts. Plugs into AgentLoop._build_context_envelope().
    """

    def __init__(
        self,
        *,
        session_id: str,
        workspace_root: Path | None = None,
        receipt_store: Any | None = None,
        repo_index: RepoContextIndex | None = None,
    ) -> None:
        self._session_id = session_id
        self._workspace_root = (workspace_root or Path.cwd()).resolve()
        self._receipt_store = receipt_store
        self._repo_index = repo_index

    def build_envelope(
        self,
        user_text: str = "",
        snapshot: Any | None = None,
        messages: list[Any] | None = None,
    ) -> ContextEnvelopeReceipt:
        """Build a context envelope using the cache-aware renderer."""
        _emit_context_trace(
            "context.assembly.started",
            session_id=self._session_id,
            payload={
                "has_user_text": bool(user_text),
                "has_snapshot": snapshot is not None,
                "has_messages": bool(messages),
            },
        )
        renderer = ContextRenderer(workspace_root=self._workspace_root)
        dirty_count = 0
        collision_count = 0

        try:
            repo = build_repo_info(self._workspace_root)
            head = repo.head or "unknown"
            branch = repo.branch or "unknown"
            dirty_summary = getattr(repo, "dirty_summary", {}) or {}
            dirty_count = dirty_summary.get("modified", 0)

            renderer.add_repo_section(
                root=str(self._workspace_root),
                branch=branch,
                head=head,
                modified=dirty_summary.get("modified", 0),
                untracked=dirty_summary.get("untracked", 0),
                staged=dirty_summary.get("staged", 0),
            )

            if snapshot is not None:
                renderer.add_snapshot_section(str(snapshot))

            active = build_active_work(self._workspace_root, [])
            lanes = active.get("lanes", [])
            collisions = active.get("collision_warnings", [])
            collision_count = len(collisions)

            renderer.add_active_work_section(
                lane_count=len(lanes) if lanes else 0,
                collision_count=collision_count,
                collision_paths=[c.get("path", "") for c in collisions]
                if collisions
                else None,
            )

            renderer.add_recent_messages_section(messages)

        except Exception as e:
            renderer.add_warning(
                build_warning(
                    ContextWarningCode.REPO_SCAN_FAILED,
                    detail=f"{exception_class_name(e)}: context build partial",
                    source="compiler.build_envelope",
                )
            )

        rendered = renderer.rendered_content
        receipt_sha256 = ""
        if rendered:
            receipt_sha256 = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

        envelope = ContextEnvelopeReceipt(
            session_id=self._session_id,
            rendered_prompt=rendered,
            section_count=renderer.section_count,
            estimated_tokens=max(1, len(rendered) // 4),
            dirty_file_count=dirty_count,
            collision_warnings=collision_count,
            receipt_sha256=receipt_sha256,
        )
        _emit_context_trace(
            "context.envelope.built",
            session_id=self._session_id,
            payload={
                "section_count": renderer.section_count,
                "estimated_tokens": envelope.estimated_tokens,
                "dirty_count": dirty_count,
                "collision_count": collision_count,
                "receipt_sha256": receipt_sha256[:16] if receipt_sha256 else "",
            },
        )
        return envelope


def execute(
    request: ContextRequest, workspace_root: Path | None = None
) -> ContextPacket:
    """Execute a get_context request and return a ContextPacket.

    Thin facade that delegates mode dispatch to ContextRuntime.
    Preserved for backward compatibility.

    Args:
        request: The validated ContextRequest.
        workspace_root: Optional workspace root. Defaults to CWD.

    Returns:
        A ContextPacket with all fields populated per the request mode.
    """
    return _get_runtime().execute(request, workspace_root)


def build_receipt(packet: ContextPacket) -> ContextReceipt:
    """Build a content-light receipt from a completed packet."""
    # Check findings lifecycle
    open_count = 0
    stale_count = 0
    try:
        from rig_relay.governance.findings_lifecycle import compute_findings_summary

        _fs = compute_findings_summary()
        open_count = _fs.get("by_status", {}).get("open", 0)
        stale_count = len(_fs.get("stale_findings", []))
    except Exception as e:
        from rig_relay.context.warnings import (
            ContextWarningCode,
            build_warning,
            exception_class_name,
        )

        _emit_context_trace(
            "context.assembly.failed", payload={"error": exception_class_name(e)}
        )
        # ContextReceipt has no warnings field; record safe zero counts only.
        # The warning is emitted through the packet warnings path instead.
        _receipt_findings_warning = build_warning(
            ContextWarningCode.FINDINGS_SUMMARY_FAILED,
            detail=f"{exception_class_name(e)}",
            source="compiler.build_receipt",
        )

    return ContextReceipt(
        context_id=packet.context_id,
        mode=packet.mode.value,
        request_sha256=packet.request_sha256,
        packet_sha256=packet.canonical_packet_sha256 or "",
        subsystem_count=len(packet.subsystems),
        active_lane_count=len(packet.active_work.get("lanes", [])),
        collision_warning_count=len(packet.active_work.get("collision_warnings", [])),
        receipt_count=len(packet.receipts),
        dirty_file_count=packet.repo.dirty_summary.get("modified", 0),
        symbol_count=len(packet.symbol_map.get("symbols", [])),
        open_finding_count=open_count,
        stale_finding_count=stale_count,
        estimated_tokens=_estimate_tokens(packet),
        duration_ms=packet.duration_ms,
    )


def _build_recommended_context(subsystems: list) -> list[PathRecommendation]:
    """Build a list of recommended context files from the subsystem map.

    Kept for backward compatibility. Prefer _map_selections_to_recommendations.
    """
    recommendations: list[PathRecommendation] = []

    for sub in subsystems[:5]:
        if sub.config_files:
            recommendations.append(
                PathRecommendation(
                    path=sub.config_files[0],
                    reason=f"Core configuration for {sub.name} subsystem",
                )
            )
        if sub.docs:
            recommendations.append(
                PathRecommendation(
                    path=sub.docs[0], reason=f"Documentation for {sub.name} subsystem"
                )
            )

    return recommendations


def _build_do_not_touch(collisions: list[dict]) -> list[PathRecommendation]:
    """Build a do-not-touch list from collision warnings.

    Kept for backward compatibility. Prefer _map_omissions_to_do_not_touch.
    """
    return [
        PathRecommendation(path=c.get("path", ""), reason=c.get("reason", ""))
        for c in collisions
    ]


_map_omissions_to_do_not_touch = _build_do_not_touch  # backward compatibility alias
_map_selections_to_recommendations = (
    _build_recommended_context  # backward compatibility alias
)


def _estimate_tokens(packet: ContextPacket) -> int:
    """Rough token estimate from the packet JSON length."""
    raw = packet.model_dump_json(exclude_none=True)
    return max(1, len(raw) // 4)
