from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pydantic
import pytest

from rig_relay.extensions.safari.models import (
    SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
    MessageDirection,
    PageKind,
    PingMessage,
    SafariExtensionMessage,
    TriggeredBy,
    validate_content_light,
)

SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.relay.safari_extension_message.v1.schema.json"
)


def _validate_against_jsonschema(instance: dict[str, Any]) -> None:
    if not SCHEMA_PATH.exists():
        pytest.skip(f"Schema file not found: {SCHEMA_PATH}")
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.validate(instance=instance, schema=schema)


# ── JS-produced golden fixtures ────────────────────────────────────────────


def test_js_handoff_repository_json_validates_as_python_model() -> None:
    js_message = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
        "direction": "extension_to_app",
        "kind": "handoff.github_repository",
        "created_at": "2026-05-26T12:00:00Z",
        "payload": {
            "url": "https://github.com/owner/repo",
            "owner": "owner",
            "repo": "repo",
            "page_kind": "repository_main",
            "triggered_by": "popup_action",
        },
    }
    msg = SafariExtensionMessage.model_validate(js_message)
    assert msg.direction == MessageDirection.EXTENSION_TO_APP
    assert msg.kind == "handoff.github_repository"
    assert validate_content_light(msg)
    _validate_against_jsonschema(js_message)


def test_js_handoff_pull_request_json_validates_as_python_model() -> None:
    js_message = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
        "direction": "extension_to_app",
        "kind": "handoff.github_pull_request",
        "created_at": "2026-05-26T12:01:00Z",
        "payload": {
            "url": "https://github.com/octocat/hello-world/pull/42",
            "owner": "octocat",
            "repo": "hello-world",
            "pr_number": 42,
            "page_kind": "pull_request_conversation",
            "triggered_by": "toolbar_button",
        },
    }
    msg = SafariExtensionMessage.model_validate(js_message)
    assert msg.kind == "handoff.github_pull_request"
    assert validate_content_light(msg)
    _validate_against_jsonschema(js_message)


def test_js_handoff_issue_json_validates_as_python_model() -> None:
    js_message = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "c3d4e5f6-a7b8-4c9d-0e1f-2a3b4c5d6e7f",
        "direction": "extension_to_app",
        "kind": "handoff.github_issue",
        "created_at": "2026-05-26T12:02:00Z",
        "payload": {
            "url": "https://github.com/octocat/hello-world/issues/99",
            "owner": "octocat",
            "repo": "hello-world",
            "issue_number": 99,
            "triggered_by": "popup_action",
        },
    }
    msg = SafariExtensionMessage.model_validate(js_message)
    assert msg.kind == "handoff.github_issue"
    assert validate_content_light(msg)
    _validate_against_jsonschema(js_message)


def test_js_ping_json_validates_as_python_model() -> None:
    js_message = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f8a",
        "direction": "extension_to_app",
        "kind": "ping",
        "created_at": "2026-05-26T12:03:00Z",
        "payload": {"extension_version": "0.1.0"},
    }
    msg = SafariExtensionMessage.model_validate(js_message)
    assert isinstance(msg.payload, PingMessage)
    assert msg.payload.extension_version == "0.1.0"
    assert validate_content_light(msg)
    _validate_against_jsonschema(js_message)


def test_js_accepted_response_json_validates() -> None:
    js_message = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "e5f6a7b8-c9d0-4e1f-2a3b-4c5d6e7f8a9b",
        "direction": "app_to_extension",
        "kind": "response.accepted",
        "created_at": "2026-05-26T12:04:00Z",
        "payload": {
            "in_response_to": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
            "action": "open_in_rig_relay",
            "repository_status": "known_and_available",
        },
    }
    msg = SafariExtensionMessage.model_validate(js_message)
    assert msg.direction == MessageDirection.APP_TO_EXTENSION
    assert msg.kind == "response.accepted"
    assert validate_content_light(msg)


