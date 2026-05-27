from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rig_relay.extensions.safari.models import PageKind

_TOKEN_PATTERNS = frozenset({
    "ghp_",
    "ghs_",
    "gho_",
    "ghu_",
    "ghr_",
    "github_pat_",
    "access_token",
    "token",
})

_MIN_SEGMENTS = 2
_OWNER_REPO_LEN = 2
_SUB_INDEX = 2
_LEAF_INDEX = 3
_PR_START_LEN = 4
_PR_SUB_MIN_LEN = 5
_PR_SUB_INDEX = 4
_ISSUE_MIN_LEN = 4
_ISSUE_IDX = 3
_SETTINGS_PAGES_MIN_LEN = 4
_ORGS_INDEX = 3


def _has_token_in_url(url: str) -> bool:
    lowered = url.lower()
    return any(pattern in lowered for pattern in _TOKEN_PATTERNS)


_PATH_SEGMENT_MAP: dict[str, PageKind] = {
    "code": PageKind.REPOSITORY_CODE,
    "issues": PageKind.REPOSITORY_ISSUES,
    "pulls": PageKind.REPOSITORY_PULLS,
    "actions": PageKind.REPOSITORY_ACTIONS,
    "projects": PageKind.REPOSITORY_PROJECTS,
    "wiki": PageKind.REPOSITORY_WIKI,
    "security": PageKind.REPOSITORY_SECURITY,
    "insights": PageKind.REPOSITORY_INSIGHTS,
    "settings": PageKind.REPOSITORY_SETTINGS,
    "pages": PageKind.REPOSITORY_PAGES,
}

_PR_PAGE_MAP: dict[str, PageKind] = {
    "commits": PageKind.PULL_REQUEST_COMMITS,
    "checks": PageKind.PULL_REQUEST_CHECKS,
    "files": PageKind.PULL_REQUEST_FILES_CHANGED,
}


class GitHubPageContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    owner: str
    repo: str
    page_kind: PageKind
    pr_number: int | None = Field(default=None, ge=1)
    issue_number: int | None = Field(default=None, ge=1)

    @field_validator("owner", "repo")
    @classmethod
    def _non_empty_str(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


def _make_context(
    url: str,
    owner: str,
    repo: str,
    page_kind: PageKind,
    *,
    pr_number: int | None = None,
    issue_number: int | None = None,
) -> GitHubPageContext:
    return GitHubPageContext(
        url=url,
        owner=owner,
        repo=repo,
        page_kind=page_kind,
        pr_number=pr_number,
        issue_number=issue_number,
    )


def _try_recognize_pr(
    url: str, owner: str, repo: str, segments: list[str]
) -> GitHubPageContext | None:
    if segments[_SUB_INDEX] != "pull":
        return None
    if len(segments) < _PR_START_LEN:
        return None
    try:
        pr_number = int(segments[_LEAF_INDEX])
    except (ValueError, IndexError):
        return _make_context(url, owner, repo, PageKind.PULL_REQUEST_UNKNOWN)

    page_kind = PageKind.PULL_REQUEST_CONVERSATION
    if len(segments) >= _PR_SUB_MIN_LEN:
        page_kind = _PR_PAGE_MAP.get(
            segments[_PR_SUB_INDEX], PageKind.PULL_REQUEST_UNKNOWN
        )

    return _make_context(url, owner, repo, page_kind, pr_number=pr_number)


def _try_recognize_issue(
    url: str, owner: str, repo: str, segments: list[str]
) -> GitHubPageContext | None:
    if segments[_SUB_INDEX] != "issues":
        return None
    if len(segments) < _ISSUE_MIN_LEN:
        return None
    try:
        issue_number = int(segments[_ISSUE_IDX])
    except (ValueError, IndexError):
        return None
    return _make_context(
        url, owner, repo, PageKind.REPOSITORY_ISSUES, issue_number=issue_number
    )


def recognize_github_page(url: str) -> GitHubPageContext | None:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        return None
    if parsed.hostname != "github.com":
        return None
    if _has_token_in_url(url):
        return None

    path = parsed.path.strip("/")
    segments = [s for s in path.split("/") if s]

    if len(segments) < _MIN_SEGMENTS:
        return None

    owner = segments[0]
    repo = segments[1]

    if len(segments) == _OWNER_REPO_LEN:
        return _make_context(url, owner, repo, PageKind.REPOSITORY_MAIN)

    sub = segments[_SUB_INDEX] if len(segments) > _SUB_INDEX else ""

    ctx = _try_recognize_pr(url, owner, repo, segments)
    if ctx is not None:
        return ctx

    ctx = _try_recognize_issue(url, owner, repo, segments)
    if ctx is not None:
        return ctx

    if (
        sub == "settings"
        and len(segments) >= _SETTINGS_PAGES_MIN_LEN
        and segments[_LEAF_INDEX] == "pages"
    ):
        return _make_context(url, owner, repo, PageKind.REPOSITORY_PAGES)

    mapped = _PATH_SEGMENT_MAP.get(sub)
    if mapped is not None:
        return _make_context(url, owner, repo, mapped)

    if segments[_SUB_INDEX] == "orgs":
        mapped = _PATH_SEGMENT_MAP.get(
            segments[_ORGS_INDEX] if len(segments) > _ORGS_INDEX else ""
        )
        if mapped is not None:
            return _make_context(url, owner, repo, mapped)

    return _make_context(url, owner, repo, PageKind.UNKNOWN_GITHUB)


__all__ = ["GitHubPageContext", "recognize_github_page"]
