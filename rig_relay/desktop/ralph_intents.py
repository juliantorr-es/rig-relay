"""Ralph intent handlers — desktop HITL approval contract.

Standard intent result envelope, run_id/scan_id identity binding,
structured refusal codes, and pywebview-ready projection provider.

Core invariants:
- Approval binds to exact run_id + scan_id + panel_sha256 + mission_candidate_sha256
- Approval does not mean execution — execution_enabled always False
- Backend owns policy; frontend is a dumb renderer
- Refusal codes are desktop contract, not incidental strings

Desktop event vocabulary:
  rig.desktop.ralph.scan.requested
  rig.desktop.ralph.scan.completed
  rig.desktop.ralph.approval.requested
  rig.desktop.ralph.approval.accepted
  rig.desktop.ralph.approval.refused
  rig.desktop.ralph.decline.accepted
  rig.desktop.ralph.rescan.completed
"""

from __future__ import annotations

import uuid
from typing import Any

from rig_relay.ralph.models import ApprovalState, RunStatus
from rig_relay.ralph.scanner import (
    build_ralph_panel,
    build_run_state,
    compute_decision_request,
    compute_decision_result,
    scan_projections,
)
from rig_relay.ralph.state_store import (
    FilesystemRalphRunStateStore,
    InMemoryRalphRunStateStore,
    RalphRunStateRecord,
)
from rig_relay.ralph.decision_events import (
    DecisionEvent,
    DecisionEventStore,
)
from rig_relay.desktop.events import (
    DesktopEventRecord,
    InMemoryDesktopEventSink,
    NoOpDesktopEventSink,
)

DESKTOP_EVENTS = {
    "scan_requested": "rig.desktop.ralph.scan.requested",
    "scan_completed": "rig.desktop.ralph.scan.completed",
    "approval_requested": "rig.desktop.ralph.approval.requested",
    "approval_accepted": "rig.desktop.ralph.approval.accepted",
    "approval_refused": "rig.desktop.ralph.approval.refused",
    "decline_accepted": "rig.desktop.ralph.decline.accepted",
    "rescan_completed": "rig.desktop.ralph.rescan.completed",
}

REFUSAL_CODES = {
    "no_scan_state": "No Ralph scan found. Run ralph_scan first.",
    "stale_run_id": "Run ID does not match current state. The state has been replaced by a newer scan.",
    "stale_scan_id": "Scan ID does not match current state. A rescan has occurred.",
    "stale_panel_hash": "Panel hash does not match the current Ralph panel. Rescan to get the latest.",
    "stale_mission_hash": "Mission candidate hash has changed. Rescan to approve against the current candidate.",
    "missing_mission_candidate": "No mission candidate is present in the current scan.",
    "unsupported_action": "Unknown Ralph intent.",
    "invalid_payload": "Required payload fields are missing or invalid.",
    "execution_disabled": "Mission execution is not yet implemented.",
    "internal_error": "An unexpected error occurred.",
}

INTENT_RESULT_VERSION = "rig.desktop.intent_result.v1"

_RALPH_STATE: dict[str, Any] = {}
_state_store = InMemoryRalphRunStateStore()
_decision_store = DecisionEventStore()
_event_sink = InMemoryDesktopEventSink()


def set_state_store(store: Any) -> None:
    global _state_store
    _state_store = store


def set_event_sink(sink: Any) -> None:
    global _event_sink
    _event_sink = sink


