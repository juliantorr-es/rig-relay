from __future__ import annotations

from rig_relay.evidence.redaction import redact_for_remote

test_kind = "adversarial"


def test_fake_api_keys_redacted() -> None:
    payload = {
        "api_key": "sk-abc123def4567890abcdef",
        "github_token": "ghp_1234567890abcdef123456",
        "slack_bot_token": "xoxb-123-456-abc",
        "openai_api_key": "sk-test1234567890abcdefghij",
    }
    result = redact_for_remote(payload)
    for key in payload:
        value = result.payload[key]
        assert isinstance(value, str)
        assert value == "[REDACTED]" or value.startswith("sha256:"), (
            f"{key} not redacted: {value!r}"
        )


def test_private_paths_hashed() -> None:
    payload = {
        "file_path": "/Users/alice/private/repo/secrets.py",
        "ssh_key": "/home/bob/.ssh/id_rsa",
        "config_path": "C:\\Users\\charlie\\AppData\\Local\\tokens.json",
    }
    result = redact_for_remote(payload)
    for key in payload:
        value = result.payload[key]
        assert isinstance(value, str)
        assert value.startswith("sha256:"), f"{key} not hashed: {value!r}"


def test_env_var_names_not_leaked() -> None:
    payload = {
        "secret_value": "AWS_SECRET_ACCESS_KEY=wJalrXUtn...",
        "api_token": "DEEPSEEK_API_KEY=sk-test1234567890abcdef",
        "token_value": "GITHUB_TOKEN=ghp_1234567890abcdef123456",
        "bare_value": "sk-test1234567890abcdefghijkl",
    }
    result = redact_for_remote(payload)
    assert result.payload["secret_value"].startswith("sha256:")
    assert result.payload["api_token"].startswith("sha256:")
    assert result.payload["token_value"].startswith("sha256:")
    assert result.payload["bare_value"] == "[REDACTED]"


def test_prompt_text_redacted() -> None:
    payload = {
        "raw_prompt": "Here is the system prompt with instructions about tool usage",
        "prompt": "Here is the system prompt with instructions about tool usage",
        "safe_field": "just a normal field",
    }
    result = redact_for_remote(payload)
    assert result.payload["raw_prompt"] == "[REDACTED]"
    assert result.payload["prompt"] == "[REDACTED]"
    assert result.payload["safe_field"] == "just a normal field"


def test_unicode_secrets_redacted() -> None:
    payload = {
        "api_token": "tok_\u03b1\u03b2\u03b3\u03b4\u03b5\u03b6\u03b7\u03b8",
        "secret_key": "secret\U0001f525\U0001f525\U0001f525value",
        "password_field": "\u30d1\u30b9\u30ef\u30fc\u30c9=abc123",
    }
    result = redact_for_remote(payload)
    assert result.payload["api_token"].startswith("sha256:")
    assert result.payload["secret_key"].startswith("sha256:")
    assert result.payload["password_field"].startswith("sha256:")


def test_redaction_preserves_analytical_value() -> None:
    payload = {
        "secret_key": "leaked-value-123",
        "session_id": "sess-abc-123",
        "event_name": "test.completed",
        "receipt_sha256": "sha256:" + "a" * 64,
        "byte_count": 1024,
        "status": "ok",
    }
    result = redact_for_remote(payload)
    assert result.payload["secret_key"].startswith("sha256:")
    assert result.payload["session_id"] == "sess-abc-123"
    assert result.payload["event_name"] == "test.completed"
    assert result.payload["receipt_sha256"] == "sha256:" + "a" * 64
    assert result.payload["byte_count"] == 1024
    assert result.payload["status"] == "ok"


def test_deeply_nested_secrets_redacted() -> None:
    payload = {"a": {"b": {"c": {"d": {"secret_key": "leaked"}}}}}
    result = redact_for_remote(payload)
    nested = result.payload["a"]["b"]["c"]["d"]
    assert nested["secret_key"].startswith("sha256:")


def test_redaction_produces_warnings() -> None:
    payload = {
        "api_key": "sk-test1234567890abcdefghij",
        "raw_prompt": "system instructions here",
    }
    result = redact_for_remote(payload)
    assert len(result.warnings) > 0, "expected warnings, got none"
    warning_text = " ".join(result.warnings)
    assert "api_key" in warning_text


