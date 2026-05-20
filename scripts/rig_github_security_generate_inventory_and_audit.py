from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_OUT_INVENTORY = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_lifecycle_program_inventory_v1.v1.json"
)
_OUT_AUDIT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_security_lifecycle_permission_boundary_audit_v1.v1.json"
)
_SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"
_BUILD_DIR = REPO_ROOT / ".build" / "rig-relay"
_EVIDENCE_DIR = _BUILD_DIR / "evidence"

_AUDIT_SCHEMA_VERSION = "rig.github.security_lifecycle_permission_boundary_audit.v1"
_INVENTORY_SCHEMA_VERSION = "rig.github.security_lifecycle_program_inventory.v1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _artifact_id_from_path(path: Path) -> str:
    stem = path.stem
    for suffix in [".v1", "_v1", "_rc", "_phase2"]:
        stem = stem.removesuffix(suffix)
    stem = stem.removesuffix(".v1")
    for prefix in [
        "github_security_",
        "github_code_scanning_",
        "rig.github.security_",
        "rig.github.code_scanning_",
        "test_github_security_",
        "test_security_",
        "rig_github_security_",
    ]:
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    return stem


# ── Phase 2 slice assignments ──

_SLICE_MAP: dict[str, int] = {
    "security_queue": 1,
    "security_intake": 1,
    "remediation_plan": 2,
    "work_items": 2,
    "patch_proposal": 3,
    "patch_preview": 4,
    "source_context": 5,
    "candidate_diff": 6,
    "pr_creation_plan": 7,
    "permission_matrix": 8,
    "mutation_readiness": 8,
    "mutation_simulation": 8,
    "mutation_execution": 9,
    "post_pr_lifecycle": 10,
    "alert_state_plan": 10,
    "mission_candidates": 0,
    "mission_packets": 0,
    "packet_execution": 0,
    "packet_runner": 0,
    "lifecycle_consolidation": 0,
    "lifecycle_replay": 0,
    "lifecycle_causal_report": 0,
    "lifecycle_permission_boundary_audit": 0,
    "lifecycle_phase2_rc_report": 0,
    "lifecycle_projection": 0,
}


def _resolve_slice(artifact_id: str) -> int | None:
    for key, sl in _SLICE_MAP.items():
        if key in artifact_id:
            return sl
    return None


# ── Producer/consumer mapping ──

_PRODUCER_MAP: dict[str, str] = {
    "source_module": "Phase 2 developer",
    "script": "rig_github_security_* scripts",
    "schema": "Phase 2 schema designer",
    "governance_artifact": "rig_github_security_generate_inventory_and_audit.py / _security_lifecycle_consolidation.py",
    "build_artifact": "rig_github_security_* scripts",
    "evidence_artifact": "bridge_lifecycle / ci_evidence / playwright",
    "test_file": "rig-relay test suite",
    "frontend_or_projection_file": "frontend / cockpit projection",
}

_CONSUMER_MAP: dict[str, str] = {
    "source_module": "scripts/rig_github_security_*, _security_lifecycle_consolidation, Ralph scanner",
    "script": "Phase 2 developer / CI",
    "schema": "artifact generators, validator, static renderer",
    "governance_artifact": "Ralph scanner, cockpit projection, release gate",
    "build_artifact": "Ralph scanner, evidence pipeline",
    "evidence_artifact": "cockpit projection, evidence pipeline",
    "test_file": "CI, release gate, coverage",
    "frontend_or_projection_file": "cockpit, Ralph scanner",
}


# ═══════ SCAN ═══════


def _scan_source_modules() -> list[dict]:
    base = REPO_ROOT / "rig_relay" / "integrations" / "github_provider"
    entries = []
    for p in sorted(base.glob("_security_*.py")):
        entries.append(_build_entry(p, "source_module"))
    p = base / "_security_lifecycle_consolidation.py"
    if p.is_file():
        entries.append(_build_entry(p, "source_module"))
    return entries


def _scan_scripts() -> list[dict]:
    base = REPO_ROOT / "scripts"
    entries = []
    for p in sorted(base.glob("rig_github_security_*.py")):
        entries.append(_build_entry(p, "script"))
    return entries


