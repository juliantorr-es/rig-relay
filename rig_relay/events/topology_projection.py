from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

_PRESSURE_MODERATE_THRESHOLD = 3
_PRESSURE_ELEVATED_THRESHOLD = 4
_PRESSURE_HIGH_THRESHOLD = 11

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DERIVED_DIR = _REPO_ROOT / ".build" / "rig-relay" / "derived"
_DEFAULT_DUCKDB_REPORT_PATH = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "event_fabric_duckdb_projection_report_v1.v1.json"
)
_DEFAULT_PRESSURE_SUMMARY_PATH = (
    _DERIVED_DIR / "event_fabric_resource_pressure_summary.v1.json"
)
_OUTPUT_PATH = _DERIVED_DIR / "mission_topology_projection.v1.json"

_BRIDGE_EVENT_TYPES = [
    "bridge.connection.begin",
    "bridge.auth.succeeded",
    "bridge.backend_loop.started",
    "bridge.status.updated",
    "bridge.first_status.sent",
    "bridge.heartbeat.sent",
    "bridge.backend_stale.detected",
    "bridge.disconnect",
    "bridge.backend_loop.stopped",
    "bridge.projection_loop.error",
    "bridge.reconnect_failed",
]

_NODE_BLUEPRINTS: dict[str, dict[str, Any]] = {
    "event_fabric": {"label": "Event Fabric", "node_type": "event_fabric"},
    "duckdb_projection": {
        "label": "DuckDB Projection",
        "node_type": "duckdb_projection",
    },
    "derived_artifact": {"label": "Derived Artifacts", "node_type": "derived_artifact"},
    "bridge": {"label": "Bridge", "node_type": "bridge"},
    "projection": {"label": "Projection", "node_type": "projection"},
    "runtime": {"label": "Runtime", "node_type": "runtime"},
    "worker": {"label": "Workers", "node_type": "worker"},
    "supervisor": {"label": "Supervisor", "node_type": "supervisor"},
    "tool": {"label": "Tools", "node_type": "tool"},
    "github": {"label": "GitHub Provider", "node_type": "github"},
    "test": {"label": "Tests", "node_type": "test"},
    "release_gate": {"label": "Release Gate", "node_type": "release_gate"},
    "telemetry": {"label": "Telemetry", "node_type": "telemetry"},
    "redaction": {"label": "Redaction", "node_type": "redaction"},
    "coordination": {"label": "Coordination", "node_type": "coordination"},
    "resource": {"label": "Resource Allocator", "node_type": "resource"},
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, FileNotFoundError):
        return ""


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _strand_state_from_count(count: int) -> str:
    if count > 0:
        return "active"
    return "no_input"


def _derive_pressure(value: int) -> str:
    if value == 0:
        return "none"
    if value < _PRESSURE_MODERATE_THRESHOLD:
        return "moderate"
    return "high"


def _derive_error_pressure(value: int) -> str:
    if value == 0:
        return "none"
    if value < _PRESSURE_ELEVATED_THRESHOLD:
        return "low"
    if value < _PRESSURE_HIGH_THRESHOLD:
        return "elevated"
    return "high"


