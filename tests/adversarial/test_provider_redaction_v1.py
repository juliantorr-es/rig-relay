"""Provider redaction adversarial tests.

Tests that GitHub and Google Workspace redaction helpers correctly
detect, hash, and reject sensitive content in live API response payloads.
"""

from __future__ import annotations

import json

import pytest

from rig_relay.integrations.github_provider._redaction import (
    assert_no_raw_github_token,
    assert_response_content_light,
    hash_private_field,
    redact_github_response,
    scan_response_for_secrets,
)
from rig_relay.integrations.google_workspace._redaction import (
    assert_no_raw_secret_patterns,
    assert_response_content_light as workspace_assert_response_content_light,
    detect_pii_in_response,
    redact_workspace_response,
)

pytestmark = [pytest.mark.adversarial]


# ---------------------------------------------------------------------------
# GitHub redaction adversarial tests
# ---------------------------------------------------------------------------

_FAKE_SHA = "sha256:" + "a" * 64


class TestGitHubRedactionAdversarial:
    def test_github_response_with_embedded_token_detected(self):
        response = {
            "id": 1,
            "name": "example-repo",
            "description": "Look at ghp_abc123def456ghi789jkl012mno345pqr678stu embedded here",
        }
        text = json.dumps(response)
        with pytest.raises(ValueError, match="raw_github_token_detected"):
            assert_no_raw_github_token(text)

    def test_github_response_with_user_email_hashed(self):
        response = {"id": 1, "login": "octocat", "email": "octocat@github.com"}
        result = hash_private_field(response, "email")
        assert result["email"] != "octocat@github.com"
        assert result["email"].startswith("sha256:")
        assert result["login"] == "octocat"

    def test_github_response_with_raw_file_content_rejected(self):
        response = {
            "name": "README.md",
            "content": "import secrets\n\nSECRET_KEY = 'abc123'\n",
            "encoding": "utf-8",
        }
        with pytest.raises(ValueError, match="forbidden_response_field_detected"):
            assert_response_content_light(response, ["content", "raw_file_content"])

    def test_github_response_with_private_repo_name_hashed(self):
        response = {
            "full_name": "acme-corp/secret-project",
            "visibility": "private",
            "owner": {"login": "acme-corp", "email": "admin@acme-corp.com"},
        }
        result = redact_github_response(response, "github.repo.metadata.read")
        assert result["full_name"].startswith("sha256:")
        assert result["full_name"] != "acme-corp/secret-project"

    def test_github_issue_body_masked_in_read_response(self):
        response = {
            "number": 42,
            "title": "Bug report",
            "body": "The server returns 500 when I POST with a valid payload.\n\nSteps to reproduce...",
            "user": {"login": "reporter", "email": "reporter@example.com"},
        }
        result = redact_github_response(response, "github.repo.issues.read")
        assert result["body"].startswith("sha256:")
        assert result["body"] != response["body"]

    def test_github_pr_body_masked_in_read_response(self):
        response = {
            "number": 99,
            "title": "Add feature X",
            "body": "This PR adds the long-awaited feature X.\n\nCloses #55",
            "user": {"login": "dev123", "email": "dev123@example.com"},
        }
        result = redact_github_response(response, "github.repo.pull_requests.read")
        assert result["body"].startswith("sha256:")
        assert result["body"] != response["body"]

    def test_github_commit_message_hashed_not_raw(self):
        response = {
            "sha": "a" * 40,
            "commit": {
                "message": "Fix critical security vulnerability in auth module",
                "author": {"name": "Jane Dev", "email": "jane.dev@example.com"},
            },
        }
        result = redact_github_response(response, "github.repo.commits.read")
        assert result["commit"]["message"].startswith("sha256:")
        assert (
            result["commit"]["message"]
            != "Fix critical security vulnerability in auth module"
        )

    def test_github_actions_log_content_rejected(self):
        response = {
            "id": 1,
            "status": "completed",
            "logs_url": "https://api.github.com/repos/acme/repo/actions/runs/1/logs",
        }
        result = redact_github_response(response, "github.actions.runs.read")
        assert result["logs_url"].startswith("sha256:")
        assert result["logs_url"] != response["logs_url"]


# ---------------------------------------------------------------------------
# scan_response_for_secrets tests
# ---------------------------------------------------------------------------


class TestGitHubSecretScanning:
    def test_scan_detects_github_token_patterns(self):
        payload = '{"token":"ghp_abc123def456ghi789jkl012mno345pqr678stu"}'
        results = scan_response_for_secrets(payload)
        assert "github_token_pattern" in results

    def test_scan_detects_jwt_in_response(self):
        jwt = (
            "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
            ".abc123def456"
        )
        payload = f'{{"auth":"{jwt}"}}'
        results = scan_response_for_secrets(payload)
        assert "jwt_pattern" in results

    def test_scan_detects_pem_private_key(self):
        payload = '{"key":"-----BEGIN RSA PRIVATE KEY-----\\nMOCK\\n-----END RSA PRIVATE KEY-----"}'
        results = scan_response_for_secrets(payload)
        assert "pem_private_key_pattern" in results

    def test_scan_clean_response_returns_empty(self):
        payload = '{"id":1,"name":"public-repo","visibility":"public"}'
        results = scan_response_for_secrets(payload)
        assert results == []


# ---------------------------------------------------------------------------
# Google Workspace redaction adversarial tests
# ---------------------------------------------------------------------------