def test_deeply_nested_fake_api_keys_in_json() -> None:
    payload = {
        "top": {
            "middle": {
                "bottom": {
                    "tools": [
                        {"name": "bash", "api_key": "sk-deeply-buried-key-12345"},
                        {"name": "write", "safe": True},
                    ],
                    "provider_api_key": "sk-another-key-at-same-level",
                }
            }
        }
    }
    result = redact_for_remote(payload)
    tool0 = result.payload["top"]["middle"]["bottom"]["tools"][0]
    assert tool0["api_key"] == "[REDACTED]" or tool0["api_key"].startswith("sha256:")
    provider_key = result.payload["top"]["middle"]["bottom"]["provider_api_key"]
    assert provider_key == "[REDACTED]" or provider_key.startswith("sha256:")


def test_weird_unicode_in_secrets_redacted() -> None:
    payload = {
        "api_token": "tok_\u03b1\u03b2\u03b3\u03b4\u03b5\u03b6\u03b7\u03b8\u03b9\u03ba\u03bb\u03bc\u03bd\u03be\u03bf\u03c0\u03c1\u03c2\u03c3",
        "nested": {
            "secret_key": "key\U0001f525\U0001f525\U0001f525\U0001f525\U0001f525_val"
        },
        "emoji_secret": "\U0001f512 secret \u2605 value \u2622",
    }
    result = redact_for_remote(payload)
    assert result.payload["api_token"].startswith("sha256:")
    assert result.payload["nested"]["secret_key"].startswith("sha256:")
    emoji = result.payload["emoji_secret"]
    assert emoji.startswith("sha256:") or emoji == "[REDACTED]"


def test_env_var_style_credentials_redacted() -> None:
    payload = {
        "env": {
            "DEEPSEEK_API_KEY": "sk-deepseek-env-key-12345abcd",
            "OPENAI_API_KEY": "sk-openai-env-key-67890efgh",
            "ANTHROPIC_API_KEY": "sk-ant-anthropic-key-deeply-hidden",
            "GITHUB_TOKEN": "ghp_github_env_token_abcdef",
            "HARMLESS_VAR": "just a regular value",
        }
    }
    result = redact_for_remote(payload)
    env = result.payload["env"]
    for sensitive_key in [
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
    ]:
        assert env[sensitive_key] == "[REDACTED]" or env[sensitive_key].startswith(
            "sha256:"
        )
    assert env["HARMLESS_VAR"] == "just a regular value"


def test_repo_local_paths_hashed_not_leaked() -> None:
    payload = {"config_path": "/home/user/projects/rig-relay/.rig/reports/config.json"}
    result = redact_for_remote(payload)
    assert (
        result.payload["config_path"].startswith("sha256:")
        or result.payload["config_path"] == "[REDACTED]"
    )


def test_bearer_token_patterns_redacted() -> None:
    payload = {
        "header": "Bearer sk-test-bearer-token-very-long-key-12345",
        "auth": "Bearer ghp_bearer_github_personal_access_token",
        "safe_field": "this has bearer but no valid pattern",
    }
    result = redact_for_remote(payload)
    assert (
        result.payload["header"].startswith("sha256:")
        or result.payload["header"] == "[REDACTED]"
    )
    assert (
        result.payload["auth"].startswith("sha256:")
        or result.payload["auth"] == "[REDACTED]"
    )
    assert result.payload["safe_field"] == "this has bearer but no valid pattern"


def test_array_of_api_keys_all_redacted() -> None:
    payload = {
        "provider_keys": [
            {"name": "key1", "api_key": "sk-abc123"},
            {"name": "key2", "api_key": "sk-def456"},
            {"name": "safe", "value": "ok"},
        ]
    }
    result = redact_for_remote(payload)
    items = result.payload["provider_keys"]
    assert isinstance(items, list), f"expected list, got {type(items)}"
    assert items[0]["api_key"] == "[REDACTED]" or items[0]["api_key"].startswith(
        "sha256:"
    )
    assert items[1]["api_key"] == "[REDACTED]" or items[1]["api_key"].startswith(
        "sha256:"
    )
    assert items[2]["value"] == "ok"