def build_ralph_projection() -> dict[str, Any]:
    """Return a desktop-ready Ralph projection for pywebview.

    Returns idle/no-scan state when no scan has been run.
    """
    stored = _RALPH_STATE

    if not stored or not stored.get("panel_sha256"):
        return {
            "schema_version": "rig.ui.ralph_panel.v1",
            "status": "idle",
            "decision_required": False,
            "approval_state": ApprovalState.NOT_REQUESTED.value,
            "run_id": "",
            "scan_id": "",
            "panel_sha256": "",
            "mission_candidate_sha256": "",
            "input_snapshot_sha256": "",
            "top_candidate": None,
            "ranked_candidates": [],
            "mission_candidate": None,
            "available_actions": [
                {"action": "ralph_scan", "label": "Scan", "requires_confirmation": False},
            ],
            "latest_intent_result": None,
            "execution_enabled": False,
        }

    panel = stored.get("cached_panel")
    return {
        "schema_version": "rig.ui.ralph_panel.v1",
        "status": "ready",
        "decision_required": stored.get("decision_required", False),
        "approval_state": stored.get("approval_state", ApprovalState.NOT_REQUESTED.value),
        "run_id": stored.get("run_id", ""),
        "scan_id": stored.get("scan_id", ""),
        "panel_sha256": stored.get("panel_sha256", ""),
        "mission_candidate_sha256": stored.get("mission_candidate_sha256", ""),
        "input_snapshot_sha256": stored.get("input_snapshot_sha256", ""),
        "top_candidate": panel.get("top_candidate") if panel else None,
        "ranked_candidates": panel.get("ranked_candidates", []) if panel else [],
        "mission_candidate": panel.get("mission_candidate") if panel else None,
        "available_actions": _available_actions(stored),
        "latest_intent_result": stored.get("latest_intent_result"),
        "execution_enabled": False,
    }


