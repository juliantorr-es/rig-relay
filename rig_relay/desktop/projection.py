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
import hashlib
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

PATCH_SECTION_NAMES: frozenset[str] = frozenset({
    "current_state",
    "queue",
    "dataset",
    "semantic_snippets",
    "telemetry_bundle",
    "update",
    "storage",
    "providers",
    "identity",
    "integrations",
    "release_gate",
    "service_state",
    "warnings",
    "read_only_actions",
    "execution_progress",
    "resources",
    "spiderweb_topology",
    "security_lifecycle_program",
    "live_mutation_readiness",
    "carte_blanche_dashboard",
    "site_editor",
    "operating_picture",
})


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


def _build_identity() -> dict[str, Any]:
    """Build content-light identity status from token store."""
    from rig_relay.identity.token_store import (
        DevFileTokenStore,
        enable_dev_file_token_store,
    )

    # explicitly opt in to dev-only plaintext token storage
    enable_dev_file_token_store()
    store = DevFileTokenStore()
    statuses = store.all_statuses()
    providers: dict[str, dict[str, Any]] = {}
    for name, st in statuses.items():
        providers[name] = {
            "status": st.get("status", "signed_out"),
            "display_name": st.get("display_name", ""),
            "scopes": st.get("scopes", []),
            "expires_at": st.get("expires_at", ""),
        }
    any_signed_in = any(s.get("status") == "signed_in" for s in providers.values())
    return {"available": True, "any_signed_in": any_signed_in, "providers": providers}


def _build_integrations() -> dict[str, Any]:
    """Build content-light integration provider status from manifests and identity."""
    try:
        from rig_relay.core.integrations.registry import build_integration_projection

        providers_list = build_integration_projection()
        connected_count = sum(
            1 for p in providers_list if p.get("connection_state") == "connected"
        )
        configured_count = sum(
            1
            for p in providers_list
            if p.get("connection_state") not in {"not_configured", "auth_required"}
        )
        return {
            "available": True,
            "total": len(providers_list),
            "connected": connected_count,
            "configured": configured_count,
            "providers": providers_list,
        }
    except Exception:
        return {"available": False}


def _build_resources() -> dict[str, Any]:
    """Derive resource projection snapshot from event fabric events."""
    try:
        from rig_relay.events.resource_projection_feed import ResourceProjectionFeed

        feed = ResourceProjectionFeed()
        snapshot = feed.snapshot()
        return {"available": True, **snapshot}
    except Exception:
        return {
            "available": False,
            "bridge_backend_health": "unknown",
            "projection_freshness": "unknown",
            "reconnect_pressure": "none",
            "event_queue_pressure": "none",
            "consumer_error_count": 0,
            "redaction_status": "content_light",
        }


def _build_spiderweb_topology() -> dict[str, Any]:
    """Read mission topology projection from event fabric derived artifact."""
    topo_path = (
        REPO_ROOT
        / ".build"
        / "rig-relay"
        / "derived"
        / "mission_topology_projection.v1.json"
    )
    data = _load_json(topo_path)
    if not data:
        return {"available": False, "status": "missing_artifact"}
    try:
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        strand = data.get("strand_states", {})
        pressure = data.get("resource_pressure", {})
        source_arts = data.get("source_artifacts", [])
        causal = data.get("causal_links", [])
        return {
            "available": True,
            "status": data.get("status", "unknown"),
            "generated_at": data.get("generated_at", ""),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "active_strand_count": strand.get("active_count", 0),
            "strand_state_summary": {
                "total_nodes": strand.get("total_nodes", 0),
                "healthy_count": strand.get("healthy_count", 0),
                "active_count": strand.get("active_count", 0),
                "idle_count": strand.get("idle_count", 0),
                "stale_count": strand.get("stale_count", 0),
                "degraded_count": strand.get("degraded_count", 0),
                "blocked_count": strand.get("blocked_count", 0),
                "no_input_count": strand.get("no_input_count", 0),
            },
            "resource_pressure_summary": {
                "reconnect_pressure": pressure.get("reconnect_pressure", "none"),
                "queue_pressure": pressure.get("queue_pressure", "none"),
                "consumer_errors": pressure.get("consumer_errors", "none"),
                "consumer_error_count": pressure.get("consumer_error_count", 0),
                "bridge_health": pressure.get("bridge_health", "unknown"),
            },
            "causal_summary": {
                "observed_links": sum(
                    1 for link in causal if link.get("confidence") == "observed"
                ),
                "correlated_only_links": sum(
                    1 for link in causal if link.get("confidence") == "correlated_only"
                ),
                "total_links": len(causal),
            },
            "degraded_reasons": data.get("degraded_reasons", []),
            "source_artifact_hashes": {
                a.get("artifact_id", ""): a.get("artifact_hash", "")[:16]
                for a in source_arts
            },
            "renderer_mode": "deterministic_svg",
            "raw_payloads_exposed": False,
            "redaction_status": "content_light",
        }
    except Exception:
        return {"available": False, "status": "invalid_artifact"}


