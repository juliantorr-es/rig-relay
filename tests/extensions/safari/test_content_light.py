from __future__ import annotations

from typing import Any

from rig_relay.extensions.safari.models import (
    PageKind,
    RepositoryStatus,
    SafariExtensionMessage,
    TriggeredBy,
    validate_content_light,
)


def _make_handoff_envelope(
    extra_payload: dict[str, Any] | None = None,
) -> SafariExtensionMessage:
    payload: dict[str, Any] = {
        "url": "https://github.com/owner/repo",
        "owner": "owner",
        "repo": "repo",
        "page_kind": "repository_main",
        "triggered_by": "popup_action",
    }
    if extra_payload:
        payload.update(extra_payload)
    return SafariExtensionMessage.model_validate({
        "schema_version": "rig.relay.safari_extension_message.v1",
        "direction": "extension_to_app",
        "kind": "handoff.github_repository",
        "payload": payload,
    })


def _make_accepted_envelope(**overrides: Any) -> SafariExtensionMessage:
    payload: dict[str, Any] = {
        "in_response_to": "uuid-1",
        "action": "open_in_rig_relay",
        "repository_status": "known_and_available",
    }
    payload.update(overrides)
    return SafariExtensionMessage.model_validate({
        "schema_version": "rig.relay.safari_extension_message.v1",
        "direction": "app_to_extension",
        "kind": "response.accepted",
        "payload": payload,
    })


def _make_deferred_envelope(**overrides: Any) -> SafariExtensionMessage:
    payload: dict[str, Any] = {
        "in_response_to": "uuid-2",
        "action": "study_repository",
        "deferral_reason": "app_not_connected_to_carte_blanche",
    }
    payload.update(overrides)
    return SafariExtensionMessage.model_validate({
        "schema_version": "rig.relay.safari_extension_message.v1",
        "direction": "app_to_extension",
        "kind": "response.deferred",
        "payload": payload,
    })


def _make_refused_envelope(**overrides: Any) -> SafariExtensionMessage:
    payload: dict[str, Any] = {
        "in_response_to": "uuid-3",
        "action": "open_in_rig_relay",
        "refusal_reason": "action_not_permitted",
    }
    payload.update(overrides)
    return SafariExtensionMessage.model_validate({
        "schema_version": "rig.relay.safari_extension_message.v1",
        "direction": "app_to_extension",
        "kind": "response.refused",
        "payload": payload,
    })


def _make_app_unavailable_envelope(**overrides: Any) -> SafariExtensionMessage:
    payload: dict[str, Any] = {"message": "App not running"}
    payload.update(overrides)
    return SafariExtensionMessage.model_validate({
        "schema_version": "rig.relay.safari_extension_message.v1",
        "direction": "app_to_extension",
        "kind": "response.app_unavailable",
        "payload": payload,
    })


def _make_ping_envelope(**overrides: Any) -> SafariExtensionMessage:
    payload: dict[str, Any] = {"extension_version": "0.1.0"}
    payload.update(overrides)
    return SafariExtensionMessage.model_validate({
        "schema_version": "rig.relay.safari_extension_message.v1",
        "direction": "extension_to_app",
        "kind": "ping",
        "payload": payload,
    })


# ── content_light happy path ──────────────────────────────────────────────


def test_clean_handoff_passes_content_light() -> None:
    msg = _make_handoff_envelope()
    assert validate_content_light(msg)
    assert msg.validate_content_light() == []


def test_detects_ghp_token_in_message() -> None:
    msg = _make_accepted_envelope(message="token leaked: ghp_1234567890abcdef")
    assert not validate_content_light(msg)
    violations = msg.validate_content_light()
    assert len(violations) > 0
    assert any("GitHub token" in v for v in violations)


def test_detects_ghs_token_in_message() -> None:
    msg = _make_accepted_envelope(message="ghs_secret_stuff")
    assert not validate_content_light(msg)


def test_detects_gho_token_in_message() -> None:
    msg = _make_accepted_envelope(message="gho_oauth_token")
    assert not validate_content_light(msg)


def test_detects_github_pat_prefix() -> None:
    msg = _make_accepted_envelope(message="github_pat_11AABBCC")
    assert not validate_content_light(msg)


def test_clean_accepted_response_passes() -> None:
    msg = _make_accepted_envelope()
    assert validate_content_light(msg)


def test_clean_deferred_response_passes() -> None:
    msg = _make_deferred_envelope()
    assert validate_content_light(msg)


def test_clean_refused_response_passes() -> None:
    msg = _make_refused_envelope()
    assert validate_content_light(msg)


def test_app_unavailable_response_passes() -> None:
    msg = _make_app_unavailable_envelope()
    assert validate_content_light(msg)


def test_ping_message_passes() -> None:
    msg = _make_ping_envelope()
    assert validate_content_light(msg)


# ── message length guard ──────────────────────────────────────────────────


def test_rejects_excessively_long_message() -> None:
    long_text = "x" * 10_001
    msg = _make_app_unavailable_envelope(message=long_text)
    assert not validate_content_light(msg)
    violations = msg.validate_content_light()
    assert any("10,000" in v for v in violations)


def test_accepted_response_with_normal_message_passes() -> None:
    msg = _make_accepted_envelope(message="Changes applied to repository settings.")
    assert validate_content_light(msg)


# ── roundtrip validation ──────────────────────────────────────────────────


def test_validates_after_roundtrip() -> None:
    msg = _make_handoff_envelope()
    raw = msg.model_dump_json()
    reloaded = SafariExtensionMessage.model_validate_json(raw)
    assert validate_content_light(reloaded)


# ── enum content safety ───────────────────────────────────────────────────


def test_all_enum_values_are_content_safe() -> None:
    from rig_relay.extensions.safari.models import (
        DeferralReason,
        MessageKind,
        RefusalReason,
        UnavailableReason,
    )

    all_enums = (
        list(MessageKind)
        + list(PageKind)
        + list(TriggeredBy)
        + list(RepositoryStatus)
        + list(DeferralReason)
        + list(RefusalReason)
        + list(UnavailableReason)
    )

    token_substrings = ("ghp_", "ghs_", "gho_", "ghu_", "ghr_", "github_pat_")

    for member in all_enums:
        val = member.value
        for token in token_substrings:
            assert token not in val, (
                f"{member.__class__.__name__}.{member.name} "
                f"contains token pattern {token!r}"
            )


def test_reserved_words_not_in_payload() -> None:
    msg = _make_handoff_envelope()
    payload_dict = msg.payload.model_dump(exclude={"kind"})
    forbidden_keys = {"file_contents", "html", "raw_prompt", "model_output"}
    assert not (forbidden_keys & set(payload_dict.keys()))

    msg2 = _make_accepted_envelope()
    payload_dict2 = msg2.payload.model_dump(exclude={"kind"})
    assert not (forbidden_keys & set(payload_dict2.keys()))
