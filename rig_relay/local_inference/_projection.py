"""Local inference assistance projection builder — M0.

Produces typed, content-light projections for the Gridline Interface.
Designed for desktop/Gridline consumption: deterministic, content-safe,
non-mutating. Follows the projection pattern established in
rig_relay/desktop/projection.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from rig_relay.local_inference._models import (
    AssistanceResult,
    AssistanceTaskKind,
    OutputDisposition,
    PublicationApplicability,
)
from rig_relay.local_inference._service import LocalProjectInferenceService
from rig_relay.recovery.capability_admission import EnforcementClass

_PROJECTION_SCHEMA = "rig.relay.local_inference.assistance_projection.v1"


def build_assistance_projection(
    service: LocalProjectInferenceService, *, projection_id: str | None = None
) -> dict[str, Any]:
    """Build a content-light local inference assistance projection.

    Exposes runtime availability, capability suitability, current
    assistance results, draft status, and refusal explanations.

    Content-light: hashes, counts, statuses, classifications only.
    Never includes raw model output, prompts, or private paths.
    """
    pid = projection_id or f"liproj_{datetime.now(UTC).isoformat()}"
    now = datetime.now(UTC)
    runtime_info = service.get_runtime_info()

    tasks_available = _build_task_suitability(runtime_info)
    results = _build_results_summary(service.list_results())
    requests_awaiting_review = results.get("drafts_awaiting_review", 0)
    refusal_summary = results.get("refusals", [])
    approval_needed = requests_awaiting_review > 0

    next_actions: list[str] = []
    if not runtime_info.get("available"):
        next_actions.append("configure_local_runtime")
    if not runtime_info.get("configured"):
        next_actions.append("configure_endpoint_in_airlock")
    if requests_awaiting_review > 0:
        next_actions.append("review_drafts")
    if results.get("total_executed", 0) == 0 and runtime_info.get("available"):
        next_actions.append("exercise_capability_admission")
    if not next_actions:
        next_actions.append("no_action_needed")

    projection: dict[str, Any] = {
        "schema_version": _PROJECTION_SCHEMA,
        "projection_id": pid,
        "created_at": now.isoformat(),
        "local_runtime": {
            "available": runtime_info.get("available", False),
            "configured": runtime_info.get("configured", False),
            "endpoint_sha256": runtime_info.get("endpoint_sha256", ""),
            "runtime_kind": runtime_info.get("runtime_kind", "unknown"),
            "platform_class": runtime_info.get("platform_class", "unknown"),
        },
        "task_suitability": tasks_available,
        "assistance_results": results,
        "approval_needed": approval_needed,
        "drafts_awaiting_review": requests_awaiting_review,
        "refusal_count": len(refusal_summary),
        "refusal_explanations": refusal_summary,
        "next_actions": next_actions,
        "content_light": True,
        "raw_drafts_exposed": False,
    }

    digest_payload = {
        k: v
        for k, v in projection.items()
        if k not in {"projection_digest", "created_at", "projection_id"}
    }
    payload = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"))
    projection["projection_digest"] = (
        f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"
    )

    return projection


def _build_task_suitability(runtime_info: dict[str, Any]) -> dict[str, Any]:
    runtime_available = runtime_info.get("available", False)

    tasks: dict[str, dict[str, Any]] = {}
    for kind in AssistanceTaskKind:
        task_info = {
            "task_kind": kind.value,
            "suitable": runtime_available,
            "requires_runtime": True,
            "enforcement_class_required": _required_enforcement_for_kind(kind).value,
            "publication_applicability": _publication_applicability_for_kind(
                kind
            ).value,
            "refusal_reason": "" if runtime_available else "runtime_unavailable",
        }
        tasks[kind.value] = task_info

    return {
        "runtime_available": runtime_available,
        "runtime_kind": runtime_info.get("runtime_kind", "unknown"),
        "tasks": tasks,
    }


def _required_enforcement_for_kind(kind: AssistanceTaskKind) -> EnforcementClass:
    match kind:
        case AssistanceTaskKind.PROJECT_SUMMARY:
            return EnforcementClass.JSON_OBJECT_FORMATTING_ONLY
        case AssistanceTaskKind.PAGE_SECTION_ORDERING:
            return EnforcementClass.JSON_OBJECT_FORMATTING_ONLY
        case AssistanceTaskKind.CAPABILITY_CLASSIFICATION:
            return EnforcementClass.JSON_OBJECT_FORMATTING_ONLY
        case AssistanceTaskKind.MISSING_MATERIAL_CHECKLIST:
            return EnforcementClass.JSON_OBJECT_FORMATTING_ONLY


def _publication_applicability_for_kind(
    kind: AssistanceTaskKind,
) -> PublicationApplicability:
    match kind:
        case AssistanceTaskKind.PROJECT_SUMMARY:
            return PublicationApplicability.PROJECT_PAGE
        case AssistanceTaskKind.PAGE_SECTION_ORDERING:
            return PublicationApplicability.PROJECT_PAGE
        case AssistanceTaskKind.CAPABILITY_CLASSIFICATION:
            return PublicationApplicability.PORTFOLIO
        case AssistanceTaskKind.MISSING_MATERIAL_CHECKLIST:
            return PublicationApplicability.INTERNAL_ONLY


def _build_results_summary(results: list[AssistanceResult]) -> dict[str, Any]:
    if not results:
        return {
            "total_results": 0,
            "total_executed": 0,
            "total_refused": 0,
            "drafts_awaiting_review": 0,
            "drafts": [],
            "refusals": [],
        }

    total_executed = 0
    total_refused = 0
    drafts_awaiting_review = 0
    drafts: list[dict[str, Any]] = []
    refusals: list[dict[str, Any]] = []

    for r in results:
        is_executed = r.status in {"executed", "degraded_json_object_only"}
        if is_executed:
            total_executed += 1
        else:
            total_refused += 1

        if r.draft_sha256:
            drafts_awaiting_review += 1
            drafts.append({
                "result_id": r.result_id,
                "task_id": r.task_id,
                "draft_sha256": r.draft_sha256,
                "draft_byte_count": r.draft_byte_count,
                "output_disposition": r.output_disposition.value,
                "publication_applicability": r.publication_applicability.value,
                "requires_approval": r.output_disposition
                == OutputDisposition.DRAFT_REQUIRES_REVIEW,
                "created_at": r.created_at,
            })

        if not is_executed:
            refusals.append({
                "result_id": r.result_id,
                "task_id": r.task_id,
                "status": r.status.value,
                "refusal_reason": r.refusal_reason,
                "refusal_code": r.refusal_code,
                "created_at": r.created_at,
            })

    return {
        "total_results": len(results),
        "total_executed": total_executed,
        "total_refused": total_refused,
        "drafts_awaiting_review": drafts_awaiting_review,
        "drafts": drafts,
        "refusals": refusals,
    }


__all__ = ["build_assistance_projection"]
