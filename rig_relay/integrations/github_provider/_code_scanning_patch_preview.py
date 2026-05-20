"""Code Scanning Patch Preview v1 — governed, dry-run, candidate diff preview.

Generates a candidate diff preview artifact for the top code scanning alert.
Blocks honestly if source context is unavailable or unsafe. No fake diffs.
No patches applied, no PRs created, no alerts dismissed. All mutations disabled.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PROPOSAL = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_patch_proposal_v1.v1.json"
)
_DEFAULT_OUTPUT = (
    _REPO_ROOT
    / "docs"
    / "json"
    / "governance"
    / "github_code_scanning_patch_preview_v1.v1.json"
)
_DEFAULT_DIFF_PATH = (
    _REPO_ROOT
    / ".build"
    / "rig-relay"
    / "previews"
    / "code_scanning_patch_preview.diff"
)

_FORBIDDEN_PREVIEW = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "patch",
    "diff",
    "code_snippet",
    "vulnerable_code",
    "file_body",
    "auth_header",
    "bearer",
    "secret_value",
    "raw_secret",
    "source_content",
})


class PatchPreviewError(Exception):
    """Raised when patch preview building fails."""


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


def build_code_scanning_patch_preview(
    *, proposal_path: Path = _DEFAULT_PROPOSAL, generated_at_utc: str | None = None
) -> dict[str, Any]:
    proposal = _load_json(proposal_path)
    if proposal is None:
        raise PatchPreviewError(f"Patch proposal not found: {proposal_path}")

    alert_number = proposal.get("alert_number")
    rule_hash = proposal.get("rule_id_hash")
    file_hashes = proposal.get("affected_path_hashes")
    sev = proposal.get("severity", "unknown")

    source_context_available = False  # no live repo access, no raw source content
    unsafe_to_generate_diff = True

    _safe = source_context_available and not unsafe_to_generate_diff

    # Build the preview
    preview_status = "blocked_no_source_context"
    diff_path: str | None = None
    diff_sha256: str | None = None
    diff_bytes: int | None = None
    diff_line_count: int | None = None
    diff_content_classification = "not_generated"
    blocked_reasons: list[str] = []

    if not source_context_available:
        blocked_reasons.append("source_context_unavailable")
        blocked_reasons.append("raw_source_file_not_accessible")
    if unsafe_to_generate_diff:
        blocked_reasons.append("unsafe_to_generate_diff")
        blocked_reasons.append("live_repo_access_deferred")
        blocked_reasons.append(
            "code_fix_generation_requires_live_API_or_safe_local_mirror"
        )

    # Generate a deterministic blocked preview diff file
    _DEFAULT_DIFF_PATH.parent.mkdir(parents=True, exist_ok=True)
    diff_content = (
        "# Code Scanning Patch Preview — BLOCKED\n"
        "# Source context unavailable: no live repo access, no raw file contents accessible.\n"
        "# Cannot generate a candidate diff without source code context.\n"
        "# Blocked reasons:\n"
        + "".join(f"#   - {r}\n" for r in blocked_reasons)
        + f"# Alert: {alert_number}\n"
        f"# Severity: {sev}\n"
        f"# Rule hash: {rule_hash}\n"
        f"# File path hashes: {', '.join(file_hashes) if file_hashes else 'N/A'}\n"
    )
    _DEFAULT_DIFF_PATH.write_text(diff_content, encoding="utf-8")

    diff_path = str(_DEFAULT_DIFF_PATH)
    diff_sha256 = _sha256_file(_DEFAULT_DIFF_PATH)
    diff_bytes = _DEFAULT_DIFF_PATH.stat().st_size
    diff_line_count = len(diff_content.splitlines())
    diff_content_classification = "blocked_explanation_only"
    preview_status = "blocked_source_unavailable"

    # Proposed operations — all blocked
    proposed_operations = [
        {
            "operation_type": "inspect",
            "target_path_hash": file_hashes[0] if file_hashes else None,
            "mutation_required_later": False,
            "permission_required_later": "contents:read",
            "blocked_reason": "source_context_unavailable",
        },
        {
            "operation_type": "modify_candidate",
            "target_path_hash": file_hashes[0] if file_hashes else None,
            "mutation_required_later": True,
            "permission_required_later": "contents:write",
            "blocked_reason": "source_context_unavailable",
        },
        {
            "operation_type": "test_candidate",
            "target_path_hash": file_hashes[0] if file_hashes else None,
            "mutation_required_later": False,
            "permission_required_later": "none",
            "blocked_reason": "patch_not_generated",
        },
    ]

    report: dict[str, Any] = {
        "schema_version": "rig.github.code_scanning_patch_preview.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "source_queue_artifact": proposal.get("source_queue_artifact", ""),
        "source_remediation_plan_artifact": proposal.get(
            "source_remediation_plan_artifact", ""
        ),
        "source_patch_proposal_artifact": str(proposal_path),
        "selected_queue_item_id": proposal.get("selected_queue_item_id"),
        "selected_plan_id": proposal.get("selected_plan_id"),
        "selected_alert_identifier_hash": proposal.get("alert_identifier_hash"),
        "alert_number": alert_number,
        "severity": sev,
        "rule_id_hash": rule_hash,
        "file_path_hash": file_hashes[0] if file_hashes else None,
        "patch_preview_status": preview_status,
        "diff_preview_path": diff_path,
        "diff_preview_sha256": diff_sha256,
        "diff_preview_bytes": diff_bytes,
        "diff_preview_line_count": diff_line_count,
        "diff_content_classification": diff_content_classification,
        "proposed_operations": proposed_operations,
        "affected_file_summaries": [
            f"file_hash={h[:16]}..." for h in (file_hashes or [])
        ],
        "verification_plan": [
            "source_context_acquisition (live API or safe local mirror)",
            "rule context review from CodeQL alert metadata",
            "targeted unit/integration test for affected area once source available",
            "static analysis relevant to CodeQL rule category",
            "redaction scan on generated patch artifacts",
            "schema validation on any generated artifacts",
            "do_not_run_full_pytest",
        ],
        "permission_audit": {
            "read_for_context": [
                "security_events:read",
                "metadata:read",
                "contents:read",
            ],
            "mutation_later": [
                "contents:write",
                "pull_requests:write",
                "security_events:write",
            ],
            "none_used_in_this_slice": True,
        },
        "local_mutation_status": "disabled",
        "remote_mutation_status": "disabled",
        "pr_creation_status": "disabled",
        "alert_update_status": "disabled",
        "blocked_reasons": blocked_reasons,
        "redaction_status": {
            "content_light": True,
            "forbidden_fields_present": False,
            "redaction_rules": len(_FORBIDDEN_PREVIEW),
            "raw_code_snippets_present": False,
            "source_content_present": False,
            "diff_preview_redaction_clean": True,
        },
        "content_light_status": "preview_content_light",
        "human_review_required": True,
        "recommended_next_slice": (
            "Phase 2 Slice 5 — acquire source context (live API or local mirror), "
            "generate actual candidate diff, then proceed to PR plan"
        ),
    }

    _assert_preview_content_light(report)
    return report


def _assert_preview_content_light(data: dict[str, Any]) -> None:
    serialized = json.dumps(data, sort_keys=True)
    for key in _FORBIDDEN_PREVIEW:
        if f'"{key}"' in serialized:
            raise ValueError(f"forbidden_key_in_preview: {key}")
    for pattern in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "BEGIN PRIVATE KEY",
    ):
        if pattern in serialized:
            raise ValueError(f"forbidden_pattern_in_preview: {pattern}")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_code_scanning_patch_preview(
    output_path: Path = _DEFAULT_OUTPUT,
    *,
    proposal_path: Path = _DEFAULT_PROPOSAL,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    report = build_code_scanning_patch_preview(
        proposal_path=proposal_path, generated_at_utc=generated_at_utc
    )
    _write_json(output_path, report)
    return report


__all__ = [
    "PatchPreviewError",
    "build_code_scanning_patch_preview",
    "write_code_scanning_patch_preview",
]
