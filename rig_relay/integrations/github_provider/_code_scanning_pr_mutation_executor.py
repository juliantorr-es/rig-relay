"""Gated GitHub PR Mutation Executor v1 — governed, dry-run-first, receipt-backed.

Full remote mutation chain: preflight → branch → file → PR → receipt.
Disabled by default. Requires --execute-remote-mutation + approval + readiness.
Fake GitHub boundary for deterministic testing. No alert mutation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.github_provider._fake_github_boundary import (
    FakeGitHubBoundary,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_READINESS = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "code_scanning_pr_mutation_readiness_v1.v1.json"
)
_DEFAULT_CANDIDATE = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "code_scanning_dry_run_candidate_diff_v1.v1.json"
)
_DEFAULT_EXEC_OUTPUT = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_pr_mutation_execution_v1.v1.json"
)
_DEFAULT_RECEIPT = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_pr_operation_receipt_v1.v1.json"
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
_BRANCH_MAX_LEN = 100
_UNSAFE_PREFIXES = ("../", "/etc/", "/home/", "~")
_WORKFLOW_PREFIX = ".github/workflows/"
_SAFE_BRANCH_PREFIX = "rig/security/"


class MutationExecutorError(Exception):
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


def _is_path_safe(target: str) -> tuple[bool, list[str]]:
    blocked: list[str] = []
    if target.startswith(_WORKFLOW_PREFIX):
        blocked.append("workflow_path_blocked")
    for pfx in _UNSAFE_PREFIXES:
        if pfx in target or target.startswith(pfx.lstrip(".")):
            blocked.append("path_traversal_unsafe")
            break
    ext = Path(target).suffix.lower()
    if ext in {".pyc", ".so", ".dylib", ".dll", ".exe", ".bin"}:
        blocked.append("binary_path_blocked")
    return len(blocked) == 0, blocked


def _is_branch_safe(branch: str, base: str = "main") -> tuple[bool, list[str]]:
    blocked: list[str] = []
    if not branch:
        blocked.append("branch_name_empty")
    if branch == base:
        blocked.append("branch_equals_base")
    if not branch.startswith(_SAFE_BRANCH_PREFIX):
        blocked.append("branch_prefix_unsafe")
    if len(branch) > _BRANCH_MAX_LEN:
        blocked.append("branch_name_too_long")
    return len(blocked) == 0, blocked


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


def _check_approval(approval: dict[str, Any] | None) -> tuple[bool, str]:
    if approval is None:
        return False, "no_approval_receipt"
    pol = approval.get("policy", "human_required")
    st = approval.get("status", "pending")
    if pol == "denied":
        return False, "approval_denied"
    if st != "approved":
        return False, f"approval_not_approved_status={st}"
    return True, f"{pol}_approved"


def execute_pr_mutation(
    *,
    readiness_path: Path = _DEFAULT_READINESS,
    candidate_diff_path: Path = _DEFAULT_CANDIDATE,
    approval: dict[str, Any] | None = None,
    allow_remote: bool = False,
    fake_boundary: FakeGitHubBoundary | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    readiness = _load_json(readiness_path)
    candidate = _load_json(candidate_diff_path)

    gates: list[dict[str, Any]] = []
    blocked: list[str] = []

    def _gate(name: str, passed: bool, detail: str = "") -> None:
        gates.append({"gate": name, "passed": passed, "detail": detail})
        if not passed:
            blocked.append(name)

    # Core gates
    _gate("readiness_artifact_present", readiness is not None)
    if readiness:
        _gate(
            "readiness_simulation_passed",
            readiness.get("status")
            in {"simulation_passed", "ready_for_mutation_execution"},
        )
    _gate("candidate_diff_present", candidate is not None)
    if candidate:
        _gate(
            "candidate_not_blocked_explanation",
            candidate.get("diff_classification") != "blocked_explanation",
        )
        _gate("candidate_has_real_diff", candidate.get("has_real_diff") is True)

    # Approval
    approval_ok, approval_reason = _check_approval(approval)
    _gate(f"approval_{approval_reason}", approval_ok)

    # Path safety from candidate
    path_target = candidate.get("diff_path", "") if candidate else ""
    path_safe, path_blocked = (
        _is_path_safe(path_target) if candidate else (False, ["no_candidate"])
    )
    _gate("path_safety", path_safe, str(path_blocked))

    # Branch safety
    branch = readiness.get("proposed_branch_name", "") if readiness else ""
    branch_safe, branch_blocked = _is_branch_safe(branch)
    _gate("branch_safety", branch_safe, str(branch_blocked))

    # Remote mutation gate
    _gate("explicit_remote_flag", allow_remote, "requires --execute-remote-mutation")

    # Permission gate via fake boundary
    if fake_boundary is not None:
        contents_ok = fake_boundary._permissions.get("contents:write", False)
        pr_ok = fake_boundary._permissions.get("pull_requests:write", False)
        _gate("permission_contents_write", contents_ok)
        _gate("permission_pull_requests_write", pr_ok)

    all_gates_ok = len(blocked) == 0
    remote_attempted = False
    remote_succeeded = False
    pr_created = False
    idem_key = _build_idempotency_key(
        "code_scanning_remediation",
        candidate.get("selected_alert_number") if candidate else None,
        candidate.get("diff_sha256") if candidate else None,
        _sha256_file(readiness_path) if readiness_path.exists() else None,
        branch,
    )

    # Mutation steps modeled
    steps: list[dict[str, Any]] = [
        {
            "step_id": "preflight_readiness_load",
            "step_name": "load readiness",
            "operation_class": "read_only",
            "required_permissions": [],
            "status": "passed" if readiness else "blocked",
            "remote_mutation_attempted": False,
        },
        {
            "step_id": "approval_receipt_verify",
            "step_name": "verify approval",
            "operation_class": "read_only",
            "required_permissions": [],
            "status": "passed" if approval_ok else "blocked",
            "remote_mutation_attempted": False,
        },
        {
            "step_id": "branch_ref_create",
            "step_name": "create branch ref",
            "operation_class": "remote_mutation",
            "required_permissions": ["contents:write"],
            "status": "blocked",
            "remote_mutation_attempted": False,
        },
        {
            "step_id": "file_write",
            "step_name": "write candidate file",
            "operation_class": "remote_mutation",
            "required_permissions": ["contents:write"],
            "status": "blocked",
            "remote_mutation_attempted": False,
        },
        {
            "step_id": "pr_create",
            "step_name": "create pull request",
            "operation_class": "remote_mutation",
            "required_permissions": ["pull_requests:write"],
            "status": "blocked",
            "remote_mutation_attempted": False,
        },
        {
            "step_id": "operation_receipt_write",
            "step_name": "write operation receipt",
            "operation_class": "local_artifact_write",
            "required_permissions": [],
            "status": "blocked",
            "remote_mutation_attempted": False,
        },
        {
            "step_id": "alert_update_deferred",
            "step_name": "alert update deferred",
            "operation_class": "deferred",
            "required_permissions": [],
            "status": "deferred",
            "remote_mutation_attempted": False,
        },
    ]

    # If all gates pass and remote is allowed, simulate mutation via fake boundary
    if (
        all_gates_ok
        and allow_remote
        and fake_boundary is not None
        and candidate is not None
    ):
        remote_attempted = True

        # Create branch
        sc, _ = fake_boundary.create_branch(branch, "base_sha")
        steps[2]["status"] = "passed" if sc in {201, 200} else f"http_{sc}"
        steps[2]["remote_mutation_attempted"] = True
        steps[2]["remote_mutation_succeeded"] = sc in {201, 200}

        # Write file
        sc2, _ = fake_boundary.write_file(path_target, candidate.get("diff_sha256"))
        steps[3]["status"] = "passed" if sc2 in {201, 200} else f"http_{sc2}"
        steps[3]["remote_mutation_attempted"] = True
        steps[3]["remote_mutation_succeeded"] = sc2 in {201, 200}

        # Create PR
        pr_title = readiness.get("proposed_pr_title", "Fix patch")
        sc3, pr_data = fake_boundary.create_pr(pr_title, branch, "main", idem_key)
        steps[4]["status"] = "passed" if sc3 in {201, 200} else f"http_{sc3}"
        steps[4]["remote_mutation_attempted"] = True
        steps[4]["remote_mutation_succeeded"] = sc3 in {201, 200}

        pr_created = sc3 in {201, 200}
        remote_succeeded = all(
            s.get("remote_mutation_succeeded")
            for s in steps
            if s.get("remote_mutation_attempted")
        )

    if remote_succeeded:
        steps[5]["status"] = "passed"

    operation_status = (
        "simulated_success"
        if remote_succeeded
        else "simulated_blocked"
        if remote_attempted
        else "blocked"
    )

    report: dict[str, Any] = {
        "schema_version": "rig.github.code_scanning_pr_mutation_execution.v1",
        "operation_id": idem_key[:16],
        "idempotency_key": idem_key,
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "operation_status": operation_status,
        "dry_run": not allow_remote,
        "remote_mutation_attempted": remote_attempted,
        "remote_mutation_succeeded": remote_succeeded,
        "pr_created": pr_created,
        "alert_updated": False,
        "alert_update_deferred": True,
        "gates": gates,
        "gates_passed": all_gates_ok,
        "blocked_reasons": blocked,
        "steps": steps,
        "permissions_used": ["contents:write", "pull_requests:write"]
        if remote_succeeded
        else [],
        "simulation_type": "fake_github_boundary" if fake_boundary else "none",
        "redaction_summary": {
            "content_light": True,
            "forbidden_fields_present": False,
            "raw_response_bodies_persisted": False,
        },
        "rollback_or_cleanup": "delete branch if PR failed; close PR if rejected",
        "intentionally_deferred": ["alert_update", "pr_merge", "default_branch_push"],
        "recommended_next_slice": "Phase 2 Slice 10 — alert state management (gated)"
        if remote_succeeded
        else "Phase 2 Slice 9 — pass all readiness gates first",
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


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_mutation_execution(
    output_path: Path = _DEFAULT_EXEC_OUTPUT,
    *,
    approval: dict[str, Any] | None = None,
    allow_remote: bool = False,
    simulate: bool = False,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    fake_boundary = FakeGitHubBoundary() if simulate else None
    report = execute_pr_mutation(
        approval=approval,
        allow_remote=allow_remote,
        fake_boundary=fake_boundary,
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_path, report)
    _write_json(_DEFAULT_RECEIPT, report)
    if fake_boundary:
        fake_boundary.write_trace()
    return report


__all__ = [
    "MutationExecutorError",
    "_build_idempotency_key",
    "_check_approval",
    "_is_branch_safe",
    "_is_path_safe",
    "execute_pr_mutation",
    "write_mutation_execution",
]