def _build_nodes(
    category_counts: dict[str, int], bridge_summary: dict[str, int]
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    for node_id, blueprint in _NODE_BLUEPRINTS.items():
        count = category_counts.get(node_id, 0)
        state = _strand_state_from_count(count)
        if node_id == "bridge" and bridge_summary:
            total_bridge = sum(bridge_summary.values())
            if total_bridge > 0:
                state = "active"
            else:
                state = "no_input"
        nodes.append({
            "node_id": node_id,
            "node_type": blueprint["node_type"],
            "label": blueprint["label"],
            "strand_state": state,
            "event_count": count
            if node_id != "bridge"
            else sum(bridge_summary.values()),
            "details": f"{count} events" if count > 0 else "no events received",
        })

    return nodes


def _build_edges() -> list[dict[str, Any]]:
    return [
        {
            "edge_id": "edge_001",
            "from_node_id": "event_fabric",
            "to_node_id": "duckdb_projection",
            "edge_type": "consumed_by",
            "confidence": "observed",
            "label": "JSONL read",
        },
        {
            "edge_id": "edge_002",
            "from_node_id": "duckdb_projection",
            "to_node_id": "derived_artifact",
            "edge_type": "produced",
            "confidence": "observed",
            "label": "query output",
        },
        {
            "edge_id": "edge_003",
            "from_node_id": "derived_artifact",
            "to_node_id": "bridge",
            "edge_type": "observes",
            "confidence": "derived",
            "label": "lifecycle summary",
        },
        {
            "edge_id": "edge_004",
            "from_node_id": "derived_artifact",
            "to_node_id": "worker",
            "edge_type": "observes",
            "confidence": "derived",
            "label": "error summary",
        },
        {
            "edge_id": "edge_005",
            "from_node_id": "derived_artifact",
            "to_node_id": "tool",
            "edge_type": "observes",
            "confidence": "derived",
            "label": "event counts",
        },
        {
            "edge_id": "edge_006",
            "from_node_id": "bridge",
            "to_node_id": "projection",
            "edge_type": "reports_to",
            "confidence": "observed",
            "label": "status feed",
        },
        {
            "edge_id": "edge_007",
            "from_node_id": "resource",
            "to_node_id": "bridge",
            "edge_type": "observes",
            "confidence": "derived",
            "label": "pressure signals",
        },
        {
            "edge_id": "edge_008",
            "from_node_id": "resource",
            "to_node_id": "worker",
            "edge_type": "observes",
            "confidence": "derived",
            "label": "error pressure",
        },
        {
            "edge_id": "edge_009",
            "from_node_id": "supervisor",
            "to_node_id": "worker",
            "edge_type": "reports_to",
            "confidence": "observed",
            "label": "spawn control",
        },
        {
            "edge_id": "edge_010",
            "from_node_id": "runtime",
            "to_node_id": "supervisor",
            "edge_type": "reports_to",
            "confidence": "observed",
            "label": "execution context",
        },
    ]


def _build_pressure(pressure_data: dict[str, int] | None) -> dict[str, Any]:
    if pressure_data is None:
        pressure_data = {}
    reconnect_count = pressure_data.get("reconnect_failed_count", 0)
    queue_count = pressure_data.get("queue_pressure_high_count", 0)
    error_count = pressure_data.get("consumer_error_count", 0)
    return {
        "reconnect_pressure": _derive_pressure(reconnect_count),
        "reconnect_failed_count": reconnect_count,
        "queue_pressure": _derive_pressure(queue_count),
        "queue_pressure_high_count": queue_count,
        "consumer_errors": _derive_error_pressure(error_count),
        "consumer_error_count": error_count,
        "bridge_health": "unknown",
        "github_rate_limit_health": "unknown",
    }


def _build_strand_states(nodes: list[dict[str, Any]]) -> dict[str, int]:
    state_counts: dict[str, int] = {}
    for node in nodes:
        state = node.get("strand_state", "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
    result: dict[str, int] = {"total_nodes": len(nodes)}
    for state_name in [
        "healthy",
        "idle",
        "active",
        "stale",
        "degraded",
        "blocked",
        "quarantined",
        "backpressured",
        "waiting_for_permission",
        "no_input",
        "unknown",
    ]:
        result[f"{state_name}_count"] = state_counts.get(state_name, 0)
    return result


@dataclass(slots=True)
class MissionTopologyProjection:
    duckdb_report_path: Path = field(
        default_factory=lambda: _DEFAULT_DUCKDB_REPORT_PATH
    )
    pressure_summary_path: Path = field(
        default_factory=lambda: _DEFAULT_PRESSURE_SUMMARY_PATH
    )
    output_path: Path = field(default_factory=lambda: _OUTPUT_PATH)

    def build(self) -> dict[str, Any]:
        report = _read_json(self.duckdb_report_path)
        pressure_data = _read_json(self.pressure_summary_path)

        if report is None:
            return self._no_input_topology()

        status = report.get("status", "no_input_logs")
        if status == "no_input_logs":
            category_counts: dict[str, int] = {}
            bridge_summary: dict[str, int] = {}
        else:
            category_counts = {
                k: int(v) for k, v in report.get("event_category_counts", {}).items()
            }
            bridge_summary = {
                k: int(v) for k, v in report.get("bridge_lifecycle_summary", {}).items()
            }

        nodes = _build_nodes(category_counts, bridge_summary)
        edges = _build_edges()
        pressure = _build_pressure(pressure_data)
        strand_states = _build_strand_states(nodes)

        degraded: list[str] = []
        if status == "no_input_logs":
            degraded.append("no_input_logs: event fabric has no live input data")
        if pressure["reconnect_pressure"] in {"moderate", "high"}:
            degraded.append(f"reconnect_pressure={pressure['reconnect_pressure']}")
        if pressure["consumer_errors"] in {"elevated", "high"}:
            degraded.append(f"consumer_errors={pressure['consumer_errors']}")

        source_artifacts = [
            {
                "artifact_id": "duckdb_projection_report",
                "path": str(self.duckdb_report_path),
                "present": report is not None,
                "artifact_hash": _sha256_file(self.duckdb_report_path),
                "schema_version": "rig.event.duckdb_projection_report.v1",
                "summary": f"status={status}, event_count={report.get('event_count', 0)}",
            },
            {
                "artifact_id": "resource_pressure_summary",
                "path": str(self.pressure_summary_path),
                "present": pressure_data is not None,
                "artifact_hash": _sha256_file(self.pressure_summary_path),
                "schema_version": "",
                "summary": "derived pressure signal summary",
            },
        ]

        return {
            "schema_version": "rig.relay.mission_topology_projection.v1",
            "generated_at": _now_iso(),
            "branch": "",
            "head": "",
            "content_light": True,
            "read_side_only": True,
            "mutation_authority": False,
            "status": "live" if status != "no_input_logs" else "degraded_no_input",
            "nodes": nodes,
            "edges": edges,
            "source_artifacts": source_artifacts,
            "strand_states": strand_states,
            "resource_pressure": pressure,
            "causal_links": [],
            "degraded_reasons": degraded,
            "redaction_summary": {
                "raw_event_payloads_exposed": False,
                "envelope_level_only": True,
                "source_artifact_hashes_used": True,
            },
            "recommended_next_slice": (
                "Seed event fabric JSONL with bridge events → re-run DuckDB projection "
                "→ re-build topology to validate live data path"
            ),
        }

    def _no_input_topology(self) -> dict[str, Any]:
        return {
            "schema_version": "rig.relay.mission_topology_projection.v1",
            "generated_at": _now_iso(),
            "branch": "",
            "head": "",
            "content_light": True,
            "read_side_only": True,
            "mutation_authority": False,
            "status": "empty",
            "nodes": [
                {
                    "node_id": "event_fabric",
                    "node_type": "event_fabric",
                    "label": "Event Fabric",
                    "strand_state": "no_input",
                    "event_count": 0,
                    "details": "no event fabric JSONL found",
                },
                {
                    "node_id": "duckdb_projection",
                    "node_type": "duckdb_projection",
                    "label": "DuckDB Projection",
                    "strand_state": "no_input",
                    "event_count": 0,
                    "details": "no input data for projection",
                },
                {
                    "node_id": "derived_artifact",
                    "node_type": "derived_artifact",
                    "label": "Derived Artifacts",
                    "strand_state": "no_input",
                    "event_count": 0,
                    "details": "no derived artifacts generated",
                },
            ],
            "edges": [
                {
                    "edge_id": "edge_001",
                    "from_node_id": "event_fabric",
                    "to_node_id": "duckdb_projection",
                    "edge_type": "consumed_by",
                    "confidence": "observed",
                    "label": "JSONL read",
                }
            ],
            "source_artifacts": [
                {
                    "artifact_id": "duckdb_projection_report",
                    "path": str(self.duckdb_report_path),
                    "present": False,
                    "artifact_hash": "",
                    "schema_version": "",
                    "summary": "not found",
                }
            ],
            "strand_states": {
                "total_nodes": 3,
                "healthy_count": 0,
                "idle_count": 0,
                "active_count": 0,
                "stale_count": 0,
                "degraded_count": 0,
                "blocked_count": 0,
                "quarantined_count": 0,
                "backpressured_count": 0,
                "waiting_for_permission_count": 0,
                "no_input_count": 3,
                "unknown_count": 0,
            },
            "resource_pressure": {
                "reconnect_pressure": "none",
                "reconnect_failed_count": 0,
                "queue_pressure": "none",
                "queue_pressure_high_count": 0,
                "consumer_errors": "none",
                "consumer_error_count": 0,
                "bridge_health": "unknown",
                "github_rate_limit_health": "unknown",
            },
            "causal_links": [],
            "degraded_reasons": [
                "empty_topology: no event fabric data, no DuckDB projection report available"
            ],
            "redaction_summary": {
                "raw_event_payloads_exposed": False,
                "envelope_level_only": True,
                "source_artifact_hashes_used": False,
            },
            "recommended_next_slice": "Seed event fabric JSONL with bridge events to activate the topology",
        }


def build_mission_topology_projection(
    *,
    duckdb_report_path: Path | None = None,
    pressure_summary_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    return MissionTopologyProjection(
        duckdb_report_path=duckdb_report_path or _DEFAULT_DUCKDB_REPORT_PATH,
        pressure_summary_path=pressure_summary_path or _DEFAULT_PRESSURE_SUMMARY_PATH,
        output_path=output_path or _OUTPUT_PATH,
    ).build()


def write_mission_topology_projection(path: Path | None = None) -> dict[str, Any]:
    proj = build_mission_topology_projection()
    out = path or _OUTPUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(proj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return proj


__all__ = [
    "MissionTopologyProjection",
    "build_mission_topology_projection",
    "write_mission_topology_projection",
]
