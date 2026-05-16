from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.desktop.intent_audit import emit_result
from rig_relay.evidence.redaction import (
    assert_remote_safe,
    content_light_summary,
    hash_sensitive_value,
    redact_for_remote,
)
from scripts import (
    rig_relay_create_chatgpt_dev_bundle as chat_bundle,
    rig_relay_create_telemetry_bundle as telemetry_bundle,
)

pytestmark = [pytest.mark.integration]

def test_redact_for_remote_redacts_sensitive_payload() -> None:
    payload = {
        "authorization_receipt": {"raw": "secret"},
        "raw_prompt_text": "write me a secret",
        "model_output_text": "generated code",
        "stdout_bodies": ["hello"],
        "stderr_bodies": ["oops"],
        "raw_diff": "diff --git a/x b/x",
        "api_token": "tok_1234567890",
        "path": "/Users/user/private/repo/file.py",
        "count": 2,
        "status": "ok",
    }

    result = redact_for_remote(payload)

    assert result.payload["authorization_receipt"] == "[REDACTED]"
    assert result.payload["raw_prompt_text"] == "[REDACTED]"
    assert result.payload["model_output_text"] == "[REDACTED]"
    assert result.payload["stdout_bodies"] == "[REDACTED]"
    assert result.payload["stderr_bodies"] == "[REDACTED]"
    assert result.payload["raw_diff"] == "[REDACTED]"
    assert result.payload["api_token"].startswith("sha256:")
    assert result.payload["path"].startswith("sha256:")
    assert result.payload["count"] == 2
    assert "authorization_receipt" in " ".join(result.warnings)


def test_assert_remote_safe_allows_content_light_payload() -> None:
    payload = {
        "schema_version": "rig.relay.example.v1",
        "count": 3,
        "status": "ok",
        "event_name": "example.completed",
        "receipt_sha256": "sha256:" + "a" * 64,
    }

    assert assert_remote_safe(payload) == payload
    summary = content_light_summary(payload)
    assert summary["redacted_count"] == 0
    assert summary["hashed_count"] == 0


def test_hash_sensitive_value_is_deterministic() -> None:
    assert hash_sensitive_value({"a": 1}) == hash_sensitive_value({"a": 1})


def test_telemetry_bundle_builder_calls_redaction(monkeypatch) -> None:
    called: list[dict[str, object]] = []

    def fake_assert_remote_safe(payload, policy=None):
        called.append(payload)
        return payload

    monkeypatch.setattr(telemetry_bundle, "assert_remote_safe", fake_assert_remote_safe)
    manifest = telemetry_bundle.create_bundle(
        participant_id="anon_test",
        share_level="derived_only",
        derived_dir=Path("/tmp/rig-relay-redaction-empty"),
        reports_dir=Path("/tmp/rig-relay-redaction-empty"),
        output_dir=Path("/tmp/rig-relay-redaction-out"),
        dry_run=True,
    )

    assert called
    assert manifest["content_light_guarantee"] is True


def test_chatgpt_bundle_builder_calls_redaction(monkeypatch, tmp_path: Path) -> None:
    called: list[dict[str, object]] = []

    def fake_assert_remote_safe(payload, policy=None):
        called.append(payload)
        return payload

    monkeypatch.setattr(chat_bundle, "assert_remote_safe", fake_assert_remote_safe)
    exit_code = chat_bundle.main([
        "--build-root",
        str(tmp_path),
        "--docs-root",
        str(tmp_path),
        "--profile",
        "lite",
        "--dry-run",
    ])

    assert called
    assert exit_code == 0


def test_emit_result_strips_raw_receipt(tmp_path: Path) -> None:
    result = {
        "schema_version": "rig.relay.desktop_intent_result.v1",
        "intent_id": "intent_test_001",
        "intent_name": "mint_authorization_receipt_dev",
        "status": "completed",
        "authorization_receipt": {"raw": "secret"},
        "authorization_receipt_sha256": "sha256:" + "1" * 64,
        "authorization_action": "checkpoint.commit",
        "authorization_status": "valid",
        "expires_at": "2026-05-13T00:00:00Z",
        "method": "dev",
    }

    emit_result(result, build_root=tmp_path)
    artifact = tmp_path / "intent_results" / "intent_test_001.json"
    text = artifact.read_text(encoding="utf-8")
    assert '"authorization_receipt":' not in text
    assert "raw" not in text
    loaded = json.loads(text)
    assert loaded["authorization_receipt_sha256"].startswith("sha256:")