class TestWorkspaceRedactionAdversarial:
    def test_gmail_message_body_never_in_response(self):
        response = {
            "raw_gmail_body": "Hello, this is a confidential email body.",
            "raw_gmail_subject": "URGENT: Project Update",
        }
        with pytest.raises(ValueError, match="forbidden_response_field_detected"):
            workspace_assert_response_content_light(
                response, ["raw_gmail_body", "raw_gmail_subject", "raw_email"]
            )

    def test_gmail_sender_email_hashed(self):
        response = {"emailAddress": "sender@example.com", "messagesTotal": 42}
        result = redact_workspace_response(
            response, "google_workspace.gmail.profile.get"
        )
        assert result["emailAddress"].startswith("sha256:")
        assert result["emailAddress"] != "sender@example.com"

    def test_drive_file_content_never_in_response(self):
        response = {
            "name": "secret_plan.docx",
            "content": b"confidential data bytes".hex(),
            "raw_drive_content": "actual file content here",
        }
        with pytest.raises(ValueError, match="forbidden_response_field_detected"):
            workspace_assert_response_content_light(
                response, ["content", "raw_drive_content"]
            )

    def test_drive_file_owner_hashed(self):
        response = {
            "id": "file123",
            "name": "budget.xlsx",
            "owners": [{"email": "owner@example.com", "displayName": "Owner Name"}],
        }
        result = redact_workspace_response(
            response, "google_workspace.drive.files.list"
        )
        assert result["id"].startswith("sha256:")
        assert result["name"].startswith("sha256:")

    def test_calendar_event_description_masked(self):
        response = {
            "id": "cal_event_1",
            "summary": "Team standup",
            "description": "Discuss Q3 roadmap and hiring plan",
        }
        result = redact_workspace_response(
            response, "google_workspace.calendar.calendarList.list"
        )
        assert result["id"].startswith("sha256:")
        assert result["summary"].startswith("sha256:")

    def test_calendar_attendee_emails_hashed(self):
        response = {
            "attendees": [
                {"email": "alice@example.com", "responseStatus": "accepted"},
                {"email": "bob@example.com", "responseStatus": "tentative"},
            ]
        }
        pii_paths = detect_pii_in_response(response)
        email_paths = [p for p in pii_paths if p.startswith("pii_email:")]
        assert len(email_paths) == 2
        for path in email_paths:
            assert "attendees" in path

    def test_contacts_email_addresses_hashed(self):
        response = {
            "resourceName": "people/c123",
            "emailAddresses": [{"value": "contact@example.com", "type": "work"}],
            "names": [{"displayName": "John Doe"}],
        }
        result = redact_workspace_response(response, "google_workspace.contacts.list")
        assert result["resourceName"].startswith("sha256:")

    def test_admin_directory_user_emails_refused_or_hashed(self):
        response = {
            "users": [
                {"primaryEmail": "user1@example.com", "id": "u1"},
                {"primaryEmail": "user2@example.com", "id": "u2"},
            ]
        }
        pii_paths = detect_pii_in_response(response)
        email_paths = [p for p in pii_paths if p.startswith("pii_email:")]
        assert len(email_paths) == 2

    def test_google_access_token_not_leaked(self):
        token_payload = {
            "auth": "ya29.a0AfH6SMAaBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890_abcdef"
        }
        text = json.dumps(token_payload)
        with pytest.raises(ValueError, match="raw_secret_pattern_detected"):
            assert_no_raw_secret_patterns(text)

    def test_google_refresh_token_not_leaked(self):
        token_payload = {
            "auth": "1//0gA-BcDeFgHiJkLmNoPqRsTuVwXyZ1234567890_abcdef-ghijkl"
        }
        text = json.dumps(token_payload)
        with pytest.raises(ValueError, match="raw_secret_pattern_detected"):
            assert_no_raw_secret_patterns(text)


# ---------------------------------------------------------------------------
# Google Workspace PII detection tests
# ---------------------------------------------------------------------------


class TestWorkspacePIIDetection:
    def test_detect_pii_emails_in_flat_dict(self):
        data = {"id": 1, "email": "user@example.com", "name": "Public Name"}
        results = detect_pii_in_response(data)
        assert any("pii_email:" in r for r in results)

    def test_detect_pii_emails_in_nested_dict(self):
        data = {"profile": {"contact": {"email": "deeply@nested.com"}}}
        results = detect_pii_in_response(data)
        assert any("pii_email:" in r and "profile.contact.email" in r for r in results)

    def test_detect_pii_emails_in_list(self):
        data = {"members": ["alice@example.com", "bob@example.com"]}
        results = detect_pii_in_response(data)
        assert len([r for r in results if "pii_email:" in r]) == 2

    def test_pii_detection_returns_field_paths_not_values(self):
        data = {"email": "top-secret@example.com"}
        results = detect_pii_in_response(data)
        for result in results:
            assert "top-secret" not in result
            assert "@" not in result.split(":")[-1]

    def test_no_pii_in_clean_data(self):
        data = {"id": 42, "label": "INBOX", "count": 3}
        results = detect_pii_in_response(data)
        assert results == []


# ---------------------------------------------------------------------------
# hash_private_field unit tests
# ---------------------------------------------------------------------------


class TestHashPrivateField:
    def test_hashes_existing_field(self):
        data = {"name": "sensitive-name", "public_field": "ok"}
        result = hash_private_field(data, "name")
        assert result["name"].startswith("sha256:")
        assert result["name"] != "sensitive-name"
        assert result["public_field"] == "ok"

    def test_noop_when_field_missing(self):
        data = {"name": "safe"}
        result = hash_private_field(data, "nonexistent")
        assert result["name"] == "safe"

    def test_noop_when_field_is_not_string(self):
        data = {"count": 42}
        result = hash_private_field(data, "count")
        assert result["count"] == 42

    def test_does_not_mutate_original(self):
        data = {"name": "original"}
        result = hash_private_field(data, "name")
        assert data["name"] == "original"
        assert result["name"] != "original"
