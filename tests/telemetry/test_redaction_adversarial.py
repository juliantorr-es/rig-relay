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
        assert value.startswith("sha256:"), (
            f"{key} not hashed: {value!r}"
        )


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
