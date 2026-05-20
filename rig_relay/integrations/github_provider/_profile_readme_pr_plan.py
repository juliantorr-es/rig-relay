"""Profile README PR plan v1 — governed, dry-run-first, multi-gate.

Models PR creation as separable steps: branch/ref → file content → PR create → receipt.
Default: dry-run only. Remote mutation requires explicit publish flag and all gates pass.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PREVIEW_PATH = (
    _REPO_ROOT / ".build" / "rig-relay" / "previews" / "profile_readme_preview.md"
)
_DEFAULT_PREVIEW_ARTIFACT = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_profile_readme_preview_v1.v1.json"
)
_DEFAULT_OUTPUT_DIR = _REPO_ROOT / "docs" / "json" / "governance"

_LIVE_AUTH_ENV = "RIG_LIVE_AUTH_TESTS"
_WORKFLOW_PATH_PREFIX = ".github/workflows/"

_REQUIRED_READ_PERMISSIONS = ["contents:read", "metadata:read"]
_REQUIRED_WRITE_CONTENT_PERMISSIONS = ["contents:write"]
_REQUIRED_WRITE_PR_PERMISSIONS = ["pull_requests:write"]
_EXPLICITLY_NOT_REQUIRED = ["workflows:write", "actions:write"]

_FORBIDDEN_PLAN_FIELDS = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "patch",
    "diff",
    "bearer",
    "token",
    "auth_header",
})


class ProfileReadmePrPlanError(Exception):
    """Raised when PR plan building fails."""


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _build_gates(
    *,
    allow_publish: bool,
    preview_path: Path,
    expected_preview_sha256: str | None,
    target_path: str,
    base_branch: str,
    proposed_branch: str,
    live_permission_verified: bool,
    redaction_scan: dict[str, Any] | None,
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    """Evaluate all publish gates. Returns (all_pass, blocked_reasons, gate_details)."""
    blocked: list[str] = []
    details: list[dict[str, Any]] = []

    # Gate 1: explicit publish flag
    gate_flag: dict[str, Any] = {
        "gate": "explicit_publish_flag",
        "passed": allow_publish,
        "detail": "Publish flag must be explicitly supplied",
    }
    details.append(gate_flag)
    if not allow_publish:
        blocked.append("explicit_publish_flag_not_set")

    # Gate 2: preview file exists
    preview_exists = preview_path.exists()
    gate_preview_exist: dict[str, Any] = {
        "gate": "preview_file_exists",
        "passed": preview_exists,
        "detail": str(preview_path),
    }
    details.append(gate_preview_exist)
    if not preview_exists:
        blocked.append("preview_file_missing")

    # Gate 3: preview hash matches
    preview_hash_match = True
    if expected_preview_sha256 and preview_exists:
        actual_sha = _sha256_file(preview_path)
        preview_hash_match = actual_sha == expected_preview_sha256
        gate_hash: dict[str, Any] = {
            "gate": "preview_hash_match",
            "passed": preview_hash_match,
            "detail": f"expected={expected_preview_sha256[:16]}... actual={actual_sha[:16]}...",
        }
        details.append(gate_hash)
        if not preview_hash_match:
            blocked.append("preview_hash_mismatch")
    elif expected_preview_sha256 and not preview_exists:
        gate_hash = {
            "gate": "preview_hash_match",
            "passed": False,
            "detail": "preview file missing, cannot verify hash",
        }
        details.append(gate_hash)
        blocked.append("preview_hash_unverifiable")

    # Gate 4: redaction scan passes
    if redaction_scan is not None:
        redaction_clean = redaction_scan.get("content_clean", False)
        gate_redact: dict[str, Any] = {
            "gate": "redaction_scan",
            "passed": redaction_clean,
            "detail": f"redaction_matches={len(redaction_scan.get('redaction_matches', []))}",
        }
        details.append(gate_redact)
        if not redaction_clean:
            blocked.append("redaction_scan_failed")

    # Gate 5: target path is README.md, not workflow path
    target_is_readme = target_path == "README.md"
    target_not_workflow = not target_path.startswith(_WORKFLOW_PATH_PREFIX)
    gate_target: dict[str, Any] = {
        "gate": "target_path_safe",
        "passed": target_is_readme and target_not_workflow,
        "detail": f"target_path={target_path}",
    }
    details.append(gate_target)
    if not target_is_readme:
        blocked.append("target_path_not_readme")
    if not target_not_workflow:
        blocked.append("target_path_is_workflow_blocked")

    # Gate 6: proposed branch is non-default
    branch_differs = proposed_branch != base_branch
    gate_branch: dict[str, Any] = {
        "gate": "non_default_branch",
        "passed": branch_differs,
        "detail": f"base={base_branch} proposed={proposed_branch}",
    }
    details.append(gate_branch)
    if not branch_differs:
        blocked.append("proposed_branch_equals_base_branch")

    # Gate 7: live permission verified
    gate_perm: dict[str, Any] = {
        "gate": "live_permission_verified",
        "passed": live_permission_verified,
        "detail": "Live API permission truth must be observed or explicitly waived",
    }
    details.append(gate_perm)
    if not live_permission_verified:
        blocked.append("live_permission_not_verified")

    # Gate 8: workflow:write and actions:write not needed (verified)
    gate_wf: dict[str, Any] = {
        "gate": "workflows_not_required",
        "passed": True,
        "detail": "workflows:write confirmed not needed for README.md path",
    }
    details.append(gate_wf)
    gate_act: dict[str, Any] = {
        "gate": "actions_not_required",
        "passed": True,
        "detail": "actions:write confirmed not needed for README.md path",
    }
    details.append(gate_act)

    all_pass = len(blocked) == 0 and allow_publish
    return all_pass, blocked, details


def build_pr_plan(
    owner: str,
    *,
    allow_publish: bool = False,
    generated_at_utc: str | None = None,
    preview_path: Path = _DEFAULT_PREVIEW_PATH,
    preview_artifact_path: Path = _DEFAULT_PREVIEW_ARTIFACT,
    base_branch: str = "main",
    proposed_branch: str | None = None,
    target_path: str = "README.md",
) -> dict[str, Any]:
    """Build a governed profile README PR publish plan. Dry-run by default."""
    if proposed_branch is None:
        proposed_branch = "relay/profile-readme-update"

    preview_artifact = _load_json(preview_artifact_path)
    expected_sha = None
    preview_bytes = None
    preview_lines = None
    redaction_scan = None
    live_perm_verified = False

    if preview_artifact is not None:
        expected_sha = preview_artifact.get("generated_preview_sha256")
        preview_bytes = preview_artifact.get("generated_preview_bytes")
        preview_lines = preview_artifact.get("generated_preview_line_count")
        redaction_scan = preview_artifact.get("redaction_scan")
        live_verif = preview_artifact.get("live_permission_verification")
        if isinstance(live_verif, dict) and live_verif.get("live_verification_run"):
            live_perm_verified = True

    preview_exists = preview_path.exists()
    preview_sha = _sha256_file(preview_path) if preview_exists else None

    all_pass, blocked_reasons, gate_details = _build_gates(
        allow_publish=allow_publish,
        preview_path=preview_path,
        expected_preview_sha256=expected_sha,
        target_path=target_path,
        base_branch=base_branch,
        proposed_branch=proposed_branch,
        live_permission_verified=live_perm_verified,
        redaction_scan=redaction_scan,
    )

    # Determine publish gate status
    if not allow_publish:
        gate_status = "dry_run_blocked"
    elif not all_pass:
        gate_status = "publish_blocked"
    else:
        gate_status = "publish_ready"

    # Planned steps: always recorded, even in dry-run
    planned_steps = [
        {
            "step": 1,
            "operation": "read_repo_metadata",
            "permission": "metadata:read",
            "description": "Verify profile repo exists and fetch base branch",
        },
        {
            "step": 2,
            "operation": "prepare_branch",
            "permission": "contents:write",
            "description": f"Create branch {proposed_branch} from {base_branch}",
        },
        {
            "step": 3,
            "operation": "write_file",
            "permission": "contents:write",
            "description": f"Write README.md from preview {preview_sha[:16] if preview_sha else 'N/A'}...",
        },
        {
            "step": 4,
            "operation": "create_pull_request",
            "permission": "pull_requests:write",
            "description": f"Create PR from {proposed_branch} to {base_branch}",
        },
        {
            "step": 5,
            "operation": "emit_operation_receipt",
            "permission": "none",
            "description": "Record mutation receipt with before/after SHAs",
        },
    ]

    plan: dict[str, Any] = {
        "schema_version": "rig.github.profile_readme_pr_plan.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "owner": owner,
        "repo": f"{owner}/{owner}",
        "base_branch": base_branch,
        "proposed_branch": proposed_branch,
        "target_path": target_path,
        "preview_path": str(preview_path),
        "preview_sha256": preview_sha,
        "preview_bytes": preview_bytes,
        "preview_line_count": preview_lines,
        "operation_mode": "dry_run" if not allow_publish else "publish_requested",
        "requested_remote_mutation": allow_publish,
        "remote_mutation": False,
        "content_light": True,
        "mutation_lane_id": "profile_readme_publish_pr",
        "required_permissions": {
            "read": _REQUIRED_READ_PERMISSIONS,
            "write_content": _REQUIRED_WRITE_CONTENT_PERMISSIONS,
            "write_pr": _REQUIRED_WRITE_PR_PERMISSIONS,
            "explicitly_not_required": _EXPLICITLY_NOT_REQUIRED,
        },
        "live_permission_verification_summary": {
            "verified": live_perm_verified,
            "source": "embedded_from_preview_artifact",
        },
        "publish_gate_status": gate_status,
        "blocked_reasons": blocked_reasons,
        "gate_details": gate_details,
        "planned_steps": planned_steps,
        "idempotency_key": _sha256_text(
            f"{owner}:{target_path}:{preview_sha or 'N/A'}"
        ),
        "expected_artifacts": ["profile_readme_pr_operation_receipt"],
        "redaction_status": {"content_light": True, "forbidden_fields_present": False},
    }

    _assert_plan_content_light(plan)
    return plan


def _assert_plan_content_light(plan: dict[str, Any]) -> None:
    serialized = json.dumps(plan, sort_keys=True)
    for key in _FORBIDDEN_PLAN_FIELDS:
        if f'"{key}"' in serialized:
            raise ValueError(f"forbidden_key_in_pr_plan: {key}")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_pr_plan_artifacts(
    owner: str,
    *,
    allow_publish: bool = False,
    generated_at_utc: str | None = None,
    output_dir: Path = _DEFAULT_OUTPUT_DIR,
    preview_path: Path = _DEFAULT_PREVIEW_PATH,
    preview_artifact_path: Path = _DEFAULT_PREVIEW_ARTIFACT,
) -> dict[str, Any]:
    plan = build_pr_plan(
        owner,
        allow_publish=allow_publish,
        generated_at_utc=generated_at_utc,
        preview_path=preview_path,
        preview_artifact_path=preview_artifact_path,
    )
    _write_json(output_dir / "github_profile_readme_pr_plan_v1.v1.json", plan)
    return plan


__all__ = ["ProfileReadmePrPlanError", "build_pr_plan", "write_pr_plan_artifacts"]
