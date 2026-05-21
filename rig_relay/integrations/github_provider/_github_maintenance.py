"""GitHub Integration Periodic Maintenance v1 — scheduled workspace refresh.

Refreshes evidence-backed claims, security queue, surface probes, profile README,
and codebase evidence graph on demand. Driven by canonically versioned governance artifacts.
Content-light. No remote mutation without explicit gates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GOV = _REPO_ROOT / "docs" / "json" / "governance"


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def refresh_claims_index(generated_at_utc: str | None = None) -> dict[str, Any]:
    """Re-run the claims index from existing evidence artifacts. Metadata only."""
    gen_at = generated_at_utc or _now_iso()
    existing = _GOV / "github_evidence_backed_claims_index_v1.v1.json"

    status = {
        "refreshed": existing.exists(),
        "generated_at": gen_at,
        "source": str(existing),
        "claims_count": 0,
        "remote_mutation": False,
    }

    if existing.exists():
        try:
            data = json.loads(existing.read_text(encoding="utf-8"))
            claims = data.get("claims", [])
            status["claims_count"] = len(claims) if isinstance(claims, list) else 0
        except json.JSONDecodeError:
            status["error"] = "claims_index_parse_failed"

    _write_json(_GOV / "github_maintenance_claims_refresh_v1.v1.json", status)
    return status


def refresh_surface_probes(generated_at_utc: str | None = None) -> dict[str, Any]:
    """Re-run surface probes against live GitHub API (read-only)."""
    from rig_relay.integrations.github_provider._carte_blanche_governed_lanes import (
        probe_all_surfaces,
    )

    return probe_all_surfaces(generated_at_utc=generated_at_utc)


def refresh_security_queue(generated_at_utc: str | None = None) -> dict[str, Any]:
    """Re-run the security queue from existing intake artifacts."""
    from rig_relay.integrations.github_provider._security_queue import (
        build_security_queue,
    )

    queue = build_security_queue(generated_at_utc=generated_at_utc)
    _write_json(_GOV / "github_security_queue_v1.v1.json", queue)
    return {
        "refreshed": True,
        "total_items": queue.get("queue_summary", {}).get("total_queue_items", 0),
    }


def refresh_evidence_graph(generated_at_utc: str | None = None) -> dict[str, Any]:
    """Re-build the codebase evidence graph from existing repo artifacts."""
    from rig_relay.integrations._codebase_evidence_graph import (
        build_codebase_evidence_graph,
    )
    from rig_relay.integrations._codebase_evidence_graph_projection import (
        build_projection_manifest,
    )

    graph = build_codebase_evidence_graph(generated_at_utc=generated_at_utc)
    # Build projection manifest alongside
    build_projection_manifest()
    return {
        "refreshed": True,
        "total_nodes": graph.get("summary", {}).get("total_nodes", 0),
        "total_edges": graph.get("summary", {}).get("total_edges", 0),
        "node_types": len(graph.get("summary", {}).get("node_type_counts", {})),
    }


def refresh_profile_readme(generated_at_utc: str | None = None) -> dict[str, Any]:
    """Re-run profile README live check and preview generation."""
    from rig_relay.integrations.github_provider._profile_readme_live_check import (
        check_profile_readme,
    )
    from rig_relay.integrations.github_provider._profile_readme_preview_generator import (
        generate_preview_file,
    )

    gen_at = generated_at_utc or _now_iso()

    check = check_profile_readme("juliantorr-es", dry_run=True)
    preview = generate_preview_file(owner="juliantorr-es")

    _write_json(_GOV / "github_profile_readme_live_check_v1.v1.json", check)

    status = {
        "refreshed": True,
        "generated_at": gen_at,
        "readme_status": check.get("status", "unknown"),
        "preview_path": preview.get("generated_preview_path", ""),
        "preview_lines": preview.get("generated_preview_line_count", 0),
        "included_claims": preview.get("included_claim_count", 0),
        "remote_mutation": False,
    }
    _write_json(_GOV / "github_maintenance_profile_readme_refresh_v1.v1.json", status)
    return status


def run_full_maintenance(generated_at_utc: str | None = None) -> dict[str, Any]:
    """Run all maintenance tasks. Content-light, no mutation."""
    gen_at = generated_at_utc or _now_iso()

    results: dict[str, Any] = {
        "schema_version": "rig.github.maintenance_report.v1",
        "generated_at": gen_at,
        "content_light": True,
        "remote_mutation": False,
        "tasks": {},
        "summary": {"tasks_run": 0, "tasks_refreshed": 0},
    }

    tasks = [
        ("claims_index", refresh_claims_index),
        ("security_queue", refresh_security_queue),
        ("evidence_graph", refresh_evidence_graph),
        ("profile_readme", refresh_profile_readme),
        ("surface_probes", refresh_surface_probes),
    ]

    for task_id, task_fn in tasks:
        results["summary"]["tasks_run"] += 1
        try:
            task_result = task_fn(gen_at)
            results["tasks"][task_id] = task_result
            if task_result.get("refreshed"):
                results["summary"]["tasks_refreshed"] += 1
        except Exception as e:
            results["tasks"][task_id] = {"error": str(e)[:200], "refreshed": False}

    _write_json(
        _GOV / "github_maintenance_report_v1.v1.json", results.get("summary", results)
    )

    # Also build the maintenance projection for cockpit
    projection = {
        "available": True,
        "last_run": gen_at,
        "tasks_run": results["summary"]["tasks_run"],
        "tasks_refreshed": results["summary"]["tasks_refreshed"],
        "next_scheduled": "manual — run `uv run python scripts/rig_github_maintenance.py`",
        "remote_mutation": False,
        "raw_payloads_exposed": False,
    }
    _write_json(_GOV / "github_maintenance_projection_v1.v1.json", projection)

    return results


__all__ = [
    "refresh_claims_index",
    "refresh_profile_readme",
    "refresh_security_queue",
    "refresh_surface_probes",
    "run_full_maintenance",
]