def execute_ralph_intent(
    intent_name: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = params or {}

    handlers: dict[str, Any] = {
        "ralph_scan": lambda: _handle_ralph_scan(params),
        "ralph_approve": lambda: _handle_ralph_approve(params),
        "ralph_decline": lambda: _handle_ralph_decline(params),
        "ralph_rescan": lambda: _handle_ralph_rescan(params),
        "ralph_background_toggle_on": lambda: _handle_background_toggle(True),
        "ralph_background_toggle_off": lambda: _handle_background_toggle(False),
    }

    handler = handlers.get(intent_name)
    if handler is None:
        return _refuse("unsupported_action", intent_kind=intent_name)

    try:
        return handler()
    except Exception as exc:
        return _refuse("internal_error", intent_kind=intent_name, message=str(exc))


def _handle_ralph_scan(params: dict[str, Any]) -> dict[str, Any]:
    _event_sink.emit(DesktopEventRecord(
        event_name="rig.desktop.ralph.scan.requested",
        intent_kind="ralph_scan",
    ))

    result = scan_projections()
    panel = build_ralph_panel(result)
    run_state = build_run_state(panel)

    scan_id = result.scan_id
    run_id = str(uuid.uuid4())

    _store_state(panel, run_state, run_id, scan_id)

    record = RalphRunStateRecord(
        run_id=run_id,
        scan_id=scan_id,
        status=run_state.status,
        phase=run_state.phase,
        approval_state=panel.approval_state,
        panel_sha256=panel.panel_sha256,
        mission_candidate_sha256=panel.mission_candidate_sha256,
        input_snapshot_sha256=panel.input_snapshot_sha256,
        selected_candidate_id=(
            panel.top_candidate.candidate_id if panel.top_candidate else ""
        ),
        decision_required=panel.decision_required,
        execution_enabled=False,
    )
    _state_store.save_run_state(record)
    _state_store.mark_current_run(run_id)

    panel_dict = panel.model_dump(mode="json")
    _RALPH_STATE["cached_panel"] = panel_dict
    _RALPH_STATE["latest_intent_result"] = {
        "intent_kind": "ralph_scan",
        "ok": True,
        "status": "completed",
        "message": f"Scan completed: {panel.summary.candidate_count} candidates, top score={panel.summary.top_score:.1f}",
    }

    _event_sink.emit(DesktopEventRecord(
        event_name="rig.desktop.ralph.scan.completed",
        intent_kind="ralph_scan",
        run_id=run_id,
        scan_id=scan_id,
        panel_sha256=panel.panel_sha256,
        mission_candidate_sha256=panel.mission_candidate_sha256,
        ok=True,
        status="completed",
        execution_enabled=False,
    ))

    return _ok(
        "ralph_scan",
        message=f"Scan completed: {panel.summary.candidate_count} candidates, top score={panel.summary.top_score:.1f}",
        ralph_panel=panel_dict,
        ralph_run_state=run_state.model_dump(mode="json"),
    )


def _handle_ralph_approve(params: dict[str, Any]) -> dict[str, Any]:
    submitted_run_id = params.get("run_id", "")
    submitted_scan_id = params.get("scan_id", "")
    submitted_panel_sha = params.get("panel_sha256", "")
    submitted_mission_sha = params.get("mission_candidate_sha256", "")

    _event_sink.emit(DesktopEventRecord(
        event_name="rig.desktop.ralph.approval.requested",
        intent_kind="ralph_approve",
        run_id=submitted_run_id,
        scan_id=submitted_scan_id,
        panel_sha256=submitted_panel_sha,
        mission_candidate_sha256=submitted_mission_sha,
    ))

    if not submitted_panel_sha or not submitted_mission_sha:
        return _refuse_with_event("invalid_payload", intent_kind="ralph_approve",
                                 message="panel_sha256 and mission_candidate_sha256 are required",
                                 run_id=submitted_run_id)

    stored = _RALPH_STATE
    approval_before = stored.get("approval_state", ApprovalState.NOT_REQUESTED.value)

    if not stored.get("panel_sha256"):
        return _refuse_with_event("no_scan_state", intent_kind="ralph_approve",
                                 run_id=submitted_run_id)

    if submitted_run_id and submitted_run_id != stored.get("run_id"):
        return _refuse_with_event("stale_run_id", intent_kind="ralph_approve",
                                 message=f"Run ID mismatch: your approval binds to a stale state. Rescan.",
                                 run_id=submitted_run_id)

    if submitted_scan_id and submitted_scan_id != stored.get("scan_id"):
        return _refuse_with_event("stale_scan_id", intent_kind="ralph_approve",
                                 message=f"Scan ID mismatch: a rescan has occurred since you loaded this panel.",
                                 run_id=submitted_run_id)

    if submitted_panel_sha != stored["panel_sha256"]:
        return _refuse_with_event("stale_panel_hash", intent_kind="ralph_approve",
                                 message=f"Panel hash mismatch.", run_id=submitted_run_id)

    if submitted_mission_sha != stored["mission_candidate_sha256"]:
        return _refuse_with_event("stale_mission_hash", intent_kind="ralph_approve",
                                 message=f"Mission candidate hash mismatch.", run_id=submitted_run_id)

    if not stored.get("decision_required"):
        return _refuse_with_event("missing_mission_candidate", intent_kind="ralph_approve",
                                 run_id=submitted_run_id)

    stored["approval_state"] = ApprovalState.APPROVED.value
    stored["run_status"] = RunStatus.COMPLETED.value

    decision_id = stored.get("decision_id", "")
    candidate_id = stored.get("selected_candidate_id", "")
    decision = compute_decision_result(
        decision_id=decision_id,
        scan_id="",
        candidate_id=candidate_id,
        decision=ApprovalState.APPROVED.value,
        rationale=params.get("rationale", "Approved by user"),
    )

    _emit_decision_event(
        event_kind="ralph.decision.approved",
        run_id=stored["run_id"],
        scan_id=stored["scan_id"],
        panel_sha=stored["panel_sha256"],
        mission_sha=stored["mission_candidate_sha256"],
        input_sha=stored.get("input_snapshot_sha256", ""),
        decision_action="approve_read_only_mission",
        approval_before=approval_before,
        approval_after=ApprovalState.APPROVED.value,
        status="completed",
    )

    _event_sink.emit(DesktopEventRecord(
        event_name="rig.desktop.ralph.approval.accepted",
        intent_kind="ralph_approve",
        run_id=stored["run_id"],
        scan_id=stored["scan_id"],
        panel_sha256=stored["panel_sha256"],
        mission_candidate_sha256=stored["mission_candidate_sha256"],
        ok=True,
        status="completed",
        execution_enabled=False,
    ))

    _persist_current_state(stored)

    stored["latest_intent_result"] = {
        "intent_kind": "ralph_approve",
        "ok": True,
        "status": "approved",
        "message": "Mission candidate approved. Execution is not yet implemented.",
    }

    cached = stored.get("cached_panel") or {}
    cached["approval_state"] = ApprovalState.APPROVED.value
    stored["cached_panel"] = cached

    return _ok(
        "ralph_approve",
        message="Mission candidate approved. Execution is not yet implemented.",
        ralph_panel=cached,
        decision_result=decision.model_dump(mode="json"),
        next_phase="execution_pending_implementation",
        approval_state=ApprovalState.APPROVED.value,
        run_status=RunStatus.COMPLETED.value,
    )


def _handle_ralph_decline(params: dict[str, Any]) -> dict[str, Any]:
    submitted_run_id = params.get("run_id", "")
    submitted_scan_id = params.get("scan_id", "")
    submitted_panel_sha = params.get("panel_sha256", "")
    submitted_mission_sha = params.get("mission_candidate_sha256", "")

    if not submitted_panel_sha or not submitted_mission_sha:
        return _refuse("invalid_payload", intent_kind="ralph_decline",
                       message="panel_sha256 and mission_candidate_sha256 are required")

    stored = _RALPH_STATE

    if not stored.get("panel_sha256"):
        return _refuse("no_scan_state", intent_kind="ralph_decline")

    if submitted_run_id and submitted_run_id != stored.get("run_id"):
        return _refuse("stale_run_id", intent_kind="ralph_decline")

    if submitted_scan_id and submitted_scan_id != stored.get("scan_id"):
        return _refuse("stale_scan_id", intent_kind="ralph_decline")

    if submitted_panel_sha != stored["panel_sha256"]:
        return _refuse("stale_panel_hash", intent_kind="ralph_decline")

    stored["approval_state"] = ApprovalState.DECLINED.value
    stored["run_status"] = RunStatus.REFUSED.value

    decision_id = stored.get("decision_id", "")
    candidate_id = stored.get("selected_candidate_id", "")
    decision = compute_decision_result(
        decision_id=decision_id,
        scan_id="",
        candidate_id=candidate_id,
        decision=ApprovalState.DECLINED.value,
        rationale=params.get("rationale", "Declined by user"),
    )

    stored["latest_intent_result"] = {
        "intent_kind": "ralph_decline",
        "ok": True,
        "status": "declined",
        "message": "Mission candidate declined.",
    }

    cached = stored.get("cached_panel") or {}
    cached["approval_state"] = ApprovalState.DECLINED.value
    stored["cached_panel"] = cached

    return _ok(
        "ralph_decline",
        message="Mission candidate declined.",
        ralph_panel=cached,
        decision_result=decision.model_dump(mode="json"),
        next_phase="closed",
        approval_state=ApprovalState.DECLINED.value,
        run_status=RunStatus.REFUSED.value,
    )


def _handle_ralph_rescan(params: dict[str, Any]) -> dict[str, Any]:
    _RALPH_STATE.clear()
    return _handle_ralph_scan(params)


def _handle_background_toggle(enabled: bool) -> dict[str, Any]:
    """Toggle Ralph background lanes on/off. Contract-only — no lane execution."""
    action = "ralph_background_toggle_on" if enabled else "ralph_background_toggle_off"
    from rig_relay.ralph.background_policy import demo_policy, default_policy

    policy = demo_policy() if enabled else default_policy()
    stored_policy = {
        "enabled": policy.enabled,
        "isolated_lane_execution_enabled": policy.allow_isolated_lane_execution if enabled else False,
        "live_runtime_mutation_enabled": False,
        "merge_enabled": False,
        "push_enabled": False,
    }

    return _ok(
        action,
        message=f"Ralph background lanes {'enabled' if enabled else 'disabled'}.",
        ralph_panel=stored_policy,
    )


def _store_state(panel: Any, run_state: Any, run_id: str, scan_id: str) -> None:
    req = compute_decision_request(panel)
    _RALPH_STATE.clear()
    _RALPH_STATE.update({
        "run_id": run_id,
        "scan_id": scan_id,
        "panel_sha256": panel.panel_sha256,
        "mission_candidate_sha256": panel.mission_candidate_sha256,
        "input_snapshot_sha256": panel.input_snapshot_sha256,
        "approval_state": panel.approval_state,
        "run_status": run_state.status,
        "selected_candidate_id": (
            panel.top_candidate.candidate_id if panel.top_candidate else ""
        ),
        "decision_id": req.decision_id if req else "",
        "decision_required": panel.decision_required,
        "execution_enabled": False,
    })


def _ok(
    intent_kind: str,
    message: str = "",
    ralph_panel: dict[str, Any] | None = None,
    ralph_run_state: dict[str, Any] | None = None,
    decision_result: dict[str, Any] | None = None,
    next_phase: str = "",
    approval_state: str = "",
    run_status: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": INTENT_RESULT_VERSION,
        "intent_kind": intent_kind,
        "ok": True,
        "status": "completed",
        "error_code": None,
        "message": message,
        "execution_enabled": False,
    }
    if ralph_panel:
        result["ralph"] = {"panel": ralph_panel}
    if ralph_run_state:
        result.setdefault("ralph", {})["run_state"] = ralph_run_state
    if decision_result:
        result["decision_result"] = decision_result
    if next_phase:
        result["next_phase"] = next_phase
    if approval_state:
        result["approval_state"] = approval_state
    if run_status:
        result["run_status"] = run_status
    return result


def _refuse(
    error_code: str,
    intent_kind: str = "",
    message: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": INTENT_RESULT_VERSION,
        "intent_kind": intent_kind,
        "ok": False,
        "status": "refused",
        "error_code": error_code,
        "message": message or REFUSAL_CODES.get(error_code, "Unknown refusal"),
        "execution_enabled": False,
    }


def _available_actions(stored: dict[str, Any]) -> list[dict[str, str | bool]]:
    actions = [{"action": "ralph_scan", "label": "Scan", "requires_confirmation": False}]
    if stored.get("decision_required") and stored.get("panel_sha256"):
        actions.extend([
            {"action": "ralph_approve", "label": "Approve", "requires_confirmation": True},
            {"action": "ralph_decline", "label": "Decline", "requires_confirmation": True},
        ])
    actions.append({"action": "ralph_rescan", "label": "Rescan", "requires_confirmation": False})
    return actions


def _refuse_with_event(
    error_code: str,
    intent_kind: str = "",
    message: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    result = _refuse(error_code, intent_kind=intent_kind, message=message)

    _event_sink.emit(DesktopEventRecord(
        event_name="rig.desktop.ralph.approval.refused",
        intent_kind=intent_kind,
        run_id=run_id,
        ok=False,
        status="refused",
        error_code=error_code,
        execution_enabled=False,
    ))

    _emit_decision_event(
        event_kind="ralph.decision.refused",
        run_id=run_id,
        scan_id="",
        panel_sha="",
        mission_sha="",
        input_sha="",
        decision_action=intent_kind,
        approval_before="not_requested",
        approval_after="not_requested",
        status="refused",
        error_code=error_code,
    )

    return result


def _emit_decision_event(
    event_kind: str,
    run_id: str,
    scan_id: str,
    panel_sha: str,
    mission_sha: str,
    input_sha: str,
    decision_action: str,
    approval_before: str,
    approval_after: str,
    status: str,
    error_code: str | None = None,
) -> None:
    event = DecisionEvent(
        event_kind=event_kind,
        run_id=run_id,
        scan_id=scan_id,
        panel_sha256=panel_sha,
        mission_candidate_sha256=mission_sha,
        input_snapshot_sha256=input_sha,
        decision_action=decision_action,
        approval_state_before=approval_before,
        approval_state_after=approval_after,
        status=status,
        error_code=error_code,
        execution_enabled=False,
    )
    _decision_store.append_event(event)
    _decision_store.create_receipt(event)


def _persist_current_state(stored: dict[str, Any]) -> None:
    try:
        record = _state_store.load_current_run_state()
        if record:
            record.approval_state = stored.get("approval_state", record.approval_state)
            record.status = stored.get("run_status", record.status)
            if stored.get("latest_decision_event_id"):
                record.latest_decision_event_id = stored["latest_decision_event_id"]
            _state_store.save_run_state(record)
    except Exception:
        pass