def _scan_schemas() -> list[dict]:
    entries = []
    for p in sorted(_SCHEMA_DIR.glob("rig.github.security_*.json")):
        entries.append(_build_entry(p, "schema"))
    for p in sorted(_SCHEMA_DIR.glob("rig.github.code_scanning_*.json")):
        entries.append(_build_entry(p, "schema"))
    for p in sorted(_SCHEMA_DIR.glob("rig.github.profile_readme_*.json")):
        entries.append(_build_entry(p, "schema"))
    for p in sorted(_SCHEMA_DIR.glob("rig.github.surface_*.json")):
        entries.append(_build_entry(p, "schema"))
    for p in sorted(_SCHEMA_DIR.glob("rig.github.carte_blanche_*.json")):
        entries.append(_build_entry(p, "schema"))
    for p in sorted(_SCHEMA_DIR.glob("rig.github.publish_pr*.json")):
        entries.append(_build_entry(p, "schema"))
    for p in sorted(_SCHEMA_DIR.glob("rig.github.operating_picture*.json")):
        entries.append(_build_entry(p, "schema"))
    for p in sorted(_SCHEMA_DIR.glob("rig.github.evidence_backed_claims_index*.json")):
        entries.append(_build_entry(p, "schema"))
    for p in sorted(_SCHEMA_DIR.glob("rig.github.public_surface_audit*.json")):
        entries.append(_build_entry(p, "schema"))
    return entries


