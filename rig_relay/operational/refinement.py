"""Operational Refinement Service — evidence-backed recommendation and packet generation.

Provides content-light refinement analysis and mission-packet generation
from operational evidence patterns. Read-only: never invokes models,
mutates evidence, or authorizes execution.

Extracted from scripts/rig_relay_builtin_tool_refinement.py and
scripts/rig_relay_create_builtin_refinement_packets.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import uuid

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DERIVED_DIR = REPO_ROOT / ".build" / "rig-relay" / "derived"
DEFAULT_REPORTS_DIR = REPO_ROOT / ".build" / "rig-relay" / "reports"
DEFAULT_OUTPUT = DEFAULT_REPORTS_DIR / "built-in-tool-refinement.md"
DEFAULT_JSONL_OUTPUT = DEFAULT_DERIVED_DIR / "builtin_tool_refinement_backlog.jsonl"

DATASET_FILES: dict[str, str] = {
    "tool_failure_patterns_dataset": "tool_failure_patterns_dataset.jsonl",
    "provider_task_performance_dataset": "provider_task_performance_dataset.jsonl",
    "cross_session_coordination_dataset": "cross_session_coordination_dataset.jsonl",
    "coordination_conflict_dataset": "coordination_conflict_dataset.jsonl",
    "artifact_reuse_dataset": "artifact_reuse_dataset.jsonl",
    "checkpoint_eval_dataset": "checkpoint_eval_dataset.jsonl",
    "findings_dataset": "findings_dataset.jsonl",
    "semantic_change_snippets": "semantic_change_snippets.jsonl",
}

FREQUENT_USAGE_THRESHOLD = 10
FALLBACK_THRESHOLD = 3
STORAGE_THRESHOLD = 4
COORDINATION_THRESHOLD = 3
P0_SCORE = 10
P1_SCORE = 7
P2_SCORE = 4
P3_SCORE = 0


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _present_datasets(derived_dir: Path) -> dict[str, Path]:
    present: dict[str, Path] = {}
    for name, filename in DATASET_FILES.items():
        path = derived_dir / filename
        if path.is_file():
            present[name] = path
    return present


def _missing_dataset_warnings(present: dict[str, Path]) -> list[str]:
    return [f"Missing dataset: {name}" for name in DATASET_FILES if name not in present]


def _normalize_tool_name(_dataset_name: str, row: dict[str, Any]) -> str | None:
    explicit_tool = row.get("tool_name")
    if explicit_tool is not None:
        return str(explicit_tool)
    return None


def _accumulate_row(
    bucket: dict[str, dict[str, Any]], dataset_name: str, row: dict[str, Any]
) -> None:
    tool_name = _normalize_tool_name(dataset_name, row)
    if tool_name is None:
        return
    aggregate = bucket.setdefault(
        tool_name,
        {
            "tool_name": tool_name,
            "event_count": 0,
            "failure_count": 0,
            "refusal_count": 0,
            "timeout_count": 0,
            "fallback_to_bash_count": 0,
            "truncation_count": 0,
            "artifact_size_bytes": 0,
            "storage_pressure_score": 0,
            "coordination_pressure_score": 0,
            "semantic_change_kind": None,
        },
    )
    aggregate["event_count"] += 1
    status = str(row.get("status") or "").lower()
    event_name = str(row.get("event_name") or "").lower()
    if status in {"error", "failed", "failure", "refused", "blocked"}:
        aggregate["failure_count"] += 1
    if status == "refused":
        aggregate["refusal_count"] += 1
    if "timeout" in status:
        aggregate["timeout_count"] += 1
    if "bash" in event_name or "shell" in dataset_name or tool_name == "bash":
        aggregate["fallback_to_bash_count"] += 1
    if "truncat" in status:
        aggregate["truncation_count"] += 1
    aggregate["artifact_size_bytes"] += int(
        row.get("estimated_tokens") or row.get("artifact_size_bytes") or 0
    )
    if dataset_name == "storage_audit" or "storage" in event_name:
        aggregate["storage_pressure_score"] += int(
            row.get("storage_pressure_score") or 2
        )
    if "coord" in dataset_name or "coord" in event_name:
        aggregate["coordination_pressure_score"] += 2


def _refinement_kind(
    failure_count: int,
    refusal_count: int,
    fallback_to_bash_count: int,
    storage_pressure_score: float,
    coordination_pressure_score: float,
    truncation_count: int,
) -> tuple[str, str | None]:
    if (
        failure_count > 0
        and refusal_count > 0
        and fallback_to_bash_count >= FALLBACK_THRESHOLD
    ):
        return "replace_shell_pattern", "replace bash fallback with governed tool"
    if failure_count > 0 or refusal_count > 0:
        return "harden_existing_tool", "Hardening existing built-in tool"
    if storage_pressure_score > STORAGE_THRESHOLD:
        return "reduce_artifact_weight", "Reduce storage pressure"
    if coordination_pressure_score > COORDINATION_THRESHOLD:
        return "add_coordination_hook", "Coordination hook needed"
    if truncation_count > 0:
        return "add_preflight", "Add preflight validation"
    return "investigate", "Investigate pattern"


def analyze_refinement_candidates(
    derived_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Analyze derived datasets and produce ranked refinement candidates.

    Returns (candidates, warnings). Content-light: no raw prompts, secrets,
    or model outputs.
    """
    root = derived_dir or DEFAULT_DERIVED_DIR
    present = _present_datasets(root)
    warnings = _missing_dataset_warnings(present)
    if not present:
        return [], warnings

    bucket: dict[str, dict[str, Any]] = {}
    for dataset_name, path in present.items():
        rows = _load_jsonl(path)
        for row in rows:
            _accumulate_row(bucket, dataset_name, row)

    rows_raw = sorted(
        bucket.values(),
        key=lambda row: (
            -int(row["failure_count"]),
            -int(row["refusal_count"]),
            -int(row["fallback_to_bash_count"]),
            -int(row["artifact_size_bytes"]),
            str(row["tool_name"]),
        ),
    )

    now = datetime.now(UTC).isoformat()
    candidates: list[dict[str, Any]] = []
    for r in rows_raw:
        score = (
            (5 if r["failure_count"] > 0 else 0)
            + (5 if r["refusal_count"] > 0 and r["event_count"] >= 10 else 0)
            + (4 if r["fallback_to_bash_count"] >= FALLBACK_THRESHOLD else 0)
            + min(r["storage_pressure_score"], 4)
            + min(r["coordination_pressure_score"], 3)
            + (2 if r["truncation_count"] > 0 else 0)
        )
        rkind, rdesc = _refinement_kind(
            r["failure_count"],
            r["refusal_count"],
            r["fallback_to_bash_count"],
            r["storage_pressure_score"],
            r["coordination_pressure_score"],
            r["truncation_count"],
        )
        if score >= P0_SCORE:
            priority = "P0"
        elif score >= P1_SCORE:
            priority = "P1"
        elif score >= P2_SCORE:
            priority = "P2"
        else:
            priority = "P3"

        candidates.append({
            "item_id": str(uuid.uuid4()),
            "tool_name": r["tool_name"],
            "priority": priority,
            "event_count": r["event_count"],
            "failure_count": r["failure_count"],
            "refusal_count": r["refusal_count"],
            "fallback_to_bash_count": r["fallback_to_bash_count"],
            "truncation_count": r["truncation_count"],
            "storage_pressure_score": r["storage_pressure_score"],
            "coordination_pressure_score": r["coordination_pressure_score"],
            "refinement_kind": rkind,
            "refinement_description": rdesc,
            "confidence": min(100, score * 10),
            "evidence_window": f"derived datasets ({len(present)} present)",
            "suggested_next_action": f"Investigate {r['tool_name']} for {rkind}",
            "created_at": now,
            "content_light": True,
        })

    return candidates, warnings