def test_js_refused_response_json_validates() -> None:
    js_message = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "f6a7b8c9-d0e1-4f2a-3b4c-5d6e7f8a9b0c",
        "direction": "app_to_extension",
        "kind": "response.refused",
        "created_at": "2026-05-26T12:05:00Z",
        "payload": {
            "in_response_to": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
            "action": "handoff.github_repository",
            "refusal_reason": "unsupported_github_context",
        },
    }
    msg = SafariExtensionMessage.model_validate(js_message)
    assert msg.kind == "response.refused"
    assert validate_content_light(msg)


def test_js_deferred_response_json_validates() -> None:
    js_message = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "a7b8c9d0-e1f2-4a3b-4c5d-6e7f8a9b0c1d",
        "direction": "app_to_extension",
        "kind": "response.deferred",
        "created_at": "2026-05-26T12:06:00Z",
        "payload": {
            "in_response_to": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
            "action": "handoff.github_repository",
            "deferral_reason": "app_not_connected_to_carte_blanche",
        },
    }
    msg = SafariExtensionMessage.model_validate(js_message)
    assert msg.kind == "response.deferred"
    assert validate_content_light(msg)


def test_js_app_unavailable_json_validates() -> None:
    js_message = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "b8c9d0e1-f2a3-4b4c-5d6e-7f8a9b0c1d2e",
        "direction": "app_to_extension",
        "kind": "response.app_unavailable",
        "created_at": "2026-05-26T12:07:00Z",
        "payload": {
            "message": "Rig Relay app is not running.",
            "reason": "app_not_running",
        },
    }
    msg = SafariExtensionMessage.model_validate(js_message)
    assert msg.kind == "response.app_unavailable"
    assert validate_content_light(msg)


# ── Py→JS↔Py roundtrips ──────────────────────────────────────────────────


def test_envelope_json_matches_js_background_contract() -> None:
    msg = SafariExtensionMessage.model_validate({
        "schema_version": SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
        "direction": "extension_to_app",
        "kind": "handoff.github_repository",
        "payload": {
            "url": "https://github.com/owner/repo",
            "owner": "owner",
            "repo": "repo",
            "page_kind": "repository_main",
            "triggered_by": "popup_action",
        },
    })
    raw = json.loads(msg.model_dump_json())
    assert raw["schema_version"] == "rig.relay.safari_extension_message.v1"
    assert raw["direction"] == "extension_to_app"
    assert raw["kind"] == "handoff.github_repository"
    assert "message_id" in raw
    assert "created_at" in raw
    assert "payload" in raw
    assert raw["payload"]["url"] == "https://github.com/owner/repo"
    assert raw["payload"]["owner"] == "owner"
    assert "kind" not in raw["payload"]


# ── N1 contract shape compatibility ────────────────────────────────────────


def test_q0_message_contains_n1_required_fields() -> None:
    msg = SafariExtensionMessage.model_validate({
        "schema_version": SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
        "direction": "extension_to_app",
        "kind": "handoff.github_repository",
        "payload": {
            "url": "https://github.com/owner/repo",
            "owner": "owner",
            "repo": "repo",
            "page_kind": "repository_main",
            "triggered_by": "popup_action",
        },
    })
    raw = json.loads(msg.model_dump_json())
    n1_envelope_fields = {"schema_version", "message_id", "kind"}
    missing = n1_envelope_fields - set(raw.keys())
    assert not missing, f"Q0 message missing N1 fields: {missing}"


def test_n1_can_extract_url_from_opaque_payload() -> None:
    msg = SafariExtensionMessage.model_validate({
        "schema_version": SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
        "direction": "extension_to_app",
        "kind": "handoff.github_repository",
        "payload": {
            "url": "https://github.com/owner/repo",
            "owner": "owner",
            "repo": "repo",
            "page_kind": "repository_main",
            "triggered_by": "popup_action",
        },
    })
    raw = json.loads(msg.model_dump_json())
    payload = raw["payload"]
    assert "url" in payload
    assert "owner" in payload
    assert "repo" in payload
    assert payload["url"].startswith("https://github.com/")


