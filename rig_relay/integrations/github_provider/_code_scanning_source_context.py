"""Code Scanning Source Context Acquisition v1 — read-only, gated, content-light.

Acquires safe source context for the selected code scanning alert.
Default: blocked (no live access). Gated live: RIG_LIVE_AUTH_TESTS=1 + token.
Raw source content never enters canonical JSON. Only hashes, metadata, safe summaries.
"""

from __future__ import annotations

import hashlib
import json
import os
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
    / "github_code_scanning_source_context_v1.v1.json"
)

_LIVE_AUTH_ENV = "RIG_LIVE_AUTH_TESTS"

_ENDPOINTS_MODELED = [
    {
        "endpoint_family": "code_scanning_alert",
        "method": "GET",
        "route": "/repos/{owner}/{repo}/code-scanning/alerts/{alert_number}",
        "permission": "security_events:read",
        "purpose": "retrieve alert context including most_recent_instance",
    },
    {
        "endpoint_family": "code_scanning_alert_instances",
        "method": "GET",
        "route": "/repos/{owner}/{repo}/code-scanning/alerts/{alert_number}/instances",
        "permission": "security_events:read",
        "purpose": "retrieve alert instance details",
    },
    {
        "endpoint_family": "repo_contents",
        "method": "GET",
        "route": "/repos/{owner}/{repo}/contents/{path}",
        "permission": "contents:read",
        "purpose": "retrieve affected source file content",
    },
]

_FORBIDDEN_CONTEXT = frozenset({
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


class SourceContextError(Exception):
    """Raised when source context acquisition fails."""


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


def _is_live_gate_passed() -> bool:
    return os.environ.get(_LIVE_AUTH_ENV, "0") == "1"


def build_code_scanning_source_context(
    *,
    proposal_path: Path = _DEFAULT_PROPOSAL,
    generated_at_utc: str | None = None,
    allow_live: bool = False,
    access_token: str = "",
) -> dict[str, Any]:
    proposal = _load_json(proposal_path)
    if proposal is None:
        raise SourceContextError(f"Patch proposal not found: {proposal_path}")

    alert_number = proposal.get("alert_number")
    rule_hash = proposal.get("rule_id_hash")
    file_hashes = proposal.get("affected_path_hashes", [])
    file_hash = file_hashes[0] if file_hashes else None
    sev = proposal.get("severity", "unknown")

    live_gate = _is_live_gate_passed()
    live_attempted = False
    live_allowed = allow_live and live_gate and bool(access_token)

    if live_allowed:
        live_attempted = True

    context_status = "blocked_source_context_unavailable"
    acquisition_mode = "no_live_access"
    if live_attempted:
        acquisition_mode = "live_api_gated"

    safe_context_available = False
    unsafe_reasons: list[str] = [
        "no_live_api_access",
        "RIG_LIVE_AUTH_TESTS_not_set",
        "source_file_not_locally_accessible",
    ]
    if live_attempted:
        unsafe_reasons.append("live_api_not_yet_implemented")

    # Alert instance summary — from metadata only, never raw content
    alert_summary: dict[str, Any] = {
        "alert_number": alert_number,
        "severity": sev,
        "rule_id_hash": rule_hash,
        "has_most_recent_instance_data": False,
        "instance_accessible": False,
    }

    # Source file summary — from metadata only
    source_summary: dict[str, Any] = {
        "file_path_hash": file_hash,
        "file_accessible": False,
        "contents_read_permission_needed": True,
        "contents_read_granted": False,
    }

    # Source slice — empty/no content, metadata only
    source_slice: dict[str, Any] = {
        "slice_available": False,
        "slice_path_hash": file_hash,
        "slice_sha256": None,
        "slice_byte_count": None,
        "slice_line_count": None,
        "slice_redaction_scan": None,
        "raw_slice_persisted": False,
    }

    context_hashes: dict[str, Any] = {
        "alert_instance_hash": None,
        "file_content_hash": None,
        "source_slice_hash": None,
    }

    report: dict[str, Any] = {
        "schema_version": "rig.github.code_scanning_source_context.v1",
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "source_queue_artifact": proposal.get("source_queue_artifact", ""),
        "source_remediation_plan_artifact": proposal.get(
            "source_remediation_plan_artifact", ""
        ),
        "source_patch_proposal_artifact": str(proposal_path),
        "source_patch_preview_artifact": str(
            _REPO_ROOT
            / "docs"
            / "json"
            / "governance"
            / "github_code_scanning_patch_preview_v1.v1.json"
        ),
        "selected_alert_number": alert_number,
        "selected_alert_identifier_hash": proposal.get("alert_identifier_hash"),
        "rule_id_hash": rule_hash,
        "file_path_hash": file_hash,
        "source_context_status": context_status,
        "acquisition_mode": acquisition_mode,
        "live_api_attempted": live_attempted,
        "live_api_gate_status": {
            "RIG_LIVE_AUTH_TESTS_set": live_gate,
            "token_provided": bool(access_token),
            "live_allowed": live_allowed,
            "live_skipped_reason": "default_no_live_access"
            if not allow_live
            else ("RIG_LIVE_AUTH_TESTS_not_set" if not live_gate else "no_token"),
        },
        "endpoints_modeled_or_called": [
            {
                "endpoint_family": e["endpoint_family"],
                "method": e["method"],
                "permission": e["permission"],
                "called": False,
                "purpose": e["purpose"],
            }
            for e in _ENDPOINTS_MODELED
        ],
        "permissions_required": {
            "read": ["security_events:read", "metadata:read", "contents:read"],
            "mutation_later": [
                "contents:write",
                "pull_requests:write",
                "security_events:write",
            ],
        },
        "alert_instance_summary": alert_summary,
        "source_file_summary": source_summary,
        "source_slice_summary": source_slice,
        "context_hashes": context_hashes,
        "safe_context_available": safe_context_available,
        "unsafe_context_reasons": unsafe_reasons,
        "redaction_status": {
            "content_light": True,
            "forbidden_fields_present": False,
            "redaction_rules": len(_FORBIDDEN_CONTEXT),
            "raw_source_content_present": False,
            "raw_response_body_present": False,
        },
        "content_light_status": "context_content_light",
        "local_mutation_status": "disabled",
        "remote_mutation_status": "disabled",
        "recommended_next_slice": (
            "Phase 2 Slice 6 — generate actual dry-run candidate diff "
            "from acquired source context"
        ),
    }

    _assert_context_content_light(report)
    return report


def _assert_context_content_light(data: dict[str, Any]) -> None:
    serialized = json.dumps(data, sort_keys=True)
    for key in _FORBIDDEN_CONTEXT:
        if f'"{key}"' in serialized:
            raise ValueError(f"forbidden_key_in_context: {key}")
    for p in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "ghr_",
        "github_pat_",
        "BEGIN PRIVATE KEY",
    ):
        if p in serialized:
            raise ValueError(f"forbidden_pattern_in_context: {p}")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_code_scanning_source_context(
    output_path: Path = _DEFAULT_OUTPUT,
    *,
    proposal_path: Path = _DEFAULT_PROPOSAL,
    generated_at_utc: str | None = None,
    allow_live: bool = False,
    access_token: str = "",
) -> dict[str, Any]:
    report = build_code_scanning_source_context(
        proposal_path=proposal_path,
        generated_at_utc=generated_at_utc,
        allow_live=allow_live,
        access_token=access_token,
    )
    _write_json(output_path, report)
    return report


__all__ = [
    "SourceContextError",
    "build_code_scanning_source_context",
    "write_code_scanning_source_context",
]
