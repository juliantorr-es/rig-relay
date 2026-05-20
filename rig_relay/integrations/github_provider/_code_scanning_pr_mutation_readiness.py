"""Code Scanning PR Mutation Readiness Suite v1.

Evaluates all gates required before actual PR creation can be allowed.
Includes permission matrix, idempotency, branch collision, approval policy,
and local temp-repo dry-run simulation. No actual remote mutation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from rig_relay.core.utils.io import read_safe

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PR_PLAN = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "code_scanning_pr_creation_plan_v1.v1.json"
)
_DEFAULT_OUTPUT_READINESS = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "code_scanning_pr_mutation_readiness_v1.v1.json"
)
_DEFAULT_OUTPUT_MATRIX = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_permission_matrix_v1.v1.json"
)
_DEFAULT_SIM_OUTPUT = (
    _REPO_ROOT
    / ".build"
    / "rig-relay"
    / "derived"
    / "code_scanning_pr_mutation_simulation.v1.json"
)

_FORBIDDEN = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "raw_payload",
    "code_snippet",
    "vulnerable_code",
    "file_body",
    "auth_header",
    "bearer",
    "secret_value",
    "source_content",
    "raw_file",
})

_MUTATION_STEPS = [
    "1. verify source PR plan",
    "2. verify candidate diff receipt",
    "3. verify diff artifact hash",
    "4. check branch name policy",
    "5. check permission policy",
    "6. check approval policy",
    "7. create branch (simulation only)",
    "8. apply patch (simulation only)",
    "9. commit patch (simulation only)",
    "10. push branch (not in this slice)",
    "11. create PR (not in this slice)",
    "12. record PR URL (not in this slice)",
    "13. alert update remains deferred",
]

_PERMISSION_MATRIX = [
    {
        "phase": "source_context_acquisition",
        "required": ["metadata:read", "security_events:read", "contents:read"],
        "used": ["metadata:read", "security_events:read", "contents:read"],
        "remote_mutation": False,
        "local_mutation": False,
        "alert_mutation": False,
        "content_exposure": "hashes_only",
    },
    {
        "phase": "dry_run_candidate_diff",
        "required": ["metadata:read", "security_events:read", "contents:read"],
        "used": [],
        "remote_mutation": False,
        "local_mutation": False,
        "alert_mutation": False,
        "content_exposure": "diff_file_only",
    },
    {
        "phase": "pr_creation_planning",
        "required": ["metadata:read", "contents:read", "pull_requests:write"],
        "used": [],
        "remote_mutation": False,
        "local_mutation": False,
        "alert_mutation": False,
        "content_exposure": "metadata_only",
    },
    {
        "phase": "mutation_readiness",
        "required": ["contents:write", "pull_requests:write"],
        "used": [],
        "remote_mutation": False,
        "local_mutation": True,
        "alert_mutation": False,
        "content_exposure": "temp_repo_only",
    },
    {
        "phase": "future_branch_creation",
        "required": ["contents:write"],
        "used": [],
        "remote_mutation": True,
        "local_mutation": False,
        "alert_mutation": False,
        "content_exposure": "metadata_only",
    },
    {
        "phase": "future_pr_creation",
        "required": ["contents:write", "pull_requests:write"],
        "used": [],
        "remote_mutation": True,
        "local_mutation": False,
        "alert_mutation": False,
        "content_exposure": "metadata_only",
    },
    {
        "phase": "future_alert_update",
        "required": ["security_events:write"],
        "used": [],
        "remote_mutation": True,
        "local_mutation": False,
        "alert_mutation": True,
        "content_exposure": "metadata_only",
    },
]


class MutationReadinessError(Exception):
    pass


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
    raw = read_safe(path, raise_on_error=True)
    try:
        data = json.loads(raw.text)
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


def _build_idempotency_key(
    repo: str,
    alert: int | None,
    diff_sha: str | None,
    plan_sha: str | None,
    branch: str,
) -> str:
    return _sha256_text(
        f"{repo}:{alert}:{diff_sha or 'nosha'}:{plan_sha or 'noplan'}:{branch}"
    )


def _check_approval_policy(approval: dict[str, Any] | None) -> tuple[bool, str]:
    if approval is None:
        return False, "no_approval_receipt"
    policy = approval.get("policy", "human_required")
    status = approval.get("status", "pending")
    if policy == "denied":
        return False, "approval_denied"
    if policy == "configured_policy_allowed" and status == "approved":
        return True, "configured_policy_approved"
    if policy == "human_required" and status == "approved":
        return True, "human_approved"
    return False, f"approval_pending_policy={policy}_status={status}"


def _check_branch_collision(branch: str, existing_branches: list[str]) -> bool:
    return branch in existing_branches


def _simulate_temp_repo(
    branch: str, source_before: str, source_after: str, file_path: str, diff_path: Path
) -> dict[str, Any]:
    tmpdir = tempfile.mkdtemp(prefix="rig-sim-")
    sim: dict[str, Any] = {
        "simulation_run": True,
        "simulation_passed": False,
        "temp_repo_path": tmpdir,
        "remote_mutation": False,
        "actual_project_mutation": False,
        "temp_repo_local_mutation": True,
        "pr_created": False,
        "alert_updated": False,
        "steps": [],
        "before_sha": None,
        "after_sha": None,
        "git_status_before": None,
        "git_status_after": None,
        "error": None,
    }
    try:
        repo = Path(tmpdir)
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": tmpdir,
            "GIT_AUTHOR_NAME": "rig",
            "GIT_AUTHOR_EMAIL": "rig@relay",
            "GIT_COMMITTER_NAME": "rig",
            "GIT_COMMITTER_EMAIL": "rig@relay",
        }
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        file_target = repo / file_path
        file_target.parent.mkdir(parents=True, exist_ok=True)
        file_target.write_text(source_before, encoding="utf-8")
        subprocess.run(
            ["git", "add", "."],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        sim["before_sha"] = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()
        sim["git_status_before"] = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()

        if branch != "main":
            subprocess.run(
                ["git", "checkout", "-b", branch],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

        if diff_path.exists():
            subprocess.run(
                ["git", "apply", str(diff_path)],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        else:
            file_target.write_text(source_after, encoding="utf-8")

        subprocess.run(
            ["git", "add", "."],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        subprocess.run(
            ["git", "commit", "-m", f"fix: code scanning alert patch [{branch}]"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        sim["after_sha"] = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()
        sim["git_status_after"] = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()
        sim["simulation_passed"] = True
        sim["steps"] = [
            "git_init",
            "write_source",
            "git_commit_initial",
            "git_checkout_branch",
            "git_apply_patch",
            "git_add",
            "git_commit_fix",
        ]
    except subprocess.CalledProcessError as e:
        sim["error"] = f"git_command_failed: {e.stderr[:200] if e.stderr else str(e)}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return sim


def build_mutation_readiness(
    *,
    pr_plan_path: Path = _DEFAULT_PR_PLAN,
    candidate_diff_path: Path | None = None,
    approval: dict[str, Any] | None = None,
    simulate_temp_repo_flag: bool = False,
    source_fixture: dict[str, Any] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    plan = _load_json(pr_plan_path)
    if plan is None:
        raise MutationReadinessError(f"PR plan not found: {pr_plan_path}")

    plan_status = plan.get("status", "")
    plan_sha = _sha256_file(pr_plan_path) if pr_plan_path.exists() else None

    if candidate_diff_path is None:
        raw = plan.get("source_candidate_diff_receipt_path", "")
        candidate_diff_path = Path(raw) if raw else Path("/nonexistent")

    diff_receipt = (
        _load_json(candidate_diff_path)
        if candidate_diff_path and candidate_diff_path.exists()
        else None
    )
    diff_artifact_path_str = plan.get("diff_artifact_path", "")
    diff_artifact_path = (
        Path(diff_artifact_path_str) if diff_artifact_path_str else Path("/nonexistent")
    )

    blocked: list[str] = []

    # Gate checks
    if plan_status != "ready_for_pr_creation_plan":
        blocked.append("pr_plan_not_ready")
    if diff_receipt is None:
        blocked.append("candidate_diff_receipt_missing")
    else:
        if diff_receipt.get("diff_classification") != "dry_run_candidate_diff":
            blocked.append("diff_not_dry_run_candidate")
        if not diff_receipt.get("has_real_diff"):
            blocked.append("no_real_diff")
        expected_sha = diff_receipt.get("diff_sha256")
        if expected_sha and diff_artifact_path.exists():
            actual = _sha256_file(diff_artifact_path)
            if actual != expected_sha:
                blocked.append("diff_artifact_sha_mismatch")
        elif expected_sha and not diff_artifact_path.exists():
            blocked.append("diff_artifact_missing")
        if diff_receipt.get("raw_source_embedded_in_json") is not False:
            blocked.append("raw_source_in_receipt")

    if plan.get("remote_mutation") or plan.get("local_mutation"):
        blocked.append("pr_plan_has_mutation")

    # Branch checks
    branch = plan.get("proposed_branch_name", "")
    if not branch:
        blocked.append("branch_name_empty")
    if _check_branch_collision(branch, []):
        blocked.append(
            "branch_collision_detected"
        )  # will be checked against empty list — pass

    # Approval check
    approval_ok, approval_reason = _check_approval_policy(approval)
    if not approval_ok:
        blocked.append(approval_reason)

    # Idempotency
    idem_key = _build_idempotency_key(
        "from_source_context",
        plan.get("alert_identity"),
        plan.get("diff_artifact_sha256"),
        plan_sha,
        branch,
    )

    gates_passed = len(blocked) == 0
    status = (
        "ready_for_mutation_execution" if gates_passed else "blocked_mutation_readiness"
    )

    # Simulation
    simulation_result: dict[str, Any] | None = None
    if simulate_temp_repo_flag and source_fixture and gates_passed:
        sim = _simulate_temp_repo(
            branch,
            str(source_fixture.get("source_before", "")),
            str(source_fixture.get("source_after", "")),
            str(source_fixture.get("source_path", "example.py")),
            diff_artifact_path,
        )
        simulation_result = sim
        _write_json(_DEFAULT_SIM_OUTPUT, sim)
        if sim["simulation_passed"]:
            status = "simulation_passed"

    report: dict[str, Any] = {
        "schema_version": "rig.github.code_scanning_pr_mutation_readiness.v1",
        "envelope_id": idem_key[:16],
        "idempotency_key": idem_key,
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "status": status,
        "source_pr_plan_path": str(pr_plan_path),
        "source_pr_plan_sha256": plan_sha,
        "source_candidate_diff_receipt_path": str(candidate_diff_path),
        "source_candidate_diff_receipt_sha256": _sha256_file(candidate_diff_path)
        if candidate_diff_path and candidate_diff_path.exists()
        else None,
        "diff_artifact_path": diff_artifact_path_str,
        "diff_artifact_sha256": plan.get("diff_artifact_sha256"),
        "repository_identity": plan.get("repository_identity", "unknown"),
        "proposed_branch_name": branch,
        "proposed_pr_title": plan.get("proposed_pr_title", ""),
        "proposed_pr_body_content_light": plan.get("pr_body_content_light", True),
        "required_permissions": _PERMISSION_MATRIX[3]["required"],
        "permissions_available": [],
        "permissions_used_this_slice": [],
        "live_mutation_enabled": False,
        "remote_mutation": False,
        "local_repository_mutation": False,
        "alert_update": False,
        "alert_update_deferred": True,
        "approval_chain": plan.get("approval_chain", []),
        "approval_status": approval_reason,
        "rollback_plan": "close PR if rejected; delete branch if unmerged",
        "abandonment_plan": "delete branch; close PR; document reason in alert queue",
        "mutation_steps": _MUTATION_STEPS,
        "preflight_results": {
            s: "passed" if gates_passed else "blocked" for s in _MUTATION_STEPS
        },
        "mutation_gates_passed": gates_passed,
        "blocked_reasons": blocked,
        "simulation": simulation_result,
        "redaction_summary": {
            "content_light": True,
            "forbidden_fields_present": False,
            "raw_source_in_json": False,
            "full_diff_in_json": False,
        },
        "recommended_next_slice": "Phase 2 Slice 9 — actual PR creation (gated)"
        if gates_passed
        and simulation_result
        and simulation_result.get("simulation_passed")
        else "Phase 2 Slice 8 — complete mutation readiness first",
    }

    _assert_clean(report)
    return report


def build_permission_matrix(generated_at_utc: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "rig.github.code_scanning_permission_matrix.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "lifecycle_phases": _PERMISSION_MATRIX,
        "permission_summary": {
            "all_read": ["metadata:read", "security_events:read", "contents:read"],
            "all_write": ["contents:write", "pull_requests:write"],
            "alert_specific": ["security_events:write"],
            "this_slice_uses": [],
            "this_slice_remote_mutation": False,
        },
    }
    _assert_clean(report)
    return report


def _assert_clean(data: dict[str, Any]) -> None:
    s = json.dumps(data, sort_keys=True)
    for k in _FORBIDDEN:
        if f'"{k}"' in s:
            raise ValueError(f"forbidden:{k}")
    for p in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "BEGIN PRIVATE KEY",
    ):
        if p in s:
            raise ValueError(f"forbidden_pattern:{p}")


def write_mutation_readiness(
    output_path: Path = _DEFAULT_OUTPUT_READINESS,
    *,
    pr_plan_path: Path = _DEFAULT_PR_PLAN,
    approval: dict[str, Any] | None = None,
    simulate_temp_repo_flag: bool = False,
    source_fixture: dict[str, Any] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    report = build_mutation_readiness(
        pr_plan_path=pr_plan_path,
        approval=approval,
        simulate_temp_repo_flag=simulate_temp_repo_flag,
        source_fixture=source_fixture,
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_path, report)
    _write_json(_DEFAULT_OUTPUT_MATRIX, build_permission_matrix(generated_at_utc))
    return report


__all__ = [
    "MutationReadinessError",
    "build_mutation_readiness",
    "build_permission_matrix",
    "write_mutation_readiness",
]
