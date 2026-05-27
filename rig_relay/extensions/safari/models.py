from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import re
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION = "rig.relay.safari_extension_message.v1"
_MAX_MESSAGE_LENGTH = 10_000

_OWNER_REPO_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")
_URL_PATTERN = re.compile(r"^https://github\.com/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+")
_TOKEN_PATTERNS = re.compile(r"(ghp_|ghs_|gho_|ghu_|ghr_|github_pat_)")

_EXTENSION_KINDS: frozenset[str] = frozenset({
    "handoff.github_repository",
    "handoff.github_pull_request",
    "handoff.github_issue",
    "ping",
})
_APP_KINDS: frozenset[str] = frozenset({
    "response.accepted",
    "response.deferred",
    "response.refused",
    "response.app_unavailable",
})


class MessageDirection(StrEnum):
    EXTENSION_TO_APP = "extension_to_app"
    APP_TO_EXTENSION = "app_to_extension"


class MessageKind(StrEnum):
    HANDOFF_GITHUB_REPOSITORY = "handoff.github_repository"
    HANDOFF_GITHUB_PULL_REQUEST = "handoff.github_pull_request"
    HANDOFF_GITHUB_ISSUE = "handoff.github_issue"
    PING = "ping"
    RESPONSE_ACCEPTED = "response.accepted"
    RESPONSE_DEFERRED = "response.deferred"
    RESPONSE_REFUSED = "response.refused"
    RESPONSE_APP_UNAVAILABLE = "response.app_unavailable"


class PageKind(StrEnum):
    REPOSITORY_MAIN = "repository_main"
    REPOSITORY_CODE = "repository_code"
    REPOSITORY_ISSUES = "repository_issues"
    REPOSITORY_PULLS = "repository_pulls"
    REPOSITORY_ACTIONS = "repository_actions"
    REPOSITORY_PROJECTS = "repository_projects"
    REPOSITORY_WIKI = "repository_wiki"
    REPOSITORY_SECURITY = "repository_security"
    REPOSITORY_INSIGHTS = "repository_insights"
    REPOSITORY_SETTINGS = "repository_settings"
    REPOSITORY_PAGES = "repository_pages"
    ORGANIZATION_PROFILE = "organization_profile"
    UNKNOWN_GITHUB = "unknown_github"
    PULL_REQUEST_CONVERSATION = "pull_request_conversation"
    PULL_REQUEST_COMMITS = "pull_request_commits"
    PULL_REQUEST_CHECKS = "pull_request_checks"
    PULL_REQUEST_FILES_CHANGED = "pull_request_files_changed"
    PULL_REQUEST_UNKNOWN = "pull_request_unknown"


class TriggeredBy(StrEnum):
    POPUP_ACTION = "popup_action"
    TOOLBAR_BUTTON = "toolbar_button"
    CONTEXT_MENU = "context_menu"


class RepositoryStatus(StrEnum):
    KNOWN_AND_AVAILABLE = "known_and_available"
    REQUIRES_IMPORT = "requires_import"
    REQUIRES_AUTHORIZATION = "requires_authorization"
    STATUS_PENDING = "status_pending"


class DeferralReason(StrEnum):
    APP_NOT_CONNECTED_TO_CARTE_BLANCHE = "app_not_connected_to_carte_blanche"
    REPOSITORY_NOT_AUTHORIZED_BY_INSTALLED_GITHUB_APP = (
        "repository_not_authorized_by_installed_github_app"
    )
    REQUIRES_SELECTION_OR_IMPORT_IN_MAIN_APP = (
        "requires_selection_or_import_in_main_app"
    )
    NATIVE_HOST_INITIALIZING = "native_host_initializing"
    INTEGRATIONS_INCOMPLETE = "integrations_incomplete"
    UNSUPPORTED_PAGE_CONTEXT = "unsupported_page_context"
    DEFERRED_CAPABILITY = "deferred_capability"


class RefusalReason(StrEnum):
    ACTION_NOT_PERMITTED = "action_not_permitted"
    REPOSITORY_ACCESS_DENIED = "repository_access_denied"
    UNSUPPORTED_GITHUB_CONTEXT = "unsupported_github_context"
    INVALID_MESSAGE = "invalid_message"
    RATE_LIMITED = "rate_limited"
    EXTENSION_NOT_AUTHORIZED = "extension_not_authorized"


class UnavailableReason(StrEnum):
    APP_NOT_RUNNING = "app_not_running"
    APP_NOT_INSTALLED = "app_not_installed"
    NATIVE_MESSAGING_UNAVAILABLE = "native_messaging_unavailable"
    TIMEOUT = "timeout"


def _validate_owner_or_repo(value: str) -> str:
    if not _OWNER_REPO_PATTERN.match(value):
        raise ValueError(f"must match ^[a-zA-Z0-9._-]+$, got {value!r}")
    return value


def _validate_github_url(value: str) -> str:
    if not _URL_PATTERN.match(value):
        raise ValueError(
            f"must match ^https://github\\.com/<owner>/<repo>, got {value!r}"
        )
    return value


class GitHubRepositoryHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["handoff.github_repository"] = Field(
        exclude=True, default="handoff.github_repository"
    )
    url: str
    owner: str
    repo: str
    page_kind: PageKind
    triggered_by: TriggeredBy

    @field_validator("url")
    @classmethod
    def _url_matches_pattern(cls, value: str) -> str:
        return _validate_github_url(value)

    @field_validator("owner", "repo")
    @classmethod
    def _owner_repo_matches_pattern(cls, value: str) -> str:
        return _validate_owner_or_repo(value)


class GitHubPullRequestHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["handoff.github_pull_request"] = Field(
        exclude=True, default="handoff.github_pull_request"
    )
    url: str
    owner: str
    repo: str
    pr_number: int = Field(ge=1)
    page_kind: PageKind
    triggered_by: TriggeredBy

    @field_validator("url")
    @classmethod
    def _url_matches_pattern(cls, value: str) -> str:
        return _validate_github_url(value)

    @field_validator("owner", "repo")
    @classmethod
    def _owner_repo_matches_pattern(cls, value: str) -> str:
        return _validate_owner_or_repo(value)


class GitHubIssueHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["handoff.github_issue"] = Field(
        exclude=True, default="handoff.github_issue"
    )
    url: str
    owner: str
    repo: str
    issue_number: int = Field(ge=1)
    triggered_by: TriggeredBy

    @field_validator("url")
    @classmethod
    def _url_matches_pattern(cls, value: str) -> str:
        return _validate_github_url(value)

    @field_validator("owner", "repo")
    @classmethod
    def _owner_repo_matches_pattern(cls, value: str) -> str:
        return _validate_owner_or_repo(value)


class PingMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ping"] = Field(exclude=True, default="ping")
    extension_version: str | None = None
    safari_version: str | None = None


class AcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["response.accepted"] = Field(
        exclude=True, default="response.accepted"
    )
    in_response_to: str
    action: str
    message: str | None = None
    repository_status: RepositoryStatus

    @field_validator("in_response_to", "action")
    @classmethod
    def _non_empty_str(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class DeferredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["response.deferred"] = Field(
        exclude=True, default="response.deferred"
    )
    in_response_to: str
    action: str
    message: str | None = None
    deferral_reason: DeferralReason

    @field_validator("in_response_to", "action")
    @classmethod
    def _non_empty_str(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class RefusedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["response.refused"] = Field(exclude=True, default="response.refused")
    in_response_to: str
    action: str
    message: str | None = None
    refusal_reason: RefusalReason

    @field_validator("in_response_to", "action")
    @classmethod
    def _non_empty_str(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class AppUnavailableResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["response.app_unavailable"] = Field(
        exclude=True, default="response.app_unavailable"
    )
    message: str
    reason: UnavailableReason | None = None

    @field_validator("message")
    @classmethod
    def _non_empty_str(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be a non-empty string")
        return value


_HandoffPayload = (
    GitHubRepositoryHandoff
    | GitHubPullRequestHandoff
    | GitHubIssueHandoff
    | PingMessage
)
_ResponsePayload = (
    AcceptedResponse | DeferredResponse | RefusedResponse | AppUnavailableResponse
)
_Payload = _HandoffPayload | _ResponsePayload


class SafariExtensionMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["rig.relay.safari_extension_message.v1"] = (
        SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION
    )
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    direction: MessageDirection
    kind: str
    payload: Annotated[_Payload, Field(discriminator="kind")]
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @model_validator(mode="before")
    @classmethod
    def _inject_kind_into_payload(cls, data: Any) -> Any:
        if isinstance(data, dict) and "payload" in data and "kind" in data:
            payload = data["payload"]
            if isinstance(payload, dict) and "kind" not in payload:
                payload["kind"] = data["kind"]
        return data

    @model_validator(mode="after")
    def _ensure_direction_matches_kind(self) -> SafariExtensionMessage:
        if self.direction == MessageDirection.EXTENSION_TO_APP:
            if self.kind not in _EXTENSION_KINDS:
                raise ValueError(
                    f"kind '{self.kind}' is not valid for direction '{self.direction.value}'"
                )
        elif self.direction == MessageDirection.APP_TO_EXTENSION:
            if self.kind not in _APP_KINDS:
                raise ValueError(
                    f"kind '{self.kind}' is not valid for direction '{self.direction.value}'"
                )
        return self

    def validate_content_light(self) -> list[str]:
        violations: list[str] = []
        raw = self.model_dump_json()

        if _TOKEN_PATTERNS.search(raw):
            violations.append("message contains GitHub token pattern")

        forbidden_keys = {"file_contents", "html", "raw_prompt", "model_output"}
        payload_dict = self.payload.model_dump(exclude={"kind"})
        if isinstance(payload_dict, dict):
            if forbidden_keys & set(payload_dict.keys()):
                violations.append(
                    f"payload contains forbidden key: {forbidden_keys & set(payload_dict.keys())}"
                )

        if violations:
            return violations

        message_str = getattr(self.payload, "message", None)
        if isinstance(message_str, str) and len(message_str) > _MAX_MESSAGE_LENGTH:
            violations.append("message field exceeds 10,000 characters")

        return violations


def validate_content_light(message: SafariExtensionMessage) -> bool:
    return len(message.validate_content_light()) == 0


__all__ = [
    "SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION",
    "AcceptedResponse",
    "AppUnavailableResponse",
    "DeferralReason",
    "DeferredResponse",
    "GitHubIssueHandoff",
    "GitHubPullRequestHandoff",
    "GitHubRepositoryHandoff",
    "MessageDirection",
    "MessageKind",
    "PageKind",
    "PingMessage",
    "RefusalReason",
    "RefusedResponse",
    "RepositoryStatus",
    "SafariExtensionMessage",
    "TriggeredBy",
    "UnavailableReason",
    "validate_content_light",
]
