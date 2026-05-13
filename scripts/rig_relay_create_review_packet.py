#!/usr/bin/env python3
# ruff: noqa: PLR0912, PLR0913, PLR0914, PLR0915
"""Rig Relay Review Packet Creator.

Creates local handoff artifacts for human/model review of completed missions.
The review packet protocol is ChatGPT-Mac-app-independent — reviewer responses
are not executed directly, they inform the next mission prompt.

Usage:
    uv run python scripts/rig_relay_create_review_packet.py \\
        --session-id session_20250101_000000 \\
        --task-id call_00_example \\
        --final-report .build/rig-relay/reviews/latest/final_report.md \\
        --review-kind next_slice \\
        --output-dir .build/rig-relay/reviews/review_20250101

    uv run python scripts/rig_relay_create_review_packet.py \\
        --session-id s-1 --task-id t-1 \\
        --final-report docs/output.md \\
        --artifact-manifest .build/rig-relay/artifacts/manifest.json \\
        --dataset-report .build/rig-relay/derived/export_manifest.json \\
        --review-kind risk_review

Content-light safeguards:
    - Review packet JSON does not embed raw file contents, secrets, private code,
      raw prompt text, model output text, or stdout/stderr bodies.
    - Referenced files remain local and are NOT inlined into the packet.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import sys
from typing import Any

# ── Constants ────────────────────────────────────────────────────────────

VALID_REVIEW_KINDS = {
    "next_slice",
    "risk_review",
    "prompt_generation",
    "commit_review",
    "dataset_review",
    "architecture_review",
}

VALID_STATUSES = {"needs_review", "in_review", "reviewed", "cancelled"}

DEFAULT_FORBIDDEN = [
    "raw_file_contents",
    "secrets",
    "raw_private_code",
    "raw_prompt_text",
    "model_output_text",
    "stdout_bodies",
    "stderr_bodies",
]

README_TEMPLATE = """# Review: {review_id}

## How to review

1. Read `final_report.md` for the mission summary and findings.
{artifact_instructions}
3. Write your review in `reviewer_response.md` (see format below).
4. Move or soft-link the response to `resume_prompt.md` when ready.

## Review kind: {review_kind}

{review_kind_description}

## Reviewer response format

Create `reviewer_response.md` with these sections:

```markdown
## Summary

One-paragraph assessment of the mission.

## Findings

- What worked well
- What to improve
- Risks identified

## Next slice recommendation

A compact prompt for the next mission. Be specific about files, goals, and
non-goals. Do not include raw private code or unredacted transcripts.

## Rejected? (optional)

If the work should not continue, state why and close the review.
```

