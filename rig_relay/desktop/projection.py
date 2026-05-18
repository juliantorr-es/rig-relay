"""Rig Relay Desktop Projection Builder — core module.

Builds a content-light cockpit projection from available Rig Relay build
artifacts. All field names are drawn from actual artifact schemas. Missing
sources are represented as available=false, never invented.

Provenance (Rig-to-Relay porting doctrine):
  Pattern source: Rig's projection_builder.py (WidgetProjection + UIProjection
  model) adapted for Rig Relay's artifact stack.
  Porting status: ported (relay_owned).
  See docs/governance/rig-to-relay-pattern-inventory.md § shell-ui-projection.
  Not a copy of Rig's product domain — uses Rig Relay's own artifact schemas,
  field names, and read_only_actions list.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import jsonschema

from rig_relay.desktop.execution_progress import execution_progress_from_runtime_events
from rig_relay.desktop.projection_integrity import build_projection_integrity_assessment
from rig_relay.evidence.receipt_index import build_receipt_index
from rig_relay.evidence.storage_lifecycle import compute_storage_summary

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_BUILD_ROOT = REPO_ROOT / ".build" / "rig-relay"


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load a JSON file, return None on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_markdown_summary(path: Path) -> dict[str, Any] | None:
    """Parse dataset-summary.md Executive Summary table only.

    Reads only the first markdown table (Executive Summary).
    Ignores subsequent tables which may contain non-numeric values.
    """
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    result: dict[str, Any] = {}
    in_table = False

    for line in lines:
        s = line.strip()
        if s.startswith("|") and "|" in s[1:]:
            in_table = True
            parts = [p.strip() for p in s.split("|")[1:-1]]
            TABLE_COLUMN_COUNT = 2
            if len(parts) == TABLE_COLUMN_COUNT:
                val = parts[1]
                try:
                    result["exec_" + parts[0].lower().replace(" ", "_")] = int(val)
                except ValueError:
                    pass
        elif in_table:
            break

    return result if result else None


def _get_app_version() -> str:
    """Read app version from rig_relay/__init__.py."""
    init_path = REPO_ROOT / "rig_relay" / "__init__.py"
    if not init_path.is_file():
        return "unknown"
    VERSION_PARTS_COUNT = 2
    for line in init_path.read_text("utf-8").splitlines():
        if line.startswith("__version__"):
            parts = line.split("=", 1)
            if len(parts) == VERSION_PARTS_COUNT:
                return parts[1].strip().strip('"').strip("'")
    return "unknown"


PROJECTION_SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.relay.desktop_projection.v1.schema.json"
)

READ_ONLY_ACTIONS = [
    "refresh_projection",
    "view_current_state",
    "view_dataset_summary",
    "view_semantic_snippets",
    "view_telemetry_bundle",
    "view_update_status",
    "view_queue_plan",
    "view_integrity_assessment",
]


def _build_current_state(build_root: Path) -> dict[str, Any]:
    """Read current_state.json and extract summary fields."""
    state = _load_json(build_root / "current_state.json")
    if not state:
        return {"available": False}

    summary = state.get("summary", {})
    return {
        "available": True,
        "active_children": summary.get("active_children", 0),
        "max_children": summary.get("max_children", 0),
        "available_child_slots": summary.get("available_child_slots", 0),
        "active_writers": summary.get("active_writers", 0),
        "active_readers": summary.get("active_readers", 0),
        "conflicts": summary.get("conflicts", 0),
        "stale_leases": summary.get("stale_leases", 0),
        "checkpoint_commits": summary.get("checkpoint_commits", 0),
        "checkpoint_refusals": summary.get("checkpoint_refusals", 0),
        "generated_at": state.get("generated_at", ""),
    }


def _build_queue(build_root: Path) -> dict[str, Any]:
    """Read queue/ready_plan.json if present."""
    plan = _load_json(build_root / "queue" / "ready_plan.json")
    if not plan:
        return {"available": False}

    ready = plan.get("ready", []) if isinstance(plan.get("ready"), list) else []
    blocked = plan.get("blocked", []) if isinstance(plan.get("blocked"), list) else []
    waiting = plan.get("waiting", []) if isinstance(plan.get("waiting"), list) else []
    return {
        "available": True,
        "ready_items": len(ready),
        "blocked_items": len(blocked),
        "waiting_items": len(waiting),
        "total_items": len(ready) + len(blocked) + len(waiting),
    }


def _build_dataset(build_root: Path) -> dict[str, Any]:
    """Read export_manifest.json and dataset-summary.md."""
    manifest = _load_json(build_root / "derived" / "export_manifest.json")
    summary = _load_markdown_summary(build_root / "reports" / "dataset-summary.md")

    if not manifest and not summary:
        return {"available": False}

    result: dict[str, Any] = {"available": True}

    if manifest:
        rc = manifest.get("row_counts", {})
        result["exported_at"] = manifest.get("exported_at", "")
        result["coordination_rows"] = rc.get("cross_session_coordination_dataset", 0)
        result["tool_failure_rows"] = rc.get("tool_failure_patterns_dataset", 0)
        result["provider_perf_rows"] = rc.get("provider_task_performance_dataset", 0)
        result["findings_rows"] = rc.get("findings_dataset", 0)
        result["artifact_reuse_rows"] = rc.get("artifact_reuse_dataset", 0)
        result["checkpoint_rows"] = rc.get("checkpoint_eval_dataset", 0)
        result["skipped_event_count"] = manifest.get("skipped_event_count", 0)
        result["strict"] = manifest.get("strict", False)
        result["datasets_generated"] = bool(manifest.get("row_counts", {}))

    if summary:
        result["sessions_observed"] = summary.get("exec_sessions_observed", 0)
        result["coordination_events_total"] = summary.get("exec_coordination_events", 0)
        result["tool_calls_total"] = summary.get("exec_tool_calls", 0)

    return result


def _build_semantic_snippets(build_root: Path) -> dict[str, Any]:
    """Read semantic_change_snippets_manifest.json."""
    manifest = _load_json(
        build_root / "derived" / "semantic_change_snippets_manifest.json"
    )
    if not manifest:
        return {"available": False}

    return {
        "available": True,
        "snippet_count": manifest.get("snippet_count", 0),
        "skipped_count": manifest.get("skipped_count", 0),
        "forbidden_count": manifest.get("forbidden_count", 0),
        "strict_mode": manifest.get("strict_mode", False),
        "remote_sharing_safe": manifest.get("remote_sharing_safe", False),
        "created_at": manifest.get("created_at", ""),
    }


def _build_providers(state_root: Path | None = None) -> dict[str, Any]:
    """Build provider status by merging env-var and dev-file key stores.

    Env vars take precedence over dev-file keys. Uses check_provider_status
    with network_allowed=False for honest status: configured providers show
    as "skipped" (not "valid") unless a real network check succeeded.
    """
    from rig_relay.identity.state_paths import provider_state_root
    from rig_relay.providers.health_check import check_provider_status
    from rig_relay.providers.key_store import (
        DevFileProviderKeyStore,
        EnvProviderKeyStore,
    )
    from rig_relay.providers.registry import PROVIDER_REGISTRY

    providers_dir = (
        provider_state_root(root=state_root) if state_root is not None else None
    )
    env_ks = EnvProviderKeyStore()
    dev_ks = DevFileProviderKeyStore(providers_dir=providers_dir)

    merged: list[dict[str, Any]] = []
    configured_count = 0
    valid_count = 0

    for info in PROVIDER_REGISTRY:
        # Prefer env vars, fall back to dev files for key detection
        if env_ks.has_key(info.provider):
            ks = env_ks
        elif dev_ks.has_key(info.provider):
            ks = dev_ks
        else:
            ks = None

        if ks is not None:
            status_obj = check_provider_status(info.provider, ks, network_allowed=False)
            d = status_obj.to_dict()
            configured_count += 1
            if d.get("status") == "valid":
                valid_count += 1
        else:
            d = {
                "provider": info.provider.value,
                "display_name": info.display_name,
                "configured": False,
                "key_source": "missing",
                "key_fingerprint": "",
                "base_url": info.base_url if info.supports_base_url else None,
                "default_model": info.default_model,
                "status": "skipped",
                "warnings": [],
                "last_checked_at": datetime.now(UTC).isoformat(),
            }
        merged.append(d)

    return {
        "total": len(merged),
        "configured": configured_count,
        "valid_count": valid_count,
        "providers": merged,
    }


def _build_telemetry_bundle(build_root: Path) -> dict[str, Any]:
    """Find the most recent telemetry bundle manifest."""
    bundle_dir = build_root / "telemetry-bundles"
    if not bundle_dir.is_dir():
        return {"available": False}

    manifests: list[tuple[str, dict[str, Any]]] = []
    for entry in sorted(bundle_dir.iterdir(), reverse=True):
        manifest_path = entry / "telemetry_bundle_manifest.json"
        data = _load_json(manifest_path)
        if data:
            manifests.append((entry.name, data))
            break

    if not manifests:
        return {"available": False}

    name, data = manifests[0]
    return {
        "available": True,
        "bundle_id": data.get("bundle_id", name),
        "share_level": data.get("share_level", "unknown"),
        "status": data.get("status", "unknown"),
        "bundle_sha256": data.get("bundle_sha256", ""),
        "created_at": data.get("created_at", ""),
    }


def _build_tool_runtime_summary() -> dict[str, Any]:
    """Build tool runtime summary from the active session ledger."""
    try:
        from rig_relay.core.tool_runtime_ledger import get_active_ledger

        ledger = get_active_ledger()
        summary = ledger.build_summary()
        return {
            "available": summary.total_executions > 0,
            **summary.model_dump(mode="json"),
        }
    except Exception:
        return {"available": False}


def _build_storage(build_root: Path) -> dict[str, Any]:
    """Compute storage summary from build artifacts."""
    summary = compute_storage_summary(build_root=build_root)
    if summary.get("budget_status") == "unknown":
        return {"available": False}

    return {
        "available": True,
        "budget_status": summary.get("budget_status", "unknown"),
        "total_size_mb": summary.get("total_size_mb", 0.0),
        "rollup_candidate_count": summary.get("rollup_candidate_count", 0),
        "prune_candidate_count": summary.get("prune_candidate_count", 0),
        "stale_lease_count": summary.get("stale_lease_count", 0),
        "recommendations": summary.get("recommendations", []),
    }


def _build_update(build_root: Path) -> dict[str, Any]:
    """Run or read update status. Falls back to checking build dir."""
    status_path = build_root / "update_status.json"
    status = _load_json(status_path)
    if not status:
        try:
            import subprocess

            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "python",
                    "scripts/rig_relay_update_status.py",
                    "--latest",
                    "0.2.0a1",
                ],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
                timeout=10,
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
        except Exception:
            pass

    if not status:
        return {"available": False}

    return {
        "available": True,
        "current_version": status.get("current_version", ""),
        "latest_version": status.get("latest_version", ""),
        "update_available": status.get("update_available", False),
        "update_state": status.get("update_state", ""),
        "restart_required": status.get("restart_required", False),
        "restart_safe": status.get("restart_safe", True),
        "blocked_by_active_sessions": status.get("blocked_by_active_sessions", 0),
    }


def _build_release_gate() -> dict[str, Any]:
    """Read release gate data from docs/json/release_gate/."""
    gate_path = (
        REPO_ROOT / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
    )
    blockers_path = (
        REPO_ROOT / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
    )

    gate = _load_json(gate_path)
    if not gate:
        return {"available": False}

    open_blocker_count = 0
    total_blocker_count = 0
    if blockers_path.is_file():
        try:
            for line in blockers_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    b = json.loads(line)
                    total_blocker_count += 1
                    if b.get("status") == "open":
                        open_blocker_count += 1
                except json.JSONDecodeError:
                    pass
        except OSError:
            pass

    phases = [
        {
            "phase_id": p.get("phase_id", ""),
            "title": p.get("title", ""),
            "status": p.get("status", "unknown"),
        }
        for p in gate.get("phases", [])
    ]

    last_validation_run = None
    val_dir = DEFAULT_BUILD_ROOT / "validation_runs"
    if val_dir.is_dir():
        val_files = sorted(
            val_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        if val_files:
            val_data = _load_json(val_files[0])
            if val_data:
                last_validation_run = {
                    "result": val_data.get("result", "unknown"),
                    "tests_run": val_data.get("tests_run", 0),
                    "created_at": val_data.get("created_at", ""),
                }

    return {
        "available": True,
        "gate_id": gate.get("gate_id", ""),
        "overall_status": gate.get("overall_status", "unknown"),
        "phases": phases,
        "open_blocker_count": open_blocker_count,
        "total_blocker_count": total_blocker_count,
        "last_validation_run": last_validation_run,
    }


def _build_integrity(root: Path | None = None) -> dict[str, Any] | None:
    """Build a content-light projection integrity assessment from available receipts.

    Tries to load the most recent session's receipt index and produce an
    assessment. Returns ``None`` when no receipt records are available.

    Args:
        root: Path to .build/rig-relay directory (unused, for signature
            consistency with other _build_* helpers).

    Returns:
        ProjectionIntegrityAssessment as a dict, or None.
    """
    from pathlib import Path as _Path

    sessions_root = _Path.home() / ".rig" / "relay" / "sessions"
    if not sessions_root.is_dir():
        return None

    # Find the most recent session directory
    session_dirs = sorted(
        (d for d in sessions_root.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not session_dirs:
        return None

    # Try each session until we find one with receipt records
    for session_dir in session_dirs:
        session_id = session_dir.name
        records, _errors = build_receipt_index(session_id)
        if records:
            assessment = build_projection_integrity_assessment(
                receipt_records=[r.model_dump(mode="json") for r in records]
            )
            return assessment.model_dump(mode="json")

    return None


def _validate_against_schema(projection: dict[str, Any]) -> list[str]:
    """Validate projection against schema. Returns list of violation messages."""
    schema = _load_json(PROJECTION_SCHEMA_PATH)
    if not schema:
        return ["Schema file not found or invalid"]

    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(projection)]


def build_projection(  # noqa: PLR0914
    build_root: Path | None = None, runtime_events: Sequence[Any] | None = None
) -> dict[str, Any]:
    """Build a content-light desktop projection from available artifacts.

    Args:
        build_root: Path to .build/rig-relay directory.
        runtime_events: Optional sequence of runtime stream events (model instances
            or dicts). When provided, aggregates into execution_progress using
            execution_progress_from_runtime_events(). The result is content-light:
            no raw chunk_text, stdout/stderr content, or file contents.

    Returns:
        Projection dict with schema_version, source_status, category fields,
        and optional execution_progress.
    """
    root = build_root or DEFAULT_BUILD_ROOT
    now = datetime.now(UTC)
    app_version = _get_app_version()

    current_state = _build_current_state(root)
    queue = _build_queue(root)
    dataset = _build_dataset(root)
    semantic_snippets = _build_semantic_snippets(root)
    telemetry_bundle = _build_telemetry_bundle(root)
    update = _build_update(root)
    storage = _build_storage(root)
    providers = _build_providers()
    integrity = _build_integrity(root)
    tool_runtime_summary = _build_tool_runtime_summary()
    release_gate = _build_release_gate()

    source_status = {
        "current_state": current_state["available"],
        "queue": queue["available"],
        "dataset": dataset["available"],
        "semantic_snippets": semantic_snippets["available"],
        "telemetry_bundle": telemetry_bundle["available"],
        "update": update["available"],
        "storage": storage["available"],
        "provider_status": providers["total"] > 0,
        "integrity": integrity is not None,
        "tool_runtime_summary": tool_runtime_summary.get("available", False),
        "release_gate": release_gate["available"],
    }

    warnings: list[str] = []
    for name, available in source_status.items():
        if not available:
            warnings.append(
                f"Data source '{name}' not available. Run the corresponding generator."
            )

    from rig_relay.core.telemetry.local import is_telemetry_enabled as _tele_enabled

    effective_mode = "full" if _tele_enabled() else "disabled"

    projection: dict[str, Any] = {
        "schema_version": "rig.relay.desktop_projection.v1",
        "generated_at": now.isoformat(),
        "app_version": app_version,
        "alpha_label": "a" in app_version or "alpha" in app_version,
        "telemetry_mode": effective_mode,
        "telemetry_degraded": not _tele_enabled(),
        "source_status": source_status,
        "current_state": current_state,
        "queue": queue,
        "dataset": dataset,
        "semantic_snippets": semantic_snippets,
        "telemetry_bundle": telemetry_bundle,
        "update": update,
        "storage": storage,
        "providers": providers,
        "integrity": integrity,
        "tool_runtime_summary": tool_runtime_summary,
        "_release_gate": release_gate,
        "warnings": warnings,
        "read_only_actions": list(READ_ONLY_ACTIONS),
    }

    if runtime_events is not None:
        exec_progress = execution_progress_from_runtime_events(runtime_events)
        projection["execution_progress"] = exec_progress.model_dump(mode="json")

    schema_errors = _validate_against_schema(projection)
    if schema_errors:
        projection["_schema_validation_errors"] = schema_errors
        warnings.extend(f"Schema violation: {e}" for e in schema_errors)

    return projection


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Rig Relay desktop cockpit projection from available artifacts."
    )
    parser.add_argument(
        "--build-root",
        type=Path,
        default=DEFAULT_BUILD_ROOT,
        help="Path to .build/rig-relay directory (default: .build/rig-relay)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for projection JSON (default: .build/rig-relay/desktop/projection.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    projection = build_projection(build_root=args.build_root)

    output_path = args.output or DEFAULT_BUILD_ROOT / "desktop" / "projection.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(projection, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    available = sum(1 for v in projection["source_status"].values() if v)
    total = len(projection["source_status"])
    print(f"Projection written to {output_path}")
    print(f"  Data sources: {available}/{total} available")
    print(f"  App version: {projection['app_version']}")
    print(f"  Warnings: {len(projection['warnings'])}")
    if projection.get("_schema_validation_errors"):
        print(f"  Schema errors: {len(projection['_schema_validation_errors'])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
