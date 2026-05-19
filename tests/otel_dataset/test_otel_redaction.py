from __future__ import annotations

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.adversarial]

from rig_relay.otel_dataset._redact import redact_otel_attributes


def test_prompt_and_completion_attributes_are_not_retained() -> None:
    result = redact_otel_attributes({
        "raw_prompt": "system instructions",
        "prompt": "user text",
        "raw_completion": "assistant output",
        "model_output": "assistant output",
        "safe": "ok",
    })

    assert result.attributes["safe"] == "ok"
    assert result.attributes["raw_prompt"] != "system instructions"
    assert result.attributes["prompt"] != "user text"
    assert result.attributes["raw_completion"] != "assistant output"
    assert result.attributes["model_output"] != "assistant output"


def test_credentials_are_dropped_or_hashed() -> None:
    result = redact_otel_attributes({
        "api_key": "sk-test-123",
        "bearer_token": "Bearer abc",
        "github_token": "ghp_test",
    })

    assert result.attributes["api_key"] != "sk-test-123"
    assert result.attributes["bearer_token"] != "Bearer abc"
    assert result.attributes["github_token"] != "ghp_test"


def test_absolute_paths_are_not_retained() -> None:
    result = redact_otel_attributes({
        "workspace.path": "/Users/user/Developer/GitHub/rig-relay",
        "file.path": "/tmp/private.txt",
    })

    assert (
        result.attributes["workspace.path"] != "/Users/user/Developer/GitHub/rig-relay"
    )
    assert result.attributes["file.path"] != "/tmp/private.txt"
