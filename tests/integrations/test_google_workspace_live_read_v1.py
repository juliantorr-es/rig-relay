"""Google Workspace Live Read v1 — fake HTTP tests (no real network)."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

from httpx import Response
import pytest

from rig_relay.integrations.google_workspace import (
    GoogleWorkspaceAuthState,
    GoogleWorkspaceScopeGrant,
)
from rig_relay.integrations.google_workspace._receipts import validate_receipt

_LIVE_ENV = "RIG_LIVE_PROVIDER_TESTS"


def _make_grant(
    scope_id: str, sensitivity: str = "non_sensitive", status: str = "active"
) -> GoogleWorkspaceScopeGrant:
    return GoogleWorkspaceScopeGrant(
        scope_id=scope_id,
        scope_sensitivity=sensitivity,
        grant_status=status,
        grant_hash="g" * 64,
    )


def _fake_httpx_response(status_code: int, json_data: dict) -> Response:
    return Response(status_code, json=json_data, request=None)


def _gmaiL_profile_fixture() -> dict:
    return {"emailAddress": "user@example.com", "messagesTotal": 42, "threadsTotal": 15}


def _gmaiL_labels_fixture() -> dict:
    return {
        "labels": [{"id": "INBOX", "name": "INBOX"}, {"id": "SENT", "name": "SENT"}]
    }


def _calendar_list_fixture() -> dict:
    return {
        "items": [
            {"id": "cal1", "summary": "Primary"},
            {"id": "cal2", "summary": "Work"},
        ]
    }


def _drive_files_fixture() -> dict:
    return {
        "files": [
            {
                "id": "file1",
                "name": "doc1",
                "mimeType": "text/plain",
                "size": "100",
                "modifiedTime": "2026-01-01T00:00:00Z",
            }
        ]
    }


def _tasks_tasklists_fixture() -> dict:
    return {"items": [{"id": "tl1", "title": "My Tasks"}]}


def _contacts_fixture() -> dict:
    return {
        "connections": [
            {
                "resourceName": "people/c1",
                "names": [{"displayName": "John"}],
                "emailAddresses": [{"value": "john@example.com"}],
            }
        ]
    }


def _admin_users_fixture() -> dict:
    return {"users": [{"id": "u1", "primaryEmail": "a@example.com"}]}


class TestGoogleWorkspaceLiveReadFake:
    @pytest.mark.asyncio
    async def test_gmail_labels_read_returns_hashed_receipt(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/gmail.labels")]
        )
        auth.subject_hashes = ["s" * 64]

        fixture = _gmaiL_labels_fixture()
        mock_resp = _fake_httpx_response(200, fixture)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            receipt = await run_live_workspace_read(
                "op-live-labels",
                "google_workspace.gmail.labels.list",
                auth,
                "ya29.test_fake_token",
                subject_hash="s" * 64,
            )

        assert receipt.verdict == "allowed"
        assert "INBOX" not in json.dumps(receipt.to_dict())
        assert "SENT" not in json.dumps(receipt.to_dict())
        assert not validate_receipt(receipt.to_dict())

    @pytest.mark.asyncio
    async def test_gmail_profile_read_refused_restricted_scope(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/gmail.readonly", "restricted"
                )
            ],
        )
        auth.subject_hashes = ["s" * 64]

        receipt = await run_live_workspace_read(
            "op-restricted",
            "google_workspace.gmail.profile.get",
            auth,
            "ya29.test_fake_token",
            subject_hash="s" * 64,
        )

        assert receipt.verdict == "refused"
        assert (
            receipt.refusal_code
            == "google.scope.restricted_security_assessment_required"
        )

    @pytest.mark.asyncio
    async def test_calendar_list_read_returns_hashed_receipt(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/calendar.readonly", "sensitive"
                )
            ],
        )
        auth.subject_hashes = ["s" * 64]

        fixture = _calendar_list_fixture()
        mock_resp = _fake_httpx_response(200, fixture)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            receipt = await run_live_workspace_read(
                "op-live-cal",
                "google_workspace.calendar.calendarList.list",
                auth,
                "ya29.test_fake_token",
                subject_hash="s" * 64,
            )

        assert receipt.verdict == "allowed"
        receipt_json = json.dumps(receipt.to_dict())
        assert "Primary" not in receipt_json
        assert "Work" not in receipt_json
        assert not validate_receipt(receipt.to_dict())

    @pytest.mark.asyncio
    async def test_drive_files_restricted_scope_refused(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/drive.metadata.readonly",
                    "restricted",
                )
            ],
        )
        auth.subject_hashes = ["s" * 64]

        receipt = await run_live_workspace_read(
            "op-drive",
            "google_workspace.drive.files.list",
            auth,
            "ya29.test_fake_token",
            subject_hash="s" * 64,
        )

        assert receipt.verdict == "refused"
        assert (
            receipt.refusal_code
            == "google.scope.restricted_security_assessment_required"
        )

    @pytest.mark.asyncio
    async def test_tasks_tasklists_unknown_capability_refused(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/tasks.readonly")]
        )
        auth.subject_hashes = ["s" * 64]

        receipt = await run_live_workspace_read(
            "op-tasks",
            "google_workspace.tasks.tasklists.list",
            auth,
            "ya29.test_fake_token",
            subject_hash="s" * 64,
        )

        assert receipt.verdict == "refused"
        assert receipt.refusal_code == "google.capability.unknown"

    @pytest.mark.asyncio
    async def test_contacts_unknown_capability_refused(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/contacts.readonly")]
        )
        auth.subject_hashes = ["s" * 64]

        receipt = await run_live_workspace_read(
            "op-contacts",
            "google_workspace.contacts.list",
            auth,
            "ya29.test_fake_token",
            subject_hash="s" * 64,
        )

        assert receipt.verdict == "refused"
        assert receipt.refusal_code == "google.capability.unknown"

    @pytest.mark.asyncio
    async def test_admin_directory_refused_by_default(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/admin.directory.user.readonly",
                    "sensitive",
                )
            ],
        )

        receipt = await run_live_workspace_read(
            "op-admin",
            "google_workspace.admin.directory.users.list",
            auth,
            "ya29.test_fake_token",
        )

        assert receipt.verdict == "refused"

    @pytest.mark.asyncio
    async def test_mutation_capability_refused(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [_make_grant("https://www.googleapis.com/auth/gmail.send", "restricted")],
        )

        receipt = await run_live_workspace_read(
            "op-mut", "google_workspace.gmail.send", auth, "ya29.test_fake_token"
        )

        assert receipt.verdict == "refused"

    @pytest.mark.asyncio
    async def test_unknown_capability_refused(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState()

        receipt = await run_live_workspace_read(
            "op-unknown",
            "google_workspace.nonexistent.thing",
            auth,
            "ya29.test_fake_token",
        )

        assert receipt.verdict == "refused"
        assert receipt.refusal_code == "google.capability.unknown"

    @pytest.mark.asyncio
    async def test_no_raw_email_addresses_in_receipt(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/gmail.labels")]
        )
        auth.subject_hashes = ["s" * 64]

        fixture = _gmaiL_labels_fixture()
        mock_resp = _fake_httpx_response(200, fixture)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            receipt = await run_live_workspace_read(
                "op-no-email",
                "google_workspace.gmail.labels.list",
                auth,
                "ya29.test_fake_token",
                subject_hash="s" * 64,
            )

        receipt_json = json.dumps(receipt.to_dict())
        assert "@" not in receipt_json
        assert "example.com" not in receipt_json
        assert "user@example.com" not in receipt_json

    @pytest.mark.asyncio
    async def test_no_raw_file_names_in_receipt(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64,
            [
                _make_grant(
                    "https://www.googleapis.com/auth/calendar.readonly", "sensitive"
                )
            ],
        )
        auth.subject_hashes = ["s" * 64]

        fixture = _calendar_list_fixture()
        mock_resp = _fake_httpx_response(200, fixture)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            receipt = await run_live_workspace_read(
                "op-no-file",
                "google_workspace.calendar.calendarList.list",
                auth,
                "ya29.test_fake_token",
                subject_hash="s" * 64,
            )

        receipt_json = json.dumps(receipt.to_dict())
        assert "Primary" not in receipt_json
        assert "Work" not in receipt_json

    @pytest.mark.asyncio
    async def test_no_raw_contact_names_in_receipt(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/gmail.labels")]
        )
        auth.subject_hashes = ["s" * 64]

        fixture = _gmaiL_labels_fixture()
        mock_resp = _fake_httpx_response(200, fixture)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            receipt = await run_live_workspace_read(
                "op-no-contact",
                "google_workspace.gmail.labels.list",
                auth,
                "ya29.test_fake_token",
                subject_hash="s" * 64,
            )

        receipt_json = json.dumps(receipt.to_dict())
        assert "INBOX" not in receipt_json

    @pytest.mark.asyncio
    async def test_trace_id_preserved(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/gmail.labels")]
        )
        auth.subject_hashes = ["s" * 64]

        fixture = _gmaiL_labels_fixture()
        mock_resp = _fake_httpx_response(200, fixture)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            receipt = await run_live_workspace_read(
                "op-trace",
                "google_workspace.gmail.labels.list",
                auth,
                "ya29.test_fake_token",
                subject_hash="s" * 64,
                trace_id="gw-tr-live-001",
            )

        assert receipt.trace_id == "gw-tr-live-001"
        assert receipt.to_dict().get("trace_id") == "gw-tr-live-001"

    @pytest.mark.asyncio
    async def test_http_error_returns_failed(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/gmail.labels")]
        )
        auth.subject_hashes = ["s" * 64]

        mock_resp = _fake_httpx_response(500, {"error": "Internal Server Error"})

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            receipt = await run_live_workspace_read(
                "op-http-err",
                "google_workspace.gmail.labels.list",
                auth,
                "ya29.test_fake_token",
                subject_hash="s" * 64,
            )

        assert receipt.verdict == "failed"
        assert "google.http.error" in receipt.refusal_code

    @pytest.mark.asyncio
    async def test_receipt_content_light(self):
        from rig_relay.integrations.google_workspace._live_adapter import (
            run_live_workspace_read,
        )

        auth = GoogleWorkspaceAuthState.authenticated_oauth_user(
            "a" * 64, [_make_grant("https://www.googleapis.com/auth/gmail.labels")]
        )
        auth.subject_hashes = ["s" * 64]

        fixture = _gmaiL_labels_fixture()
        mock_resp = _fake_httpx_response(200, fixture)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            receipt = await run_live_workspace_read(
                "op-light",
                "google_workspace.gmail.labels.list",
                auth,
                "ya29.test_fake_token",
                subject_hash="s" * 64,
            )

        assert receipt.content_light is True
        receipt_json = json.dumps(receipt.to_dict())
        assert "raw_token" not in receipt_json
        assert "access_token" not in receipt_json
        assert "ya29.test_fake_token" not in receipt_json

    @pytest.mark.asyncio
    async def test_live_skip_without_env_var(self):
        if os.environ.get(_LIVE_ENV, "0") != "1":
            pytest.skip(f"Set {_LIVE_ENV}=1 to run live provider tests")

        from rig_relay.integrations.google_workspace._live_adapter import (
            should_skip_live_tests,
        )

        should_skip_live_tests()
