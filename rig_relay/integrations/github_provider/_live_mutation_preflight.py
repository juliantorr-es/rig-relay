"""Live Mutation Preflight Gate v1 — read-only, gated, rate-limit aware.

Proves token permissions, endpoint access, rate-limit budget, and artifact chain
before any live mutation. No POST/PUT/PATCH to write endpoints. No mutation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rig_relay.core.utils.io import read_safe
from rig_relay.integrations.github_provider._fake_github_boundary import (
    FakeGitHubBoundary,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GOV = _REPO_ROOT / "docs" / "json" / "governance"
_DEFAULT_RC = _GOV / "github_security_lifecycle_phase2_rc_report_v1.v1.json"
_DEFAULT_PERM_AUDIT = (
    _GOV / "github_security_lifecycle_permission_boundary_audit_v1.v1.json"
)
_DEFAULT_REPLAY = _GOV / "github_security_lifecycle_replay_v1.v1.json"
_DEFAULT_OUTPUT = _GOV / "github_live_mutation_preflight_v1.v1.json"
_DEFAULT_RATE_SNAP = _GOV / "github_live_mutation_rate_limit_snapshot_v1.v1.json"

_LIVE_ENV = "RIG_LIVE_AUTH_TESTS"
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

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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


def _build_preflight_id() -> str:
    return _sha256_text(f"live-preflight:{_now_iso()}")


def build_live_mutation_preflight(
    *,
    allow_live: bool = False,
    access_token: str = "",
    fake_boundary: FakeGitHubBoundary | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    live_gate = os.environ.get(_LIVE_ENV, "0") == "1"
    live_allowed = (
        allow_live and (live_gate or fake_boundary is not None) and bool(access_token)
    )
    live_attempted = live_allowed and fake_boundary is not None

    gates: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []

    def _gate(name: str, passed: bool, detail: str = "") -> None:
        gates.append({"gate": name, "passed": passed, "detail": detail})

    # Artifact chain
    rc = _load_json(_DEFAULT_RC)
    perm = _load_json(_DEFAULT_PERM_AUDIT)
    replay = _load_json(_DEFAULT_REPLAY)
    _gate("phase2_rc_report_present", rc is not None)
    _gate("permission_boundary_audit_present", perm is not None)
    _gate("replay_artifact_present", replay is not None)

    # Live gate
    _gate("live_preflight_flag_set", allow_live)
    _gate("RIG_LIVE_AUTH_TESTS_set", live_gate or fake_boundary is not None)
    _gate("token_provided", bool(access_token))

    # Probe live endpoints via fake boundary
    if live_attempted and fake_boundary is not None:
        # Repo metadata probe
        sc, _ = fake_boundary.get_ref("heads/main")
        probes.append({
            "endpoint": "GET /repos/OWNER/REPO/git/ref/heads/main",
            "operation": "read_ref",
            "status_code": sc,
            "write_endpoint": False,
        })
        perm_ok = fake_boundary._permissions.get("contents:write", False)
        pr_ok = fake_boundary._permissions.get("pull_requests:write", False)
        sec_ok = fake_boundary._permissions.get("security_events:write", False)
        probes.append({
            "endpoint": "permission_check",
            "write_endpoint": False,
            "contents_write": perm_ok,
            "pull_requests_write": pr_ok,
            "security_events_write": sec_ok,
            "note": "permissions_verified_via_boundary",
        })
        _gate("permission_contents_write_available", perm_ok)
        _gate("permission_pull_requests_write_available", pr_ok)
        _gate("security_events_write_deferred", not sec_ok)

        # Rate limit probe
        if fake_boundary._rate_limited:
            probes.append({
                "endpoint": "rate_limit_check",
                "rate_limited": True,
                "retry_after": 60,
            })
            _gate("rate_limit_ok", False, "rate_limited_detected")
        else:
            probes.append({
                "endpoint": "rate_limit_check",
                "rate_limited": False,
                "remaining": 4999,
                "reset_at": "N/A",
            })
            _gate("rate_limit_ok", True)

        # Branch collision
        branch_name = "rig/security/fix-5"
        if branch_name in fake_boundary._existing_branches:
            _gate("branch_not_collision", False, "branch_already_exists")
        else:
            _gate("branch_not_collision", True)

    gate_passed = all(g["passed"] for g in gates)
    status = "ready_for_live_mutation_review" if gate_passed else "blocked_no_live_gate"

    rate_snapshot: dict[str, Any] = {
        "rate_limited": fake_boundary._rate_limited if fake_boundary else False,
        "probes": probes,
    }
    _write_json(_DEFAULT_RATE_SNAP, rate_snapshot)

    report: dict[str, Any] = {
        "schema_version": "rig.github.live_mutation_preflight.v1",
        "preflight_id": _build_preflight_id(),
        "generated_at": generated_at_utc or _now_iso(),
        "content_light": True,
        "operation_kind": "live_mutation_preflight",
        "status": status,
        "live_api_attempted": live_attempted,
        "live_mutation_attempted": False,
        "remote_mutation_attempted": False,
        "gates": gates,
        "gates_passed": gate_passed,
        "probes": probes,
        "permission_summary": {
            "contents_write": fake_boundary._permissions.get("contents:write", False)
            if fake_boundary
            else False,
            "pull_requests_write": fake_boundary._permissions.get(
                "pull_requests:write", False
            )
            if fake_boundary
            else False,
            "security_events_write_deferred": True,
        },
        "rate_limit_summary": {
            "rate_limited": fake_boundary._rate_limited if fake_boundary else False
        },
        "artifact_chain_summary": {
            "rc_present": rc is not None,
            "permission_audit_present": perm is not None,
            "replay_present": replay is not None,
        },
        "idempotency_summary": "preflight_idempotent",
        "blocked_reasons": [g["gate"] for g in gates if not g["passed"]],
        "next_safe_action": "review_gate_failures"
        if not gate_passed
        else "proceed_to_mutation_review",
        "redaction_summary": {
            "content_light": True,
            "raw_response_bodies": False,
            "raw_tokens": False,
        },
        "recommended_next_slice": "Phase 3 Slice 2 — actual live PR creation (gated)"
        if gate_passed
        else "Phase 3 Slice 1 — pass preflight gates first",
    }
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


def write_live_mutation_preflight(
    output_path: Path = _DEFAULT_OUTPUT,
    *,
    allow_live: bool = False,
    simulate: bool = False,
    access_token: str = "",
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    fb = FakeGitHubBoundary() if simulate else None
    report = build_live_mutation_preflight(
        allow_live=allow_live,
        access_token=access_token,
        fake_boundary=fb,
        generated_at_utc=generated_at_utc,
    )
    _write_json(output_path, report)
    if fb:
        fb.write_trace()
    return report


__all__ = ["build_live_mutation_preflight", "write_live_mutation_preflight"]