_EXTENSION_KIND_FIXTURES: dict[str, dict[str, Any]] = {
    "handoff.github_repository": {
        "url": "https://github.com/owner/repo",
        "owner": "owner",
        "repo": "repo",
        "page_kind": "repository_main",
        "triggered_by": "popup_action",
    },
    "handoff.github_pull_request": {
        "url": "https://github.com/owner/repo/pull/1",
        "owner": "owner",
        "repo": "repo",
        "pr_number": 1,
        "page_kind": "pull_request_conversation",
        "triggered_by": "popup_action",
    },
    "handoff.github_issue": {
        "url": "https://github.com/owner/repo/issues/1",
        "owner": "owner",
        "repo": "repo",
        "issue_number": 1,
        "triggered_by": "popup_action",
    },
    "ping": {"extension_version": "0.1.0"},
}


def test_n1_kind_strings_are_stable() -> None:
    for kind, payload in _EXTENSION_KIND_FIXTURES.items():
        msg = SafariExtensionMessage.model_validate({
            "schema_version": SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
            "direction": "extension_to_app",
            "kind": kind,
            "payload": payload,
        })
        assert msg.kind == kind


def test_n1_can_detect_kind_before_full_parse() -> None:
    raw = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "test-id",
        "direction": "extension_to_app",
        "kind": "handoff.github_pull_request",
        "created_at": "2026-05-26T12:00:00Z",
        "payload": {
            "url": "https://github.com/owner/repo",
            "owner": "owner",
            "repo": "repo",
            "pr_number": 42,
            "page_kind": "pull_request_conversation",
            "triggered_by": "popup_action",
        },
    }
    assert raw["kind"] == "handoff.github_pull_request"
    msg = SafariExtensionMessage.model_validate(raw)
    assert msg.kind == "handoff.github_pull_request"


# ── Refusal scenarios from JS extension ────────────────────────────────────


def test_refuses_invalid_message_kind() -> None:
    with pytest.raises(pydantic.ValidationError):
        SafariExtensionMessage.model_validate({
            "schema_version": SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
            "direction": "extension_to_app",
            "kind": "unknown.invalid_kind",
            "created_at": "2026-05-26T12:00:00Z",
            "payload": {},
        })


def test_refuses_app_kind_in_extension_direction() -> None:
    with pytest.raises(pydantic.ValidationError):
        SafariExtensionMessage.model_validate({
            "schema_version": SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
            "direction": "extension_to_app",
            "kind": "response.refused",
            "created_at": "2026-05-26T12:00:00Z",
            "payload": {
                "in_response_to": "x",
                "action": "y",
                "refusal_reason": "invalid_message",
            },
        })


def test_js_credential_url_rejected_by_content_light() -> None:
    msg = SafariExtensionMessage.model_validate({
        "schema_version": SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
        "direction": "extension_to_app",
        "kind": "handoff.github_repository",
        "created_at": "2026-05-26T12:00:00Z",
        "payload": {
            "url": "https://github.com/owner/repo",
            "owner": "owner",
            "repo": "repo",
            "page_kind": "repository_main",
            "triggered_by": "popup_action",
        },
    })
    assert validate_content_light(msg)
    raw = json.loads(msg.model_dump_json())
    raw["payload"]["url"] = "https://github.com/owner/repo?access_token=ghp_secret"
    result = SafariExtensionMessage.model_validate(raw)
    assert not validate_content_light(result)