def _build_carte_blanche_dashboard() -> dict[str, Any]:
    governance_root = REPO_ROOT / "docs" / "json" / "governance"
    expansion = _load_json(
        governance_root / "github_carte_blanche_expansion_plan_v1.v1.json"
    )
    surface_report = _load_json(
        governance_root / "github_carte_blanche_surface_report_v1.v1.json"
    )
    probes = surface_report.get("probes", {}) if surface_report else {}
    lanes = expansion.get("mutation_lanes", []) if expansion else []

    surface_status = {}
    for name, probe in probes.items():
        surface_status[name] = {
            "probed": probe.get("probed", False),
            "status_code": probe.get("status_code", 0),
        }

    lane_status = {
        "live_proven": len([l for l in lanes if l.get("live_proven")]),
        "read_verified": sum(
            1 for v in surface_status.values() if v["status_code"] == 200
        ),
        "write_wired": sum(1 for l in lanes if l.get("implemented")),
        "total": len(lanes),
    }

    return {
        "available": bool(expansion or surface_report),
        "surface_count": 13,
        "live_proven_write_lanes": lane_status["live_proven"],
        "read_verified_surfaces": lane_status["read_verified"],
        "gated_write_lanes": lane_status["write_wired"],
        "total_mutation_lanes": lane_status["total"],
        "surface_probes": surface_status,
        "content_light": True,
        "raw_payloads_exposed": False,
    }


def _build_site_editor_projection() -> dict[str, Any]:
    from rig_relay.integrations._site_editor import build_site_editor_projection

    return build_site_editor_projection()


