"""Context compiler — the core logic for rig.get_context.

Takes a ContextRequest, builds a ContextPacket by composing repo_map,
work_map, and optional receipt/symbol scans. Produces structured output,
hash-stable receipts, and content-light metadata.

This is the front door for the rig.get_context built-in tool.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Any

from rig_relay.context.assembly_plan import ContextAssemblyPlan, ContextCandidate
from rig_relay.context.models import (
    ContextEnvelopeReceipt,
    ContextPacket,
    ContextReceipt,
    ContextRequest,
    PathRecommendation,
    ReceiptEntry,
)
from rig_relay.context.planner import plan_context
from rig_relay.context.renderer import ContextRenderer
from rig_relay.context.repo_index import RepoContextIndex
from rig_relay.context.repo_map import build_repo_info, build_subsystem_map
from rig_relay.context.warnings import (
    ContextWarningCode,
    build_warning,
    exception_class_name,
)
from rig_relay.context.work_map import build_active_work


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
            renderer.warnings.append(
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

        return ContextEnvelopeReceipt(
            session_id=self._session_id,
            rendered_prompt=rendered,
            section_count=len(renderer._sections),
            estimated_tokens=max(1, len(rendered) // 4),
            dirty_file_count=dirty_count,
            collision_warnings=collision_count,
            receipt_sha256=receipt_sha256,
        )



def execute(  # noqa: PLR0914
    request: ContextRequest, workspace_root: Path | None = None
) -> ContextPacket:
    """Execute a get_context request and return a ContextPacket.

    Args:
        request: The validated ContextRequest.
        workspace_root: Optional workspace root. Defaults to CWD.

    Returns:
        A ContextPacket with all fields populated per the request mode.
    """
    start = time.perf_counter()
    root = (workspace_root or Path.cwd()).resolve()
    _context_warnings: list[dict[str, Any]] = []

    # Check findings lifecycle
    try:
        from rig_relay.governance.findings_lifecycle import compute_findings_summary

        _findings_summary = compute_findings_summary()
        if _findings_summary.get("stale_findings"):
            pass  # Available for correlation; not yet surfaced in packet
    except Exception as e:
        _context_warnings.append(
            build_warning(
                ContextWarningCode.FINDINGS_SUMMARY_FAILED,
                detail=f"{exception_class_name(e)}",
                source="compiler.execute.findings",
            )
        )

    # Compute request hash
    req_json = request.model_dump_json(exclude_none=True)
    request_sha256 = hashlib.sha256(req_json.encode("utf-8")).hexdigest()

    # Build repo info (always)
    repo = build_repo_info(root)

    # Build subsystem map (always for map mode)
    subsystems = build_subsystem_map(root)

    # Build active work map
    active_work = build_active_work(root, request.scope.paths)

    # ── Plan context via ContextAssemblyPlan ────────────────────
    plan = plan_context(
        request,
        workspace_root=root,
        subsystems=subsystems,
        active_work=active_work,
        repo_index=None,
    )

    # Build recommended context from plan selections
    recommended = _map_selections_to_recommendations(plan)

    # Build do-not-touch list from plan omissions (risk/collision)
    do_not_touch = _map_omissions_to_do_not_touch(plan)

    # Build receipt entries if requested
    receipts: list[ReceiptEntry] = []
    if request.scope.include_receipts:
        receipts = _scan_receipts(root)

    # Build summary text (existing + plan metadata)
    summary = _build_summary(repo, subsystems, active_work, plan)

    # Compute packet hash (canonical: excludes volatile fields)
    packet = ContextPacket(
        mode=request.mode,
        request_sha256=request_sha256,
        repo=repo,
        subsystems=subsystems,
        active_work=active_work,
        recommended_context=recommended,
        do_not_touch=do_not_touch,
        receipts=receipts,
        summary_text=summary,
        canonical_packet_sha256=None,
        optimized_packet_sha256=None,
        substitution_table_sha256=None,
    )

    # Canonical hash: excludes volatile fields
    import json

    packet_dict = packet.model_dump(mode="json", exclude_none=True)
    volatile = {
        "context_id",
        "generated_at",
        "duration_ms",
        "canonical_packet_sha256",
        "optimized_packet_sha256",
        "substitution_table_sha256",
    }
    stable_dict = {k: v for k, v in packet_dict.items() if k not in volatile}
    stable_json = json.dumps(stable_dict, sort_keys=True, separators=(",", ":"))
    packet_sha256 = hashlib.sha256(stable_json.encode("utf-8")).hexdigest()

    # Store hashes
    packet.canonical_packet_sha256 = packet_sha256
    packet.optimized_packet_sha256 = packet_sha256
    packet.duration_ms = (time.perf_counter() - start) * 1000

    return packet


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
    except Exception:
        pass

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
            recommendations.append(PathRecommendation(
                path=sub.config_files[0],
                reason=f"Core configuration for {sub.name} subsystem",
            ))
        if sub.docs:
            recommendations.append(PathRecommendation(
                path=sub.docs[0],
                reason=f"Documentation for {sub.name} subsystem",
            ))

    return recommendations[:10]


def _build_do_not_touch(collisions: list[dict]) -> list[PathRecommendation]:
    """Build a do-not-touch list from collision warnings.

    Kept for backward compatibility. Prefer _map_omissions_to_do_not_touch.
    """
    return [
        PathRecommendation(path=c.get("path", ""), reason=c.get("reason", ""))
        for c in collisions
    ]


def _map_selections_to_recommendations(
    plan: ContextAssemblyPlan,
) -> list[PathRecommendation]:
    """Convert plan selections into recommended context entries."""
    result: list[PathRecommendation] = []
    seen: set[str] = set()
    for sel in plan.selections:
        cand = _find_candidate(plan, sel.candidate_id)
        if cand is None:
            continue
        if cand.path in seen:
            continue
        seen.add(cand.path)
        result.append(PathRecommendation(
            path=cand.path,
            reason=sel.selection_reason or cand.reason,
        ))
    return result


def _map_omissions_to_do_not_touch(
    plan: ContextAssemblyPlan,
) -> list[PathRecommendation]:
    """Convert risk/collision omissions into do-not-touch entries."""
    result: list[PathRecommendation] = []
    for om in plan.omissions:
        _RISK_OMISSION_REASONS = frozenset({"risk_policy", "collision"})
        if om.omission_reason not in _RISK_OMISSION_REASONS:
            continue
        cand = _find_candidate(plan, om.candidate_id)
        if cand is None:
            continue
        result.append(PathRecommendation(
            path=cand.path,
            reason=om.detail or f"omitted: {om.omission_reason}",
        ))
    return result


def _find_candidate(
    plan: ContextAssemblyPlan, candidate_id: str
) -> ContextCandidate | None:
    for c in plan.candidates:
        if c.candidate_id == candidate_id:
            return c
    return None


def _scan_receipts(root: Path) -> list[ReceiptEntry]:
    """Scan for recent receipt files in the build directory."""
    receipts_dir = root / ".build" / "rig-relay" / "coordination" / "receipts"
    if not receipts_dir.is_dir():
        return []
    entries: list[ReceiptEntry] = []
    for f in sorted(receipts_dir.iterdir(), reverse=True)[:10]:
        if f.is_file():
            import hashlib as _hl

            try:
                data = f.read_bytes()
                sha = _hl.sha256(data).hexdigest()
            except Exception:
                sha = ""
            entries.append(ReceiptEntry(
                kind=f.suffix.lstrip(".") or "receipt",
                path=str(f.relative_to(root)) if f.is_relative_to(root) else str(f),
                sha256=f"sha256:{sha[:16]}" if sha else "",
            ))
    return entries


def _build_summary(
    repo: Any,
    subsystems: list,
    active_work: dict,
    plan: ContextAssemblyPlan | None = None,
) -> str:
    """Build a human-readable summary text from the context data."""
    lines: list[str] = []
    lines.append(f"Repository: {repo.root}")
    lines.append(f"Branch: {repo.branch} @ {repo.head}")
    lines.append(f"Dirty files: {repo.dirty_summary.get('modified', 0)} modified, "
                 f"{repo.dirty_summary.get('untracked', 0)} untracked, "
                 f"{repo.dirty_summary.get('staged', 0)} staged")
    lines.append("")

    if subsystems:
        lines.append(f"Subsystems ({len(subsystems)}):")
        for sub in subsystems[:10]:
            lines.append(f"  {sub.name}: {len(sub.paths)} files")
            if sub.entry_points:
                lines.append(f"    Entry: {', '.join(sub.entry_points[:3])}")
            if sub.schemas:
                lines.append(f"    Schemas: {len(sub.schemas)}")
        lines.append("")

    lanes = active_work.get("lanes", [])
    if lanes:
        lines.append(f"Active work ({len(lanes)} lanes):")
        for lane in lanes:
            lines.append(f"  {lane.get('agent_id', '?')}: {lane.get('status', '?')} "
                         f"({len(lane.get('claimed_paths', []))} claimed paths)")
        lines.append("")

    collisions = active_work.get("collision_warnings", [])
    if collisions:
        lines.append(f"Collision warnings ({len(collisions)}):")
        for c in collisions[:5]:
            lines.append(f"  ! {c.get('path', '?')}: {c.get('reason', '')[:80]}")

    if plan is not None:
        lines.append("")
        lines.append(f"Assembly plan: {len(plan.candidates)} candidates, "
                     f"{len(plan.selections)} selected, "
                     f"{len(plan.omissions)} omitted, "
                     f"{len(plan.warnings)} warnings")
        lines.append(f"  plan_id: {plan.plan_id}")
        if plan.budget.used_tokens > 0:
            lines.append(f"  budget: {plan.budget.used_tokens}/{plan.budget.requested_tokens} tokens")

    return "\n".join(lines)


def _estimate_tokens(packet: ContextPacket) -> int:
    """Rough token estimate from the packet JSON length."""
    raw = packet.model_dump_json(exclude_none=True)
    return max(1, len(raw) // 4)