def run_refinement_report(
    derived_dir: Path | None = None,
    reports_dir: Path | None = None,
    output: Path | None = None,
    jsonl_output: Path | None = None,
    *,
    strict: bool = False,
) -> int:
    """Run refinement analysis and emit report + JSONL backlog.

    Returns exit code (0 = success, 1 = no data, 2 = write error).
    """
    root = derived_dir or DEFAULT_DERIVED_DIR
    rdir = reports_dir or DEFAULT_REPORTS_DIR
    out = output or DEFAULT_OUTPUT
    jsonl = jsonl_output or DEFAULT_JSONL_OUTPUT

    candidates, warnings = analyze_refinement_candidates(root)

    rdir.mkdir(parents=True, exist_ok=True)
    jsonl.parent.mkdir(parents=True, exist_ok=True)

    if not candidates and strict:
        return 1

    # Write JSONL backlog
    with jsonl.open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, sort_keys=True) + "\n")

    # Write Markdown report
    lines = [
        "# Built-in Tool Refinement Report",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Candidates: {len(candidates)}",
        "",
    ]
    if warnings:
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    by_prio: dict[str, list[dict[str, Any]]] = {}
    for c in candidates:
        by_prio.setdefault(c["priority"], []).append(c)

    for prio in ["P0", "P1", "P2", "P3"]:
        items = by_prio.get(prio, [])
        if not items:
            continue
        lines.append(f"## {prio} Candidates ({len(items)})")
        for c in items:
            lines.append(
                f"- **{c['tool_name']}** ({c['refinement_kind']}): "
                f"failures={c['failure_count']}, refusals={c['refusal_count']}, "
                f"confidence={c['confidence']}"
            )
        lines.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return 0


