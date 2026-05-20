"""Code Scanning PR Creation Plan v1 — governed, content-light, planning-only.

Produces a PR creation plan only from a verified dry_run_candidate_diff.
Blocked diffs produce blocked_pr_creation_plan. No actual PR creation, no mutation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from rig_relay.core.utils.io import read_safe

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CANDIDATE_DIFF = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "code_scanning_dry_run_candidate_diff_v1.v1.json"
)
_DEFAULT_OUTPUT = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "code_scanning_pr_creation_plan_v1.v1.json"
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

_UNSAFE_BRANCH_RE = re.compile(r"[^a-z0-9/_\-.]")

_FUTURE_PERMISSIONS = ["contents:write", "pull_requests:write"]


class PrPlanError(Exception):
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


_BRANCH_MAX_LEN = 80


def _sanitize_branch_name(raw: str) -> str:
    cleaned = raw.lower().strip()
    cleaned = cleaned.replace("..", "-")
    cleaned = re.sub(r"^\.|\.$", "-", cleaned)
    cleaned = _UNSAFE_BRANCH_RE.sub("-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned)
    cleaned = cleaned.strip("-").strip(".")
    if not cleaned:
        cleaned = "fix"
    if len(cleaned) > _BRANCH_MAX_LEN:
        cleaned = cleaned[:_BRANCH_MAX_LEN].rstrip("-")
    return cleaned


def _build_branch_name(diff_receipt: dict[str, Any]) -> str:
    alert = diff_receipt.get("selected_alert_number", "0")
    sha = (diff_receipt.get("diff_sha256") or "nosha")[:8]
    raw = f"rig/code-scanning/{alert}-fix-{sha}"
    return _sanitize_branch_name(raw)


def _pr_gates_pass(
    diff_receipt: dict[str, Any], diff_path: Path
) -> tuple[bool, list[str]]:
    blocked: list[str] = []

    if not diff_receipt:
        blocked.append("candidate_diff_receipt_missing")
        return False, blocked

    if diff_receipt.get("diff_classification") != "dry_run_candidate_diff":
        blocked.append("diff_classification_not_dry_run_candidate")
    if not diff_receipt.get("has_real_diff"):
        blocked.append("no_real_candidate_diff")
    if not diff_receipt.get("policy_gate_passed"):
        blocked.append("candidate_diff_policy_gate_failed")
    if not diff_path.exists():
        blocked.append("diff_artifact_file_missing")

    expected_sha = diff_receipt.get("diff_sha256")
    if expected_sha and diff_path.exists():
        actual = _sha256_file(diff_path)
        if actual != expected_sha:
            blocked.append("diff_sha256_mismatch")

    if not diff_receipt.get("source_context_hash"):
        blocked.append("source_context_hash_missing")
    if not diff_receipt.get("selected_alert_number"):
        blocked.append("alert_identity_missing")
    if diff_receipt.get("raw_source_embedded_in_json") is not False:
        blocked.append("raw_source_may_be_embedded")
    if diff_receipt.get("remote_mutation"):
        blocked.append("candidate_diff_has_remote_mutation")
    if diff_receipt.get("local_mutation"):
        blocked.append("candidate_diff_has_local_mutation")

    return len(blocked) == 0, blocked


def build_code_scanning_pr_plan(
    *,
    candidate_diff_path: Path = _DEFAULT_CANDIDATE_DIFF,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    receipt = _load_json(candidate_diff_path)
    if receipt is None:
        raise PrPlanError(f"Candidate diff not found: {candidate_diff_path}")

    diff_artifact_path_str = str(receipt.get("diff_path", ""))
    diff_artifact_path = (
        Path(diff_artifact_path_str) if diff_artifact_path_str else Path("/nonexistent")
    )

    gates_ok, blocked = _pr_gates_pass(receipt, diff_artifact_path)
    status = "ready_for_pr_creation_plan" if gates_ok else "blocked_pr_creation_plan"

    branch_name = _build_branch_name(receipt) if gates_ok else ""
    alert = receipt.get("selected_alert_number", 0)
    sha = (receipt.get("diff_sha256") or "nosha")[:16]
    sev = receipt.get("severity", "unknown")

    commit_title = f"fix: address code scanning alert #{alert} ({sev})"
    pr_title = f"[Rig Relay] Fix code scanning alert #{alert} [{sev}]"
    pr_body = (
        f"## Proposed Fix for Code Scanning Alert #{alert}\n\n"
        f"- **Severity:** {sev}\n"
        f"- **Rule ID hash:** {receipt.get('rule_id_hash', 'N/A')[:16]}...\n"
        f"- **Diff artifact:** `{diff_artifact_path_str}`\n"
        f"- **Diff SHA256:** `{sha}`\n"
        f"- **Candidate receipt:** `{candidate_diff_path}`\n\n"
        f"**Note:** This PR was planned from a bounded, content-light source context. "
        f"The fix patch was generated as a dry-run candidate diff and has not been applied. "
        f"All mutation gates must be passed before this PR can be created.\n\n"
        f"**Validation:** Targeted unit/integration tests should be run for the affected path. "
        f"Do not run full pytest.\n\n"
        f"**Alert update:** Alert dismissal/state change is a separate lane and must be gated independently."
    )

    plan_id = _sha256_text(f"pr_plan:{alert}:{sha}")

    report: dict[str, Any] = {
        "schema_version": "rig.github.code_scanning_pr_creation_plan.v1",
        "plan_id": plan_id,
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "status": status,
        "source_candidate_diff_receipt_path": str(candidate_diff_path),
        "source_candidate_diff_receipt_sha256": _sha256_file(candidate_diff_path)
        if candidate_diff_path.exists()
        else None,
        "diff_artifact_path": diff_artifact_path_str,
        "diff_artifact_sha256": receipt.get("diff_sha256"),
        "diff_classification": receipt.get("diff_classification"),
        "source_context_hash": receipt.get("source_context_hash"),
        "alert_identity": alert,
        "severity": sev,
        "rule_id_hash": receipt.get("rule_id_hash"),
        "repository_identity": "from_source_context",
        "proposed_branch_name": branch_name,
        "proposed_commit_title": commit_title if gates_ok else "",
        "proposed_pr_title": pr_title if gates_ok else "",
        "proposed_pr_body_summary": pr_body if gates_ok else "",
        "required_permissions_future": _FUTURE_PERMISSIONS,
        "permissions_used_this_slice": [],
        "remote_mutation": False,
        "local_mutation": False,
        "alert_update_deferred": True,
        "approval_chain": [
            "1. candidate diff receipt verified",
            "2. PR plan receipt verified",
            "3. human approval or configured policy approval",
            "4. branch creation allowed",
            "5. commit allowed",
            "6. PR creation allowed",
            "7. alert update remains separate (later gate)",
        ],
        "rollback_strategy": "close PR if rejected; delete branch if unmerged",
        "blocked_reasons": blocked,
        "pr_body_content_light": True,
        "redaction_status": {
            "content_light": True,
            "forbidden_fields_present": False,
            "raw_source_in_plan": False,
        },
        "recommended_next_slice": "Phase 2 Slice 8 — actual PR creation (gated)"
        if gates_ok
        else "Phase 2 Slice 6 — produce real candidate diff first",
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


def write_code_scanning_pr_plan(
    output_path: Path = _DEFAULT_OUTPUT,
    *,
    candidate_diff_path: Path = _DEFAULT_CANDIDATE_DIFF,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    report = build_code_scanning_pr_plan(
        candidate_diff_path=candidate_diff_path, generated_at_utc=generated_at_utc
    )
    _write_json(output_path, report)
    return report


__all__ = ["PrPlanError", "build_code_scanning_pr_plan", "write_code_scanning_pr_plan"]
