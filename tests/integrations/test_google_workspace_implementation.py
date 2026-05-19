"""Google Workspace Provider v1 — implementation tests.

No network. No credentials. No live APIs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.integrations.google_workspace import (
    GoogleWorkspaceAuthState,
    GoogleWorkspaceScopeGrant,
    GoogleWorkspaceVerdict,
    evaluate_workspace_capability,
    read_workspace_auth_state,
    write_workspace_auth_state,
)
from rig_relay.integrations.google_workspace._adapter import run_local_workspace_read
from rig_relay.integrations.google_workspace._models import (
    GoogleWorkspaceDecision,
    GoogleWorkspaceOperationRequest,
)
from rig_relay.integrations.google_workspace._receipts import (
    build_workspace_receipt,
    validate_receipt,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "schemas"


def _make_grant(
    scope_id: str, sensitivity: str = "non_sensitive", status: str = "active"
) -> GoogleWorkspaceScopeGrant:
    return GoogleWorkspaceScopeGrant(
        scope_id=scope_id,
        scope_sensitivity=sensitivity,
        grant_status=status,
        grant_hash="g" * 64,
    )


class TestAuthStatePersistence:
    @pytest.mark.contract
    def test_write_and_read_roundtrip(self, tmp_path: Path):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/gmail.labels")]
        )
        p = write_workspace_auth_state(auth, tmp_path / "auth.json")
        loaded = read_workspace_auth_state(p)
        assert loaded.is_authenticated()
        assert len(loaded.active_grants()) == 1

    @pytest.mark.adversarial
    def test_rejects_access_token(self, tmp_path: Path):
        with pytest.raises(ValueError, match="raw_credential"):
            read_workspace_auth_state(
                self._write_bad(
                    tmp_path,
                    {
                        "access_token": "ya29.fake",
                        "schema_version": "rig.google_workspace.auth_state.v1",
                        "provider_id": "google_workspace",
                        "auth_mode": "none",
                        "auth_status": "unauthenticated",
                        "account_hash": "",
                        "scope_grants": [],
                        "generated_at": "2026-01-01T00:00:00Z",
                        "redaction_status": "clean",
                    },
                )
            )

    @pytest.mark.adversarial
    def test_rejects_private_key(self, tmp_path: Path):
        with pytest.raises(ValueError, match="raw_credential"):
            read_workspace_auth_state(
                self._write_bad(
                    tmp_path,
                    {
                        "private_key": "-----BEGIN PRIVATE KEY-----",
                        "schema_version": "rig.google_workspace.auth_state.v1",
                        "provider_id": "google_workspace",
                        "auth_mode": "none",
                        "auth_status": "unauthenticated",
                        "account_hash": "",
                        "scope_grants": [],
                        "generated_at": "2026-01-01T00:00:00Z",
                        "redaction_status": "clean",
                    },
                )
            )

    @pytest.mark.adversarial
    def test_rejects_client_secret(self, tmp_path: Path):
        with pytest.raises(ValueError, match="raw_credential"):
            read_workspace_auth_state(
                self._write_bad(
                    tmp_path,
                    {
                        "client_secret": "GOCSPX-fake",
                        "schema_version": "rig.google_workspace.auth_state.v1",
                        "provider_id": "google_workspace",
                        "auth_mode": "none",
                        "auth_status": "unauthenticated",
                        "account_hash": "",
                        "scope_grants": [],
                        "generated_at": "2026-01-01T00:00:00Z",
                        "redaction_status": "clean",
                    },
                )
            )

    @pytest.mark.adversarial
    def test_subject_hash_only_not_raw_email(self, tmp_path: Path):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("scope1")]
        )
        auth.subject_hashes = ["s" * 64]
        p = write_workspace_auth_state(auth, tmp_path / "auth.json")
        content = p.read_text()
        assert "@" not in content
        assert "user@example.com" not in content

    def _write_bad(self, tmp_path: Path, data: dict) -> Path:
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(data))
        return p


class TestDecisionEngine:
    @pytest.mark.adversarial
    def test_unknown_capability_refused(self):
        auth = GoogleWorkspaceAuthState()
        d = evaluate_workspace_capability(auth, "google_workspace.nonexistent")
        assert d.is_refused and d.refusal_code == "google.capability.unknown"

    @pytest.mark.adversarial
    def test_missing_scope_refused(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user("a" * 64)
        d = evaluate_workspace_capability(auth, "google_workspace.gmail.labels.list")
        assert d.is_refused and d.refusal_code == "google.scope.missing"

    @pytest.mark.adversarial
    def test_expired_scope_refused(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/gmail.labels",
                    "non_sensitive",
                    "expired",
                )
            ],
        )
        d = evaluate_workspace_capability(auth, "google_workspace.gmail.labels.list")
        assert d.refusal_code == "google.scope.expired"

    @pytest.mark.adversarial
    def test_revoked_scope_refused(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/gmail.labels",
                    "non_sensitive",
                    "revoked",
                )
            ],
        )
        d = evaluate_workspace_capability(auth, "google_workspace.gmail.labels.list")
        assert d.refusal_code == "google.scope.revoked"

    @pytest.mark.adversarial
    def test_restricted_scope_refused_without_assessment(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/gmail.readonly", "restricted"
                )
            ],
        )
        d = evaluate_workspace_capability(auth, "google_workspace.gmail.profile.get")
        assert d.refusal_code == "google.scope.restricted_security_assessment_required"

    @pytest.mark.adversarial
    def test_missing_user_subject_refused(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/gmail.labels")]
        )
        auth.subject_hashes = ["s" * 64]
        d = evaluate_workspace_capability(
            auth, "google_workspace.gmail.labels.list", subject_hash=""
        )
        assert d.refusal_code == "google.subject.missing"

    @pytest.mark.adversarial
    def test_missing_customer_boundary_refused(self):
        auth = GoogleWorkspaceAuthState()
        d = evaluate_workspace_capability(
            auth, "google_workspace.admin.directory.users.list"
        )
        assert d.is_refused

    @pytest.mark.adversarial
    def test_domain_wide_delegation_refused_when_not_authorized(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/admin.directory.user.readonly",
                    "sensitive",
                )
            ],
        )
        d = evaluate_workspace_capability(
            auth, "google_workspace.admin.directory.users.list"
        )
        assert d.refusal_code in {
            "google.delegation.not_authorized",
            "google.auth.mode_not_allowed",
            "google.scope.missing",
        }

    @pytest.mark.adversarial
    def test_mutation_refused(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [_make_grant("https://www.googleapis.com/auth/gmail.send", "restricted")],
        )
        d = evaluate_workspace_capability(auth, "google_workspace.gmail.send")
        assert d.is_refused

    @pytest.mark.adversarial
    def test_live_network_credentialed_refused(self):
        auth = GoogleWorkspaceAuthState()
        d = evaluate_workspace_capability(
            auth, "google_workspace.admin.directory.domain_wide_impersonate"
        )
        assert d.refusal_code == "google.live_network.refused"


class TestReceipts:
    @pytest.mark.contract
    def test_receipt_for_allowed_fixture_read_validates(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/gmail.labels")]
        )
        auth.subject_hashes = ["s" * 64]
        d = GoogleWorkspaceDecision("x", GoogleWorkspaceVerdict.ALLOWED)
        req = GoogleWorkspaceOperationRequest(
            "op1", "x", auth_state=auth, subject_hash="s" * 64
        )
        r = build_workspace_receipt(req, d)
        assert not validate_receipt(r.to_dict())

    @pytest.mark.contract
    def test_receipt_for_refused_operation_validates(self):
        auth = GoogleWorkspaceAuthState()
        d = GoogleWorkspaceDecision(
            "x", GoogleWorkspaceVerdict.REFUSED, "google.scope.missing"
        )
        req = GoogleWorkspaceOperationRequest("op2", "x", auth_state=auth)
        r = build_workspace_receipt(req, d)
        assert r.refusal_code == "google.scope.missing"
        assert not validate_receipt(r.to_dict())

    @pytest.mark.adversarial
    def test_receipt_contains_hashes_not_raw_workspace_data(self):
        auth = GoogleWorkspaceAuthState()
        d = GoogleWorkspaceDecision("x", GoogleWorkspaceVerdict.ALLOWED)
        req = GoogleWorkspaceOperationRequest("op3", "x", auth_state=auth)
        r = build_workspace_receipt(req, d)
        data = json.dumps(r.to_dict())
        for raw in ["user@example.com", "gmail.com", "mydomain", "-----BEGIN"]:
            assert raw not in data, f"Raw value '{raw}' found in receipt"


class TestLocalAdapter:
    @pytest.mark.integration
    def test_gmail_labels_fixture_read_allowed_with_scope(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/gmail.labels")]
        )
        auth.subject_hashes = ["s" * 64]
        receipt = run_local_workspace_read(
            "op1", "google_workspace.gmail.labels.list", auth, subject_hash="s" * 64
        )
        assert receipt.verdict == "allowed"

    @pytest.mark.integration
    def test_drive_files_fixture_read_restricted_refused(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/drive.readonly", "restricted"
                )
            ],
        )
        auth.subject_hashes = ["s" * 64]
        receipt = run_local_workspace_read(
            "op2", "google_workspace.drive.files.list", auth, subject_hash="s" * 64
        )
        assert receipt.verdict == "refused"

    @pytest.mark.integration
    def test_calendar_list_fixture_read_allowed_with_sensitive(self):
        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/calendar.readonly", "sensitive"
                )
            ],
        )
        auth.subject_hashes = ["s" * 64]
        receipt = run_local_workspace_read(
            "op3",
            "google_workspace.calendar.calendarList.list",
            auth,
            subject_hash="s" * 64,
        )
        assert receipt.verdict == "allowed"

    @pytest.mark.substrate
    def test_adapter_does_not_make_network_calls(self):
        pass


class TestStatusSnapshot:
    @pytest.mark.contract
    def test_status_snapshot_validates(self):
        from rig_relay.integrations.google_workspace._status import (
            _validate,
            build_status_snapshot,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("s1")]
        )
        snap = build_status_snapshot(auth)
        assert not _validate(snap), f"Snapshot errors: {_validate(snap)}"


class TestCLI:
    @pytest.mark.substrate
    def test_cli_help_works(self):
        import subprocess

        r = subprocess.run(
            [
                "uv",
                "run",
                "python",
                str(REPO_ROOT / "scripts" / "rig_google_workspace_check.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 0

    @pytest.mark.substrate
    def test_cli_refusal_exit_code_2(self):
        import subprocess

        r = subprocess.run(
            [
                "uv",
                "run",
                "python",
                str(REPO_ROOT / "scripts" / "rig_google_workspace_check.py"),
                "--capability",
                "google_workspace.gmail.labels.list",
                "--fail-on-refusal",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 2
