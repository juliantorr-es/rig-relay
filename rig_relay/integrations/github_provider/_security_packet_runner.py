from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import uuid

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.github_provider._redaction import (
    assert_content_light_mapping,
    safe_summary,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKET_INDEX_PATH = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_mission_packets_v1.v1.json"
)
_OPERATING_PICTURE_PATH = (
    _REPO_ROOT / "docs" / "json" / "governance" / "github_operating_picture_v1.v1.json"
)

_VALIDATION_COMMANDS = [
    "uv run python scripts/rig_relay_validate_schemas.py",
    "uv run pytest tests/integrations/test_github_security_packet_runner.py -v",
    "uv run pytest tests/adversarial/test_github_security_packet_runner_redaction.py -v",
    "uv run pytest tests/governance/test_github_security_packet_runner_artifact.py -v",
]


class GitHubSecurityPacketRunnerError(Exception):
    """Raised when packet runner plan generation fails."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else str(value) if value is not None else ""


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _as_bool(value: object) -> bool:
    return bool(value) if value is not None else False


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path) -> dict | None:
    try:
        result = read_safe(path)
        return json.loads(result.text)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _build_plan_item(packet: dict) -> dict:
    packet_id = _as_str(packet.get("packet_id"))
    candidate_id = _as_str(packet.get("mission_candidate_id"))
    route = _as_str(packet.get("route"))
    source_surface = _as_str(packet.get("source_surface"))
    normalized_severity = _as_str(packet.get("normalized_severity"))
    priority = _as_str(packet.get("priority"))
    source_alert_count = _as_int(packet.get("source_alert_count"))
    mission_type = _as_str(packet.get("mission_type"))

    lane_map = {
        "investigate_security_alert": "code_scanning_investigation",
        "dependency_update_plan": "dependency_management",
        "permission_enablement_plan": "permission_follow_up",
        "advisory_record": "advisory_triage",
        "refusal_record": "refusal_analysis",
        "unknown_security_work": "manual_triage",
    }
    local_lane_type = lane_map.get(mission_type, "manual_triage")

    category_map = {
        "code_scanning_investigation": [
            "codeql_security",
            "code_quality",
            "workflow_or_ci",
        ],
        "dependency_management": ["dependency_updates", "supply_chain"],
        "permission_follow_up": ["permissions", "enablement"],
        "advisory_triage": ["advisory", "review"],
        "refusal_analysis": ["refusal", "diagnosis"],
        "manual_triage": ["unknown", "investigation"],
    }
    expected_categories = category_map.get(local_lane_type, ["unknown"])

    return {
        "plan_item_id": _sha256_text(f"plan:{packet_id}:{_now_iso()}"),
        "packet_id": packet_id,
        "candidate_id": candidate_id,
        "route": route,
        "source_surface": source_surface,
        "severity_summary": {
            "normalized_severity": normalized_severity,
            "priority": priority,
            "source_alert_count": source_alert_count,
        },
        "local_lane_type": local_lane_type,
        "expected_local_categories": expected_categories,
        "required_validation_commands": list(_VALIDATION_COMMANDS),
        "remote_mutation": False,
        "apply_local": False,
        "status": "planned",
    }


def _check_packet_index_stale(operating_picture: dict) -> bool:
    packet_summary = _as_dict(operating_picture.get("packet_summary"))
    return _as_bool(packet_summary.get("packet_index_stale"))


def _check_remote_mutation_requested(operating_picture: dict) -> bool:
    return _as_bool(operating_picture.get("remote_mutation"))


def _select_packets(
    packets: list[dict], *, limit: int = 3, packet_ids: list[str] | None = None
) -> list[dict]:
    if packet_ids:
        selected = [p for p in packets if _as_str(p.get("packet_id")) in packet_ids]
        return sorted(selected, key=lambda p: _as_str(p.get("packet_id")))
    header_packets = sorted(packets, key=lambda p: _as_str(p.get("packet_id")))
    return header_packets[:limit]


@dataclass(slots=True)
class GitHubSecurityPacketRunnerPlan:
    packet_index_path: Path = field(default_factory=lambda: _PACKET_INDEX_PATH)
    operating_picture_path: Path = field(
        default_factory=lambda: _OPERATING_PICTURE_PATH
    )
    limit: int = 3
    packet_ids: list[str] | None = None

    def build(
        self, *, receipt_id: str | None = None, trace_id: str | None = None
    ) -> dict:
        receipt_id = receipt_id or _new_uuid()
        trace_id = trace_id or _new_uuid()

        packet_index = _read_json(self.packet_index_path)
        operating_picture = _read_json(self.operating_picture_path)

        refusals: list[dict] = []

        if packet_index is None:
            refusals.append({
                "reason": "packet_index_missing",
                "detail": f"Packet index not found or unreadable at {self.packet_index_path}.",
            })
            return self._build_refusal_plan(
                source_index_hash="",
                packet_count=0,
                refusals=refusals,
                receipt_id=receipt_id,
                trace_id=trace_id,
            )

        source_index_hash = _sha256_text(json.dumps(packet_index, sort_keys=True))

        if operating_picture is not None and _check_packet_index_stale(
            operating_picture
        ):
            refusals.append({
                "reason": "packet_index_stale",
                "detail": "The mission packet index is stale. Re-run packet generation before planning.",
            })

        if operating_picture is not None and _check_remote_mutation_requested(
            operating_picture
        ):
            refusals.append({
                "reason": "remote_mutation_requested",
                "detail": "Remote mutation is not allowed in this wave. Refusing to build plan.",
            })

        packets = _as_list(packet_index.get("packets"))
        packet_count = len(packets)

        if packet_count == 0:
            refusals.append({
                "reason": "no_packets_available",
                "detail": "Zero packets in the mission packet index. Nothing to plan.",
            })

        if refusals:
            return self._build_refusal_plan(
                source_index_hash=source_index_hash,
                packet_count=packet_count,
                refusals=refusals,
                receipt_id=receipt_id,
                trace_id=trace_id,
            )

        selected = _select_packets(
            packets, limit=self.limit, packet_ids=self.packet_ids
        )
        selection_mode = (
            "by_packet_id"
            if self.packet_ids
            else ("all" if self.limit >= packet_count else "default_limit")
        )
        plan_items = [_build_plan_item(packet) for packet in selected]

        return self._build_plan(
            source_index_hash=source_index_hash,
            selected_packet_count=len(selected),
            total_available_packets=packet_count,
            selection_mode=selection_mode,
            plan_items=plan_items,
            receipt_id=receipt_id,
            trace_id=trace_id,
        )

    def _build_base_report(
        self, *, source_index_hash: str, receipt_id: str, trace_id: str
    ) -> dict:
        return {
            "schema_version": "rig.github.security_packet_runner_plan.v1",
            "generated_at": _now_iso(),
            "source_packet_index_path": str(self.packet_index_path),
            "source_packet_index_hash": source_index_hash,
            "content_light": True,
            "remote_mutation": False,
            "apply_local": False,
            "limit": self.limit,
            "selected_packet_count": 0,
            "total_available_packets": 0,
            "selection_mode": "default_limit",
            "plan_items": [],
            "refusals": [],
            "validation_commands": list(_VALIDATION_COMMANDS),
            "summary": {
                "plan_item_count": 0,
                "refusal_count": 0,
                "status_summary": {"planned": 0, "blocked": 0, "refused": 0},
                "next_recommended_action": "review_plan",
            },
        }

    def _build_plan(
        self,
        *,
        source_index_hash: str,
        selected_packet_count: int,
        total_available_packets: int,
        selection_mode: str,
        plan_items: list[dict],
        receipt_id: str,
        trace_id: str,
    ) -> dict:
        report = self._build_base_report(
            source_index_hash=source_index_hash,
            receipt_id=receipt_id,
            trace_id=trace_id,
        )
        report["selected_packet_count"] = selected_packet_count
        report["total_available_packets"] = total_available_packets
        report["selection_mode"] = selection_mode
        report["plan_items"] = plan_items
        report["summary"] = {
            "plan_item_count": selected_packet_count,
            "refusal_count": 0,
            "status_summary": {
                "planned": selected_packet_count,
                "blocked": 0,
                "refused": 0,
            },
            "next_recommended_action": "run_plan_lane",
        }
        return self._finalize(report)

    def _build_refusal_plan(
        self,
        *,
        source_index_hash: str,
        packet_count: int,
        refusals: list[dict],
        receipt_id: str,
        trace_id: str,
    ) -> dict:
        report = self._build_base_report(
            source_index_hash=source_index_hash,
            receipt_id=receipt_id,
            trace_id=trace_id,
        )
        report["total_available_packets"] = packet_count
        report["refusals"] = refusals
        report["selection_mode"] = "default_limit"
        report["summary"] = {
            "plan_item_count": 0,
            "refusal_count": len(refusals),
            "status_summary": {"planned": 0, "blocked": 0, "refused": len(refusals)},
            "next_recommended_action": "resolve_refusals_first",
        }
        return self._finalize(report)

    def _finalize(self, report: dict) -> dict:
        assert_content_light_mapping(report)
        return safe_summary(report)


def build_github_security_packet_runner_plan(
    *,
    packet_index_path: Path | None = None,
    operating_picture_path: Path | None = None,
    limit: int = 3,
    packet_ids: list[str] | None = None,
    receipt_id: str | None = None,
    trace_id: str | None = None,
) -> dict:
    return GitHubSecurityPacketRunnerPlan(
        packet_index_path=packet_index_path or _PACKET_INDEX_PATH,
        operating_picture_path=operating_picture_path or _OPERATING_PICTURE_PATH,
        limit=limit,
        packet_ids=packet_ids,
    ).build(receipt_id=receipt_id, trace_id=trace_id)


__all__ = [
    "GitHubSecurityPacketRunnerError",
    "GitHubSecurityPacketRunnerPlan",
    "build_github_security_packet_runner_plan",
]
