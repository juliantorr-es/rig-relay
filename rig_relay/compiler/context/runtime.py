"""ContextRuntime — mode-dispatched context compiler entry point.

Wraps the `execute()` mode dispatch logic from `rig_relay.context.compiler`,
delegating each mode to its specialised compiler:
  - MAP / PACKET → planner + renderer pipeline (inlined from compiler.py)
  - HANDOFF       → compile_handoff_packet
  - COLLISION     → compile_collision_report
  - SYMBOLS       → compile_symbol_packet
  - DIGEST        → digester pipeline (inlined from compiler.py)

Uses shared compiler infrastructure: compute_sha256 (hashes), CompilerEvidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any

from rig_relay.compiler.evidence import CompilerEvidence
from rig_relay.context.assembly_plan import ContextAssemblyPlan, ContextCandidate
from rig_relay.context.models import (
    ContextMode,
    ContextPacket,
    ContextRequest,
    PathRecommendation,
    ReceiptEntry,
)
from rig_relay.context.planner import plan_context
from rig_relay.context.repo_index import RepoContextIndex
from rig_relay.context.repo_map import build_repo_info, build_subsystem_map
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


def _get_session_id(request: ContextRequest) -> str:
    return getattr(request, "session_id", "")


def _compute_request_sha256(request: ContextRequest) -> str:
    req_json = request.model_dump_json(exclude_none=True)
    return hashlib.sha256(req_json.encode("utf-8")).hexdigest()


def _compute_packet_sha256(packet: ContextPacket) -> str:
    packet_dict = packet.model_dump(mode="json", exclude_none=True)
    volatile = {
        "context_id",
        "generated_at",
        "duration_ms",
        "canonical_packet_sha256",
        "optimized_packet_sha256",
        "substitution_table_sha256",
        "warnings",
    }
    stable_dict = {k: v for k, v in packet_dict.items() if k not in volatile}
    stable_json = json.dumps(stable_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable_json.encode("utf-8")).hexdigest()


class ContextRuntime:
    """Mode-dispatched context compiler.

    Delegates to specialised compilers per ContextMode and emits
    content-light evidence for degraded / unknown states.
    """

    def __init__(self, *, evidence_dir: Path | None = None) -> None:
        self._evidence = CompilerEvidence(
            evidence_dir=evidence_dir
            or (Path.cwd() / ".build" / "rig-relay" / "context_evidence")
        )

    def execute(
        self, request: ContextRequest, workspace_root: Path | None = None
    ) -> ContextPacket:
        start = time.perf_counter()
        root = (workspace_root or Path.cwd()).resolve()
        session_id = _get_session_id(request)
        request_sha256 = _compute_request_sha256(request)

        _emit_context_trace(
            "context.sources.selected",
            session_id=session_id,
            payload={"mode": request.mode.value},
        )

        repo = build_repo_info(root)

        match request.mode:
            case ContextMode.DIGEST:
                return self._execute_digest(
                    request, root, repo, request_sha256, session_id, start
                )
            case ContextMode.HANDOFF:
                return self._execute_handoff(
                    request, root, repo, request_sha256, session_id, start
                )
            case ContextMode.COLLISION:
                return self._execute_collision(
                    request, root, repo, request_sha256, session_id, start
                )
            case ContextMode.SYMBOLS:
                return self._execute_symbols(
                    request, root, repo, request_sha256, session_id, start
                )
            case ContextMode.MAP | ContextMode.PACKET:
                return self._execute_map(
                    request, root, repo, request_sha256, session_id, start
                )
            case _:
                return self._execute_unknown(
                    request, repo, request_sha256, session_id, start
                )

    # ── MAP / PACKET (planner + renderer pipeline) ──────────────────

    def _execute_map(
        self,
        request: ContextRequest,
        root: Path,
        repo: Any,
        request_sha256: str,
        session_id: str,
        start: float,
    ) -> ContextPacket:
        warnings: list[dict[str, Any]] = []

        subsystems = build_subsystem_map(root)
        active_work = build_active_work(root, request.scope.paths)

        repo_index: RepoContextIndex | None = None
        try:
            repo_index = RepoContextIndex(root)
        except Exception as e:
            warnings.append(
                build_warning(
                    ContextWarningCode.REPO_SCAN_FAILED,
                    detail=f"{exception_class_name(e)}",
                    source="compiler.execute.repo_index",
                )
            )

        _emit_context_trace(
            "context.schema_router.invoked",
            session_id=session_id,
            payload={"planning": True},
        )

        plan = plan_context(
            request,
            workspace_root=root,
            subsystems=subsystems,
            active_work=active_work,
            repo_index=repo_index,
        )

        _emit_context_trace(
            "context.schemas.selected",
            session_id=session_id,
            payload={
                "candidate_count": len(plan.candidates),
                "selection_count": len(plan.selections),
                "omission_count": len(plan.omissions),
            },
        )

        recommended = _map_selections_to_recommendations(plan)
        do_not_touch = _map_omissions_to_do_not_touch(plan)

        receipts: list[ReceiptEntry] = []
        if request.scope.include_receipts:
            receipts = _scan_receipts(root, warnings=warnings)

        summary = _build_summary(repo, subsystems, active_work, plan)

        planner_warnings_list: list[dict[str, Any]] = []
        if hasattr(plan, "warnings"):
            for pw in getattr(plan, "warnings", []):
                if isinstance(pw, dict):
                    planner_warnings_list.append(pw)
        warnings.extend(planner_warnings_list)

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
            warnings=warnings,
            assembly_plan_summary={
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "selection_sha256": plan.selection_sha256,
                "candidate_count": len(plan.candidates),
                "selection_count": len(plan.selections),
                "omission_count": len(plan.omissions),
                "warning_count": len(plan.warnings),
            },
        )

        _emit_context_trace(
            "context.generated_html_excluded",
            session_id=session_id,
            payload={"excluded_count": 6},
        )

        pkt_sha = _compute_packet_sha256(packet)
        packet.canonical_packet_sha256 = pkt_sha
        packet.optimized_packet_sha256 = pkt_sha
        packet.duration_ms = (time.perf_counter() - start) * 1000

        _emit_context_trace(
            "context.prompt.emitted",
            session_id=session_id,
            payload={
                "packet_size_bytes": len(packet.model_dump_json(exclude_none=True)),
                "duration_ms": packet.duration_ms,
                "subsystem_count": len(packet.subsystems),
            },
        )

        return packet

    # ── DIGEST (digester pipeline) ─────────────────────────────────

    def _execute_digest(
        self,
        request: ContextRequest,
        root: Path,
        repo: Any,
        request_sha256: str,
        session_id: str,
        start: float,
    ) -> ContextPacket:
        warnings: list[dict[str, Any]] = []
        receipts: list[ReceiptEntry] = []
        if request.scope.include_receipts:
            receipts = _scan_receipts(root, warnings=warnings)

        packet = _build_digest_packet(
            request, root, repo, request_sha256, warnings, receipts
        )
        pkt_sha = _compute_packet_sha256(packet)
        packet.canonical_packet_sha256 = pkt_sha
        packet.optimized_packet_sha256 = pkt_sha
        packet.duration_ms = (time.perf_counter() - start) * 1000
        return packet

    # ── HANDOFF ────────────────────────────────────────────────────

    def _execute_handoff(
        self,
        request: ContextRequest,
        root: Path,
        repo: Any,
        request_sha256: str,
        session_id: str,
        start: float,
    ) -> ContextPacket:
        warnings: list[dict[str, Any]] = []
        packet = _build_handoff_packet(request, root, repo, request_sha256, warnings)
        pkt_sha = _compute_packet_sha256(packet)
        packet.canonical_packet_sha256 = pkt_sha
        packet.optimized_packet_sha256 = pkt_sha
        packet.duration_ms = (time.perf_counter() - start) * 1000
        return packet

    # ── COLLISION ──────────────────────────────────────────────────

    def _execute_collision(
        self,
        request: ContextRequest,
        root: Path,
        repo: Any,
        request_sha256: str,
        session_id: str,
        start: float,
    ) -> ContextPacket:
        warnings: list[dict[str, Any]] = []
        packet = _build_collision_packet(request, root, repo, request_sha256, warnings)
        pkt_sha = _compute_packet_sha256(packet)
        packet.canonical_packet_sha256 = pkt_sha
        packet.optimized_packet_sha256 = pkt_sha
        packet.duration_ms = (time.perf_counter() - start) * 1000
        return packet

    # ── SYMBOLS ────────────────────────────────────────────────────

    def _execute_symbols(
        self,
        request: ContextRequest,
        root: Path,
        repo: Any,
        request_sha256: str,
        session_id: str,
        start: float,
    ) -> ContextPacket:
        warnings: list[dict[str, Any]] = []
        packet = _build_symbols_packet(request, root, repo, request_sha256, warnings)
        pkt_sha = _compute_packet_sha256(packet)
        packet.canonical_packet_sha256 = pkt_sha
        packet.optimized_packet_sha256 = pkt_sha
        packet.duration_ms = (time.perf_counter() - start) * 1000
        return packet

    # ── UNKNOWN / invalid mode ─────────────────────────────────────

    def _execute_unknown(
        self,
        request: ContextRequest,
        repo: Any,
        request_sha256: str,
        session_id: str,
        start: float,
    ) -> ContextPacket:
        mode_str = (
            request.mode.value if hasattr(request.mode, "value") else str(request.mode)
        )
        warnings: list[dict[str, Any]] = [
            build_warning(
                ContextWarningCode.REPO_SCAN_FAILED,
                detail=f"unknown context mode: {mode_str}",
                source="compiler.execute.unknown",
            )
        ]

        _emit_context_trace(
            "context.degraded",
            session_id=session_id,
            payload={"mode": mode_str, "reason": "unknown_mode"},
        )

        # Emit evidence
        try:
            self._evidence.write_jsonl(
                "degraded_modes.jsonl",
                {
                    "mode": mode_str,
                    "request_sha256": request_sha256,
                    "reason": "unknown_mode",
                    "timestamp": time.time(),
                },
            )
        except Exception:
            pass

        packet = ContextPacket(
            mode=ContextMode.MAP,
            request_sha256=request_sha256,
            repo=repo,
            subsystems=[],
            active_work={},
            warnings=warnings,
            summary_text=f"Unknown context mode: {mode_str}. Falling back to map.",
        )
        pkt_sha = _compute_packet_sha256(packet)
        packet.canonical_packet_sha256 = pkt_sha
        packet.optimized_packet_sha256 = pkt_sha
        packet.duration_ms = (time.perf_counter() - start) * 1000
        return packet


# ── Shared helpers extracted from compiler.py ──────────────────────


def _map_selections_to_recommendations(
    plan: ContextAssemblyPlan,
) -> list[PathRecommendation]:
    result: list[PathRecommendation] = []
    seen: set[str] = set()
    for sel in plan.selections:
        cand = _find_candidate(plan, sel.candidate_id)
        if cand is None:
            continue
        if cand.path in seen:
            continue
        seen.add(cand.path)
        result.append(
            PathRecommendation(
                path=cand.path, reason=sel.selection_reason or cand.reason
            )
        )
    return result


def _map_omissions_to_do_not_touch(
    plan: ContextAssemblyPlan,
) -> list[PathRecommendation]:
    result: list[PathRecommendation] = []
    _RISK_OMISSION_REASONS = frozenset({"risk_policy", "collision"})
    for om in plan.omissions:
        if om.omission_reason not in _RISK_OMISSION_REASONS:
            continue
        cand = _find_candidate(plan, om.candidate_id)
        if cand is None:
            continue
        result.append(
            PathRecommendation(
                path=cand.path, reason=om.detail or f"omitted: {om.omission_reason}"
            )
        )
    return result


def _find_candidate(
    plan: ContextAssemblyPlan, candidate_id: str
) -> ContextCandidate | None:
    for c in plan.candidates:
        if c.candidate_id == candidate_id:
            return c
    return None


def _scan_receipts(
    root: Path, warnings: list[dict[str, Any]] | None = None
) -> list[ReceiptEntry]:
    receipts_dir = root / ".build" / "rig-relay" / "coordination" / "receipts"
    if not receipts_dir.is_dir():
        return []
    entries: list[ReceiptEntry] = []
    for f in sorted(receipts_dir.iterdir(), reverse=True)[:10]:
        if f.is_file():
            try:
                data = f.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
            except Exception:
                if warnings is not None:
                    warnings.append(
                        build_warning(
                            ContextWarningCode.RECEIPT_SCAN_FAILED,
                            detail="read/hash failed for receipt",
                            source="compiler._scan_receipts",
                        )
                    )
                sha = ""
            entries.append(
                ReceiptEntry(
                    kind=f.suffix.lstrip(".") or "receipt",
                    path=str(f.relative_to(root)) if f.is_relative_to(root) else str(f),
                    sha256=f"sha256:{sha[:16]}" if sha else "",
                )
            )
    return entries


def _build_summary(
    repo: Any,
    subsystems: list,
    active_work: dict,
    plan: ContextAssemblyPlan | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"Repository: {repo.root}")
    lines.append(f"Branch: {repo.branch} @ {repo.head}")
    lines.append(
        f"Dirty files: {repo.dirty_summary.get('modified', 0)} modified, "
        f"{repo.dirty_summary.get('untracked', 0)} untracked, "
        f"{repo.dirty_summary.get('staged', 0)} staged"
    )
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
            lines.append(
                f"  {lane.get('agent_id', '?')}: {lane.get('status', '?')} "
                f"({len(lane.get('claimed_paths', []))} claimed paths)"
            )
        lines.append("")

    collisions = active_work.get("collision_warnings", [])
    if collisions:
        lines.append(f"Collision warnings ({len(collisions)}):")
        for c in collisions[:5]:
            lines.append(f"  ! {c.get('path', '?')}: {c.get('reason', '')[:80]}")

    if plan is not None:
        lines.append("")
        lines.append(
            f"Assembly plan: {len(plan.candidates)} candidates, "
            f"{len(plan.selections)} selected, "
            f"{len(plan.omissions)} omitted, "
            f"{len(plan.warnings)} warnings"
        )
        lines.append(f"  plan_id: {plan.plan_id}")
        if plan.budget.used_tokens > 0:
            lines.append(
                f"  budget: {plan.budget.used_tokens}/{plan.budget.requested_tokens} tokens"
            )

    return "\n".join(lines)


# ── Mode-specific packet builders (extracted from compiler.py) ────


def _build_digest_packet(
    request: ContextRequest,
    root: Path,
    repo: Any,
    request_sha256: str,
    warnings: list[dict[str, Any]],
    receipts: list[ReceiptEntry],
) -> ContextPacket:
    store_root = root / ".build" / "rig-relay" / "coordination"
    cache_dir = root / ".build" / "rig-relay" / "cache"

    try:
        from rig_relay.context.digester import ContextDigester

        digester = ContextDigester()
        digestion_result = digester.digest(
            store_root=str(store_root), repo_root=str(root)
        )

        try:
            from rig_relay.context.cache import ContextCache

            cache = ContextCache(cache_dir=cache_dir, ttl_seconds=300)
            cache_key = cache.cache_key(
                repo_root=root,
                source_event_range=digestion_result.source_event_range,
                source_commit=digestion_result.source_commit,
            )
            if cache.is_fresh(cache_key, digestion_result.source_commit):
                cached = cache.get(cache_key)
                if cached is not None:
                    return _build_packet_from_digestion(
                        request,
                        repo,
                        request_sha256,
                        digestion_result,
                        warnings,
                        receipts,
                    )
            cache.set(cache_key, digestion_result)
        except Exception as cache_exc:
            _emit_context_trace(
                "context.cache.store_failed",
                payload={"error": exception_class_name(cache_exc)},
            )

        return _build_packet_from_digestion(
            request, repo, request_sha256, digestion_result, warnings, receipts
        )
    except Exception as e:
        warnings.append(
            build_warning(
                ContextWarningCode.SYMBOL_DIGEST_FAILED,
                detail=f"{exception_class_name(e)}: falling back to store projection",
                source="compiler._build_digest_packet.digester",
            )
        )

    return _build_digest_packet_from_store(
        request, root, repo, request_sha256, warnings, receipts, store_root
    )


def _build_digest_packet_from_store(
    request: ContextRequest,
    root: Path,
    repo: Any,
    request_sha256: str,
    warnings: list[dict[str, Any]],
    receipts: list[ReceiptEntry],
    store_root: Path,
) -> ContextPacket:
    try:
        from rig_relay.coordination import CoordinationStore

        store = CoordinationStore(store_root)
        projection = store.read_state_projection()
    except Exception as e:
        warnings.append(
            build_warning(
                ContextWarningCode.REPO_SCAN_FAILED,
                detail=f"{exception_class_name(e)}: store projection unavailable",
                source="compiler._build_digest_packet_from_store",
            )
        )
        return ContextPacket(
            mode=ContextMode.DIGEST,
            repo=repo,
            request_sha256=request_sha256,
            warnings=warnings,
            receipts=receipts,
        )

    return _build_packet_from_projection(
        request, repo, request_sha256, projection, warnings, receipts
    )


def _build_packet_from_digestion(
    request: ContextRequest,
    repo: Any,
    request_sha256: str,
    digestion_result: Any,
    warnings: list[dict[str, Any]],
    receipts: list[ReceiptEntry],
) -> ContextPacket:
    from rig_relay.context.digester import ContextDigestionResult

    if isinstance(digestion_result, ContextDigestionResult):
        active_lanes_raw = digestion_result.active_lanes
        do_not_touch_paths = list(digestion_result.do_not_touch_paths)
        recent_conflicts = digestion_result.recent_conflicts
    elif isinstance(digestion_result, dict):
        active_lanes_raw = digestion_result.get("active_lanes", [])
        do_not_touch_paths = digestion_result.get("do_not_touch_paths", [])
        recent_conflicts = digestion_result.get("recent_conflicts", [])
    else:
        active_lanes_raw = getattr(digestion_result, "active_lanes", []) or []
        do_not_touch_paths = getattr(digestion_result, "do_not_touch_paths", []) or []
        recent_conflicts = getattr(digestion_result, "recent_conflicts", []) or []

    lanes: list[dict[str, Any]] = []
    for lane in active_lanes_raw:
        if isinstance(lane, dict):
            lanes.append({
                "agent_id": lane.get("session_id", ""),
                "mission_id": lane.get("task_id", ""),
                "worktree_path": "",
                "claimed_paths": lane.get("reserved_paths", []),
                "dirty_paths": [],
                "status": lane.get("status", "active"),
            })

    do_not_touch = [
        PathRecommendation(path=p, reason="Digestion do-not-touch")
        for p in do_not_touch_paths
    ]

    collision_warnings: list[dict[str, Any]] = []
    for conflict in recent_conflicts:
        if isinstance(conflict, dict):
            conflict_paths = conflict.get("paths", [])
            collision_warnings.append({
                "path": conflict_paths[0] if conflict_paths else "",
                "claimed_by": conflict.get("other_session_id", ""),
                "reason": conflict.get("kind", ""),
            })

    active_work: dict[str, Any] = {
        "lanes": lanes,
        "collision_warnings": collision_warnings,
    }

    summary_lines = [
        "Digest mode context from coordination digestion",
        f"Active lanes: {len(lanes)}",
        f"Do-not-touch paths: {len(do_not_touch)}",
        f"Collision warnings: {len(collision_warnings)}",
    ]

    return ContextPacket(
        mode=ContextMode.DIGEST,
        repo=repo,
        request_sha256=request_sha256,
        subsystems=[],
        active_work=active_work,
        recommended_context=[
            PathRecommendation(path=lane.get("agent_id", ""), reason="Active lane")
            for lane in lanes[:10]
        ],
        do_not_touch=do_not_touch,
        receipts=receipts,
        summary_text="\n".join(summary_lines),
        warnings=warnings,
    )


def _build_packet_from_projection(
    request: ContextRequest,
    repo: Any,
    request_sha256: str,
    projection: Any,
    warnings: list[dict[str, Any]],
    receipts: list[ReceiptEntry],
) -> ContextPacket:
    from rig_relay.coordination.models import CoordinationStateProjection

    lanes: list[dict[str, Any]] = []
    do_not_touch: list[PathRecommendation] = []
    collision_warnings: list[dict[str, Any]] = []

    if isinstance(projection, CoordinationStateProjection):
        claims = projection.active_task_claims
        reservations = projection.active_path_reservations
        conflicts = projection.conflicts
    elif hasattr(projection, "active_task_claims"):
        claims = projection.active_task_claims
        reservations = projection.active_path_reservations
        conflicts = getattr(projection, "conflicts", [])
    else:
        claims = {}
        reservations = {}
        conflicts = []

    for task_id, claim in claims.items():
        sid = getattr(claim, "session_id", "")
        lanes.append({
            "agent_id": sid,
            "mission_id": task_id,
            "worktree_path": "",
            "claimed_paths": getattr(claim, "scope_allowed_paths", []) or [],
            "dirty_paths": [],
            "status": getattr(claim, "status", "unknown"),
        })
    for _lease_key, reservation in reservations.items():
        sid = getattr(reservation, "session_id", "")
        task_id = getattr(reservation, "task_id", "")
        reservation_paths: list[str] = getattr(reservation, "paths", []) or []
        if getattr(reservation, "mode", "read") == "write":
            for p in reservation_paths:
                if p not in {r.path for r in do_not_touch}:
                    do_not_touch.append(
                        PathRecommendation(path=p, reason=f"Write lease by {sid}")
                    )
        existing = [l for l in lanes if l.get("agent_id") == sid]
        if existing:
            existing_paths = set(existing[0].get("claimed_paths", []))
            existing_paths.update(reservation_paths)
            existing[0]["claimed_paths"] = list(existing_paths)
        else:
            lanes.append({
                "agent_id": sid,
                "mission_id": task_id,
                "worktree_path": "",
                "claimed_paths": reservation_paths,
                "dirty_paths": [],
                "status": "active",
            })

    for conflict in conflicts:
        collision_warnings.append({
            "path": getattr(conflict, "paths", [None])[0] or "",
            "claimed_by": getattr(conflict, "other_session_id", ""),
            "reason": getattr(conflict, "kind", ""),
        })

    active_work: dict[str, Any] = {
        "lanes": lanes,
        "collision_warnings": collision_warnings,
    }

    summary_lines = [
        "Digest mode context from coordination store projection",
        f"Active lanes: {len(lanes)}",
        f"Write-lease do-not-touch paths: {len(do_not_touch)}",
        f"Collision warnings: {len(collision_warnings)}",
    ]

    return ContextPacket(
        mode=ContextMode.DIGEST,
        repo=repo,
        request_sha256=request_sha256,
        subsystems=[],
        active_work=active_work,
        recommended_context=[
            PathRecommendation(path=lane.get("agent_id", ""), reason="Active lane")
            for lane in lanes[:10]
        ],
        do_not_touch=do_not_touch,
        receipts=receipts,
        summary_text="\n".join(summary_lines),
        warnings=warnings,
    )


def _build_handoff_packet(
    request: ContextRequest,
    root: Path,
    repo: Any,
    request_sha256: str,
    warnings: list[dict[str, Any]],
) -> ContextPacket:
    store_root = root / ".build" / "rig-relay" / "coordination"
    session_id = getattr(request, "session_id", "") or ""
    handoff: dict[str, Any] = {}
    try:
        from rig_relay.compiler.context.handoff import compile_handoff_packet

        handoff = compile_handoff_packet(session_id, store_root)
    except Exception as e:
        _emit_context_trace(
            "context.handoff_degraded",
            session_id=session_id,
            payload={
                "coordination_store_available": False,
                "error": exception_class_name(e),
            },
        )
        warnings.append(
            build_warning(
                ContextWarningCode.HANDOFF_DEGRADED,
                detail=f"{exception_class_name(e)}: handoff compile failed",
                source="compiler._build_handoff_packet",
            )
        )
        handoff = {
            "evidence_status": "degraded",
            "degraded_reason": f"handoff compilation failed: {exception_class_name(e)}",
        }

    handoff_evidence = handoff.get("evidence_status")
    if handoff_evidence in {"missing", "degraded"}:
        _emit_context_trace(
            "context.handoff_degraded",
            session_id=session_id,
            payload={
                "coordination_store_available": False,
                "evidence_status": handoff_evidence,
                "degraded_reason": handoff.get("degraded_reason", ""),
            },
        )
        warnings.append(
            build_warning(
                ContextWarningCode.HANDOFF_DEGRADED,
                detail=f"handoff evidence {handoff_evidence}",
                source="compiler._build_handoff_packet",
            )
        )

    active_agents = handoff.get("active_agents", [])
    file_leases = handoff.get("file_leases", [])
    collision_warnings_list = handoff.get("collision_warnings", [])
    do_not_touch_paths = handoff.get("do_not_touch_paths", [])
    recommended_paths = handoff.get("recommended_next_paths", [])

    active_work: dict[str, Any] = {
        "lanes": [
            {
                "agent_id": a.get("agent_id", ""),
                "mission_id": "",
                "worktree_path": "",
                "claimed_paths": a.get("claimed_paths", []),
                "dirty_paths": [],
                "status": a.get("status", "unknown"),
            }
            for a in active_agents
        ],
        "collision_warnings": collision_warnings_list,
    }

    do_not_touch = [
        PathRecommendation(path=p, reason="Active lease") for p in do_not_touch_paths
    ]
    recommended_context = [
        PathRecommendation(path=p, reason="Recommended next path")
        for p in recommended_paths
    ]

    summary_lines = [
        "Handoff mode: cross-agent coordination snapshot",
        f"Active agents: {len(active_agents)}",
        f"File leases: {len(file_leases)}",
        f"Collision warnings: {len(collision_warnings_list)}",
        f"Do-not-touch paths: {len(do_not_touch_paths)}",
        f"Recommended next paths: {len(recommended_paths)}",
    ]
    if handoff.get("pending_handoffs"):
        pending = handoff["pending_handoffs"]
        summary_lines.append(f"Pending handoffs: {len(pending)}")
    if handoff.get("published_artifacts"):
        artifacts = handoff["published_artifacts"]
        summary_lines.append(f"Published artifacts: {len(artifacts)}")

    return ContextPacket(
        mode=ContextMode.HANDOFF,
        repo=repo,
        request_sha256=request_sha256,
        subsystems=[],
        active_work=active_work,
        recommended_context=recommended_context,
        do_not_touch=do_not_touch,
        summary_text="\n".join(summary_lines),
        warnings=warnings,
    )


def _build_collision_packet(
    request: ContextRequest,
    root: Path,
    repo: Any,
    request_sha256: str,
    warnings: list[dict[str, Any]],
) -> ContextPacket:
    store_root = root / ".build" / "rig-relay" / "coordination"
    requesting_paths = request.scope.paths if request.scope.paths else []
    collision: dict[str, Any] = {}
    try:
        from rig_relay.compiler.context.collision import compile_collision_report

        collision = compile_collision_report(requesting_paths, store_root)
    except Exception as e:
        _emit_context_trace(
            "context.collision_degraded",
            payload={
                "coordination_store_available": False,
                "error": exception_class_name(e),
            },
        )
        warnings.append(
            build_warning(
                ContextWarningCode.COLLISION_DEGRADED,
                detail=f"{exception_class_name(e)}: collision compile failed",
                source="compiler._build_collision_packet",
            )
        )
        collision = {
            "requested_paths": requesting_paths,
            "conflicting_paths": [],
            "conflict_detail": [],
            "safe_paths": [],
            "recommended_actions": [],
            "overall_risk": "unknown",
            "evidence_status": "degraded",
            "degraded_reason": f"collision compilation failed: {exception_class_name(e)}",
        }

    coll_evidence = collision.get("evidence_status")
    if coll_evidence in {"missing", "degraded"}:
        _emit_context_trace(
            "context.collision_degraded",
            payload={
                "coordination_store_available": False,
                "evidence_status": coll_evidence,
                "degraded_reason": collision.get("degraded_reason", ""),
            },
        )
        warnings.append(
            build_warning(
                ContextWarningCode.COLLISION_DEGRADED,
                detail=f"collision evidence {coll_evidence}",
                source="compiler._build_collision_packet",
            )
        )

    conflicting = collision.get("conflicting_paths", [])
    conflict_detail = collision.get("conflict_detail", [])
    safe_paths = collision.get("safe_paths", [])

    collision_warnings_list: list[dict[str, Any]] = [
        {
            "path": cd.get("path", ""),
            "claimed_by": cd.get("current_holder", ""),
            "reason": (
                f"severity={cd.get('conflict_severity', '?')}"
                f" expiry={cd.get('lease_expiry', '?')}"
            ),
        }
        for cd in conflict_detail
    ]

    active_work: dict[str, Any] = {
        "lanes": [],
        "collision_warnings": collision_warnings_list,
    }

    do_not_touch = [
        PathRecommendation(path=p, reason="Path conflict detected") for p in conflicting
    ]
    recommended_context = [
        PathRecommendation(path=p, reason="Safe path") for p in safe_paths
    ]

    overall_risk = collision.get("overall_risk", "none")
    summary_lines = [
        "Collision mode: path conflict detection",
        f"Requested paths: {len(requesting_paths)}",
        f"Conflicting paths: {len(conflicting)}",
        f"Safe paths: {len(safe_paths)}",
        f"Overall risk: {overall_risk}",
    ]

    return ContextPacket(
        mode=ContextMode.COLLISION,
        repo=repo,
        request_sha256=request_sha256,
        subsystems=[],
        active_work=active_work,
        recommended_context=recommended_context,
        do_not_touch=do_not_touch,
        summary_text="\n".join(summary_lines),
        warnings=warnings,
    )


def _build_symbols_packet(
    request: ContextRequest,
    root: Path,
    repo: Any,
    request_sha256: str,
    warnings: list[dict[str, Any]],
) -> ContextPacket:
    source_paths = request.scope.paths if request.scope.paths else None
    try:
        from rig_relay.compiler.context.symbols import compile_symbol_packet

        symbols = compile_symbol_packet(source_paths)
    except Exception as e:
        warnings.append(
            build_warning(
                ContextWarningCode.SYMBOL_DIGEST_FAILED,
                detail=f"{exception_class_name(e)}: symbols compile failed",
                source="compiler._build_symbols_packet",
            )
        )
        symbols = {
            "symbol_map": {"aliases": {}, "symbols": []},
            "manifest_hash": "",
            "estimated_token_savings": 0,
            "manifest_entry_count": 0,
        }

    symbol_map = symbols.get("symbol_map", {})
    estimated_token_savings = symbols.get("estimated_token_savings", 0)
    manifest_hash = symbols.get("manifest_hash", "")

    summary_lines = [
        "Symbols mode: symbol substitution compression",
        f"Manifest entries: {symbols.get('manifest_entry_count', 0)}",
        f"Estimated token savings: {estimated_token_savings}",
        f"Manifest hash: {manifest_hash[:16] if manifest_hash else 'N/A'}",
    ]

    return ContextPacket(
        mode=ContextMode.SYMBOLS,
        repo=repo,
        request_sha256=request_sha256,
        subsystems=[],
        active_work={},
        symbol_map=symbol_map,
        summary_text="\n".join(summary_lines),
        warnings=warnings,
    )
