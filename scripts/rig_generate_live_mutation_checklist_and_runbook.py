#!/usr/bin/env python3
"""Generate Workstream A (Operator Checklist) and B (Runbook) artifacts.

Reads existing artifacts for hashes. Writes JSON only.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import uuid

REPO_ROOT = Path(__file__).resolve().parent.parent

CHECKLIST_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_live_mutation_operator_checklist_v1.v1.json"
)
RUNBOOK_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_live_mutation_runbook_v1.v1.json"
)
RUNBOOK_MD_OUTPUT = REPO_ROOT / "docs" / "github_live_mutation_runbook.md"

CANDIDATE_DIFF_PATH = (
    REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "code_scanning_dry_run_candidate_diff_v1.v1.json"
)


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _deterministic_uuid(seed: str) -> str:
    ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    return str(uuid.uuid5(ns, seed))


def _read_candidate_diff_hash() -> str:
    data = _load_json(CANDIDATE_DIFF_PATH)
    if data is None:
        return ""
    return data.get("diff_sha256", "")


def _build_target_paths_summary() -> list[str]:
    return [
        "[file_path_unknown]",
        "file_path_hash=080e04a484e9a0f65c08b7fd6f257990d2534ba0d7de1a1dc38c7dccb9c20b26",
    ]


def _build_target_paths_hashes(target_paths: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for p in target_paths:
        full = REPO_ROOT / p
        if full.is_file():
            result[p] = _sha256_file(full)
        else:
            result[p] = ""
    return result


def build_operator_checklist() -> dict:
    candidate_diff_hash = _read_candidate_diff_hash()
    target_paths = _build_target_paths_summary()
    generated_at = _now_iso()
    operation_seed = f"rig-relay::code-scanning-fix-001::{generated_at}"

    return {
        "checklist_id": _deterministic_uuid(f"checklist::{operation_seed}"),
        "schema_version": "rig.github.live_mutation_operator_checklist.v1",
        "generated_at": generated_at,
        "target_repository_safe_id": "rig-relay",
        "base_branch": "main",
        "proposed_branch": "rig/security/code-scanning-fix-001",
        "branch_prefix_requirement": "rig/security/",
        "target_paths_summary": [
            "[file_path_unknown]",
            "file_path_hash=080e04a484e9a0f65c08b7fd6f257990d2534ba0d7de1a1dc38c7dccb9c20b26",
        ],
        "target_paths_hashes": _build_target_paths_hashes(target_paths),
        "candidate_diff_hash": candidate_diff_hash,
        "candidate_diff_source_artifact": (
            "docs/json/governance/code_scanning_dry_run_candidate_diff_v1.v1.json"
        ),
        "operation_idempotency_key": _deterministic_uuid(
            f"idempotency::{operation_seed}"
        ),
        "required_env_flags": [
            "RIG_LIVE_MUTATION=1",
            "RIG_GITHUB_AUTH_TOKEN=<from-token-store>",
        ],
        "required_cli_flags": [
            "--execute-remote",
            "--branch",
            "rig/security/code-scanning-fix-001",
            "--gates-approved",
        ],
        "required_permissions": [
            {
                "permission": "pull_requests:write",
                "scope": "repository",
                "required_for": "PR creation",
                "status": "not_granted",
            },
            {
                "permission": "contents:write",
                "scope": "repository",
                "required_for": "file write on new branch",
                "status": "not_granted",
            },
        ],
        "readiness_gates": [
            {
                "gate_id": "phase2_rc_gates_passed",
                "description": "Phase 2 RC gates are all passed",
                "status": "pending",
                "evidence_path": "docs/json/release_gate/rc_readiness_gate.v1.json",
            },
            {
                "gate_id": "phase3_rc_gates_passed",
                "description": "Phase 3 RC gates are all passed",
                "status": "pending",
                "evidence_path": "docs/json/release_gate/rc_readiness_gate.v1.json",
            },
            {
                "gate_id": "preflight_completed",
                "description": "Live mutation preflight has completed successfully",
                "status": "pending",
                "evidence_path": "docs/json/governance/github_live_mutation_preflight_v1.v1.json",
            },
            {
                "gate_id": "permissions_verified",
                "description": "Required GitHub App permissions are verified active",
                "status": "pending",
                "evidence_path": "docs/json/governance/github_live_mutation_phase3_permission_boundary_audit_v1.v1.json",
            },
            {
                "gate_id": "branch_safety_check",
                "description": "Proposed branch does not collide with existing branches",
                "status": "pending",
                "evidence_path": "",
            },
            {
                "gate_id": "path_safety_check",
                "description": "Target paths are safe (no workflow files, no default branch overwrite)",
                "status": "pending",
                "evidence_path": "",
            },
            {
                "gate_id": "rate_limit_check",
                "description": "GitHub API rate limits are not near exhaustion",
                "status": "pending",
                "evidence_path": "docs/json/governance/github_live_mutation_rate_limit_snapshot_v1.v1.json",
            },
            {
                "gate_id": "idempotency_check",
                "description": "Operation idempotency key has not been previously executed",
                "status": "pending",
                "evidence_path": "",
            },
            {
                "gate_id": "approval_gate",
                "description": "Human operator approval is recorded",
                "status": "pending",
                "evidence_path": "",
            },
        ],
        "operator_acknowledgements": [
            "I acknowledge this operation will create a real branch on the remote repository.",
            "I acknowledge this operation will commit file changes to a remote branch via --execute-remote.",
            "I acknowledge this operation will create a real pull request with a visible diff.",
            "I acknowledge this operation requires `contents:write` and `pull_requests:write` GitHub App permissions.",
            "I acknowledge rate limits are monitored and the operation degrades gracefully on exhaustion.",
            "I acknowledge the alert state update/dismissal is explicitly deferred to post-merge validation.",
            "I acknowledge this operation produces a content-light attestation receipt with no raw secrets, tokens, or vulnerable code.",
            "I acknowledge the rollback path is: delete the created branch, close the PR without merging. Operation receipt remains as canonical evidence.",
        ],
        "explicitly_deferred_actions": [
            "alert_dismissal",
            "alert_state_update",
            "pr_merge",
            "workflow_file_edit",
            "branch_deletion",
        ],
        "forbidden_actions": [
            "force_push",
            "direct_main_write",
            "skip_approval",
            "skip_idempotency_check",
        ],
        "rollback_guidance_summary": (
            "Delete the created branch (rig/security/code-scanning-fix-001). "
            "Close the PR without merging. "
            "Operation receipt remains as canonical evidence."
        ),
        "next_safe_action": (
            "Review operator checklist, confirm all gates pass, "
            "then execute with --execute-remote --gates-approved"
        ),
        "redaction_status": "content_light",
        "raw_payloads_exposed": False,
    }


def build_runbook() -> dict:
    generated_at = _now_iso()
    return {
        "schema_version": "rig.github.live_mutation_runbook.v1",
        "generated_at": generated_at,
        "purpose": (
            "Prepare and execute the first real rig-relay live pull request mutation "
            "for a code scanning alert fix."
        ),
        "prerequisites": [
            "Phase 2 RC gates passed (ref: docs/json/release_gate/rc_readiness_gate.v1.json)",
            "Phase 3 RC gates passed (ref: docs/json/release_gate/rc_readiness_gate.v1.json)",
            "GitHub App installed on target repository with contents:write and pull_requests:write permissions",
            "Live mutation preflight completed successfully",
            "Operator checklist reviewed and all gates passed",
            "API token stored in ~/.rig/relay/.env",
            "Rate limit snapshot confirms headroom",
        ],
        "environment_variables": [
            {
                "name": "RIG_LIVE_MUTATION",
                "description": "Master gate flag; must be set to 1 to enable any remote mutation",
                "required": True,
                "example": "1",
            },
            {
                "name": "RIG_GITHUB_AUTH_TOKEN",
                "description": "GitHub personal access token or installation token",
                "required": True,
                "example": "<from-token-store>",
            },
            {
                "name": "RIG_LIVE_AUTH_TESTS",
                "description": "Enables live auth verification probes",
                "required": True,
                "example": "1",
            },
            {
                "name": "RIG_GITHUB_PERMISSION_MODE",
                "description": "Permission mode (read_only, write, admin)",
                "required": False,
                "example": "write",
            },
        ],
        "cli_commands": {
            "dry_run": (
                "uv run python scripts/rig_github_security_packet_execution.py "
                "  --plan-json docs/json/governance/github_security_packet_runner_plan_v1.v1.json "
                "  --output-json docs/json/governance/github_security_packet_execution_v1.v1.json "
                "  --limit 1 --summary"
            ),
            "simulate": (
                "uv run python scripts/rig_github_security_packet_execution.py "
                "  --plan-json docs/json/governance/github_security_packet_runner_plan_v1.v1.json "
                "  --output-json docs/json/governance/github_security_packet_execution_v1.v1.json "
                "  --limit 1"
            ),
            "live_execution": (
                "RIG_LIVE_MUTATION=1 RIG_LIVE_AUTH_TESTS=1 "
                "RIG_GITHUB_PERMISSION_MODE=write "
                "uv run python scripts/rig_github_security_packet_execution.py "
                "  --plan-json docs/json/governance/github_security_packet_runner_plan_v1.v1.json "
                "  --output-json docs/json/governance/github_security_packet_execution_v1.v1.json "
                "  --limit 1 --summary"
            ),
            "verify": (
                "uv run python scripts/rig_github_security_lifecycle_replay.py --summary"
            ),
        },
        "gate_checklist": [
            {
                "gate": "RC Phase 2 gates passed",
                "command_to_verify": (
                    "uv run python scripts/rig_release_gate_validate.py"
                ),
                "expected_result": "All Phase 2 gates PASSED",
            },
            {
                "gate": "RC Phase 3 gates passed",
                "command_to_verify": (
                    "uv run python scripts/rig_release_gate_validate.py"
                ),
                "expected_result": "All Phase 3 gates PASSED",
            },
            {
                "gate": "Preflight ready",
                "command_to_verify": (
                    "cat docs/json/governance/github_live_mutation_preflight_v1.v1.json "
                    '| uv run python -c "import json,sys; d=json.load(sys.stdin); '
                    "print(d.get('status',''))\""
                ),
                "expected_result": "ready_for_live_mutation_review",
            },
            {
                "gate": "Permissions verified",
                "command_to_verify": (
                    "cat docs/json/governance/github_live_mutation_phase3_permission_boundary_audit_v1.v1.json "
                    '| uv run python -c "import json,sys; d=json.load(sys.stdin); '
                    "print(d.get('gates_passed',''))\""
                ),
                "expected_result": "True",
            },
            {
                "gate": "Rate limit headroom",
                "command_to_verify": (
                    "cat docs/json/governance/github_live_mutation_rate_limit_snapshot_v1.v1.json "
                    '| uv run python -c "import json,sys; d=json.load(sys.stdin); '
                    "print(d.get('rate_limited',''))\""
                ),
                "expected_result": "False",
            },
            {
                "gate": "Operator checklist signed",
                "command_to_verify": (
                    "cat docs/json/governance/github_live_mutation_operator_checklist_v1.v1.json "
                    '| uv run python -c "import json,sys; d=json.load(sys.stdin); '
                    "acks=d.get('operator_acknowledgements',[]); print(len(acks)==8)\""
                ),
                "expected_result": "True",
            },
            {
                "gate": "Dry-run candidate diff exists",
                "command_to_verify": (
                    "cat docs/json/governance/code_scanning_dry_run_candidate_diff_v1.v1.json "
                    '| uv run python -c "import json,sys; d=json.load(sys.stdin); '
                    "print(d.get('diff_sha256','')[:8])\""
                ),
                "expected_result": "Non-empty hash prefix",
            },
        ],
        "expected_artifacts": [
            {
                "artifact_path": (
                    "docs/json/governance/github_live_mutation_operator_checklist_v1.v1.json"
                ),
                "purpose": "Operator checklist — must be reviewed before execution",
                "required": True,
            },
            {
                "artifact_path": (
                    "docs/json/governance/github_live_mutation_preflight_v1.v1.json"
                ),
                "purpose": "Preflight probe results — gates permission and rate limit status",
                "required": True,
            },
            {
                "artifact_path": (
                    "docs/json/governance/github_live_mutation_phase3_permission_boundary_audit_v1.v1.json"
                ),
                "purpose": "Permission boundary audit — verifies required scopes are active",
                "required": True,
            },
            {
                "artifact_path": (
                    "docs/json/governance/code_scanning_dry_run_candidate_diff_v1.v1.json"
                ),
                "purpose": "Dry-run candidate diff — the proposed change being promoted to live",
                "required": True,
            },
            {
                "artifact_path": (
                    "docs/json/governance/github_live_mutation_rate_limit_snapshot_v1.v1.json"
                ),
                "purpose": "Rate limit snapshot — confirms headroom before mutation",
                "required": True,
            },
            {
                "artifact_path": (
                    "docs/json/governance/github_security_lifecycle_replay_v1.v1.json"
                ),
                "purpose": "Lifecycle replay — end-to-end dry-run before live promotion",
                "required": True,
            },
        ],
        "expected_github_operations": [
            "create_branch",
            "commit_file_change",
            "create_pull_request",
        ],
        "expected_blocked_states": [
            {
                "state": "preflight_blocked",
                "reason": "One or more preflight gates failed (permissions, rate limit, branch collision)",
                "resolution": "Resolve the failing gate and re-run preflight before proceeding",
            },
            {
                "state": "rate_limit_exhaustion",
                "reason": "GitHub API rate limit near or at exhaustion",
                "resolution": "Wait for rate limit reset window. Re-run rate limit snapshot.",
            },
            {
                "state": "permission_denied",
                "reason": "Required GitHub App permissions not granted or token expired",
                "resolution": "Re-install GitHub App or refresh token. Re-run permission boundary audit.",
            },
            {
                "state": "branch_collision",
                "reason": "Proposed branch name already exists on remote",
                "resolution": "Choose a new branch name or delete the stale branch if safe.",
            },
            {
                "state": "idempotency_collision",
                "reason": "Operation idempotency key already recorded as executed",
                "resolution": "Review the previous execution receipt. If intentional re-execution, generate new idempotency key.",
            },
        ],
        "success_criteria": [
            "Remote branch rig/security/code-scanning-fix-001 created on the target repository",
            "File change committed to the remote branch with correct diff contents",
            "Pull request opened with title referencing code scanning alert fix",
            "Operation receipt generated and persisted to docs/json/governance/",
            "No secrets, tokens, or raw vulnerable code present in any persisted artifact",
            "Rate limits not exhausted by the operation",
            "Alert state explicitly documented as deferred (not dismissed, not fixed)",
        ],
        "rollback_steps": [
            {
                "step": 1,
                "command": (
                    "gh pr close <PR_NUMBER> --comment "
                    '"Rollback: per operator checklist rollback procedure."'
                ),
                "description": "Close the pull request without merging",
            },
            {
                "step": 2,
                "command": "git push origin --delete rig/security/code-scanning-fix-001",
                "description": "Delete the created remote branch",
            },
            {
                "step": 3,
                "command": (
                    "Ensure operation receipt at "
                    "docs/json/governance/github_code_scanning_pr_operation_receipt_v1.v1.json "
                    "is preserved with rollback annotation"
                ),
                "description": "Preserve operation receipt as canonical evidence",
            },
        ],
        "post_review_steps": [
            "Review the pull request diff for correctness and unintended changes",
            "Confirm the branch prefix matches rig/security/",
            "Verify no workflow files (.github/workflows/) were modified",
            "Verify no default branch write occurred",
            "Check that the operation receipt is content-light (no secrets, tokens, raw code)",
            "Document the alert state deferral reason in the PR body",
            "Schedule alert state update for post-merge validation lane",
        ],
        "alert_deferred_explanation": (
            "Code scanning alert state update/dismissal requires separate "
            "security_events:write permission and is deferred to post-merge validation."
        ),
        "troubleshooting": [
            {
                "issue": "RIG_LIVE_MUTATION=1 not recognized",
                "cause": "Environment variable not exported or shell session not refreshed",
                "resolution": "Re-export: export RIG_LIVE_MUTATION=1. Verify: echo $RIG_LIVE_MUTATION.",
            },
            {
                "issue": "HTTP 401 or 403 on API calls",
                "cause": "Token expired, invalid, or missing required permissions",
                "resolution": "Refresh token. Re-run permission boundary audit. Check GitHub App installation.",
            },
            {
                "issue": "HTTP 429 rate limit exceeded",
                "cause": "API rate limit exhausted",
                "resolution": "Check X-RateLimit-Reset header. Wait for reset window. Re-run rate limit snapshot.",
            },
            {
                "issue": "Branch already exists (HTTP 422)",
                "cause": "Proposed branch name collision with existing remote branch",
                "resolution": "Verify branch safety. Delete stale branch if safe, or choose new branch name.",
            },
            {
                "issue": "Diff does not apply cleanly",
                "cause": "Base branch has diverged from the expected SHA",
                "resolution": "Re-run dry-run candidate diff generation against current base branch HEAD.",
            },
        ],
        "rate_limit_handling": (
            "GitHub API rate limits are monitored via event fabric. "
            "Near-exhaustion triggers polling cadence reduction. "
            "Exhaustion triggers graceful degradation."
        ),
        "privacy_posture": (
            "No raw file contents, tokens, or secrets in operation receipts. "
            "Content-light evidence only."
        ),
        "stop_conditions": [
            "Any readiness gate returns 'blocked'",
            "Rate limit snapshot shows rate_limited=True",
            "Permission boundary audit shows required permission not_granted",
            "Preflight status is not ready_for_live_mutation_review",
            "Operator checklist has not been fully acknowledged",
            "Idempotency key collision detected (operation already executed)",
            "Branch safety check fails (proposed branch exists on remote)",
        ],
    }


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _generate_markdown_runbook(data: dict) -> str:
    lines = [
        "# GitHub Live Mutation Runbook",
        "",
        f"**Schema version:** `{data['schema_version']}`",
        f"**Generated at:** `{data['generated_at']}`",
        "",
        "## Purpose",
        "",
        data["purpose"],
        "",
        "## Prerequisites",
        "",
    ]
    for p in data["prerequisites"]:
        lines.append(f"- {p}")
    lines.extend([
        "",
        "## Environment Variables",
        "",
        "| Name | Description | Required | Example |",
        "|------|-------------|----------|---------|",
    ])
    for ev in data["environment_variables"]:
        req = "Yes" if ev["required"] else "No"
        lines.append(
            f"| `{ev['name']}` | {ev['description']} | {req} | `{ev['example']}` |"
        )
    lines.extend([
        "",
        "## CLI Commands",
        "",
        "### Dry-run",
        "",
        "```bash",
        data["cli_commands"]["dry_run"],
        "```",
        "",
        "### Simulate (fake boundary)",
        "",
        "```bash",
        data["cli_commands"]["simulate"],
        "```",
        "",
        "### Live Execution",
        "",
        "```bash",
        data["cli_commands"]["live_execution"],
        "```",
        "",
        "### Verify",
        "",
        "```bash",
        data["cli_commands"]["verify"],
        "```",
        "",
        "## Gate Checklist",
        "",
    ])
    for g in data["gate_checklist"]:
        lines.append(f"### {g['gate']}")
        lines.append(f"- **Command:** `{g['command_to_verify']}`")
        lines.append(f"- **Expected:** {g['expected_result']}")
        lines.append("")
    lines.extend(["## Expected Artifacts", ""])
    for a in data["expected_artifacts"]:
        lines.append(
            f"- `{a['artifact_path']}` — {a['purpose']} {'(required)' if a['required'] else '(optional)'}"
        )
    lines.extend(["", "## Expected GitHub Operations", ""])
    for op in data["expected_github_operations"]:
        lines.append(f"- {op}")
    lines.extend(["", "## Blocked States", ""])
    for bs in data["expected_blocked_states"]:
        lines.append(f"- **{bs['state']}**: {bs['reason']} → {bs['resolution']}")
    lines.extend(["", "## Success Criteria", ""])
    for sc in data["success_criteria"]:
        lines.append(f"- {sc}")
    lines.extend(["", "## Rollback Steps", ""])
    for rs in data["rollback_steps"]:
        lines.append(f"{rs['step']}. **{rs['description']}**")
        lines.append("   ```bash")
        lines.append(f"   {rs['command']}")
        lines.append("   ```")
    lines.extend(["", "## Post-Review Steps", ""])
    for pr in data["post_review_steps"]:
        lines.append(f"- {pr}")
    lines.extend([
        "",
        "## Alert Deferred Explanation",
        "",
        data["alert_deferred_explanation"],
        "",
        "## Troubleshooting",
        "",
    ])
    for t in data["troubleshooting"]:
        lines.append(f"- **{t['issue']}**: {t['cause']} → {t['resolution']}")
    lines.extend([
        "",
        "## Rate Limit Handling",
        "",
        data["rate_limit_handling"],
        "",
        "## Privacy Posture",
        "",
        data["privacy_posture"],
        "",
        "## Stop Conditions",
        "",
    ])
    for sc in data["stop_conditions"]:
        lines.append(f"- {sc}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    print(f"Building operator checklist → {CHECKLIST_OUTPUT}")
    checklist = build_operator_checklist()
    _write_json(CHECKLIST_OUTPUT, checklist)
    print(f"  checklist_id: {checklist['checklist_id']}")
    print(f"  candidate_diff_hash: {checklist['candidate_diff_hash'][:12]}...")

    print(f"Building runbook → {RUNBOOK_OUTPUT}")
    runbook = build_runbook()
    _write_json(RUNBOOK_OUTPUT, runbook)

    print(f"Generating Markdown runbook → {RUNBOOK_MD_OUTPUT}")
    md_content = _generate_markdown_runbook(runbook)
    RUNBOOK_MD_OUTPUT.write_text(md_content, encoding="utf-8")
    print("  Done.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
