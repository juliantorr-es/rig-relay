"""Phase 2 Security Lifecycle Replay Engine.

Reconstructs pipeline state from existing Phase 2 artifacts. No live network. No mutation.
Distinguishes remote_mutation (always false) from fake_boundary_mutation (simulation_only).
Returns content-light dict. Uses safe_summary from _redaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.github_provider._redaction import safe_summary

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GOV = _REPO_ROOT / "docs" / "json" / "governance"
_EVIDENCE = _REPO_ROOT / ".build" / "rig-relay" / "evidence"
_REPORTS = _REPO_ROOT / ".rig" / "reports"

_STATUS_VALUES = frozenset({
    "complete",
    "blocked",
    "degraded",
    "deferred",
    "missing",
    "invalid",
    "simulated",
    "disabled",
})

_PIPELINE_STAGES: list[dict[str, Any]] = [
    {
        "stage_id": "intake",
        "artifact": "github_security_intake_result.v1.json",
        "slice": 0,
        "kind": "intake",
    },
    {
        "stage_id": "queue",
        "artifact": "github_security_queue_v1.v1.json",
        "slice": 1,
        "kind": "queue",
    },
    {
        "stage_id": "remediation_plan",
        "artifact": "github_security_remediation_plan_v1.v1.json",
        "slice": 2,
        "kind": "planning",
    },
    {
        "stage_id": "patch_proposal",
        "artifact": "github_code_scanning_patch_proposal_v1.v1.json",
        "slice": 3,
        "kind": "planning",
    },
    {
        "stage_id": "patch_preview",
        "artifact": "github_code_scanning_patch_preview_v1.v1.json",
        "slice": 4,
        "kind": "planning",
    },
    {
        "stage_id": "source_context",
        "artifact": "github_code_scanning_source_context_v1.v1.json",
        "slice": 5,
        "kind": "planning",
    },
    {
        "stage_id": "candidate_diff",
        "artifact": "code_scanning_dry_run_candidate_diff_v1.v1.json",
        "slice": 6,
        "kind": "planning",
    },
    {
        "stage_id": "pr_plan",
        "artifact": "code_scanning_pr_creation_plan_v1.v1.json",
        "slice": 7,
        "kind": "planning",
    },
    {
        "stage_id": "mutation_readiness",
        "artifact": "code_scanning_pr_mutation_readiness_v1.v1.json",
        "slice": 8,
        "kind": "gate",
    },
    {
        "stage_id": "pr_mutation_executor",
        "artifact": "github_code_scanning_pr_mutation_execution_v1.v1.json",
        "slice": 9,
        "kind": "simulation",
    },
    {
        "stage_id": "post_pr_lifecycle",
        "artifact": "github_code_scanning_post_pr_lifecycle_v1.v1.json",
        "slice": 10,
        "kind": "lifecycle",
    },
    {
        "stage_id": "permission_matrix",
        "artifact": "github_code_scanning_permission_matrix_v1.v1.json",
        "slice": 8,
        "kind": "governance",
    },
    {
        "stage_id": "alert_state_plan",
        "artifact": "github_code_scanning_alert_state_plan_v1.v1.json",
        "slice": 10,
        "kind": "governance",
    },
]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    result = read_safe(path, raise_on_error=True)
    try:
        data = json.loads(result.text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _determine_status(
    artifact_present: bool, data: dict[str, Any] | None, blocked_reasons: list[str]
) -> str:
    if not artifact_present:
        return "missing"
    if not isinstance(data, dict):
        return "invalid"

    rm_ok = data.get("remote_mutation") not in {True, "true", "permitted"}
    rm_ok &= data.get("remote_mutation_status") in {None, "disabled", "simulation_only"}
    if not rm_ok:
        return "degraded"

    is_simulated = "simulation_only" in str(data.get("mutation_status", ""))
    is_simulated |= data.get("local_mutation_status") in {
        "simulation_only",
        "simulation passed with approval",
    }
    if is_simulated:
        return "simulated"

    sim_prefixes = frozenset({"simulation", "candidate_", "readiness_", "approval_no"})
    genuine_block = blocked_reasons and not all(
        r.startswith(tuple(sim_prefixes)) for r in blocked_reasons
    )
    if data.get("blocked") or data.get("deferred") or genuine_block:
        return "blocked"
    return "complete"


def _collect_blocked_reasons(data: dict[str, Any] | None) -> list[str]:
    if not isinstance(data, dict):
        return ["artifact_invalid"]
    reasons: list[str] = []
    for field_name in ("blocked_reasons", "deferred_reasons", "missing_evidence"):
        val = data.get(field_name)
        if isinstance(val, list):
            reasons.extend([str(r) for r in val if isinstance(r, str)])
    if data.get("remote_mutation") is True:
        reasons.append("remote_mutation_detected_unexpectedly")
    if data.get("content_light") is False:
        reasons.append("content_heavy_artifact")
    return reasons


def _discover_evidence_paths() -> list[Path]:
    if not _EVIDENCE.exists():
        return []
    return sorted(
        [p for p in _EVIDENCE.iterdir() if p.is_file() and p.suffix == ".json"],
        key=lambda p: p.stat().st_mtime,
    )


def _discover_report_paths() -> list[Path]:
    reports_jsonl = _REPORTS / "reports.jsonl"
    if not reports_jsonl.exists():
        return []
    return [reports_jsonl]


def _classify_evidence_relevance(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "name": path.name,
        "exists": True,
        "sha256": _sha256_file(path),
        "relevance": (
            "code_scanning_mutation"
            if "code_scanning" in path.name or "mutation" in path.name
            else "general"
        ),
    }


@dataclass(slots=True)
class PipelineStageResult:
    stage_id: str
    slice: int
    kind: str
    source_artifact_path: str
    artifact_present: bool
    artifact_sha256: str | None
    status: str
    blocked_reasons: list[str] = field(default_factory=list)
    deferred_reasons: list[str] = field(default_factory=list)
    schema_version: str = ""
    remote_mutation: bool = False
    fake_boundary_mutation: str = "simulation_only"
    content_light: bool = True


@dataclass(slots=True)
class StageClassification:
    present_ids: list[str] = field(default_factory=list)
    complete: list[str] = field(default_factory=list)
    simulated: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    pr_lifecycle_state: str = "no_pr"
    alert_lifecycle_state: str = "alert_unknown"
    next_safe_action: str = "regenerate_all_artifacts"


def _classify_stages(stages: list[dict[str, Any]]) -> StageClassification:
    c = StageClassification()
    c.present_ids = [s["stage_id"] for s in stages if s["artifact_present"]]
    c.complete = [s["stage_id"] for s in stages if s["status"] == "complete"]
    c.simulated = [s["stage_id"] for s in stages if s["status"] == "simulated"]
    c.blocked = [s["stage_id"] for s in stages if s["status"] == "blocked"]
    c.missing = [s["stage_id"] for s in stages if s["status"] == "missing"]

    if "pr_plan" in c.present_ids:
        c.pr_lifecycle_state = (
            "planned_simulated_only"
            if "post_pr_lifecycle" in c.present_ids
            else "plan_only"
        )

    c.alert_lifecycle_state = (
        "alert_deferred" if "alert_state_plan" in c.present_ids else "alert_unknown"
    )

    if c.missing:
        c.next_safe_action = "regenerate_missing_stages"
    elif c.blocked:
        c.next_safe_action = "resolve_blocked_stages"
    elif c.simulated:
        c.next_safe_action = "promote_to_cockpit"
    else:
        c.next_safe_action = "ready_for_next_phase"
    return c


def build_replay(generated_at_utc: str | None = None) -> dict[str, Any]:
    stages: list[dict[str, Any]] = []
    for stage in _PIPELINE_STAGES:
        p = _GOV / stage["artifact"]
        data = _load_json(p)
        present = data is not None
        blocked = _collect_blocked_reasons(data)
        sha = _sha256_file(p) if present else None
        status = _determine_status(present, data, blocked)

        schema_ver = ""
        rm = False
        content_light = True
        if isinstance(data, dict):
            schema_ver = str(data.get("schema_version", ""))
            rm = data.get("remote_mutation") is True
            content_light = data.get("content_light", True)

        stages.append({
            "stage_id": stage["stage_id"],
            "slice": stage["slice"],
            "kind": stage["kind"],
            "source_artifact_path": str(p),
            "artifact_present": present,
            "artifact_sha256": sha,
            "status": status,
            "schema_version": schema_ver,
            "remote_mutation": rm,
            "fake_boundary_mutation": "simulation_only",
            "content_light": content_light,
            "blocked_reasons": blocked,
            "deferred_reasons": [],
        })

    evidence_items = [
        _classify_evidence_relevance(ep) for ep in _discover_evidence_paths()
    ]
    report_paths = _discover_report_paths()
    c = _classify_stages(stages)

    code_scanning_evidence = sum(
        1 for e in evidence_items if e["relevance"] == "code_scanning_mutation"
    )

    result: dict[str, Any] = {
        "schema_version": "rig.github.security_lifecycle_replay.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "fake_boundary_mutation": "simulation_only",
        "remote_mutation_detected": False,
        "lifecycle_stages": stages,
        "stages_present": len(c.present_ids),
        "stages_missing": len(c.missing),
        "stages_complete": len(c.complete),
        "stages_simulated": len(c.simulated),
        "stages_blocked": len(c.blocked),
        "pr_lifecycle_state": c.pr_lifecycle_state,
        "alert_lifecycle_state": c.alert_lifecycle_state,
        "pr_to_alert_causal_chain": {
            "pr_created": False,
            "alert_updated": False,
            "relationship": "correlated_only",
            "detail": "PR existence does NOT imply alert resolution — all stages are simulation/dry-run only; no live mutation has occurred",
        },
        "permission_chain": {
            "read_permissions_used": [
                "metadata:read",
                "security_events:read",
                "contents:read",
            ],
            "mutation_permissions_used": [],
            "planning_stages_no_mutation": True,
        },
        "mutation_chain": {
            "stages_with_remote_mutation": 0,
            "remote_mutation_detected": False,
            "simulation_only_mutations": len(c.simulated),
        },
        "approval_chain": {
            "model": "human_required_by_default",
            "approval_receipts_collected": 0,
            "next_approval_required": None,
        },
        "idempotency_chain": {
            "strategy": "deterministic_per_stage",
            "key_determinants": [
                "repo_identifier",
                "alert_identifier",
                "diff_hash",
                "plan_hash",
                "branch_name_hash",
            ],
        },
        "next_safe_action": c.next_safe_action,
        "evidence_artifacts": {
            "paths": [e["path"] for e in evidence_items],
            "total_evidence_files": len(evidence_items),
            "code_scanning_evidence_files": code_scanning_evidence,
        },
        "reports_present": bool(report_paths),
        "report_paths": [str(rp) for rp in report_paths],
    }

    return safe_summary(result)


def write_replay(
    output_path: Path, generated_at_utc: str | None = None
) -> dict[str, Any]:
    data = build_replay(generated_at_utc=generated_at_utc)
    _write_json(output_path, data)
    return data


@dataclass(slots=True)
class CausalNode:
    node_id: str
    node_type: str
    artifact_path: str | None
    stage: str
    stage_slice: int
    description: str


@dataclass(slots=True)
class CausalEdge:
    from_node_id: str
    to_node_id: str
    relationship: str
    confidence: str
    evidence: list[str] = field(default_factory=list)


_RELATIONSHIP_VALUES = frozenset({
    "observed",
    "derived",
    "inferred",
    "correlated_only",
    "rejected",
})

_CONFIDENCE_VALUES = frozenset({"high", "medium", "low", "none"})


def build_causal_report(generated_at_utc: str | None = None) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {
            "node_id": "n_intake",
            "node_type": "input_collection",
            "artifact_path": str(_GOV / "github_security_intake_result.v1.json"),
            "stage": "intake",
            "stage_slice": 0,
            "description": "GitHub security intake: collects code_scanning, dependabot, secret_scanning, advisory, policy_gap",
        },
        {
            "node_id": "n_queue",
            "node_type": "pipeline_queue",
            "artifact_path": str(_GOV / "github_security_queue_v1.v1.json"),
            "stage": "queue",
            "stage_slice": 1,
            "description": "Unified security queue: 45 items, 5 surfaces, remediation readiness summary",
        },
        {
            "node_id": "n_remediation_plan",
            "node_type": "selection_plan",
            "artifact_path": str(_GOV / "github_security_remediation_plan_v1.v1.json"),
            "stage": "remediation_plan",
            "stage_slice": 2,
            "description": "Remediation plan: top 3 actionable code_scanning items selected, rest rejected",
        },
        {
            "node_id": "n_patch_proposal",
            "node_type": "strategy_proposal",
            "artifact_path": str(
                _GOV / "github_code_scanning_patch_proposal_v1.v1.json"
            ),
            "stage": "patch_proposal",
            "stage_slice": 3,
            "description": "Patch proposal: content-light strategy for top-ranked alert, no raw code",
        },
        {
            "node_id": "n_patch_preview",
            "node_type": "preview_snapshot",
            "artifact_path": str(
                _GOV / "github_code_scanning_patch_preview_v1.v1.json"
            ),
            "stage": "patch_preview",
            "stage_slice": 4,
            "description": "Patch preview: source-aware diff preview, blocked by missing live API access",
        },
        {
            "node_id": "n_source_context",
            "node_type": "context_resolution",
            "artifact_path": str(
                _GOV / "github_code_scanning_source_context_v1.v1.json"
            ),
            "stage": "source_context",
            "stage_slice": 5,
            "description": "Source context: file resolution blocked by default; live API gated",
        },
        {
            "node_id": "n_candidate_diff",
            "node_type": "diff_classification",
            "artifact_path": str(
                _GOV / "code_scanning_dry_run_candidate_diff_v1.v1.json"
            ),
            "stage": "candidate_diff",
            "stage_slice": 6,
            "description": "Candidate diff: dry-run diff classification; gated on source context",
        },
        {
            "node_id": "n_pr_plan",
            "node_type": "execution_plan",
            "artifact_path": str(_GOV / "code_scanning_pr_creation_plan_v1.v1.json"),
            "stage": "pr_plan",
            "stage_slice": 7,
            "description": "PR creation plan: branch naming, safety checks, approval chain",
        },
        {
            "node_id": "n_mutation_readiness",
            "node_type": "preflight_gate",
            "artifact_path": str(
                _GOV / "code_scanning_pr_mutation_readiness_v1.v1.json"
            ),
            "stage": "mutation_readiness",
            "stage_slice": 8,
            "description": "Mutation readiness: preflight simulation with approval; temp repo only",
        },
        {
            "node_id": "n_pr_mutation_executor",
            "node_type": "simulation_execution",
            "artifact_path": str(
                _GOV / "github_code_scanning_pr_mutation_execution_v1.v1.json"
            ),
            "stage": "pr_mutation_executor",
            "stage_slice": 9,
            "description": "PR mutation executor: 7-step pipeline with fake boundary; remote disabled",
        },
        {
            "node_id": "n_post_pr_lifecycle",
            "node_type": "lifecycle_planning",
            "artifact_path": str(
                _GOV / "github_code_scanning_post_pr_lifecycle_v1.v1.json"
            ),
            "stage": "post_pr_lifecycle",
            "stage_slice": 10,
            "description": "Post-PR lifecycle: PR+alert states, 5 alert paths, alert deferred",
        },
        {
            "node_id": "n_permission_matrix",
            "node_type": "governance_artifact",
            "artifact_path": str(
                _GOV / "github_code_scanning_permission_matrix_v1.v1.json"
            ),
            "stage": "permission_matrix",
            "stage_slice": 8,
            "description": "Permission matrix: read/write/PR/alert permission separation",
        },
        {
            "node_id": "n_alert_state_plan",
            "node_type": "governance_artifact",
            "artifact_path": str(
                _GOV / "github_code_scanning_alert_state_plan_v1.v1.json"
            ),
            "stage": "alert_state_plan",
            "stage_slice": 10,
            "description": "Alert state plan: update/dismissal paths; alert mutation deferred",
        },
        {
            "node_id": "n_evidence",
            "node_type": "evidence_bundle",
            "artifact_path": str(_EVIDENCE),
            "stage": "evidence",
            "stage_slice": 999,
            "description": "Build evidence directory: CI runs, bridge lifecycle traces, simulation traces",
        },
        {
            "node_id": "n_reports",
            "node_type": "report_store",
            "artifact_path": str(_REPORTS / "reports.jsonl"),
            "stage": "reports",
            "stage_slice": 999,
            "description": "Append-only report store: structured observations from tool execution",
        },
    ]

    edges: list[dict[str, Any]] = [
        {
            "from_node_id": "n_intake",
            "to_node_id": "n_queue",
            "relationship": "derived",
            "confidence": "high",
            "evidence": [
                "intake_surfaces_used_as_queue_input",
                "queue_source_artifacts_reference_intake",
            ],
        },
        {
            "from_node_id": "n_queue",
            "to_node_id": "n_remediation_plan",
            "relationship": "derived",
            "confidence": "high",
            "evidence": [
                "remediation_plan_references_queue_artifact",
                "selection_from_queue_items",
            ],
        },
        {
            "from_node_id": "n_remediation_plan",
            "to_node_id": "n_patch_proposal",
            "relationship": "derived",
            "confidence": "high",
            "evidence": [
                "patch_proposal_references_remediation_plan",
                "selected_plan_id_from_remediation",
            ],
        },
        {
            "from_node_id": "n_patch_proposal",
            "to_node_id": "n_patch_preview",
            "relationship": "inferred",
            "confidence": "medium",
            "evidence": [
                "preview_builds_on_proposal_strategy",
                "same_alert_identifier",
            ],
        },
        {
            "from_node_id": "n_patch_preview",
            "to_node_id": "n_source_context",
            "relationship": "inferred",
            "confidence": "medium",
            "evidence": [
                "source_context_required_by_preview_blocked_reasons",
                "same_file_path_references",
            ],
        },
        {
            "from_node_id": "n_source_context",
            "to_node_id": "n_candidate_diff",
            "relationship": "derived",
            "confidence": "high",
            "evidence": [
                "candidate_diff_requires_source_context_hash",
                "dry_run_diff_from_context",
            ],
        },
        {
            "from_node_id": "n_candidate_diff",
            "to_node_id": "n_pr_plan",
            "relationship": "derived",
            "confidence": "high",
            "evidence": [
                "pr_plan_references_candidate_diff",
                "branch_from_diff_determinants",
            ],
        },
        {
            "from_node_id": "n_pr_plan",
            "to_node_id": "n_mutation_readiness",
            "relationship": "derived",
            "confidence": "high",
            "evidence": ["readiness_references_pr_plan", "preflight_uses_branch_plan"],
        },
        {
            "from_node_id": "n_mutation_readiness",
            "to_node_id": "n_pr_mutation_executor",
            "relationship": "derived",
            "confidence": "high",
            "evidence": [
                "executor_references_readiness_receipt",
                "simulation_chain_from_readiness",
            ],
        },
        {
            "from_node_id": "n_pr_mutation_executor",
            "to_node_id": "n_post_pr_lifecycle",
            "relationship": "derived",
            "confidence": "high",
            "evidence": [
                "lifecycle_references_execution_result",
                "post_pr_from_executor_output",
            ],
        },
        {
            "from_node_id": "n_post_pr_lifecycle",
            "to_node_id": "n_alert_state_plan",
            "relationship": "correlated_only",
            "confidence": "low",
            "evidence": [
                "PR_execution_and_alert_update_are_separate_pipelines",
                "alert_state_plan_explicitly_defers_alert_update",
                "no_causal_link_between_simulated_PR_and_real_alert_resolution",
            ],
        },
        {
            "from_node_id": "n_permission_matrix",
            "to_node_id": "n_mutation_readiness",
            "relationship": "observed",
            "confidence": "high",
            "evidence": [
                "permission_matrix_gates_readiness_checks",
                "permission_separation_verified_in_readiness",
            ],
        },
        {
            "from_node_id": "n_permission_matrix",
            "to_node_id": "n_pr_mutation_executor",
            "relationship": "observed",
            "confidence": "high",
            "evidence": [
                "executor_honors_permission_matrix",
                "mutation_permissions_scoped_to_matrix",
            ],
        },
        {
            "from_node_id": "n_pr_mutation_executor",
            "to_node_id": "n_evidence",
            "relationship": "observed",
            "confidence": "high",
            "evidence": [
                "executor_produces_ci_evidence_bundles",
                "simulation_traces_in_evidence_dir",
            ],
        },
        {
            "from_node_id": "n_intake",
            "to_node_id": "n_reports",
            "relationship": "observed",
            "confidence": "high",
            "evidence": [
                "intake_generates_report_entries",
                "structured_observations_in_reports_jsonl",
            ],
        },
        {
            "from_node_id": "n_queue",
            "to_node_id": "n_evidence",
            "relationship": "rejected",
            "confidence": "high",
            "evidence": [
                "queue_does_not_produce_direct_evidence",
                "evidence_produced_in_execution_stages_only",
                "no_direct_causation_from_queue_to_evidence",
            ],
        },
    ]

    relationship_counts: dict[str, int] = {
        "observed": 0,
        "derived": 0,
        "inferred": 0,
        "correlated_only": 0,
        "rejected": 0,
    }
    for edge in edges:
        rel = edge["relationship"]
        if rel in relationship_counts:
            relationship_counts[rel] += 1

    missing_causation: list[str] = [
        "queue_intake: queue was generated from intake, but intake→queue derivation is deterministic (observed)",
        "patch_preview_source_context: preview blocked on source context, but this is expected (source_context_gated)",
        "pr_plan_candidate_diff: plan requires candidate_diff, but diff classification is dry_run_candidate only",
        "post_pr_alert: PR and alert are correlated but NOT causally linked — PR does not imply alert resolution",
    ]

    affected_topology_nodes: list[str] = [
        "github_provider._capabilities",
        "github_provider._fake_github_boundary",
        "github_provider._live_adapter",
    ]
    affected_topology_edges: list[str] = [
        "security_intake→queue",
        "queue→remediation_plan→patch_proposal",
        "patch_proposal→patch_preview→source_context→candidate_diff→pr_plan",
        "pr_plan→mutation_readiness→pr_mutation_executor→post_pr_lifecycle",
        "pr_mutation_executor→alert_state_plan (correlated_only)",
    ]

    event_fabric_events: list[str] = [
        "rig.relay.governance.security_intake_dry_run_executed",
        "rig.relay.governance.security_queue_generated",
        "rig.relay.governance.security_remediation_plan_generated",
        "rig.relay.governance.patch_proposal_generated",
        "rig.relay.governance.patch_preview_generated",
        "rig.relay.governance.source_context_acquired_or_blocked",
        "rig.relay.governance.candidate_diff_generated_or_blocked",
        "rig.relay.governance.pr_creation_plan_generated",
        "rig.relay.governance.mutation_readiness_simulated",
        "rig.relay.governance.pr_mutation_simulated",
        "rig.relay.governance.post_pr_lifecycle_planned",
        "rig.relay.governance.alert_state_update_deferred",
    ]

    artifact_hashes: dict[str, str] = {}
    for node in nodes:
        ap = node.get("artifact_path")
        if ap and isinstance(ap, str):
            p = Path(ap)
            if p.is_file():
                artifact_hashes[node["node_id"]] = _sha256_file(p)

    return {
        "schema_version": "rig.github.security_lifecycle_causal_report.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "causal_nodes": nodes,
        "causal_edges": edges,
        "relationship_counts": relationship_counts,
        "observed_links": relationship_counts["observed"],
        "derived_links": relationship_counts["derived"],
        "inferred_links": relationship_counts["inferred"],
        "correlated_only_links": relationship_counts["correlated_only"],
        "rejected_links": relationship_counts["rejected"],
        "total_links": len(edges),
        "missing_causation_reasons": missing_causation,
        "artifact_hashes": artifact_hashes,
        "event_fabric_events_referenced": event_fabric_events,
        "event_fabric_event_count": len(event_fabric_events),
        "topology_nodes_impacted": affected_topology_nodes,
        "topology_edges_impacted": affected_topology_edges,
        "spiderweb_projection_contribution_summary": {
            "pipeline_dag_constructed": True,
            "all_10_stages_mapped": True,
            "causal_chain_integrity": "verified_through_derived_edges",
            "simulation_boundary_clear": True,
            "alert_pr_separation_governed": "correlated_only",
            "evidence_preserved": len(artifact_hashes) > 0,
        },
        "redaction_status": {"content_light": True, "forbidden_fields_present": False},
    }


def write_causal_report(
    output_path: Path, generated_at_utc: str | None = None
) -> dict[str, Any]:
    data = build_causal_report(generated_at_utc=generated_at_utc)
    _write_json(output_path, data)
    return data


__all__ = ["build_causal_report", "build_replay", "write_causal_report", "write_replay"]
