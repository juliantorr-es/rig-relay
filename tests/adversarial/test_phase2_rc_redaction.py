from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.github_provider._security_lifecycle_consolidation import (
    build_artifact_inventory,
    build_permission_boundary_audit,
    build_rc_report,
    build_replay,
)

pytestmark = [pytest.mark.adversarial]

REPO_ROOT = Path(__file__).resolve().parents[2]
GOV = REPO_ROOT / "docs" / "json" / "governance"

TOKEN_PATTERNS = (
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "github_pat_",
    "BEGIN PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "BEGIN EC PRIVATE KEY",
)

FORBIDDEN_FIELDS = (
    '"access_token"',
    '"authorization"',
    '"client_secret"',
    '"private_key"',
    '"api_key"',
    '"bearer_token"',
    '"secret_value"',
    '"raw_response"',
    '"raw_body"',
    '"raw_payload"',
)


def _all_artifact_snapshots() -> list[tuple[str, dict]]:
    snapshots: list[tuple[str, dict]] = []
    snapshots.append(("inventory", build_artifact_inventory()))
    snapshots.append(("replay", build_replay()))
    snapshots.append(("permission_audit", build_permission_boundary_audit()))
    snapshots.append(("rc_report", build_rc_report()))
    causal_path = GOV / "github_security_lifecycle_causal_report_v1.v1.json"
    if causal_path.exists():
        snapshots.append((
            "causal_report",
            json.loads(causal_path.read_text(encoding="utf-8")),
        ))
    return snapshots


def test_all_5_artifacts_have_no_token_like_strings():
    for name, data in _all_artifact_snapshots():
        s = json.dumps(data, sort_keys=True)
        for pat in TOKEN_PATTERNS:
            assert pat not in s, f"Token pattern '{pat}' found in {name}"


def test_all_5_artifacts_are_content_light():
    for name, data in _all_artifact_snapshots():
        if name == "causal_report":
            assert data.get("content_light") is True, f"{name} not content_light"
        else:
            assert data.get("content_light") is True, f"{name} not content_light"


def test_replay_has_no_raw_payload_exposure():
    replay = build_replay()
    s = json.dumps(replay, sort_keys=True)
    for f in FORBIDDEN_FIELDS:
        assert f not in s, f"Forbidden field '{f}' found in replay"


def test_causal_report_has_no_alert_resolution_from_pr_creation():
    causal_path = GOV / "github_security_lifecycle_causal_report_v1.v1.json"
    if not causal_path.exists():
        pytest.skip("Causal report not found")
    data = json.loads(causal_path.read_text(encoding="utf-8"))
    s = json.dumps(data, sort_keys=True)
    assert "pr causes alert" not in s.lower()
    assert "pr_creation_causes_alert_resolution" not in s


def test_permission_audit_has_no_credential_exposure():
    audit = build_permission_boundary_audit()
    s = json.dumps(audit, sort_keys=True)
    for f in FORBIDDEN_FIELDS:
        assert f not in s, f"Forbidden field '{f}' found in permission audit"
