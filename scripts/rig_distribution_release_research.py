#!/usr/bin/env python3
"""Rig Relay Distribution & Release Governance Research CLI.

Produces 8 structured research artifacts. No live API calls, no publishing.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "docs" / "json" / "governance"

from rig_relay.integrations.distribution_release_research import (
    APIS,
    ARTIFACT_CONCEPTS,
    CHANNELS,
    CREDENTIALS,
    MUTATIONS,
    PUBLIC_METADATA,
    RISKS,
    ROADMAP,
    VALIDATIONS,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _det_id(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:12]


def _git_state(repo_root: Path) -> tuple[str | None, str | None, list[str]]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        dirty_files = [f.strip()[3:] for f in dirty.split("\n") if f.strip()]
        return branch or None, head or None, dirty_files
    except (OSError, subprocess.CalledProcessError):
        return None, None, []


def _base(
    generated_at: str | None, branch: str | None, head: str | None, dirty: list[str]
) -> dict[str, Any]:
    return {
        "generated_at": generated_at or _now(),
        "branch": branch,
        "head": head,
        "dirty_files_count": len(dirty),
        "content_light": True,
        "remote_mutation": False,
        "live_network_used_for_product": False,
    }


def _apply_ids(
    items: list[dict[str, Any]], id_field: str, id_prefix: str
) -> list[dict[str, Any]]:
    for item in items:
        if id_field not in item:
            item[id_field] = id_prefix + _det_id(json.dumps(item, sort_keys=True))
    return items


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def build_channel_matrix(
    gen_at: str | None, branch: str | None, head: str | None, dirty: list[str]
) -> dict[str, Any]:
    result = _base(gen_at, branch, head, dirty)
    result["schema_version"] = "rig.distribution.release_channel_matrix.v1"
    result["channels"] = _apply_ids(CHANNELS, "channel_id", "dist-channel:")
    result["channel_count"] = len(result["channels"])
    return result


def build_credential_matrix(
    gen_at: str | None, branch: str | None, head: str | None, dirty: list[str]
) -> dict[str, Any]:
    result = _base(gen_at, branch, head, dirty)
    result["schema_version"] = "rig.distribution.release_credential_matrix.v1"
    result["credentials"] = _apply_ids(CREDENTIALS, "credential_id", "dist-cred:")
    result["credential_count"] = len(result["credentials"])
    return result


def build_api_matrix(
    gen_at: str | None, branch: str | None, head: str | None, dirty: list[str]
) -> dict[str, Any]:
    result = _base(gen_at, branch, head, dirty)
    result["schema_version"] = "rig.distribution.release_api_matrix.v1"
    result["apis"] = _apply_ids(APIS, "surface_id", "dist-api:")
    result["api_count"] = len(result["apis"])
    return result


def build_validation_matrix(
    gen_at: str | None, branch: str | None, head: str | None, dirty: list[str]
) -> dict[str, Any]:
    result = _base(gen_at, branch, head, dirty)
    result["schema_version"] = "rig.distribution.release_validation_matrix.v1"
    result["validations"] = _apply_ids(VALIDATIONS, "validation_id", "dist-valid:")
    result["validation_count"] = len(result["validations"])
    return result


def build_mutation_lane_matrix(
    gen_at: str | None, branch: str | None, head: str | None, dirty: list[str]
) -> dict[str, Any]:
    result = _base(gen_at, branch, head, dirty)
    result["schema_version"] = "rig.distribution.release_mutation_lane_matrix.v1"
    result["mutation_lanes"] = _apply_ids(MUTATIONS, "mutation_lane_id", "dist-mut:")
    result["mutation_lane_count"] = len(result["mutation_lanes"])
    result["remote_mutation_performed"] = False
    return result


def build_risk_register(
    gen_at: str | None, branch: str | None, head: str | None, dirty: list[str]
) -> dict[str, Any]:
    result = _base(gen_at, branch, head, dirty)
    result["schema_version"] = "rig.distribution.release_risk_register.v1"
    result["risks"] = _apply_ids(RISKS, "risk_id", "dist-risk:")
    result["risk_count"] = len(result["risks"])
    return result


def build_roadmap(
    gen_at: str | None, branch: str | None, head: str | None, dirty: list[str]
) -> dict[str, Any]:
    result = _base(gen_at, branch, head, dirty)
    result["schema_version"] = "rig.distribution.release_roadmap.v1"
    result["phases"] = _apply_ids(ROADMAP, "phase_id", "dist-roadmap:")
    result["phase_count"] = len(result["phases"])
    return result


def build_research_artifact(
    gen_at: str | None,
    branch: str | None,
    head: str | None,
    dirty: list[str],
    *,
    channel_matrix: dict,
    credential_matrix: dict,
    api_matrix: dict,
    validation_matrix: dict,
    mutation_matrix: dict,
    risk_register: dict,
    roadmap: dict,
) -> dict[str, Any]:
    result = _base(gen_at, branch, head, dirty)
    result["schema_version"] = "rig.distribution.release_research.v1"
    result["summary"] = {
        "channel_count": channel_matrix["channel_count"],
        "credential_count": credential_matrix["credential_count"],
        "api_count": api_matrix["api_count"],
        "validation_count": validation_matrix["validation_count"],
        "mutation_lane_count": mutation_matrix["mutation_lane_count"],
        "risk_count": risk_register["risk_count"],
        "phase_count": roadmap["phase_count"],
        "public_metadata_count": len(PUBLIC_METADATA),
        "artifact_concept_count": len(ARTIFACT_CONCEPTS),
    }
    result["metadata_matrix"] = PUBLIC_METADATA
    result["artifact_concepts"] = ARTIFACT_CONCEPTS
    return result


ALL_BUILDERS = {
    "distribution_release_channel_matrix_v1.v1.json": (
        build_channel_matrix,
        "channel_matrix",
    ),
    "distribution_release_credential_matrix_v1.v1.json": (
        build_credential_matrix,
        "credential_matrix",
    ),
    "distribution_release_api_matrix_v1.v1.json": (build_api_matrix, "api_matrix"),
    "distribution_release_validation_matrix_v1.v1.json": (
        build_validation_matrix,
        "validation_matrix",
    ),
    "distribution_release_mutation_lane_matrix_v1.v1.json": (
        build_mutation_lane_matrix,
        "mutation_lane_matrix",
    ),
    "distribution_release_risk_register_v1.v1.json": (
        build_risk_register,
        "risk_register",
    ),
    "distribution_release_roadmap_v1.v1.json": (build_roadmap, "roadmap"),
}


def _print_summary(report: dict[str, Any]) -> None:
    for key, value in report.get("summary", report).items():
        if isinstance(value, (int, str, bool)):
            print(f"  {key}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rig-distribution-release-research",
        description="Build distribution and release governance research artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory for artifacts.",
    )
    parser.add_argument(
        "--generated-at",
        type=str,
        default=None,
        help="Override generation timestamp for deterministic tests.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print compact content-light summary."
    )
    args = parser.parse_args(argv)

    gen_at = args.generated_at
    branch, head, dirty = _git_state(REPO_ROOT)

    # Build sub-artifacts first
    channel_matrix = build_channel_matrix(gen_at, branch, head, dirty)
    credential_matrix = build_credential_matrix(gen_at, branch, head, dirty)
    api_matrix = build_api_matrix(gen_at, branch, head, dirty)
    validation_matrix = build_validation_matrix(gen_at, branch, head, dirty)
    mutation_matrix = build_mutation_lane_matrix(gen_at, branch, head, dirty)
    risk_register = build_risk_register(gen_at, branch, head, dirty)
    roadmap = build_roadmap(gen_at, branch, head, dirty)

    sub_results = {
        "channel_matrix": channel_matrix,
        "credential_matrix": credential_matrix,
        "api_matrix": api_matrix,
        "validation_matrix": validation_matrix,
        "mutation_lane_matrix": mutation_matrix,
        "risk_register": risk_register,
        "roadmap": roadmap,
    }
    for filename, (_builder_fn, name) in ALL_BUILDERS.items():
        _write(args.output_dir / filename, sub_results[name])

    # Build top-level research artifact
    research = build_research_artifact(
        gen_at,
        branch,
        head,
        dirty,
        channel_matrix=channel_matrix,
        credential_matrix=credential_matrix,
        api_matrix=api_matrix,
        validation_matrix=validation_matrix,
        mutation_matrix=mutation_matrix,
        risk_register=risk_register,
        roadmap=roadmap,
    )
    _write(args.output_dir / "distribution_release_research_v1.v1.json", research)

    if args.summary:
        print("Distribution Release Research Artifacts Generated:")
        _print_summary(research)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