def _build_security_lifecycle_program() -> dict[str, Any]:
    governance_root = REPO_ROOT / "docs" / "json" / "governance"
    inventory = _load_json(
        governance_root / "github_security_lifecycle_program_inventory_v1.v1.json"
    )
    replay = _load_json(governance_root / "github_security_lifecycle_replay_v1.v1.json")
    permission = _load_json(
        governance_root
        / "github_security_lifecycle_permission_boundary_audit_v1.v1.json"
    )

    if not inventory and not replay and not permission:
        return {"available": False, "status": "missing_artifacts"}

    artifacts = inventory.get("artifacts", []) if inventory else []
    stages = replay.get("lifecycle_stages", []) if replay else []
    gates = permission.get("gates", []) if permission else []

    has_remote_mutation = any(a.get("remote_mutation", False) for a in artifacts)

    all_blocked: list[str] = []
    for stage in stages:
        for r in stage.get("blocked_reasons", []):
            if r not in all_blocked:
                all_blocked.append(r)

    evidence_artifacts: list[dict[str, str]] = [
        {
            "path": str(governance_root / Path(a["path"]).name),
            "sha256": a["sha256"][:16],
        }
        for a in artifacts
    ]

    current_stage_count = sum(
        1
        for s in stages
        if s.get("status") == "present" and not s.get("blocked_reasons")
    )
    blocked_stage_count = sum(1 for s in stages if s.get("blocked_reasons"))

    return {
        "available": True,
        "phase_status": "active" if inventory else "unknown",
        "queue_summary": {
            "total_artifacts": inventory.get("total_artifacts", 0) if inventory else 0,
            "present_count": inventory.get("present_count", 0) if inventory else 0,
            "missing_count": inventory.get("missing_count", 0) if inventory else 0,
        },
        "selected_alert_summary": {
            "total_stages": len(stages),
            "stages_present": replay.get("stages_present", 0) if replay else 0,
            "current_stage_count": current_stage_count,
            "blocked_stage_count": blocked_stage_count,
        },
        "current_stage": next(
            (
                s["stage_id"]
                for s in stages
                if s.get("status") == "present" and not s.get("blocked_reasons")
            ),
            "none",
        )
        if stages
        else "none",
        "next_safe_action": (replay.get("next_safe_action", "") if replay else ""),
        "mutation_status": {
            "remote_mutation": has_remote_mutation,
            "local_mutation": False,
        },
        "approval_status": (replay.get("approval_chain", "") if replay else ""),
        "pr_lifecycle_state": "simulation_only"
        if (replay and replay.get("simulation_only"))
        else "unknown",
        "alert_lifecycle_state": "simulation"
        if (replay and replay.get("simulation_only"))
        else "unknown",
        "blocked_reasons": all_blocked[:20],
        "permission_summary": {
            "gates_passed": sum(1 for g in gates if g.get("proved", False)),
            "gates_total": len(gates),
            "verdict": (permission.get("verdict", "") if permission else ""),
            "read_permissions": (
                replay.get("permission_chain", {}).get("read_permissions_used", [])
                if replay
                else []
            ),
            "mutation_permissions": (
                replay.get("permission_chain", {}).get("mutation_permissions_used", [])
                if replay
                else []
            ),
        },
        "evidence_artifacts": evidence_artifacts,
        "event_fabric_summary": {
            "event_count": len(stages),
            "active_strands": current_stage_count,
        },
        "spiderweb_topology_summary": {
            "node_count": len(artifacts),
            "edge_count": max(0, len(artifacts) - 1),
            "active_strands": current_stage_count,
        },
        "raw_payloads_exposed": False,
        "redaction_status": "content_light",
    }