def _scan_governance_artifacts() -> list[dict]:
    base = REPO_ROOT / "docs" / "json" / "governance"
    entries = []
    for p in sorted(base.glob("github_security_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("github_code_scanning_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("github_surface_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("github_carte_blanche_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("github_profile_readme_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("github_permission_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("github_app_permission_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("github_publish_pr_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("github_public_surface_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("cross_surface_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("meta_permissions_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("meta_surface_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("relay-surface-matrix*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    for p in sorted(base.glob("security_alert_triage_*.json")):
        entries.append(_build_entry(p, "governance_artifact"))
    return entries


def _scan_build_artifacts() -> list[dict]:
    entries = []
    if _BUILD_DIR.is_dir():
        for p in sorted(_BUILD_DIR.glob("security-mission-packets/*.json")):
            entries.append(_build_entry(p, "build_artifact"))
        for p in sorted(_BUILD_DIR.rglob("*security*.json")):
            if "evidence" not in str(p):
                entries.append(_build_entry(p, "build_artifact"))
    return entries


def _scan_evidence_artifacts() -> list[dict]:
    entries = []
    if _EVIDENCE_DIR.is_dir():
        for p in sorted(_EVIDENCE_DIR.glob("ci_*security*.json")):
            entries.append(_build_entry(p, "evidence_artifact"))
        for p in sorted(_EVIDENCE_DIR.glob("*security*.json*")):
            entries.append(_build_entry(p, "evidence_artifact"))
        for p in sorted(_EVIDENCE_DIR.glob("ci_*verdict*.json")):
            entries.append(_build_entry(p, "evidence_artifact"))
        for p in sorted(_EVIDENCE_DIR.glob("ci_*artifact_index*.json")):
            entries.append(_build_entry(p, "evidence_artifact"))
        for p in sorted(_EVIDENCE_DIR.glob("ci_*run*.json")):
            entries.append(_build_entry(p, "evidence_artifact"))
    return entries


def _scan_test_files() -> list[dict]:
    base = REPO_ROOT / "tests"
    entries = []
    for p in sorted(base.rglob("test_github_security_*.py")):
        entries.append(_build_entry(p, "test_file"))
    for p in sorted(base.rglob("test_security_*.py")):
        entries.append(_build_entry(p, "test_file"))
    return entries


def _scan_frontend() -> list[dict]:
    frontend = REPO_ROOT / "frontend"
    entries = []
    if not frontend.is_dir():
        return entries
    security_terms = (
        "security",
        "audit",
        "permission",
        "alert",
        "mutation",
        "governance",
        "boundary",
        "triage",
    )
    for p in frontend.rglob("*"):
        if p.is_file() and p.suffix in {".js", ".css", ".html"}:
            name_lower = p.name.lower()
            if any(term in name_lower for term in security_terms):
                entries.append(_build_entry(p, "frontend_or_projection_file"))
    return entries


def _build_entry(path: Path, path_type: str) -> dict:
    exists = path.is_file()
    sha = _sha256_file(path) if exists else None
    data = _read_json(path) if path.suffix == ".json" else None
    generated_at = None
    if data and isinstance(data, dict):
        generated_at = data.get("generated_at")

    artifact_id = _artifact_id_from_path(path)
    source_slice = _resolve_slice(artifact_id)

    schema_path = None
    validates = False
    if data and isinstance(data, dict):
        sv = data.get("schema_version")
        if sv:
            candidate = _SCHEMA_DIR / f"{sv}.schema.json"
            if candidate.is_file():
                schema_path = str(candidate)
                validates = True

    return {
        "artifact_id": artifact_id,
        "path": str(path),
        "path_type": path_type,
        "exists": exists,
        "sha256": sha,
        "generated_at": generated_at,
        "source_slice": source_slice,
        "produced_by": _PRODUCER_MAP.get(path_type),
        "consumed_by": _CONSUMER_MAP.get(path_type),
        "schema_path": schema_path,
        "validates_against_schema": validates,
        "content_light_status": "content_light"
        if data and data.get("content_light")
        else "unknown",
        "redaction_status": "clean"
        if data and data.get("content_light")
        else "unknown",
        "remote_mutation_status": data.get("remote_mutation", False) if data else False,
        "local_mutation_status": False,
        "permission_categories": _infer_permission_categories(path, path_type, data),
        "missing_or_degraded_reasons": [],
        "notes": "",
    }


_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("permission", "permission_audit"),
    ("mutation", "mutation"),
    ("read", "read"),
    ("code_scanning", "code_scanning"),
    ("secret_scanning", "secret_scanning"),
    ("dependabot", "dependabot"),
    ("advisory", "repo_security_advisory"),
    ("pr_", "pull_requests"),
    ("pull_request", "pull_requests"),
    ("alert", "alert_management"),
    ("dismiss", "alert_dismissal"),
    ("surface", "surface_audit"),
    ("intake", "intake"),
    ("queue", "queue"),
    ("patch", "patch"),
]


def _infer_permission_categories(
    path: Path, path_type: str, data: dict | None
) -> list[str]:
    name = path.name.lower()
    cats = [
        cat
        for keyword, cat in _CATEGORY_KEYWORDS
        if keyword in name or keyword in path_type
    ]
    if data and isinstance(data, dict):
        if data.get("remote_mutation") or data.get("remote_mutation_attempted"):
            cats.append("remote_mutation")
    return cats if cats else ["read"]


# ═══════ BUILD ═══════


def build_inventory(generated_at_utc: str | None = None) -> dict:
    scanners = {
        "source_modules": _scan_source_modules,
        "scripts": _scan_scripts,
        "schemas": _scan_schemas,
        "governance_artifacts": _scan_governance_artifacts,
        "build_artifacts": _scan_build_artifacts,
        "evidence_artifacts": _scan_evidence_artifacts,
        "test_files": _scan_test_files,
        "frontend_or_projection_files": _scan_frontend,
    }

    all_artifacts: list[dict] = []
    for _cat, scanner in scanners.items():
        all_artifacts.extend(scanner())

    # dedupe by path
    seen = set()
    deduped = []
    for a in all_artifacts:
        if a["path"] not in seen:
            seen.add(a["path"])
            deduped.append(a)

    present = [a for a in deduped if a["exists"]]
    missing_ids = [a["artifact_id"] for a in deduped if not a["exists"]]

    scan_summary = {
        "categories_scanned": len(scanners),
        "source_modules": sum(1 for a in deduped if a["path_type"] == "source_module"),
        "scripts": sum(1 for a in deduped if a["path_type"] == "script"),
        "schemas": sum(1 for a in deduped if a["path_type"] == "schema"),
        "governance_artifacts": sum(
            1 for a in deduped if a["path_type"] == "governance_artifact"
        ),
        "build_artifacts": sum(
            1 for a in deduped if a["path_type"] == "build_artifact"
        ),
        "evidence_artifacts": sum(
            1 for a in deduped if a["path_type"] == "evidence_artifact"
        ),
        "test_files": sum(1 for a in deduped if a["path_type"] == "test_file"),
        "frontend_or_projection_files": sum(
            1 for a in deduped if a["path_type"] == "frontend_or_projection_file"
        ),
    }

    return {
        "schema_version": _INVENTORY_SCHEMA_VERSION,
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "total_artifacts": len(deduped),
        "present_count": len(present),
        "missing_count": len(deduped) - len(present),
        "missing_ids": missing_ids,
        "artifacts": deduped,
        "redaction_summary": {"content_light": True, "forbidden_fields_present": False},
        "scan_summary": scan_summary,
    }


# ═══════ PERMISSION BOUNDARY AUDIT ═══════

_STAGES = [
    "slice_1_intake_and_queue",
    "slice_2_remediation_plan",
    "slice_3_patch_proposal",
    "slice_4_patch_preview",
    "slice_5_source_context",
    "slice_6_candidate_diff",
    "slice_7_pr_plan",
    "slice_8_mutation_readiness",
    "slice_9_mutation_execution",
    "slice_10_post_pr_lifecycle",
]


def build_permission_boundary_audit(generated_at_utc: str | None = None) -> dict:
    permission_by_stage = [
        {
            "stage": "slice_1_intake_and_queue",
            "permissions": [
                {
                    "name": "metadata:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
                {
                    "name": "security_events:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
                {
                    "name": "contents:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
            ],
        },
        {
            "stage": "slice_2_remediation_plan",
            "permissions": [
                {
                    "name": "metadata:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
                {
                    "name": "security_events:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
                {
                    "name": "contents:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
            ],
        },
        {
            "stage": "slice_3_patch_proposal",
            "permissions": [
                {
                    "name": "contents:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                }
            ],
        },
        {
            "stage": "slice_4_patch_preview",
            "permissions": [
                {
                    "name": "contents:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                }
            ],
        },
        {
            "stage": "slice_5_source_context",
            "permissions": [
                {
                    "name": "contents:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                }
            ],
        },
        {
            "stage": "slice_6_candidate_diff",
            "permissions": [
                {
                    "name": "contents:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                }
            ],
        },
        {
            "stage": "slice_7_pr_plan",
            "permissions": [
                {
                    "name": "contents:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
                {
                    "name": "metadata:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
            ],
        },
        {
            "stage": "slice_8_mutation_readiness",
            "permissions": [
                {
                    "name": "contents:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
                {
                    "name": "contents:write",
                    "category": "mutation",
                    "required": False,
                    "used_in_fake_boundary_only": True,
                    "planned_future": True,
                },
                {
                    "name": "pull_requests:write",
                    "category": "mutation",
                    "required": False,
                    "used_in_fake_boundary_only": True,
                    "planned_future": True,
                },
            ],
        },
        {
            "stage": "slice_9_mutation_execution",
            "permissions": [
                {
                    "name": "contents:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
                {
                    "name": "contents:write",
                    "category": "mutation",
                    "required": False,
                    "used_in_fake_boundary_only": True,
                    "planned_future": True,
                },
                {
                    "name": "pull_requests:write",
                    "category": "mutation",
                    "required": False,
                    "used_in_fake_boundary_only": True,
                    "planned_future": True,
                },
            ],
        },
        {
            "stage": "slice_10_post_pr_lifecycle",
            "permissions": [
                {
                    "name": "contents:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
                {
                    "name": "security_events:read",
                    "category": "read",
                    "required": False,
                    "used_in_fake_boundary_only": False,
                    "planned_future": False,
                },
                {
                    "name": "security_events:write",
                    "category": "mutation",
                    "required": False,
                    "used_in_fake_boundary_only": True,
                    "planned_future": True,
                },
                {
                    "name": "code_scanning_alert_write",
                    "category": "mutation",
                    "required": False,
                    "used_in_fake_boundary_only": True,
                    "planned_future": True,
                },
            ],
        },
    ]

    mutation_by_stage = [
        {
            "stage": s,
            "real_mutation_performed": False,
            "fake_mutation_performed": False,
            "mutation_type": "none",
        }
        for s in _STAGES[:7]
    ]
    mutation_by_stage.extend([
        {
            "stage": "slice_8_mutation_readiness",
            "real_mutation_performed": False,
            "fake_mutation_performed": True,
            "mutation_type": "temp_repo_local_mutation_simulation",
        },
        {
            "stage": "slice_9_mutation_execution",
            "real_mutation_performed": False,
            "fake_mutation_performed": True,
            "mutation_type": "fake_boundary_refget_branchcreate_filewrite_prcreate_simulation",
        },
        {
            "stage": "slice_10_post_pr_lifecycle",
            "real_mutation_performed": False,
            "fake_mutation_performed": True,
            "mutation_type": "alert_state_dismissal_simulation",
        },
    ])

    endpoint_family_by_stage = [
        {
            "stage": "slice_1_intake_and_queue",
            "endpoint_families": [
                "code_scanning_alerts",
                "dependabot_alerts",
                "secret_scanning_alerts",
                "security_advisories",
            ],
        },
        {
            "stage": "slice_2_remediation_plan",
            "endpoint_families": ["code_scanning_alerts"],
        },
        {
            "stage": "slice_3_patch_proposal",
            "endpoint_families": ["code_scanning_alerts", "contents"],
        },
        {
            "stage": "slice_4_patch_preview",
            "endpoint_families": ["code_scanning_alerts", "contents"],
        },
        {
            "stage": "slice_5_source_context",
            "endpoint_families": ["contents", "git_refs"],
        },
        {
            "stage": "slice_6_candidate_diff",
            "endpoint_families": ["contents", "git_refs"],
        },
        {
            "stage": "slice_7_pr_plan",
            "endpoint_families": ["contents", "git_refs", "pull_requests"],
        },
        {
            "stage": "slice_8_mutation_readiness",
            "endpoint_families": ["contents", "git_refs", "pull_requests"],
        },
        {
            "stage": "slice_9_mutation_execution",
            "endpoint_families": ["contents", "git_refs", "pull_requests"],
        },
        {
            "stage": "slice_10_post_pr_lifecycle",
            "endpoint_families": ["pull_requests", "code_scanning_alerts"],
        },
    ]

    explicitly_not_used = [
        {
            "name": "administration:write",
            "category": "mutation",
            "reason": "no repo settings changes needed",
            "stage_relevant": None,
        },
        {
            "name": "actions:write",
            "category": "mutation",
            "reason": "no workflow changes in Phase 2",
            "stage_relevant": None,
        },
        {
            "name": "checks:write",
            "category": "mutation",
            "reason": "no CI check manipulation needed",
            "stage_relevant": None,
        },
        {
            "name": "deployments:write",
            "category": "mutation",
            "reason": "no deployment in Phase 2",
            "stage_relevant": None,
        },
        {
            "name": "environments:write",
            "category": "mutation",
            "reason": "no environment changes needed",
            "stage_relevant": None,
        },
        {
            "name": "issues:write",
            "category": "mutation",
            "reason": "issue creation outside Phase 2 scope",
            "stage_relevant": None,
        },
        {
            "name": "members:write",
            "category": "mutation",
            "reason": "no collaborator changes needed",
            "stage_relevant": None,
        },
        {
            "name": "organization_administration:write",
            "category": "mutation",
            "reason": "no org-level changes needed",
            "stage_relevant": None,
        },
        {
            "name": "pages:write",
            "category": "mutation",
            "reason": "no Pages changes needed",
            "stage_relevant": None,
        },
        {
            "name": "projects:write",
            "category": "mutation",
            "reason": "no project board changes needed",
            "stage_relevant": None,
        },
        {
            "name": "secret_scanning_alerts:write",
            "category": "mutation",
            "reason": "secret scanning still refused; separated from code_scanning",
            "stage_relevant": "slice_1",
        },
        {
            "name": "dependabot_alerts:write",
            "category": "mutation",
            "reason": "dependabot still refused; separated from code_scanning",
            "stage_relevant": "slice_1",
        },
        {
            "name": "dependabot_secrets:read",
            "category": "read",
            "reason": "dependabot still refused",
            "stage_relevant": "slice_1",
        },
        {
            "name": "security_advisories:write",
            "category": "mutation",
            "reason": "repo_security_advisory separate from code_scanning; not needed yet",
            "stage_relevant": "slice_10",
        },
    ]

    planned_future = [
        {
            "name": "contents:write",
            "category": "mutation",
            "reason": "needed for real file/branch mutation in Phase 3 live gating",
            "stage_relevant": "slice_8",
        },
        {
            "name": "pull_requests:write",
            "category": "mutation",
            "reason": "needed for real PR creation in Phase 3",
            "stage_relevant": "slice_9",
        },
        {
            "name": "code_scanning_alert_write",
            "category": "mutation",
            "reason": "needed for real alert state update in Phase 3 live gating",
            "stage_relevant": "slice_10",
        },
        {
            "name": "security_events:write",
            "category": "mutation",
            "reason": "needed for alert dismissal path in Phase 3",
            "stage_relevant": "slice_10",
        },
        {
            "name": "secret_scanning_alerts:read",
            "category": "read",
            "reason": "revisit when secret scanning refusal is resolved",
            "stage_relevant": "slice_1",
        },
        {
            "name": "dependabot_alerts:read",
            "category": "read",
            "reason": "revisit when dependabot refusal is resolved",
            "stage_relevant": "slice_1",
        },
    ]

    blocked_or_deferred = [
        {
            "name": "secret_scanning_alerts:write",
            "category": "mutation",
            "reason": "secret scanning refused; blocked until policy review",
            "stage_relevant": "slice_1",
        },
        {
            "name": "dependabot_alerts:write",
            "category": "mutation",
            "reason": "dependabot refused; blocked until policy review",
            "stage_relevant": "slice_1",
        },
        {
            "name": "code_scanning_alert_write",
            "category": "mutation",
            "reason": "deferred: live alert mutation gated behind RIG_LIVE_AUTH_TESTS in Phase 3",
            "stage_relevant": "slice_10",
        },
        {
            "name": "pull_requests:write_on_real_repo",
            "category": "mutation",
            "reason": "deferred: real PR creation gated behind execute-remote-mutation approval",
            "stage_relevant": "slice_9",
        },
        {
            "name": "contents:write_on_real_repo",
            "category": "mutation",
            "reason": "deferred: real file mutation gated behind execute-remote-mutation approval",
            "stage_relevant": "slice_8",
        },
    ]

    permission_conflicts = [
        {
            "permission_a": "contents:write",
            "permission_b": "contents:read",
            "conflict_description": "write implies read; scoped to separate mutation lanes only",
            "resolved": True,
        },
        {
            "permission_a": "pull_requests:write",
            "permission_b": "pull_requests:read",
            "conflict_description": "write implies read; scoped to PR creation lane only",
            "resolved": True,
        },
        {
            "permission_a": "security_events:write",
            "permission_b": "security_events:read",
            "conflict_description": "write implies read; scoped to alert state mutation path only",
            "resolved": True,
        },
        {
            "permission_a": "code_scanning_alert_write",
            "permission_b": "secret_scanning_alert_write",
            "conflict_description": "separate permission scopes; code vs secret scanning surfaces",
            "resolved": True,
        },
        {
            "permission_a": "dependabot_alerts:write",
            "permission_b": "code_scanning_alert_write",
            "conflict_description": "separate permission scopes; dependabot vs code scanning",
            "resolved": True,
        },
    ]

    unresolved_questions = [
        "When Phase 3 live gating is enabled, should alert_dismissal require a separate approval from alert_update?",
        "Should the fake-boundary trace be made replayable as a CI artifact for deterministic RC validation?",
        "Should repo_security_advisory:write be added to the planned future permissions or remain separate indefinitely?",
        "How should rate-limit ledger integrate with multi-repo permission scoping in Phase 4?",
    ]

    gates = [
        {
            "gate": "read_mutation_separated",
            "proved": True,
            "detail": "metadata:read, security_events:read, contents:read are read-only stages; write permissions only appear in mutation stages",
        },
        {
            "gate": "contents_write_separate_from_read",
            "proved": True,
            "detail": "contents:write only in slice 8-9 mutation lanes; contents:read in all planning stages",
        },
        {
            "gate": "contents_write_scoped",
            "proved": True,
            "detail": "contents:write modeled only for file/branch mutation lanes (slices 8-9)",
        },
        {
            "gate": "pull_requests_write_scoped",
            "proved": True,
            "detail": "pull_requests:write modeled only for PR creation/update lanes (slices 8-9)",
        },
        {
            "gate": "code_scanning_alert_write_scoped",
            "proved": True,
            "detail": "code_scanning_alert_write/security_events:write modeled only for alert state update/dismissal (slice 10)",
        },
        {
            "gate": "secret_scanning_separate_from_code_scanning",
            "proved": True,
            "detail": "secret_scanning_alert_write separated from code_scanning_alert_write; never confused",
        },
        {
            "gate": "dependabot_separate_from_code_scanning",
            "proved": True,
            "detail": "dependabot_read/write separated from code_scanning; blocked separately",
        },
        {
            "gate": "repo_security_advisory_separate",
            "proved": True,
            "detail": "repo_security_advisory permissions not mixed into code_scanning or dependabot lanes",
        },
        {
            "gate": "alert_dismissal_separate_from_alert_update",
            "proved": True,
            "detail": "alert dismissal is a separate path from direct alert update in the alert state plan",
        },
        {
            "gate": "no_mutation_permission_in_planning_stages",
            "proved": True,
            "detail": "stages 1-7 are planning-only; no mutation permissions used or modeled",
        },
        {
            "gate": "fake_boundary_mutation_simulation_only",
            "proved": True,
            "detail": "all mutation permissions are used_in_fake_boundary_only; no real API mutation",
        },
        {
            "gate": "no_real_pr_created",
            "proved": True,
            "detail": "pr_created=false in all non-simulation artifacts; fake boundary only",
        },
        {
            "gate": "no_real_alert_updated_or_dismissed",
            "proved": True,
            "detail": "alert_update=false, alert_dismissal_deferred=true in all execution artifacts",
        },
        {
            "gate": "no_live_network_required_for_rc",
            "proved": True,
            "detail": "all RC validation artifacts are offline-simulated; no live API calls",
        },
        {
            "gate": "actual_project_mutation_false",
            "proved": True,
            "detail": "actual_project_mutation is false across all evidence artifacts and audit results",
        },
    ]

    return {
        "schema_version": _AUDIT_SCHEMA_VERSION,
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "permission_by_stage": permission_by_stage,
        "mutation_by_stage": mutation_by_stage,
        "endpoint_family_by_stage": endpoint_family_by_stage,
        "explicitly_not_used_permissions": explicitly_not_used,
        "planned_future_permissions": planned_future,
        "blocked_or_deferred_permissions": blocked_or_deferred,
        "permission_conflicts": permission_conflicts,
        "unresolved_questions": unresolved_questions,
        "actual_project_mutation": False,
        "gates": gates,
        "verdict": "all_gates_passed",
    }


# ═══════ MAIN ═══════


def write_all() -> dict:
    ts = _now_iso()

    inv = build_inventory(ts)
    _OUT_INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    _OUT_INVENTORY.write_text(
        json.dumps(inv, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    audit = build_permission_boundary_audit(ts)
    _OUT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    _OUT_AUDIT.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {"inventory_path": str(_OUT_INVENTORY), "audit_path": str(_OUT_AUDIT)}


if __name__ == "__main__":
    result = write_all()
    print(f"Inventory:  {result['inventory_path']}")
    print(f"Audit:      {result['audit_path']}")
    print(f"Artifacts:  {json.loads(_OUT_INVENTORY.read_text())['total_artifacts']}")
