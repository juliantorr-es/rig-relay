from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PLAN_JSON = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_packet_runner_plan_v1.v1.json"
)
_DEFAULT_OPERATING_PICTURE_JSON = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_operating_picture_v1.v1.json"
)

_VALIDATION_COMMANDS = [
    "uv run python scripts/rig_relay_validate_schemas.py",
    "uv run pytest tests/integrations/test_github_security_packet_execution.py -v",
    "uv run pytest tests/adversarial/test_github_security_packet_execution_redaction.py -v",
    "uv run pytest tests/governance/test_github_security_packet_execution_artifact.py -v",
]

_MAX_SAFE_LIMIT = 3


class GitHubSecurityPacketExecutionError(Exception):
    """Raised when packet execution fails."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else str(value) if value is not None else ""


def _as_bool(value: object) -> bool:
    return bool(value) if value is not None else False


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path) -> dict | None:
    try:
        result = read_safe(path)
        data = json.loads(result.text)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _check_packet_index_stale(operating_picture: dict) -> bool:
    packet_summary = _as_dict(operating_picture.get("packet_summary"))
    return _as_bool(packet_summary.get("packet_index_stale"))


def _check_remote_mutation_requested(operating_picture: dict) -> bool:
    return _as_bool(operating_picture.get("remote_mutation"))


def _inspect_plan_item(plan_item: dict) -> dict:
    packet_id = _as_str(plan_item.get("packet_id"))
    candidate_id = _as_str(plan_item.get("candidate_id"))
    route = _as_str(plan_item.get("route"))
    source_surface = _as_str(plan_item.get("source_surface"))
    severity_summary = _as_dict(plan_item.get("severity_summary"))
    local_lane_type = _as_str(plan_item.get("local_lane_type"))
    required_commands = _as_list(plan_item.get("required_validation_commands"))
    apply_local = _as_bool(plan_item.get("apply_local"))

    result_status = _determine_status(route, source_surface, apply_local)
    remediation = _build_remediation(result_status, local_lane_type, source_surface)

    execution_id = _sha256_text(f"exec:{packet_id}:{_now_iso()}")

    return {
        "execution_id": execution_id,
        "packet_id": packet_id,
        "candidate_id": candidate_id,
        "route": route,
        "source_surface": source_surface,
        "severity_summary": severity_summary,
        "local_lane_type": local_lane_type,
        "result_status": result_status,
        "remediation_recommendation": remediation,
        "required_validation_commands": required_commands,
        "evidence_refs": [f"packet_id:{packet_id}", f"candidate_id:{candidate_id}"],
        "source_artifact_hashes": {"packet_id": packet_id},
        "remote_mutation": False,
        "local_mutation": False,
        "content_light": True,
    }


def _determine_status(route: str, source_surface: str, apply_local: bool) -> str:
    if apply_local:
        return "needs_local_remediation"
    if route == "permission_required":
        return "permission_blocked"
    if route == "advisory_only":
        return "advisory_only"
    if source_surface == "refusal":
        return "skipped"
    if route in {"ready_for_investigation", "ready_for_dependency_update"}:
        return "inspected"
    return "needs_human_review"


_REMEDIATION_TEMPLATES = {
    ("inspected", "code_scanning_investigation"): (
        "Investigation complete. Code scanning alert metadata inspected. "
        "Human review recommended to classify true/false positive. "
        "No local remediation can be generated without source code inspection."
    ),
    ("needs_local_remediation", "code_scanning_investigation"): (
        "Local remediation may be possible after source inspection. "
        "Requires human approval and apply-local flag to proceed."
    ),
    ("advisory_only",): "Alert is advisory. No remediation needed. Mark as reviewed.",
    (
        "permission_blocked",
    ): "Permission required to access alert details. Request maintainer to grant permission.",
    (
        "skipped",
    ): "Packet source surface is refused. Cannot investigate without upstream data.",
    (
        "needs_human_review",
    ): "Ambiguous or unknown route. Requires human classification.",
}


def _build_remediation(
    result_status: str, local_lane_type: str, source_surface: str
) -> str:
    key = (result_status, local_lane_type)
    if key in _REMEDIATION_TEMPLATES:
        return _REMEDIATION_TEMPLATES[key]
    generic = _REMEDIATION_TEMPLATES.get((result_status,))
    if generic is not None:
        return generic
    return "No specific remediation available."


def _select_plan_items(
    plan_items: list[dict], *, limit: int = 1, packet_ids: list[str] | None = None
) -> list[dict]:
    if packet_ids:
        selected = [p for p in plan_items if _as_str(p.get("packet_id")) in packet_ids]
        return sorted(selected, key=lambda p: _as_str(p.get("packet_id")))
    sorted_items = sorted(plan_items, key=lambda p: _as_str(p.get("packet_id")))
    return sorted_items[:limit]


def _build_summary(results: list[dict], selected_count: int) -> dict:
    status_counts = {
        "needs_local_remediation": 0,
        "needs_human_review": 0,
        "permission_blocked": 0,
        "advisory_only": 0,
        "skipped": 0,
    }
    for r in results:
        status = _as_str(r.get("result_status"))
        if status in status_counts:
            status_counts[status] += 1

    needs_local_remediation = status_counts["needs_local_remediation"]
    needs_human = status_counts["needs_human_review"]
    total_result_count = len(results)

    if needs_local_remediation > 0:
        next_action = "create_local_patch_plan"
    elif status_counts["permission_blocked"] > 0:
        next_action = "request_permission"
    elif status_counts["advisory_only"] > 0:
        next_action = "mark_advisory"
    elif total_result_count < selected_count:
        next_action = "run_more_packets"
    else:
        next_action = "no_action"

    return {
        "selected_count": selected_count,
        "executed_count": total_result_count,
        "needs_local_remediation_count": needs_local_remediation,
        "needs_human_review_count": needs_human,
        "permission_blocked_count": status_counts["permission_blocked"],
        "advisory_only_count": status_counts["advisory_only"],
        "skipped_count": status_counts["skipped"],
        "next_recommended_action": next_action,
    }


@dataclass(slots=True)
class GitHubSecurityPacketExecutor:
    plan_path: Path = field(default_factory=lambda: _DEFAULT_PLAN_JSON)
    operating_picture_path: Path = field(
        default_factory=lambda: _DEFAULT_OPERATING_PICTURE_JSON
    )
    limit: int = 1
    packet_ids: list[str] | None = None
    refuse_local_apply: bool = True

    def execute(self) -> dict:
        operating_picture = _read_json(self.operating_picture_path)
        plan = _read_json(self.plan_path)

        refusal = self._validate_prerequisites(plan, operating_picture)
        if refusal is not None:
            return self._refusal_report(refusal[0], refusal[1])

        if self.limit > _MAX_SAFE_LIMIT:
            return self._refusal_report(
                "unsafe_large_run",
                f"limit={self.limit} exceeds max safe limit of {_MAX_SAFE_LIMIT}.",
            )

        assert plan is not None
        plan_items = _as_list(plan.get("plan_items"))
        selected = _select_plan_items(
            plan_items, limit=self.limit, packet_ids=self.packet_ids
        )
        results = [_inspect_plan_item(item) for item in selected]

        source_plan_hash = _sha256_file(self.plan_path)
        source_op_hash = (
            _sha256_file(self.operating_picture_path)
            if self.operating_picture_path.exists()
            else ""
        )

        report = self._build_report(
            results=results,
            source_plan_hash=source_plan_hash,
            source_op_hash=source_op_hash,
            selected_count=len(selected),
            executed_count=len(results),
        )
        return self._finalize(report)

    def _validate_prerequisites(
        self, plan: dict | None, operating_picture: dict | None
    ) -> tuple[str, str] | None:
        if plan is None:
            return ("plan_missing", "Runner plan not found or unreadable.")
        if operating_picture is not None:
            if _check_packet_index_stale(operating_picture):
                return (
                    "packet_index_stale",
                    "Packet index is stale. Re-run packet generation.",
                )
            if _check_remote_mutation_requested(operating_picture):
                return (
                    "remote_mutation_requested",
                    "Remote mutation is not allowed. Refusing execution.",
                )
        plan_items = _as_list(plan.get("plan_items"))
        if len(plan_items) == 0:
            return (
                "no_plan_items",
                "Runner plan has zero plan items. Nothing to execute.",
            )
        if (
            any(_as_bool(item.get("apply_local")) for item in plan_items)
            and self.refuse_local_apply
        ):
            return (
                "local_apply_requested",
                "Plan item has apply_local=true but --allow-local-apply was not passed.",
            )
        return None

    def _refusal_report(self, reason: str, detail: str) -> dict:
        report = self._build_report(
            results=[],
            source_plan_hash="",
            source_op_hash="",
            selected_count=0,
            executed_count=0,
        )
        report["summary"]["next_recommended_action"] = "no_action"
        return self._finalize(report)

    def _build_report(
        self,
        *,
        results: list[dict],
        source_plan_hash: str,
        source_op_hash: str,
        selected_count: int,
        executed_count: int,
    ) -> dict:
        summary = _build_summary(results, selected_count)
        return {
            "schema_version": "rig.github.security_packet_execution.v1",
            "generated_at": _now_iso(),
            "source_plan_path": str(self.plan_path),
            "source_plan_hash": source_plan_hash,
            "source_operating_picture_path": str(self.operating_picture_path),
            "source_operating_picture_hash": source_op_hash,
            "content_light": True,
            "remote_mutation": False,
            "local_mutation": False,
            "refuse_local_apply": self.refuse_local_apply,
            "limit": self.limit,
            "selected_count": selected_count,
            "executed_count": executed_count,
            "execution_results": results,
            "summary": summary,
            "validation_commands": list(_VALIDATION_COMMANDS),
        }

    def _finalize(self, report: dict) -> dict:
        assert_content_light_mapping(report)
        return safe_summary(report)


def build_github_security_packet_execution(
    *,
    plan_path: Path | None = None,
    operating_picture_path: Path | None = None,
    limit: int = 1,
    packet_ids: list[str] | None = None,
    refuse_local_apply: bool = True,
) -> dict:
    return GitHubSecurityPacketExecutor(
        plan_path=plan_path or _DEFAULT_PLAN_JSON,
        operating_picture_path=operating_picture_path
        or _DEFAULT_OPERATING_PICTURE_JSON,
        limit=limit,
        packet_ids=packet_ids,
        refuse_local_apply=refuse_local_apply,
    ).execute()


__all__ = [
    "GitHubSecurityPacketExecutionError",
    "GitHubSecurityPacketExecutor",
    "build_github_security_packet_execution",
]