def _build_live_mutation_readiness() -> dict[str, Any]:
    governance_root = REPO_ROOT / "docs" / "json" / "governance"
    checklist = _load_json(
        governance_root / "github_live_mutation_operator_checklist_v1.v1.json"
    )
    if not checklist:
        checklist = _load_json(
            governance_root / "github_live_pr_rehearsal_operator_checklist_v1.v1.json"
        )
    runbook = _load_json(governance_root / "github_live_mutation_runbook_v1.v1.json")
    if not runbook:
        runbook = _load_json(governance_root / "github_live_pr_rehearsal_v1.v1.json")
    preflight = _load_json(
        governance_root / "github_live_mutation_preflight_v1.v1.json"
    )
    permission_audit = _load_json(
        governance_root
        / "github_live_mutation_phase3_permission_boundary_audit_v1.v1.json"
    )

    has_checklist = checklist is not None
    has_runbook = runbook is not None
    has_preflight = preflight is not None
    has_audit = permission_audit is not None

    if not has_checklist and not has_runbook:
        return {
            "available": False,
            "live_mutation_readiness_status": "missing_artifacts",
        }

    gates: list[dict[str, bool | str]] = []
    blocked_reasons: list[str] = []
    required_permissions: list[str] = []
    expected_live_operations: list[str] = []
    deferred_actions: list[str] = []
    rollback_guidance_summary = ""
    next_safe_action = ""

    if has_checklist:
        required_permissions = checklist.get("permissions_required", [])  # type: ignore[union-attr]
        expected_live_operations = checklist.get("expected_operations", [])  # type: ignore[union-attr]
        if checklist.get("alert_update_deferred"):  # type: ignore[union-attr]
            deferred_actions.append("alert_dismissal")
        if checklist.get("pr_merge_deferred"):  # type: ignore[union-attr]
            deferred_actions.append("pr_merge")
        rollback_guidance_summary = checklist.get("rollback_guidance", "")  # type: ignore[union-attr]

    if has_runbook:
        for g in runbook.get("gates", []) or []:  # type: ignore[union-attr]
            if isinstance(g, dict):
                gates.append({
                    "gate_id": g.get("gate", ""),
                    "passed": g.get("passed", False),
                    "detail": g.get("detail", ""),
                })
        for r in runbook.get("blocked_reasons", []) or []:  # type: ignore[union-attr]
            if r not in blocked_reasons:
                blocked_reasons.append(r)
        next_safe_action = runbook.get("next_safe_action", "")  # type: ignore[union-attr]
        if not rollback_guidance_summary:
            rollback_guidance_summary = runbook.get("rollback_guidance", "")  # type: ignore[union-attr]
        if not gates:
            gates.append({
                "gate_id": "gates_passed",
                "passed": runbook.get("gates_passed", False),  # type: ignore[union-attr]
                "detail": "",
            })

    if has_preflight:
        preflight_has_rs: bool = preflight.get("gates_passed", False)  # type: ignore[union-attr]
        for g in preflight.get("gates", []) or []:  # type: ignore[union-attr]
            gate_id = g.get("gate", "")
            if isinstance(gate_id, str) and not any(
                ex.get("gate_id") == gate_id for ex in gates
            ):
                gates.append({
                    "gate_id": gate_id,
                    "passed": g.get("passed", preflight_has_rs),
                    "detail": g.get("detail", ""),
                })
        for r in preflight.get("blocked_reasons", []) or []:  # type: ignore[union-attr]
            if r not in blocked_reasons:
                blocked_reasons.append(r)
        if not next_safe_action:
            next_safe_action = preflight.get("next_safe_action", "")  # type: ignore[union-attr]
        if not required_permissions:
            ps = preflight.get("permission_summary", {})  # type: ignore[union-attr]
            if ps.get("contents_write"):
                required_permissions.append("contents:write")
            if ps.get("pull_requests_write"):
                required_permissions.append("pull_requests:write")
            if ps.get("security_events_write_deferred"):
                required_permissions.append("security_events:write (deferred)")

    all_gates_passed = len(gates) > 0 and all(g.get("passed", False) for g in gates)
    all_perm_ready = len(required_permissions) > 0 and has_audit

    if not has_preflight:
        readiness_status = "not_configured"
    elif blocked_reasons:
        readiness_status = "blocked"
    elif all_gates_passed and all_perm_ready:
        readiness_status = "ready"
    else:
        readiness_status = "blocked"

    evidence_artifacts: list[dict[str, str | bool]] = []
    for name, present, path_suffix in [
        (
            "github_live_mutation_operator_checklist_v1.v1.json",
            has_checklist,
            "github_live_mutation_operator_checklist_v1.v1.json",
        ),
        (
            "github_live_pr_rehearsal_operator_checklist_v1.v1.json",
            not has_checklist and checklist is not None,
            "github_live_pr_rehearsal_operator_checklist_v1.v1.json",
        ),
        (
            "github_live_pr_rehearsal_v1.v1.json",
            has_runbook,
            "github_live_pr_rehearsal_v1.v1.json",
        ),
        (
            "github_live_mutation_preflight_v1.v1.json",
            has_preflight,
            "github_live_mutation_preflight_v1.v1.json",
        ),
        (
            "github_live_mutation_phase3_permission_boundary_audit_v1.v1.json",
            has_audit,
            "github_live_mutation_phase3_permission_boundary_audit_v1.v1.json",
        ),
    ]:
        if not present:
            continue
        a_path = governance_root / path_suffix
        item: dict[str, str | bool] = {"path": name, "present": True, "sha256": ""}
        if a_path.is_file():
            try:
                item["sha256"] = hashlib.sha256(a_path.read_bytes()).hexdigest()[:16]
            except OSError:
                pass
        evidence_artifacts.append(item)

    return {
        "available": True,
        "live_mutation_readiness_status": readiness_status,
        "operator_checklist_status": "present" if has_checklist else "missing",
        "runbook_status": "present" if has_runbook else "missing",
        "required_flags": ["--execute-remote", "--gates-approved"],
        "required_permissions": required_permissions,
        "readiness_gates": [
            g.get("gate_id", "") for g in gates if isinstance(g.get("gate_id"), str)
        ],
        "blocked_reasons": blocked_reasons[:20],
        "next_safe_action": next_safe_action,
        "expected_live_operations": expected_live_operations
        or ["create_branch", "commit_file", "create_pr"],
        "deferred_actions": deferred_actions
        or ["alert_dismissal", "alert_state_update", "pr_merge"],
        "rollback_guidance_summary": rollback_guidance_summary,
        "evidence_artifacts": evidence_artifacts,
        "raw_payloads_exposed": False,
        "redaction_status": "content_light",
    }

    gates: list[dict[str, bool | str]] = []
    blocked_reasons: list[str] = []
    required_permissions: list[str] = []
    expected_live_operations: list[str] = []
    deferred_actions: list[str] = []
    rollback_guidance_summary = ""
    next_safe_action = ""
    readiness_status: str

    if has_checklist:
        required_permissions = checklist.get("permissions_required", [])
        expected_live_operations = checklist.get("expected_operations", [])
        deferred_actions = []
        if checklist.get("alert_update_deferred"):
            deferred_actions.append("alert_dismissal")
        if checklist.get("pr_merge_deferred"):
            deferred_actions.append("pr_merge")
        rollback_guidance_summary = checklist.get("rollback_guidance", "")

    if has_runbook:
        runbook_gates = runbook.get("gates", [])
        if isinstance(runbook_gates, list):
            for g in runbook_gates:
                gates.append({
                    "gate_id": g.get("gate", ""),
                    "passed": g.get("passed", False),
                    "detail": g.get("detail", ""),
                })
        for r in runbook.get("blocked_reasons", []):
            if r not in blocked_reasons:
                blocked_reasons.append(r)
        if not next_safe_action:
            next_safe_action = runbook.get("next_safe_action", "")
        if not rollback_guidance_summary:
            rollback_guidance_summary = runbook.get("rollback_guidance", "")
        if not gates:
            gates.append({
                "gate_id": "gates_passed",
                "passed": runbook.get("gates_passed", False),
                "detail": "",
            })

    if has_preflight:
        preflight_gates = preflight.get("gates", [])
        if isinstance(preflight_gates, list):
            for g in preflight_gates:
                gate_id = g.get("gate", "")
                if not any(existing.get("gate_id") == gate_id for existing in gates):
                    gates.append({
                        "gate_id": gate_id,
                        "passed": g.get("passed", False),
                        "detail": g.get("detail", ""),
                    })
        for r in preflight.get("blocked_reasons", []):
            if r not in blocked_reasons:
                blocked_reasons.append(r)
        if not next_safe_action:
            next_safe_action = preflight.get("next_safe_action", "")
        if not required_permissions:
            ps = preflight.get("permission_summary", {})
            if ps.get("contents_write"):
                required_permissions.append("contents:write")
            if ps.get("pull_requests_write"):
                required_permissions.append("pull_requests:write")
            if ps.get("security_events_write_deferred"):
                required_permissions.append("security_events:write (deferred)")

    all_gates_passed = len(gates) > 0 and all(g.get("passed", False) for g in gates)
    all_perm_ready = len(required_permissions) > 0 and has_audit

    if not has_preflight:
        readiness_status = "not_configured"
    elif blocked_reasons:
        readiness_status = "blocked"
    elif all_gates_passed and all_perm_ready:
        readiness_status = "ready"
    else:
        readiness_status = "blocked"

    evidence_artifacts: list[dict[str, str | bool]] = []
    for name, present in [
        ("github_live_pr_rehearsal_operator_checklist_v1.v1.json", has_checklist),
        ("github_live_pr_rehearsal_v1.v1.json", has_runbook),
        ("github_live_mutation_preflight_v1.v1.json", has_preflight),
        ("github_live_mutation_phase3_permission_boundary_audit_v1.v1.json", has_audit),
    ]:
        a_path = governance_root / name
        item: dict[str, str | bool] = {"path": name, "present": present, "sha256": ""}
        if present and a_path.is_file():
            try:
                raw = a_path.read_bytes()
                item["sha256"] = hashlib.sha256(raw).hexdigest()[:16]
            except OSError:
                pass
        evidence_artifacts.append(item)

    return {
        "available": True,
        "live_mutation_readiness_status": readiness_status,
        "operator_checklist_status": "present" if has_checklist else "missing",
        "runbook_status": "present" if has_runbook else "missing",
        "required_flags": ["--execute-remote", "--gates-approved"],
        "required_permissions": required_permissions,
        "readiness_gates": [
            g.get("gate_id", "") for g in gates if isinstance(g.get("gate_id"), str)
        ],
        "blocked_reasons": blocked_reasons[:20],
        "next_safe_action": next_safe_action,
        "expected_live_operations": expected_live_operations
        or ["create_branch", "commit_file", "create_pr"],
        "deferred_actions": deferred_actions
        or ["alert_dismissal", "alert_state_update", "pr_merge"],
        "rollback_guidance_summary": rollback_guidance_summary,
        "evidence_artifacts": evidence_artifacts,
        "raw_payloads_exposed": False,
        "redaction_status": "content_light",
    }


