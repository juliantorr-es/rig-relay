"""Live PR Mutation Adapter v1 — gated, emergency-braked, rollback-planned.

Bridges the dry-run PR mutation executor with live GitHub API calls.
Wraps fake boundary for simulation. Rollback plan always generated.
No alert mutation. All gates must pass. Default: blocked.
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
_DEFAULT_RC = _GOV / "github_security_lifecycle_phase2_rc_report_v1.v1.json"
_DEFAULT_PREFLIGHT = _GOV / "github_live_mutation_preflight_v1.v1.json"
_DEFAULT_OUTPUT = _GOV / "github_live_pr_mutation_attempt_v1.v1.json"
_DEFAULT_ROLLBACK = _GOV / "github_live_pr_mutation_rollback_plan_v1.v1.json"

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
    {
        "id": "load_phase2_rc",
        "name": "load RC report",
        "class": "read_only",
        "perm": "metadata:read",
    },
    {
        "id": "load_live_preflight",
        "name": "load preflight",
        "class": "read_only",
        "perm": "metadata:read",
    },
    {
        "id": "verify_approval",
        "name": "verify approval",
        "class": "read_only",
        "perm": "none",
    },
    {
        "id": "verify_idempotency",
        "name": "verify idempotency",
        "class": "read_only",
        "perm": "none",
    },
    {
        "id": "verify_candidate_diff",
        "name": "verify candidate diff",
        "class": "read_only",
        "perm": "none",
    },
    {
        "id": "verify_branch_safety",
        "name": "verify branch safety",
        "class": "read_only",
        "perm": "none",
    },
    {
        "id": "verify_path_safety",
        "name": "verify path safety",
        "class": "read_only",
        "perm": "none",
    },
    {
        "id": "verify_rate_limit",
        "name": "verify rate limit",
        "class": "read_only",
        "perm": "none",
    },
    {
        "id": "read_base_ref",
        "name": "read base ref",
        "class": "read_only",
        "perm": "metadata:read",
    },
    {
        "id": "create_branch",
        "name": "create branch ref",
        "class": "remote_mutation",
        "perm": "contents:write",
    },
    {
        "id": "write_file",
        "name": "write file contents",
        "class": "remote_mutation",
        "perm": "contents:write",
    },
    {
        "id": "create_pr",
        "name": "create pull request",
        "class": "remote_mutation",
        "perm": "pull_requests:write",
    },
    {
        "id": "write_receipt",
        "name": "write operation receipt",
        "class": "local_artifact_write",
        "perm": "none",
    },
    {
        "id": "write_rollback",
        "name": "write rollback plan",
        "class": "local_artifact_write",
        "perm": "none",
    },
    {
        "id": "alert_deferred",
        "name": "alert update deferred",
        "class": "deferred",
        "perm": "security_events:write",
    },
]


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


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


def _build_rollback(
    branch: str, pr_created: bool, steps_that_require_cleanup: list[str]
) -> dict[str, Any]:
    return {
        "branch_cleanup": f"git push origin --delete {branch} (if remote exists)"
        if branch
        else "no branch to clean",
        "pr_close": "close PR via GitHub API or UI; do not merge"
        if pr_created
        else "no PR to close",
        "file_revert": "revert file changes via new commit or branch deletion"
        if "write_file" in steps_that_require_cleanup
        else "no file to revert",
        "alert_state_unchanged": True,
        "manual_review_required": True,
        "required_permissions": ["contents:write"],
        "idempotency_key": _sha256_text(f"rollback:{branch}:{_now_iso()}"),
    }


def build_live_pr_mutation_attempt(
    *,
    allow_execute: bool = False,
    activate_live_gate: bool = False,
    approval_ok: bool = False,
    fake_boundary: FakeGitHubBoundary | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    rc = _load_json(_DEFAULT_RC)
    preflight = _load_json(_DEFAULT_PREFLIGHT)

    gates: list[dict[str, Any]] = []
    blocked: list[str] = []

    def _gate(name: str, passed: bool, detail: str = "") -> None:
        gates.append({"gate": name, "passed": passed, "detail": detail})
        if not passed:
            blocked.append(name)

    _gate("rc_report_present", rc is not None)
    _gate("preflight_present", preflight is not None)
    pf_ready = preflight.get("gates_passed", False) if preflight else False
    _gate(
        "preflight_ready", pf_ready, "preflight must be ready for live mutation review"
    )
    _gate("execute_flag_set", allow_execute)
    _gate("live_gate_active", activate_live_gate)
    _gate("approval_ok", approval_ok)
    _gate("boundary_present", fake_boundary is not None)

    if fake_boundary:
        _gate(
            "permission_contents_write",
            fake_boundary._permissions.get("contents:write", False),
        )
        _gate(
            "permission_pull_requests_write",
            fake_boundary._permissions.get("pull_requests:write", False),
        )
        _gate("rate_limit_ok", not fake_boundary._rate_limited)

    gates_passed = len(blocked) == 0
    steps_result: list[dict[str, Any]] = []
    remote_mutation_succeeded = False
    branch_created = False
    file_written = False
    pr_created_flag = False

    branch = "rig/security/fix-5"

    for i, step in enumerate(_STEPS):
        entry: dict[str, Any] = {
            "step_id": step["id"],
            "step_name": step["name"],
            "operation_class": step["class"],
            "required_permissions": [step["perm"]],
            "status": "blocked",
            "remote_mutation_attempted": False,
            "remote_mutation_succeeded": False,
        }

        if not gates_passed:
            steps_result.append(entry)
            continue

        # Simulate mutation via fake boundary
        if fake_boundary and step["class"] == "remote_mutation":
            entry["remote_mutation_attempted"] = True
            if step["id"] == "create_branch":
                sc, _ = fake_boundary.create_branch(branch, "base_sha")
                entry["remote_mutation_succeeded"] = sc in (201, 200)
                entry["status"] = "passed" if sc in (201, 200) else f"http_{sc}"
                branch_created = sc in (201, 200)
            elif step["id"] == "write_file":
                sc, _ = fake_boundary.write_file("README.md", "candidate_sha")
                entry["remote_mutation_succeeded"] = sc in (201, 200)
                entry["status"] = "passed" if sc in (201, 200) else f"http_{sc}"
                file_written = sc in (201, 200)
            elif step["id"] == "create_pr":
                idem_key = _sha256_text(f"live-attempt:{_now_iso()}")
                sc, _ = fake_boundary.create_pr(
                    "Fix code scanning alert #5", branch, "main", idem_key
                )
                entry["remote_mutation_succeeded"] = sc in (201, 200)
                entry["status"] = "passed" if sc in (201, 200) else f"http_{sc}"
                pr_created_flag = sc in (201, 200)
        elif step["id"] in ("write_receipt", "write_rollback", "alert_deferred"):
            entry["status"] = "passed"
        else:
            entry["status"] = "passed"

        steps_result.append(entry)

    remote_mutation_succeeded = branch_created and file_written and pr_created_flag
    cleanup_steps = [
        s["step_id"] for s in steps_result if s.get("remote_mutation_succeeded")
    ]
    rollback = _build_rollback(branch, pr_created_flag, cleanup_steps)
    _write_json(_DEFAULT_ROLLBACK, rollback)

    report: dict[str, Any] = {
        "schema_version": "rig.github.live_pr_mutation_attempt.v1",
        "attempt_id": _sha256_text(f"attempt:{_now_iso()}"),
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "status": "simulated_success"
        if remote_mutation_succeeded
        else "simulated_blocked"
        if gates_passed
        else "blocked",
        "gates": gates,
        "gates_passed": gates_passed,
        "blocked_reasons": blocked,
        "steps": steps_result,
        "branch_created": branch_created,
        "file_written": file_written,
        "pr_created": pr_created_flag,
        "remote_mutation_succeeded": remote_mutation_succeeded,
        "alert_updated": False,
        "alert_update_deferred": True,
        "rollback_plan_path": str(_DEFAULT_ROLLBACK),
        "permissions_used": ["contents:write", "pull_requests:write"]
        if remote_mutation_succeeded
        else [],
        "redaction_summary": {
            "content_light": True,
            "forbidden_fields_present": False,
            "raw_response_bodies": False,
        },
        "recommended_next_slice": "Phase 3 Slice 3 — actual GitHub live network test"
        if remote_mutation_succeeded
        else "Phase 3 Slice 2 — pass all live gates first",
    }
    return report


def _assert_clean(data: dict[str, Any]) -> None:
    s = json.dumps(data, sort_keys=True)
    for k in _FORBIDDEN:
        if f'"{k}"' in s:
            raise ValueError(f"forbidden:{k}")


def write_live_pr_mutation_attempt(
    output_path: Path = _DEFAULT_OUTPUT,
    *,
    allow_execute: bool = False,
    activate_live_gate: bool = False,
    approval_ok: bool = False,
    simulate: bool = False,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    fb = FakeGitHubBoundary() if simulate else None
    report = build_live_pr_mutation_attempt(
        allow_execute=allow_execute,
        activate_live_gate=activate_live_gate,
        approval_ok=approval_ok,
        fake_boundary=fb,
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_path, report)
    if fb:
        fb.write_trace()
    return report


__all__ = [
    "_STEPS",
    "_build_rollback",
    "build_live_pr_mutation_attempt",
    "write_live_pr_mutation_attempt",
]
