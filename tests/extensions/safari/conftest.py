from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def valid_github_repo_url() -> str:
    return "https://github.com/owner/repo-name"


@pytest.fixture
def valid_github_pr_url() -> str:
    return "https://github.com/octocat/hello-world/pull/42"


@pytest.fixture
def valid_github_issue_url() -> str:
    return "https://github.com/octocat/hello-world/issues/99"


@pytest.fixture
def valid_github_actions_url() -> str:
    return "https://github.com/octocat/hello-world/actions"


@pytest.fixture
def valid_github_pages_url() -> str:
    return "https://github.com/octocat/hello-world/settings/pages"


@pytest.fixture
def valid_github_org_url() -> str:
    return "https://github.com/octocat"


@pytest.fixture
def token_bearing_url() -> str:
    return "https://github.com/owner/repo?access_token=ghp_1234567890"


@pytest.fixture
def non_github_url() -> str:
    return "https://example.com/some/page"


@pytest.fixture
def http_github_url() -> str:
    return "http://github.com/owner/repo"


@pytest.fixture
def sample_repository_handoff_dict() -> dict[str, Any]:
    return {
        "url": "https://github.com/owner/repo",
        "owner": "owner",
        "repo": "repo",
        "page_kind": "repository_main",
        "triggered_by": "popup_action",
    }


@pytest.fixture
def sample_pr_handoff_dict() -> dict[str, Any]:
    return {
        "url": "https://github.com/octocat/hello-world/pull/42",
        "owner": "octocat",
        "repo": "hello-world",
        "pr_number": 42,
        "page_kind": "pull_request_conversation",
        "triggered_by": "toolbar_button",
    }


@pytest.fixture
def sample_issue_handoff_dict() -> dict[str, Any]:
    return {
        "url": "https://github.com/octocat/hello-world/issues/99",
        "owner": "octocat",
        "repo": "hello-world",
        "issue_number": 99,
        "triggered_by": "popup_action",
    }


@pytest.fixture
def sample_ping_dict() -> dict[str, Any]:
    return {"extension_version": "0.1.0"}


@pytest.fixture
def sample_accepted_response_dict() -> dict[str, Any]:
    return {
        "in_response_to": "uuid-1",
        "action": "open_in_rig_relay",
        "repository_status": "known_and_available",
    }


@pytest.fixture
def sample_deferred_response_dict() -> dict[str, Any]:
    return {
        "in_response_to": "uuid-2",
        "action": "study_repository",
        "deferral_reason": "app_not_connected_to_carte_blanche",
    }


@pytest.fixture
def sample_refused_response_dict() -> dict[str, Any]:
    return {
        "in_response_to": "uuid-3",
        "action": "open_in_rig_relay",
        "refusal_reason": "action_not_permitted",
    }


@pytest.fixture
def sample_app_unavailable_response_dict() -> dict[str, Any]:
    return {"message": "App not running"}