# ── Packet generation ───────────────────────────────────────────────────


def generate_refinement_packets(
    backlog: Path,
    report: Path,
    output_dir: Path,
    limit: int = 5,
    priority_filter: set[str] | None = None,
    dry_run: bool = True,
) -> tuple[list[Path], list[str]]:
    """Generate bounded mission packets from refinement backlog.

    Returns (packet_paths, warnings). Content-light: no raw prompts,
    secrets, or model outputs.
    """
    warnings: list[str] = []
    if not backlog.is_file():
        return [], [f"Backlog not found: {backlog}"]
    if not report.is_file():
        warnings.append(f"Report not found: {report}")
    rows = _load_jsonl(backlog)
    if not rows:
        return [], ["Backlog is empty"]

    filtered = [
        row
        for row in rows
        if priority_filter is None or str(row.get("priority")) in priority_filter
    ]
    filtered.sort(
        key=lambda row: (
            str(row.get("priority", "P3")),
            -int(row.get("event_count") or 0),
            str(row.get("tool_name") or ""),
        )
    )
    selected = filtered[:limit]

    packet_paths: list[Path] = []
    for row in selected:
        tool = row.get("tool_name", "unknown")
        rkind = row.get("refinement_kind", "unknown")
        prio = row.get("priority", "P3")
        pdir = output_dir / f"{prio}-{tool}-{rkind}"
        packet_paths.append(pdir)

        mission_id = f"mission_{uuid.uuid4().hex[:12]}"
        packet_id = f"packet_{uuid.uuid4().hex[:12]}"

        packet: dict[str, Any] = {
            "schema_version": "rig.relay.builtin_tool_refinement_packet.v1",
            "packet_id": packet_id,
            "mission_title": f"{tool} {rkind} mission",
            "created_at": datetime.now(UTC).isoformat(),
            "source_item_id": row.get("item_id", ""),
            "priority": prio,
            "tool_name": tool,
            "refinement_kind": rkind,
            "mission_packet_path": str(pdir / "mission_packet.json"),
            "recommended_validation": [
                "uv run python scripts/rig_relay_validate_schemas.py"
            ],
            "warnings": [],
            "mission_id": mission_id,
            "parent_sprint_id": "builtin-tool-refinement",
            "agent_profile": "implementer",
            "tool_policy": {"allow_write": True},
            "coordination_policy": {"claim_task": True, "reserve_paths": True},
            "checkpoint_policy": "prompt",
            "validation_commands": [
                "uv run python scripts/rig_relay_validate_schemas.py"
            ],
            "done_when": ["Mission packet is bounded and content-light."],
            "max_runtime_seconds": 3600,
            "evidence_window": row.get("evidence_window", ""),
            "confidence": row.get("confidence", 0),
            "content_light": True,
        }

        if dry_run:
            continue
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "mission_packet.json").write_text(
            json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8"
        )

    return packet_paths, warnings


__all__ = [
    "analyze_refinement_candidates",
    "generate_refinement_packets",
    "run_refinement_report",
]
