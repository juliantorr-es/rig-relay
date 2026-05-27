from __future__ import annotations

from rig_relay.extensions.safari.context import PageKind, recognize_github_page


def test_recognizes_repository_main() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_MAIN
    assert ctx.owner == "owner"
    assert ctx.repo == "repo"
    assert ctx.pr_number is None
    assert ctx.issue_number is None


def test_recognizes_repository_code() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/code")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_CODE


def test_recognizes_pull_request() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/pull/42")
    assert ctx is not None
    assert ctx.page_kind == PageKind.PULL_REQUEST_CONVERSATION
    assert ctx.pr_number == 42


def test_recognizes_pull_request_commits() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/pull/42/commits")
    assert ctx is not None
    assert ctx.page_kind == PageKind.PULL_REQUEST_COMMITS
    assert ctx.pr_number == 42


def test_recognizes_pull_request_files() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/pull/42/files")
    assert ctx is not None
    assert ctx.page_kind == PageKind.PULL_REQUEST_FILES_CHANGED
    assert ctx.pr_number == 42


def test_recognizes_issue() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/issues/99")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_ISSUES
    assert ctx.issue_number == 99


def test_recognizes_actions() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/actions")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_ACTIONS


def test_recognizes_settings_pages() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/settings/pages")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_PAGES


def test_recognizes_wiki() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/wiki")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_WIKI


def test_recognizes_security() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/security")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_SECURITY


def test_recognizes_insights() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/insights")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_INSIGHTS


def test_recognizes_projects() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/projects")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_PROJECTS


def test_recognizes_organization_profile() -> None:
    result = recognize_github_page("https://github.com/octocat")
    assert result is None


def test_recognizes_unknown_path_as_unknown_github() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/something/weird")
    assert ctx is not None
    assert ctx.page_kind == PageKind.UNKNOWN_GITHUB
    assert ctx.owner == "owner"
    assert ctx.repo == "repo"


def test_rejects_non_https() -> None:
    assert recognize_github_page("http://github.com/owner/repo") is None


def test_rejects_non_github_domain() -> None:
    assert recognize_github_page("https://example.com/owner/repo") is None


def test_rejects_token_url() -> None:
    assert (
        recognize_github_page(
            "https://github.com/owner/repo?access_token=ghp_1234567890"
        )
        is None
    )


def test_rejects_github_pat_url() -> None:
    assert (
        recognize_github_page("https://github.com/owner/repo?token=ghp_abcdef") is None
    )


def test_rejects_empty_path() -> None:
    assert recognize_github_page("https://github.com/") is None


def test_rejects_single_segment_no_repo() -> None:
    assert recognize_github_page("https://github.com/owner") is None


def test_strips_trailing_slash() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_MAIN


def test_strips_query_params() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo?tab=repositories")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_MAIN


def test_rejects_client_secret_in_url() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo?client_secret=abc123")
    assert ctx is not None
    assert ctx.page_kind == PageKind.REPOSITORY_MAIN


def test_pr_with_non_numeric_segment_is_unknown() -> None:
    ctx = recognize_github_page("https://github.com/owner/repo/pull/abc")
    assert ctx is not None
    assert ctx.page_kind == PageKind.PULL_REQUEST_UNKNOWN
    assert ctx.pr_number is None