def test_js_message_roundtrip_preserves_pr_number() -> None:
    js_message = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "test-pr-1",
        "direction": "extension_to_app",
        "kind": "handoff.github_pull_request",
        "created_at": "2026-05-26T12:00:00Z",
        "payload": {
            "url": "https://github.com/octocat/hello-world/pull/42",
            "owner": "octocat",
            "repo": "hello-world",
            "pr_number": 42,
            "page_kind": "pull_request_commits",
            "triggered_by": "popup_action",
        },
    }
    msg = SafariExtensionMessage.model_validate(js_message)
    reloaded = SafariExtensionMessage.model_validate_json(msg.model_dump_json())
    assert reloaded.payload.pr_number == 42
    assert reloaded.payload.page_kind == PageKind.PULL_REQUEST_COMMITS


def test_js_message_roundtrip_preserves_issue_number() -> None:
    js_message = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "message_id": "test-issue-1",
        "direction": "extension_to_app",
        "kind": "handoff.github_issue",
        "created_at": "2026-05-26T12:00:00Z",
        "payload": {
            "url": "https://github.com/octocat/hello-world/issues/99",
            "owner": "octocat",
            "repo": "hello-world",
            "issue_number": 99,
            "triggered_by": "popup_action",
        },
    }
    msg = SafariExtensionMessage.model_validate(js_message)
    reloaded = SafariExtensionMessage.model_validate_json(msg.model_dump_json())
    assert reloaded.payload.issue_number == 99


# ── Popup action → envelope contract ───────────────────────────────────────


def test_popup_open_action_produces_valid_handoff() -> None:
    context = {
        "url": "https://github.com/owner/repo",
        "owner": "owner",
        "repo": "repo",
        "pageKind": "repository_main",
    }
    envelope = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "direction": "extension_to_app",
        "kind": "handoff.github_repository",
        "payload": {
            "url": context["url"],
            "owner": context["owner"],
            "repo": context["repo"],
            "page_kind": context["pageKind"],
            "triggered_by": "popup_action",
        },
    }
    msg = SafariExtensionMessage.model_validate(envelope)
    assert msg.direction == MessageDirection.EXTENSION_TO_APP
    assert msg.kind == "handoff.github_repository"
    assert validate_content_light(msg)
    assert msg.payload.triggered_by == TriggeredBy.POPUP_ACTION


def test_popup_study_action_produces_valid_handoff() -> None:
    context = {
        "url": "https://github.com/owner/repo",
        "owner": "owner",
        "repo": "repo",
        "pageKind": "repository_code",
    }
    envelope = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "direction": "extension_to_app",
        "kind": "handoff.github_repository",
        "payload": {
            "url": context["url"],
            "owner": context["owner"],
            "repo": context["repo"],
            "page_kind": context["pageKind"],
            "triggered_by": "popup_action",
        },
    }
    msg = SafariExtensionMessage.model_validate(envelope)
    assert msg.payload.page_kind == PageKind.REPOSITORY_CODE


def test_popup_status_action_produces_valid_handoff() -> None:
    context = {
        "url": "https://github.com/owner/repo",
        "owner": "owner",
        "repo": "repo",
        "pageKind": "repository_main",
    }
    envelope = {
        "schema_version": "rig.relay.safari_extension_message.v1",
        "direction": "extension_to_app",
        "kind": "handoff.github_repository",
        "payload": {
            "url": context["url"],
            "owner": context["owner"],
            "repo": context["repo"],
            "page_kind": context["pageKind"],
            "triggered_by": "popup_action",
        },
    }
    msg = SafariExtensionMessage.model_validate(envelope)
    assert validate_content_light(msg)


def test_popup_action_with_unsupported_page_refuses() -> None:
    with pytest.raises(pydantic.ValidationError):
        SafariExtensionMessage.model_validate({
            "schema_version": SAFARI_EXTENSION_MESSAGE_SCHEMA_VERSION,
            "direction": "extension_to_app",
            "kind": "handoff.github_repository",
            "payload": {
                "url": "https://example.com/not/github",
                "owner": "owner",
                "repo": "repo",
                "page_kind": "repository_main",
                "triggered_by": "popup_action",
            },
        })
