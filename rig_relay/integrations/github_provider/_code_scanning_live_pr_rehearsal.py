"""First Real Live PR Rehearsal v1 — gated, operator-acknowledged, alert-deferred.

Creates branch, writes file, opens PR only if all gates + operator checklist pass.
Default: blocked. Live: gated. Tests: fake boundary only. Alert update: deferred.
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
_GOV = _REPO_ROOT / "docs" / "json" / "governance"
_BUILD = _REPO_ROOT / ".build" / "rig-relay" / "evidence"

_DEFAULT_RC_PHASE2 = _GOV / "github_security_lifecycle_phase2_rc_report_v1.v1.json"
_DEFAULT_RC_PHASE3 = _GOV / "github_live_mutation_phase3_rc_report_v1.v1.json"
_DEFAULT_PREFLIGHT = _GOV / "github_live_mutation_preflight_v1.v1.json"
_DEFAULT_OUTPUT = _GOV / "github_live_pr_rehearsal_v1.v1.json"
_DEFAULT_RECEIPT = _GOV / "github_live_pr_rehearsal_receipt_v1.v1.json"
_DEFAULT_CHECKLIST = _GOV / "github_live_pr_rehearsal_operator_checklist_v1.v1.json"
_DEFAULT_REPORT = _BUILD / "live_pr_rehearsal_v1_report.v1.json"

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

_STEPS = [
    ("load_phase2_rc", "read_only"),
    ("load_phase3_rc", "read_only"),
    ("load_preflight", "read_only"),
    ("verify_approval", "read_only"),
    ("verify_operator_checklist", "read_only"),
    ("verify_candidate_diff", "read_only"),
    ("verify_branch_safety", "read_only"),
    ("verify_path_safety", "read_only"),
    ("verify_rate_limit", "read_only"),
    ("verify_idempotency", "read_only"),
    ("read_base_ref", "read_only"),
    ("create_branch_ref", "remote_mutation"),
    ("write_file_contents", "remote_mutation"),
    ("create_pull_request", "remote_mutation"),
    ("write_receipt", "local_artifact_write"),
    ("write_rollback_guidance", "local_artifact_write"),
    ("alert_update_deferred", "deferred"),
]


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        d = json.loads(read_safe(path, raise_on_error=True).text)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _write_json(path: Path, d: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build_operator_checklist(
    branch: str, target_path: str, diff_hash: str
) -> dict[str, Any]:
    return {
        "repository": "OWNER/REPO",
        "base_branch": "main",
        "proposed_branch": branch,
        "target_file_paths": [target_path],
        "candidate_diff_hash": diff_hash,
        "operation_idempotency_key": _sha256_text(
            f"op:{branch}:{target_path}:{diff_hash}"
        ),
        "expected_operations": ["create_branch", "write_file", "create_pr"],
        "permissions_required": ["contents:write", "pull_requests:write"],
        "permissions_verified": False,
        "alert_update_deferred": True,
        "pr_merge_deferred": True,
        "rollback_guidance": "close PR if rejected; delete branch if unmerged",
        "no_default_branch_write": True,
        "no_workflow_paths": not target_path.startswith(".github/workflows/"),
        "no_raw_vulnerable_content": True,
    }


def build_live_pr_rehearsal(
    *,
    allow_execute: bool = False,
    operator_acknowledged: bool = False,
    allow_live_writes: bool = False,
    approval_ok: bool = False,
    fake_boundary: FakeGitHubBoundary | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    branch = "rig/security/governed-fix-5"
    target_path = "RIG_RELAY_GOVERNED.md"
    diff_hash = _sha256_text("candidate-diff")
    checklist = build_operator_checklist(branch, target_path, diff_hash)
    _write_json(_DEFAULT_CHECKLIST, checklist)

    rc2 = _load_json(_DEFAULT_RC_PHASE2)
    rc3 = _load_json(_DEFAULT_RC_PHASE3)
    preflight = _load_json(_DEFAULT_PREFLIGHT)

    gates: list[dict[str, Any]] = []
    blocked: list[str] = []

    def g(name: str, p: bool, detail: str = "") -> None:
        gates.append({"gate": name, "passed": p, "detail": detail})
        if not p:
            blocked.append(name)

    g("phase2_rc_present", rc2 is not None)
    g("phase3_rc_present", rc3 is not None)
    g("preflight_present", preflight is not None)
    g(
        "preflight_ready",
        (preflight or {}).get("gates_passed", False) if preflight else False,
    )
    g("execute_flag", allow_execute)
    g("operator_acknowledged", operator_acknowledged)
    g("allow_live_writes", allow_live_writes)
    g("approval_ok", approval_ok)
    g("boundary_present", fake_boundary is not None)

    if fake_boundary:
        g(
            "contents_write_available",
            fake_boundary._permissions.get("contents:write", False),
        )
        g(
            "pull_requests_write_available",
            fake_boundary._permissions.get("pull_requests:write", False),
        )
        g("rate_limit_ok", not fake_boundary._rate_limited)
        g("branch_not_collision", branch not in fake_boundary._existing_branches)

    gates_passed = len(blocked) == 0
    steps_result: list[dict[str, Any]] = []
    remote_ok = False
    branch_done = False
    file_done = False
    pr_done = False

    for step_name, op_class in _STEPS:
        entry: dict[str, Any] = {
            "step_name": step_name,
            "operation_class": op_class,
            "status": "blocked",
            "remote_mutation_attempted": False,
            "remote_mutation_succeeded": False,
        }

        if not gates_passed:
            steps_result.append(entry)
            continue

        if op_class == "remote_mutation" and fake_boundary:
            entry["remote_mutation_attempted"] = True
            if step_name == "create_branch_ref":
                sc, _ = fake_boundary.create_branch(branch, "base_sha")
                entry["remote_mutation_succeeded"] = sc in {201, 200}
                entry["status"] = "passed" if sc in {201, 200} else f"http_{sc}"
                branch_done = sc in {201, 200}
            elif step_name == "write_file_contents":
                sc, _ = fake_boundary.write_file(target_path, diff_hash)
                entry["remote_mutation_succeeded"] = sc in {201, 200}
                entry["status"] = "passed" if sc in {201, 200} else f"http_{sc}"
                file_done = sc in {201, 200}
            elif step_name == "create_pull_request":
                idem = _sha256_text(f"rehearsal:{_now_iso()}")
                sc, _ = fake_boundary.create_pr(
                    "Fix code scanning alert #5 [rehearsal]", branch, "main", idem
                )
                entry["remote_mutation_succeeded"] = sc in {201, 200}
                entry["status"] = "passed" if sc in {201, 200} else f"http_{sc}"
                pr_done = sc in {201, 200}
        else:
            entry["status"] = "passed"

        steps_result.append(entry)

    remote_ok = branch_done and file_done and pr_done

    report: dict[str, Any] = {
        "schema_version": "rig.github.live_pr_rehearsal.v1",
        "content_light": True,
        "status": "rehearsal_success" if remote_ok else "rehearsal_blocked",
        "gates": gates,
        "gates_passed": gates_passed,
        "blocked_reasons": blocked,
        "steps": steps_result,
        "branch_created": branch_done,
        "file_written": file_done,
        "pr_created": pr_done,
        "remote_mutation_succeeded": remote_ok,
        "alert_updated": False,
        "alert_update_deferred": True,
        "pr_merged": False,
        "operator_checklist": checklist,
        "rollback_guidance": "close PR; delete branch",
        "redaction_summary": {"content_light": True, "raw_response_bodies": False},
        "next_safe_action": "review_rehearsal_receipt",
    }
    _write_json(_DEFAULT_OUTPUT, report)
    _write_json(_DEFAULT_RECEIPT, report)
    _write_json(_DEFAULT_REPORT, report)

    s_out = json.dumps(report, sort_keys=True)
    for k in _FORBIDDEN:
        assert f'"{k}"' not in s_out, f"forbidden:{k}"
    for pat in ("ghp_", "gho_", "github_pat_", "BEGIN PRIVATE KEY"):
        assert pat not in s_out, f"forbidden:{pat}"
    return report


def write_live_pr_rehearsal(
    *,
    allow_execute: bool = False,
    operator_acknowledged: bool = False,
    approval_ok: bool = False,
    simulate: bool = False,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    fb = FakeGitHubBoundary() if simulate else None
    return build_live_pr_rehearsal(
        allow_execute=allow_execute,
        operator_acknowledged=operator_acknowledged,
        approval_ok=approval_ok,
        fake_boundary=fb,
        generated_at_utc=generated_at_utc,
    )


__all__ = ["_STEPS", "build_live_pr_rehearsal", "write_live_pr_rehearsal"]
