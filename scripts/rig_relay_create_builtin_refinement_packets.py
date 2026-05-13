#!/usr/bin/env python3
"""Create mission packets from built-in tool refinement backlog rows."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import uuid

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"
MISSION_PACKET_SCHEMA = SCHEMAS_DIR / "rig.relay.builtin_tool_refinement_packet.v1.schema.json"
DEFAULT_BACKLOG = REPO_ROOT / ".build" / "rig-relay" / "derived" / "builtin_tool_refinement_backlog.jsonl"
DEFAULT_REPORT = REPO_ROOT / ".build" / "rig-relay" / "reports" / "built-in-tool-refinement.md"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".build" / "rig-relay" / "refinement-packets"

VALIDATION_MAP = {
    "replace_shell_pattern": [
        "uv run python scripts/rig_relay_builtin_tool_refinement.py --derived-dir .build/rig-relay/derived --reports-dir .build/rig-relay/reports",
        "uv run pytest -n0 tests/scripts/test_builtin_tool_refinement.py",
    ],
    "harden_existing_tool": [
        "uv run python scripts/rig_relay_validate_schemas.py",
        "uv run pytest -n0 tests/scripts/test_builtin_tool_refinement.py",
    ],
    "add_coordination_hook": [
        "uv run python scripts/rig_relay_validate_schemas.py",
    ],
    "reduce_artifact_weight": [
        "uv run python scripts/rig_relay_storage_audit.py",
    ],
    "add_preflight": [
        "uv run python scripts/rig_relay_storage_audit.py",
    ],
}

NON_GOALS = [
    "Do not implement new built-in tools.",
    "Do not change provider behavior.",
    "Do not change tool behavior.",
    "Do not delete or compact artifacts.",
    "Do not upload anything.",
]

CONTENT_LIGHT = [
    "Use only counts, labels, hashes, item IDs, and report references.",
    "Do not include raw prompts, model outputs, source code, stdout/stderr bodies, diffs, secrets, or raw private paths.",
]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
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


def _load_schema() -> dict[str, Any]:
    return json.loads(MISSION_PACKET_SCHEMA.read_text(encoding="utf-8"))


def _read_backlog(backlog: Path) -> list[dict[str, Any]]:
    return _load_jsonl(backlog)


def _filter_rows(
    rows: list[dict[str, Any]], priority_filter: set[str] | None, limit: int
) -> list[dict[str, Any]]:
    filtered = [
        row
        for row in rows
        if priority_filter is None or str(row.get("priority")) in priority_filter
    ]
    filtered.sort(
        key=lambda row: (
            str(row.get("priority", "P3")),
            -int(row.get("event_count") or 0),
            -int(row.get("failure_count") or 0),
            str(row.get("tool_name") or ""),
        )
    )
    return filtered[:limit]


def _mission_title(row: dict[str, Any]) -> str:
    return f"{row['tool_name']} {row['refinement_kind']} mission"


def _packet_dir_name(row: dict[str, Any]) -> str:
    return f"{row['priority']}-{row['tool_name']}-{row['refinement_kind']}"


def _prompt_text(row: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Before doing anything, read AGENTS.md and summarize the Git discipline rules you will follow. Do not edit files until you have done that.",
            "",
            "Mission: Built-In Tool Refinement Packet Mission",
            "Goal:",
            f"Turn the ranked built-in refinement backlog item for `{row['tool_name']}` into a bounded implementation mission packet.",
            "Context:",
            f"- source_item_id: {row['item_id']}",
            f"- tool_name: {row['tool_name']}",
            f"- refinement_kind: {row['refinement_kind']}",
            f"- priority: {row['priority']}",
            f"- confidence: {row['confidence']}",
            f"- evidence_window: {row['evidence_window']}",
            "",
            "Non-goals:",
            *[f"- {item}" for item in NON_GOALS],
            "",
            "Required files to inspect:",
            "- AGENTS.md",
            "- scripts/rig_relay_builtin_tool_refinement.py",
            "- docs/schemas/rig.relay.builtin_tool_refinement_item.v1.schema.json",
            "- docs/schemas/rig.relay.mission_packet.v1.schema.json",
            "- docs/governance/reviewer-orchestrator.md",
            "- docs/governance/delegate-fleet-orchestration.md",
            "- docs/governance/usage-data-doctrine.md",
            "- .build/rig-relay/derived/builtin_tool_refinement_backlog.jsonl",
            "- .build/rig-relay/reports/built-in-tool-refinement.md",
            "",
            "Implementation requirements:",
            "- Create a bounded mission packet for the reviewer/orchestrator loop.",
            "- Keep the packet content-light.",
            "- Include allowed files or path hints only when inferable.",
            "- Include recommended validation commands.",
            "- Include final report requirements.",
            "",
            "Tests:",
            "- Add focused tests for packet generation and validation.",
            "",
            "Validation:",
            "- Run schema validation and the focused packet tests.",
            "",
            "Final report requirements:",
            "- Include branch and HEAD before/after.",
            "- Include dirty files before/after.",
            "- Include files changed.",
            "- Include generated packet paths.",
        ]
    )


def _evidence_summary_text(row: dict[str, Any], report_path: Path) -> str:
    sources = ", ".join(row.get("evidence_sources", []))
    return "\n".join(
        [
            "# Evidence Summary",
            "",
            f"- item_id: {row['item_id']}",
            f"- tool_name: {row['tool_name']}",
            f"- refinement_kind: {row['refinement_kind']}",
            f"- priority: {row['priority']}",
            f"- confidence: {row['confidence']}",
            f"- event_count: {row['event_count']}",
            f"- failure_count: {row['failure_count']}",
            f"- refusal_count: {row['refusal_count']}",
            f"- fallback_to_bash_count: {row['fallback_to_bash_count']}",
            f"- truncation_count: {row['truncation_count']}",
            f"- evidence_sources: {sources}",
            f"- report_path: {report_path}",
        ]
    )


def _mission_packet(row: dict[str, Any], output_dir: Path, report_path: Path) -> dict[str, Any]:
    mission_id = f"mission_{uuid.uuid4().hex[:12]}"
    packet_id = f"packet_{uuid.uuid4().hex[:12]}"
    prompt_path = output_dir / "prompt.md"
    evidence_path = output_dir / "evidence_summary.md"
    allowed_paths = [
        "scripts/rig_relay_builtin_tool_refinement.py",
        "scripts/rig_relay_create_builtin_refinement_packets.py",
        "tests/scripts/test_builtin_tool_refinement_packets.py",
        "docs/governance/usage-data-doctrine.md",
        "docs/governance/reviewer-orchestrator.md",
        "docs/governance/delegate-fleet-orchestration.md",
    ]
    if row["refinement_kind"] == "replace_shell_pattern":
        allowed_paths.extend(
            [
                "scripts/",
                "docs/audits/",
                "docs/schemas/",
            ]
        )
    validation = VALIDATION_MAP.get(
        row["refinement_kind"],
        ["uv run python scripts/rig_relay_validate_schemas.py"],
    )
    packet = {
        "schema_version": "rig.relay.builtin_tool_refinement_packet.v1",
        "packet_id": packet_id,
        "mission_title": _mission_title(row),
        "created_at": datetime.now(UTC).isoformat(),
        "source_item_id": row["item_id"],
        "priority": row["priority"],
        "tool_name": row["tool_name"],
        "refinement_kind": row["refinement_kind"],
        "mission_prompt_path": str(prompt_path),
        "evidence_summary_path": str(evidence_path),
        "recommended_validation": validation,
        "constraints": CONTENT_LIGHT,
        "warnings": [],
        "mission_packet_path": str(output_dir / "mission_packet.json"),
        "allowed_paths": allowed_paths,
        "forbidden_paths": [
            ".build/rig-relay/coordination/",
            ".build/rig-relay/derived/",
        ],
        "instructions": _prompt_text(row),
        "mission_id": mission_id,
        "parent_sprint_id": "builtin-tool-refinement",
        "parent_review_id": None,
        "agent_profile": "implementer",
        "tool_policy": {"allow_write": True, "allow_bash": True, "bash_allowlist": validation},
        "coordination_policy": {"claim_task": True, "reserve_paths": True, "heartbeat": True},
        "checkpoint_policy": "prompt",
        "validation_commands": validation,
        "done_when": [
            "Mission packet is bounded and content-light.",
            "Generated prompt and evidence summary exist.",
            "Generated packet validates against the refinement packet schema.",
        ],
        "max_runtime_seconds": 3600,
        "parallel_group": "builtin-tool-refinement",
        "depends_on_mission_ids": [],
        "content_policy": "content_light",
        "forbidden_fields": [
            "raw_file_contents",
            "secrets",
            "raw_private_code",
            "raw_prompt_text",
            "model_output_text",
            "stdout_bodies",
            "stderr_bodies",
        ],
    }
    return packet


def _validate_packet(packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema = _load_schema()
    try:
        jsonschema.validate(instance=packet, schema=schema)
    except jsonschema.ValidationError as exc:
        errors.append(str(exc))
    return errors


def generate_packets(
    backlog: Path,
    report: Path,
    output_dir: Path,
    limit: int,
    priority_filter: set[str] | None,
    dry_run: bool,
) -> tuple[list[Path], list[str]]:
    warnings: list[str] = []
    if not backlog.is_file():
        return [], [f"Backlog not found: {backlog}"]
    if not report.is_file():
        warnings.append(f"Report not found: {report}")
    rows = _read_backlog(backlog)
    selected = _filter_rows(rows, priority_filter, limit)
    packet_paths: list[Path] = []
    for row in selected:
        packet_dir = output_dir / _packet_dir_name(row)
        packet_paths.append(packet_dir)
        packet = _mission_packet(row, packet_dir, report)
        packet_errors = _validate_packet(packet)
        warnings.extend(packet_errors)
        if dry_run:
            continue
        packet_dir.mkdir(parents=True, exist_ok=True)
        (packet_dir / "mission_packet.json").write_text(
            json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8"
        )
        (packet_dir / "prompt.md").write_text(_prompt_text(row), encoding="utf-8")
        (packet_dir / "evidence_summary.md").write_text(
            _evidence_summary_text(row, report), encoding="utf-8"
        )
    return packet_paths, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backlog", type=Path, default=DEFAULT_BACKLOG)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--priority", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    priority_filter = {p.strip() for p in args.priority.split(",") if p.strip()} or None
    packet_paths, warnings = generate_packets(
        args.backlog,
        args.report,
        args.output_dir,
        args.limit,
        priority_filter,
        args.dry_run,
    )
    for warning in warnings:
        print(f"WARNING: {warning}")
    if not args.dry_run:
        for path in packet_paths:
            print(path)
    else:
        for path in packet_paths:
            print(f"DRY-RUN: {path}")
    return 0 if not warnings or args.dry_run else 0


if __name__ == "__main__":
    raise SystemExit(main())
