from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

import pydantic
import pytest

from rig_relay.extensions.safari.models import (
    SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
    AcceptedResponse,
    AppUnavailableResponse,
    DeferredResponse,
    GitHubIssueHandoff,
    GitHubPullRequestHandoff,
    GitHubRepositoryHandoff,
    MessageDirection,
    MessageKind,
    PageKind,
    PingMessage,
    RefusalReason,
    RefusedResponse,
    RepositoryStatus,
    SafariExtensionMessage,
    TriggeredBy,
)


def _build_envelope(
    kind: str, direction: MessageDirection, payload: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
        "direction": direction.value,
        "kind": kind,
        "payload": payload,
    }


def _reparse(envelope: SafariExtensionMessage) -> SafariExtensionMessage:
    raw = envelope.model_dump_json()
    return SafariExtensionMessage.model_validate_json(raw)


# ── message envelope tests ───────────────────────────────────────────────


def test_envelope_auto_generates_message_id(
    sample_repository_handoff_dict: dict[str, Any],
) -> None:
    data = _build_envelope(
        "handoff.github_repository",
        MessageDirection.EXTENSION_TO_APP,
        sample_repository_handoff_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    assert msg.message_id
    assert isinstance(msg.message_id, str)
    assert len(msg.message_id) > 0


def test_envelope_auto_generates_created_at(
    sample_repository_handoff_dict: dict[str, Any],
) -> None:
    data = _build_envelope(
        "handoff.github_repository",
        MessageDirection.EXTENSION_TO_APP,
        sample_repository_handoff_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    assert msg.created_at
    parsed = datetime.fromisoformat(msg.created_at)
    assert parsed.tzinfo == UTC


def test_envelope_has_fixed_schema_version(
    sample_repository_handoff_dict: dict[str, Any],
) -> None:
    data = _build_envelope(
        "handoff.github_repository",
        MessageDirection.EXTENSION_TO_APP,
        sample_repository_handoff_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    assert msg.schema_version == "rig.relay.safari_extension_message.v1"


# ── roundtrip tests ──────────────────────────────────────────────────────


def test_repository_handoff_roundtrip(
    sample_repository_handoff_dict: dict[str, Any],
) -> None:
    data = _build_envelope(
        "handoff.github_repository",
        MessageDirection.EXTENSION_TO_APP,
        sample_repository_handoff_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    assert isinstance(msg.payload, GitHubRepositoryHandoff)
    reloaded = _reparse(msg)
    assert isinstance(reloaded.payload, GitHubRepositoryHandoff)
    assert reloaded.payload.url == sample_repository_handoff_dict["url"]
    assert reloaded.payload.owner == sample_repository_handoff_dict["owner"]
    assert reloaded.payload.repo == sample_repository_handoff_dict["repo"]


def test_pr_handoff_roundtrip(sample_pr_handoff_dict: dict[str, Any]) -> None:
    data = _build_envelope(
        "handoff.github_pull_request",
        MessageDirection.EXTENSION_TO_APP,
        sample_pr_handoff_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    assert isinstance(msg.payload, GitHubPullRequestHandoff)
    reloaded = _reparse(msg)
    assert isinstance(reloaded.payload, GitHubPullRequestHandoff)
    assert reloaded.payload.pr_number == 42


def test_issue_handoff_roundtrip(sample_issue_handoff_dict: dict[str, Any]) -> None:
    data = _build_envelope(
        "handoff.github_issue",
        MessageDirection.EXTENSION_TO_APP,
        sample_issue_handoff_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    assert isinstance(msg.payload, GitHubIssueHandoff)
    reloaded = _reparse(msg)
    assert isinstance(reloaded.payload, GitHubIssueHandoff)
    assert reloaded.payload.issue_number == 99


def test_ping_roundtrip(sample_ping_dict: dict[str, Any]) -> None:
    data = _build_envelope("ping", MessageDirection.EXTENSION_TO_APP, sample_ping_dict)
    msg = SafariExtensionMessage.model_validate(data)
    assert isinstance(msg.payload, PingMessage)
    reloaded = _reparse(msg)
    assert isinstance(reloaded.payload, PingMessage)
    assert reloaded.payload.extension_version == "0.1.0"


def test_accepted_response_roundtrip(
    sample_accepted_response_dict: dict[str, Any],
) -> None:
    data = _build_envelope(
        "response.accepted",
        MessageDirection.APP_TO_EXTENSION,
        sample_accepted_response_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    assert isinstance(msg.payload, AcceptedResponse)
    reloaded = _reparse(msg)
    assert isinstance(reloaded.payload, AcceptedResponse)
    assert reloaded.payload.in_response_to == "uuid-1"
    assert reloaded.payload.repository_status == RepositoryStatus.KNOWN_AND_AVAILABLE


def test_deferred_response_roundtrip(
    sample_deferred_response_dict: dict[str, Any],
) -> None:
    data = _build_envelope(
        "response.deferred",
        MessageDirection.APP_TO_EXTENSION,
        sample_deferred_response_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    assert isinstance(msg.payload, DeferredResponse)
    reloaded = _reparse(msg)
    assert isinstance(reloaded.payload, DeferredResponse)
    assert reloaded.payload.in_response_to == "uuid-2"


def test_refused_response_roundtrip(
    sample_refused_response_dict: dict[str, Any],
) -> None:
    data = _build_envelope(
        "response.refused",
        MessageDirection.APP_TO_EXTENSION,
        sample_refused_response_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    assert isinstance(msg.payload, RefusedResponse)
    reloaded = _reparse(msg)
    assert isinstance(reloaded.payload, RefusedResponse)
    assert reloaded.payload.in_response_to == "uuid-3"
    assert reloaded.payload.refusal_reason == RefusalReason.ACTION_NOT_PERMITTED


def test_app_unavailable_response_roundtrip(
    sample_app_unavailable_response_dict: dict[str, Any],
) -> None:
    data = _build_envelope(
        "response.app_unavailable",
        MessageDirection.APP_TO_EXTENSION,
        sample_app_unavailable_response_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    assert isinstance(msg.payload, AppUnavailableResponse)
    reloaded = _reparse(msg)
    assert isinstance(reloaded.payload, AppUnavailableResponse)
    assert reloaded.payload.message == "App not running"


# ── validation tests ─────────────────────────────────────────────────────


def test_rejects_invalid_owner_with_special_chars() -> None:
    with pytest.raises(pydantic.ValidationError):
        GitHubRepositoryHandoff(
            url="https://github.com/valid-owner/repo",
            owner="bad owner",
            repo="repo",
            page_kind=PageKind.REPOSITORY_MAIN,
            triggered_by=TriggeredBy.POPUP_ACTION,
        )


def test_rejects_invalid_repo_with_special_chars() -> None:
    with pytest.raises(pydantic.ValidationError):
        GitHubRepositoryHandoff(
            url="https://github.com/owner/valid-repo",
            owner="owner",
            repo="bad repo!",
            page_kind=PageKind.REPOSITORY_MAIN,
            triggered_by=TriggeredBy.POPUP_ACTION,
        )


def test_rejects_non_github_url() -> None:
    with pytest.raises(pydantic.ValidationError):
        GitHubRepositoryHandoff(
            url="https://example.com/owner/repo",
            owner="owner",
            repo="repo",
            page_kind=PageKind.REPOSITORY_MAIN,
            triggered_by=TriggeredBy.POPUP_ACTION,
        )


def test_rejects_http_url() -> None:
    with pytest.raises(pydantic.ValidationError):
        GitHubRepositoryHandoff(
            url="http://github.com/owner/repo",
            owner="owner",
            repo="repo",
            page_kind=PageKind.REPOSITORY_MAIN,
            triggered_by=TriggeredBy.POPUP_ACTION,
        )


def test_rejects_pr_number_zero() -> None:
    with pytest.raises(pydantic.ValidationError):
        GitHubPullRequestHandoff(
            url="https://github.com/owner/repo/pull/0",
            owner="owner",
            repo="repo",
            pr_number=0,
            page_kind=PageKind.PULL_REQUEST_CONVERSATION,
            triggered_by=TriggeredBy.TOOLBAR_BUTTON,
        )


def test_rejects_issue_number_zero() -> None:
    with pytest.raises(pydantic.ValidationError):
        GitHubIssueHandoff(
            url="https://github.com/owner/repo/issues/0",
            owner="owner",
            repo="repo",
            issue_number=0,
            triggered_by=TriggeredBy.POPUP_ACTION,
        )


def test_rejects_direction_kind_mismatch() -> None:
    data = _build_envelope(
        "response.accepted",
        MessageDirection.EXTENSION_TO_APP,
        {
            "in_response_to": "x",
            "action": "y",
            "repository_status": "known_and_available",
        },
    )
    with pytest.raises(pydantic.ValidationError):
        SafariExtensionMessage.model_validate(data)


def test_rejects_app_kind_with_extension_direction() -> None:
    data = _build_envelope(
        "handoff.github_repository",
        MessageDirection.APP_TO_EXTENSION,
        {
            "url": "https://github.com/owner/repo",
            "owner": "owner",
            "repo": "repo",
            "page_kind": "repository_main",
            "triggered_by": "popup_action",
        },
    )
    with pytest.raises(pydantic.ValidationError):
        SafariExtensionMessage.model_validate(data)


def test_rejects_extra_fields() -> None:
    with pytest.raises(pydantic.ValidationError):
        GitHubRepositoryHandoff(
            url="https://github.com/owner/repo",
            owner="owner",
            repo="repo",
            page_kind=PageKind.REPOSITORY_MAIN,
            triggered_by=TriggeredBy.POPUP_ACTION,
            extra_field="should not be here",  # type: ignore[call-arg]
        )


# ── serialization tests ──────────────────────────────────────────────────


def test_handoff_payload_excludes_kind_field(
    sample_repository_handoff_dict: dict[str, Any],
) -> None:
    data = _build_envelope(
        "handoff.github_repository",
        MessageDirection.EXTENSION_TO_APP,
        sample_repository_handoff_dict,
    )
    msg = SafariExtensionMessage.model_validate(data)
    payload = msg.payload.model_dump()
    assert "kind" not in payload
    payload_json = msg.payload.model_dump_json()
    payload_dict = json.loads(payload_json)
    assert "kind" not in payload_dict


def test_envelope_serialization_is_deterministic(
    sample_repository_handoff_dict: dict[str, Any],
) -> None:
    data = _build_envelope(
        "handoff.github_repository",
        MessageDirection.EXTENSION_TO_APP,
        sample_repository_handoff_dict,
    )
    msg1 = SafariExtensionMessage.model_validate(data)
    loaded = SafariExtensionMessage.model_validate_json(msg1.model_dump_json())
    assert msg1.model_dump_json() == loaded.model_dump_json()
    assert msg1.payload.model_dump() == loaded.payload.model_dump()


def test_empty_payload_fields_are_present(sample_ping_dict: dict[str, Any]) -> None:
    data = _build_envelope(
        "ping", MessageDirection.EXTENSION_TO_APP, {"extension_version": None}
    )
    msg = SafariExtensionMessage.model_validate(data)
    raw = msg.model_dump_json()
    parsed = json.loads(raw)
    assert parsed["payload"]["extension_version"] is None
    assert "extension_version" in parsed["payload"]


# ── enum member exhaustiveness smoke tests ───────────────────────────────


def test_all_message_kinds_are_valid() -> None:
    for member in MessageKind:
        assert isinstance(member.value, str)
        assert len(member.value) > 0


def test_all_page_kinds_are_valid() -> None:
    for member in PageKind:
        assert isinstance(member.value, str)
        assert len(member.value) > 0


def test_all_directions_are_valid() -> None:
    assert MessageDirection.EXTENSION_TO_APP.value == "extension_to_app"
    assert MessageDirection.APP_TO_EXTENSION.value == "app_to_extension"