def _build_operating_picture() -> dict[str, Any]:
    """Return a default unavailable operating_picture section.

    The cockpit bridge will inject the actual operating picture data
    once a repository is opened and Ralph has scanned it.
    """
    return {"available": False, "reason": "no_repository_opened"}


def _build_service_state() -> dict[str, Any]:
    from rig_relay.governance.service_state import get_capability_gate

    gate = get_capability_gate()
    summary = gate.state_summary()
    summary["available"] = True
    return summary


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


def build_projection(
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
    identity = _build_identity()
    integrations = _build_integrations()
    integrity = _build_integrity(root)
    tool_runtime_summary = _build_tool_runtime_summary()
    release_gate = _build_release_gate()
    service_state = _build_service_state()
    resources = _build_resources()
    spiderweb_topology = _build_spiderweb_topology()
    security_lifecycle_program = _build_security_lifecycle_program()
    live_mutation_readiness = _build_live_mutation_readiness()
    carte_blanche_dashboard = _build_carte_blanche_dashboard()
    site_editor = _build_site_editor_projection()
    operating_picture = _build_operating_picture()

    source_status = {
        "current_state": current_state["available"],
        "queue": queue["available"],
        "dataset": dataset["available"],
        "semantic_snippets": semantic_snippets["available"],
        "telemetry_bundle": telemetry_bundle["available"],
        "update": update["available"],
        "storage": storage["available"],
        "provider_status": providers["total"] > 0,
        "identity": identity["available"],
        "integrations": integrations["available"],
        "integrity": integrity is not None,
        "tool_runtime_summary": tool_runtime_summary.get("available", False),
        "release_gate": release_gate["available"],
        "service_state": service_state["available"],
        "resources": resources["available"],
        "spiderweb_topology": spiderweb_topology["available"],
        "security_lifecycle_program": security_lifecycle_program["available"],
        "live_mutation_readiness": live_mutation_readiness["available"],
        "carte_blanche_dashboard": carte_blanche_dashboard["available"],
        "operating_picture": operating_picture["available"],
    }

    warnings: list[str] = []
    for name, available in source_status.items():
        if not available:
            warnings.append(
                f"Data source '{name}' not available. Run the corresponding generator."
            )

    from rig_relay.core.telemetry.local import is_telemetry_enabled as _tele_enabled
    from rig_relay.core.telemetry.types import TelemetryMode as _TelemetryMode

    _runtime_enabled = _tele_enabled()

    projection: dict[str, Any] = {
        "schema_version": "rig.relay.desktop_projection.v1",
        "generated_at": now.isoformat(),
        "app_version": app_version,
        "alpha_label": "a" in app_version or "alpha" in app_version,
        "telemetry_mode": _TelemetryMode.ENABLED_FIRST_PARTY.value
        if _runtime_enabled
        else _TelemetryMode.DISABLED_BY_USER.value,
        "telemetry_degraded": not _runtime_enabled,
        "source_status": source_status,
        "current_state": current_state,
        "queue": queue,
        "dataset": dataset,
        "semantic_snippets": semantic_snippets,
        "telemetry_bundle": telemetry_bundle,
        "update": update,
        "storage": storage,
        "providers": providers,
        "identity": identity,
        "integrations": integrations,
        "integrity": integrity,
        "tool_runtime_summary": tool_runtime_summary,
        "_release_gate": release_gate,
        "service_state": service_state,
        "resources": resources,
        "spiderweb_topology": spiderweb_topology,
        "security_lifecycle_program": security_lifecycle_program,
        "live_mutation_readiness": live_mutation_readiness,
        "carte_blanche_dashboard": carte_blanche_dashboard,
        "site_editor": site_editor,
        "operating_picture": operating_picture,
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


# ── Per-session patch state ──────────────────────────────────────────────

_last_full_sections: dict[str, Any] | None = None
_last_full_projection_seq: int = 0


def reset_patch_state() -> None:
    global _last_full_sections, _last_full_projection_seq
    _last_full_sections = None
    _last_full_projection_seq = 0


def build_projection_patch(
    build_root: Path | None = None,
    trace_id: str = "",
    frontend_session_id: str = "",
    backend_session_id: str = "",
    patch_kind: str = "full",
    asked_sections: Sequence[str] | None = None,
    previous_sections: dict[str, Any] | None = None,
    stale_after_seconds: int | None = None,
) -> dict[str, Any]:
    """Build a projection patch compliant with the backend_projection_patch schema.

    Args:
        build_root: Path to .build/rig-relay directory.
        trace_id: Correlates to the intent or lifecycle event that triggered this patch.
        frontend_session_id: Frontend session this patch targets.
        backend_session_id: Backend session that produced this patch.
        patch_kind: "full", "partial", or "delta".
        asked_sections: For partial patches, the list of section names to include.
            If None for a partial patch, computes diff from ``previous_sections``.
        previous_sections: Prior section state for diff computation.
        stale_after_seconds: Optional max age before frontend should request fresh full.

    Returns:
        Dict compliant with rig.relay.backend_projection_patch.v1.
    """
    global _last_full_sections, _last_full_projection_seq

    full = build_projection(build_root=build_root)

    all_sections: dict[str, Any] = {}
    for section in PATCH_SECTION_NAMES:
        if section in full:
            all_sections[section] = full[section]

    match patch_kind:
        case "full":
            _last_full_sections = dict(all_sections)
            _last_full_projection_seq += 1
            changed = sorted(all_sections.keys())
            sections = dict(all_sections)
            seq = _last_full_projection_seq

        case "partial":
            if asked_sections:
                names = [s for s in asked_sections if s in all_sections]
            elif previous_sections:
                names = [
                    s
                    for s in sorted(all_sections.keys())
                    if s not in previous_sections
                    or all_sections.get(s) != previous_sections.get(s)
                ]
            else:
                names = sorted(all_sections.keys())

            _last_full_projection_seq += 1
            changed = names
            sections = {n: all_sections[n] for n in names}
            if _last_full_sections is not None:
                for n in names:
                    _last_full_sections[n] = all_sections[n]
            else:
                _last_full_sections = dict(all_sections)
            seq = _last_full_projection_seq

        case "delta":
            _last_full_projection_seq += 1
            changed = (
                sorted(all_sections.keys())
                if asked_sections is None
                else list(asked_sections)
            )
            sections = {n: all_sections[n] for n in changed if n in all_sections}
            seq = _last_full_projection_seq

        case _:
            raise ValueError(f"Unknown patch_kind: {patch_kind}")

    digest_sections = {k: v for k, v in sections.items() if k != "generated_at"}
    digest_raw = json.dumps(digest_sections, sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )
    digest = f"sha256:{hashlib.sha256(digest_raw).hexdigest()}"

    warnings: list[str] = []
    missing = [s for s in changed if s not in sections]
    if missing:
        warnings.append(f"Sections requested but not available: {missing}")

    return {
        "schema_version": "rig.relay.backend_projection_patch.v1",
        "projection_sequence": seq,
        "trace_id": trace_id,
        "frontend_session_id": frontend_session_id,
        "backend_session_id": backend_session_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "patch_kind": patch_kind,
        "changed_sections": changed,
        "sections": sections,
        "digest": digest,
        "redaction_status": "content_light",
        "warnings": warnings,
        **({"stale_after_seconds": stale_after_seconds} if stale_after_seconds else {}),
    }


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