**Important: Reviewer responses are not executed directly.**
They inform the next mission prompt. Rig Relay validates the response
before any agent executes a new mission based on it.
"""

REVIEW_KIND_DESCRIPTIONS = {
    "next_slice": "Review the completed mission and recommend the next implementation slice.",
    "risk_review": "Review the mission for safety, privacy, or architectural risks.",
    "prompt_generation": "Review the mission and generate a refined prompt for continuation.",
    "commit_review": "Review changes before a governed checkpoint commit.",
    "dataset_review": "Review exported dataset quality and schema compliance.",
    "architecture_review": "Review architectural decisions and design trade-offs.",
}


def _generate_review_id() -> str:
    from datetime import UTC, datetime

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"review_{ts}"


def _validate_schema(packet: dict[str, Any]) -> list[str]:
    """Validate packet against JSON Schema. Returns list of error messages."""
    errors: list[str] = []
    _js: Any = None
    try:
        import jsonschema as _js
    except ImportError:
        pass

    if _js is None:
        # Basic required-field check fallback
        required = [
            "schema_version",
            "review_id",
            "session_id",
            "status",
            "requested_review_kind",
            "final_report_path",
            "created_at",
        ]
        for field in required:
            if field not in packet or packet[field] is None:
                errors.append(f"Missing required field: {field}")
        return errors

    # Load bundled schema
    schema_path = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.review_packet.v1.schema.json"
    )
    if not schema_path.is_file():
        errors.append(f"Schema file not found: {schema_path}")
        return errors
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        _js.validate(instance=packet, schema=schema)
    except _js.ValidationError as exc:
        errors.append(exc.message)
    return errors


def create_review_packet(
    *,
    session_id: str,
    task_id: str | None = None,
    parent_session_id: str | None = None,
    final_report_path: Path,
    artifact_manifest_path: Path | None = None,
    dataset_report_path: Path | None = None,
    coordination_summary_path: Path | None = None,
    checkpoint_summary_path: Path | None = None,
    review_kind: str = "next_slice",
    output_dir: Path | None = None,
    branch: str | None = None,
    head: str | None = None,
    status: str = "needs_review",
    content_policy: str = "content_light",
    forbidden_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Create a review packet and write it to the output directory.

    Returns the packet dict for inspection.
    """
    if review_kind not in VALID_REVIEW_KINDS:
        print(
            f"ERROR: Invalid review kind '{review_kind}'. Valid: {sorted(VALID_REVIEW_KINDS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if status not in VALID_STATUSES:
        print(
            f"ERROR: Invalid status '{status}'. Valid: {sorted(VALID_STATUSES)}",
            file=sys.stderr,
        )
        sys.exit(1)

    final_report = Path(final_report_path)
    if not final_report.is_file():
        print(f"ERROR: Final report not found: {final_report}", file=sys.stderr)
        sys.exit(1)

    review_id = _generate_review_id()
    if output_dir is None:
        output_dir = Path.cwd() / ".build" / "rig-relay" / "reviews" / review_id

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy final report
    report_dest = output_dir / "final_report.md"
    shutil.copy2(final_report, report_dest)

    # Copy optional manifests
    artifact_dest: Path | None = None
    if artifact_manifest_path:
        artifact_src = Path(artifact_manifest_path)
        if artifact_src.is_file():
            artifact_dest = output_dir / "artifact_manifest.json"
            shutil.copy2(artifact_src, artifact_dest)

    dataset_dest: Path | None = None
    if dataset_report_path:
        dataset_src = Path(dataset_report_path)
        if dataset_src.is_file():
            dataset_dest = output_dir / "dataset_report.json"
            shutil.copy2(dataset_src, dataset_dest)

    coord_dest: Path | None = None
    if coordination_summary_path:
        coord_src = Path(coordination_summary_path)
        if coord_src.is_file():
            coord_dest = output_dir / "coordination_summary.json"
            shutil.copy2(coord_src, coord_dest)

    ckpt_dest: Path | None = None
    if checkpoint_summary_path:
        ckpt_src = Path(checkpoint_summary_path)
        if ckpt_src.is_file():
            ckpt_dest = output_dir / "checkpoint_summary.json"
            shutil.copy2(ckpt_src, ckpt_dest)

    # Build packet
    packet: dict[str, Any] = {
        "schema_version": "rig.relay.review_packet.v1",
        "review_id": review_id,
        "session_id": session_id,
        "parent_session_id": parent_session_id,
        "task_id": task_id,
        "branch": branch,
        "head": head,
        "status": status,
        "requested_review_kind": review_kind,
        "final_report_path": str(report_dest.resolve()),
        "artifact_manifest_path": str(artifact_dest.resolve())
        if artifact_dest
        else None,
        "coordination_summary_path": str(coord_dest.resolve()) if coord_dest else None,
        "dataset_report_path": str(dataset_dest.resolve()) if dataset_dest else None,
        "checkpoint_summary_path": str(ckpt_dest.resolve()) if ckpt_dest else None,
        "created_at": datetime.now(UTC).isoformat(),
        "content_policy": content_policy,
        "forbidden_fields": forbidden_fields or DEFAULT_FORBIDDEN,
        "warnings": [],
    }

    # Validate
    errors = _validate_schema(packet)
    if errors:
        packet["warnings"] = packet.get("warnings", []) + [
            f"Schema validation: {e}" for e in errors
        ]
        print(f"WARNING: Schema validation errors: {errors}", file=sys.stderr)

    # Write packet
    packet_path = output_dir / "review_packet.json"
    with packet_path.open("w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    # Write README
    artifact_instructions = ""
    if artifact_dest:
        artifact_instructions += (
            "2. Review `artifact_manifest.json` for the list of produced artifacts.\n"
        )
    if dataset_dest:
        artifact_instructions += (
            "3. Review `dataset_report.json` for dataset export results.\n"
        )
    if coord_dest:
        artifact_instructions += (
            "4. Review `coordination_summary.json` for coordination event data.\n"
        )

    readme_path = output_dir / "README.md"
    readme_content = README_TEMPLATE.format(
        review_id=review_id,
        review_kind=review_kind,
        review_kind_description=REVIEW_KIND_DESCRIPTIONS.get(review_kind, ""),
        artifact_instructions=artifact_instructions,
    )
    readme_path.write_text(readme_content, encoding="utf-8")

    # Create empty response placeholders
    for placeholder in ["reviewer_response.md", "resume_prompt.md"]:
        placeholder_path = output_dir / placeholder
        if not placeholder_path.exists():
            placeholder_path.write_text("", encoding="utf-8")

    print(f"Review packet created at {output_dir}")
    print("  review_packet.json — packet metadata")
    print("  final_report.md — mission final report")
    print("  README.md — manual review instructions")
    print("  reviewer_response.md — write your review here")
    print("  resume_prompt.md — copy/soft-link reviewer response here when ready")
    return packet


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a review packet for human/model review of a completed mission."
    )
    parser.add_argument("--session-id", type=str, required=True, help="Session ID")
    parser.add_argument("--task-id", type=str, default=None, help="Task ID (optional)")
    parser.add_argument(
        "--parent-session-id",
        type=str,
        default=None,
        help="Parent session ID (optional)",
    )
    parser.add_argument(
        "--final-report",
        type=Path,
        required=True,
        help="Path to final report Markdown file",
    )
    parser.add_argument(
        "--artifact-manifest",
        type=Path,
        default=None,
        help="Path to artifact manifest JSON",
    )
    parser.add_argument(
        "--dataset-report",
        type=Path,
        default=None,
        help="Path to dataset export manifest JSON",
    )
    parser.add_argument(
        "--coordination-summary",
        type=Path,
        default=None,
        help="Path to coordination summary JSON",
    )
    parser.add_argument(
        "--checkpoint-summary",
        type=Path,
        default=None,
        help="Path to checkpoint summary JSON",
    )
    parser.add_argument(
        "--review-kind",
        type=str,
        default="next_slice",
        choices=sorted(VALID_REVIEW_KINDS),
        help="Kind of review requested",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for review packet",
    )
    parser.add_argument(
        "--branch", type=str, default=None, help="Git branch at mission end"
    )
    parser.add_argument(
        "--head", type=str, default=None, help="Git HEAD SHA at mission end"
    )
    parser.add_argument(
        "--status",
        type=str,
        default="needs_review",
        choices=sorted(VALID_STATUSES),
        help="Packet status",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    create_review_packet(
        session_id=args.session_id,
        task_id=args.task_id,
        parent_session_id=args.parent_session_id,
        final_report_path=args.final_report,
        artifact_manifest_path=args.artifact_manifest,
        dataset_report_path=args.dataset_report,
        coordination_summary_path=args.coordination_summary,
        checkpoint_summary_path=args.checkpoint_summary,
        review_kind=args.review_kind,
        output_dir=args.output_dir,
        branch=args.branch,
        head=args.head,
        status=args.status,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
