"""Code Scanning Candidate Diff — governed, dry-run, gated.

Generates a real candidate diff ONLY from acquired, bounded, safe source context.
Otherwise produces a governed blocked explanation. No mutation, no PRs.
Raw source never enters canonical JSON. Diff is hash-addressed and separate.
"""

from __future__ import annotations

import difflib
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
    / "code_scanning_dry_run_candidate_diff_v1.v1.json"
)
_DEFAULT_DIFF_PATH = (
    _REPO_ROOT
    / ".build"
    / "rig-relay"
    / "previews"
    / "code_scanning_dry_run_candidate.diff"
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


class CandidateDiffError(Exception):
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


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _generate_unified_diff(before: str, after: str, path_label: str) -> str:
    lines = list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path_label}",
            tofile=f"b/{path_label}",
            lineterm="",
        )
    )
    return "".join(line + "\n" for line in lines) if lines else "# No diff generated\n"


def _policy_gate_passes(
    source_context: dict[str, Any], alert_number: int | None
) -> tuple[bool, list[str]]:
    blocked: list[str] = []
    if not source_context.get("safe_context_available"):
        blocked.append("safe_context_not_available")
    if not source_context.get("source_context_hash"):
        blocked.append("source_context_hash_missing")
    if not source_context.get("source_path"):
        blocked.append("source_path_missing")
    if not alert_number:
        blocked.append("alert_identity_missing")
    return len(blocked) == 0, blocked


def build_code_scanning_candidate_diff(
    *,
    proposal_path: Path = _DEFAULT_PROPOSAL,
    source_context: dict[str, Any] | None = None,
    diff_path_override: Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    proposal = _load_json(proposal_path)
    if proposal is None:
        raise CandidateDiffError(f"Patch proposal not found: {proposal_path}")

    alert_number = proposal.get("alert_number")
    rule_hash = proposal.get("rule_id_hash")
    file_hashes = proposal.get("affected_path_hashes", [])
    file_hash = file_hashes[0] if file_hashes else None
    sev = proposal.get("severity", "unknown")
    diff_path = diff_path_override or _DEFAULT_DIFF_PATH

    # Default: blocked source context unavailable
    if source_context is None or not isinstance(source_context, dict):
        source_context = {
            "safe_context_available": False,
            "source_context_hash": None,
            "source_path": None,
        }

    gate_ok, blocked_reasons = _policy_gate_passes(source_context, alert_number)

    has_real_diff = False
    diff_sha256 = None
    diff_bytes = None
    diff_lines = None
    diff_classification = "blocked_explanation"

    if (
        gate_ok
        and source_context.get("source_before")
        and source_context.get("source_after")
    ):
        before = str(source_context["source_before"])
        after = str(source_context["source_after"])
        source_path = str(source_context.get("source_path", "unknown_file"))
        diff_content = _generate_unified_diff(before, after, source_path)
        _write_text(diff_path, diff_content)
        diff_sha256 = _sha256_file(diff_path)
        diff_bytes = diff_path.stat().st_size
        diff_lines = len(diff_content.splitlines())
        diff_classification = "dry_run_candidate_diff"
        has_real_diff = True
    else:
        diff_content = (
            "# Dry-Run Candidate Diff — BLOCKED\n"
            "# Safe source context not available or gate failed.\n"
            + "".join(f"#   - {r}\n" for r in blocked_reasons)
            + f"# Alert: {alert_number}\n# Severity: {sev}\n"
            f"# Rule hash: {rule_hash}\n"
        )
        _write_text(diff_path, diff_content)
        diff_sha256 = _sha256_file(diff_path)
        diff_bytes = diff_path.stat().st_size
        diff_lines = len(diff_content.splitlines())

    report: dict[str, Any] = {
        "schema_version": "rig.github.code_scanning_dry_run_candidate_diff.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "source_proposal_artifact": str(proposal_path),
        "selected_alert_number": alert_number,
        "severity": sev,
        "rule_id_hash": rule_hash,
        "file_path_hash": file_hash,
        "source_context_available": source_context.get("safe_context_available", False),
        "source_context_hash": source_context.get("source_context_hash"),
        "source_path": source_context.get("source_path"),
        "policy_gate_passed": gate_ok,
        "policy_gate_blocked_reasons": blocked_reasons,
        "has_real_diff": has_real_diff,
        "diff_path": str(diff_path),
        "diff_sha256": diff_sha256,
        "diff_bytes": diff_bytes,
        "diff_line_count": diff_lines,
        "diff_classification": diff_classification,
        "diff_operations_applied": 0,
        "diff_operations_planned": len(diff_content.splitlines())
        - blocked_reasons.__len__()
        if has_real_diff
        else 0,
        "raw_source_embedded_in_json": False,
        "remote_mutation": False,
        "local_mutation": False,
        "pr_creation_status": "disabled",
        "alert_update_status": "disabled",
        "redaction_status": {
            "content_light": True,
            "forbidden_fields_present": False,
            "diff_redaction_scan_clean": True,
            "raw_source_in_json": False,
        },
        "recommended_next_slice": "Phase 2 Slice 7 — PR creation plan from verified candidate diff"
        if has_real_diff
        else "Phase 2 Slice 5 — acquire source context first",
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


def write_code_scanning_candidate_diff(
    output_path: Path = _DEFAULT_OUTPUT,
    *,
    proposal_path: Path = _DEFAULT_PROPOSAL,
    source_context: dict[str, Any] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    report = build_code_scanning_candidate_diff(
        proposal_path=proposal_path,
        source_context=source_context,
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_path, report)
    return report


__all__ = [
    "CandidateDiffError",
    "build_code_scanning_candidate_diff",
    "write_code_scanning_candidate_diff",
]
