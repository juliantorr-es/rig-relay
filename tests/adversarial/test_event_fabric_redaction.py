from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from rig_relay.events.bridge_integration import bridge_event_from_lifecycle
from rig_relay.events.store import EventStore, EventStoreError
from rig_relay.integrations.github_provider._redaction import safe_summary

pytestmark = [pytest.mark.adversarial]

_TOKEN_LIKE_PATTERNS = [
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
    re.compile(r"gho_[a-zA-Z0-9]{20,}"),
    re.compile(r"ghu_[a-zA-Z0-9]{20,}"),
    re.compile(r"ghs_[a-zA-Z0-9]{20,}"),
    re.compile(r"ghr_[a-zA-Z0-9]{20,}"),
    re.compile(r"github_pat_[a-zA-Z0-9]{20,}"),
]


def _contains_token_like(value: str) -> bool:
    for pat in _TOKEN_LIKE_PATTERNS:
        if pat.search(value):
            return True
    return False


def _recursive_scan(obj: object) -> bool:
    if isinstance(obj, str):
        return _contains_token_like(obj)
    if isinstance(obj, dict):
        return any(_recursive_scan(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_recursive_scan(item) for item in obj)
    return False


def test_bridge_event_from_lifecycle_no_token_like_strings():
    event = bridge_event_from_lifecycle(
        event_name="bridge.connection.begin",
        handshake_id="hs_001",
        correlation_id="corr_001",
        details={"session": "sess_abc"},
    )

    serialized = json.dumps(event)
    assert not _contains_token_like(serialized), (
        f"token-like string found: {serialized[:200]}"
    )


def test_bridge_event_from_lifecycle_with_empty_details_is_clean():
    event = bridge_event_from_lifecycle(
        event_name="bridge.connection.begin",
        handshake_id="hs_002",
        correlation_id="corr_002",
    )

    assert not _recursive_scan(event), "token-like content found in event dict"


def test_store_rejects_access_token_in_payload(tmp_path: Path):
    store = EventStore(path=tmp_path / "events.jsonl")
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "bridge",
        "correlation_id": "corr_001",
        "payload_hash": "a" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {"access_token": "ghp_secret1234567890abcdef"},
    }
    with pytest.raises(EventStoreError, match="raw_content_field_detected"):
        store.append(event)


def test_store_rejects_raw_response_in_payload(tmp_path: Path):
    store = EventStore(path=tmp_path / "events.jsonl")
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_002",
        "event_type": "tool.invocation.completed",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "runtime",
        "correlation_id": "corr_002",
        "payload_hash": "b" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {"raw_response": {"status": 200, "body": "sensitive data"}},
    }
    with pytest.raises(EventStoreError, match="raw_content_field_detected"):
        store.append(event)


def test_store_rejects_patch_in_payload(tmp_path: Path):
    store = EventStore(path=tmp_path / "events.jsonl")
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_003",
        "event_type": "tool.invocation.completed",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "runtime",
        "correlation_id": "corr_003",
        "payload_hash": "c" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {"patch": "+added line\\n-removed line"},
    }
    with pytest.raises(EventStoreError, match="raw_content_field_detected"):
        store.append(event)


def test_store_rejects_diff_in_payload(tmp_path: Path):
    store = EventStore(path=tmp_path / "events.jsonl")
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_004",
        "event_type": "tool.invocation.completed",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "runtime",
        "correlation_id": "corr_004",
        "payload_hash": "d" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {"diff": "--- a/file.py\\n+++ b/file.py"},
    }
    with pytest.raises(EventStoreError, match="raw_content_field_detected"):
        store.append(event)


def test_safe_summary_strips_forbidden_fields():
    data = {
        "event_type": "github.repo.metadata.read",
        "raw_response": {"very": "secret"},
        "patch": "some patch",
        "diff": "some diff",
        "safe_field": "keep_me",
        "access_token": "ghp_abc123private",
        "private_key": "-----BEGIN PRIVATE KEY-----\\n...",
        "nested": {"raw_response": "should remove", "safe_nested": "keep nested"},
        "list_data": [
            {"raw_response": "remove from list"},
            {"safe_list_item": "keep list item"},
        ],
    }

    result = safe_summary(data)

    assert "raw_response" not in result
    assert "patch" not in result
    assert "diff" not in result
    assert result["safe_field"] == "keep_me"
    assert result["access_token"].startswith("sha256:")
    assert result["private_key"].startswith("sha256:")
    assert "raw_response" not in result["nested"]
    assert result["nested"]["safe_nested"] == "keep nested"
    assert "raw_response" not in result["list_data"][0]
    assert result["list_data"][1]["safe_list_item"] == "keep list item"


def test_safe_summary_does_not_modify_original():
    data = {"access_token": "secret123", "keep": "value"}
    safe_summary(data)
    assert data["access_token"] == "secret123"
    assert data["keep"] == "value"


def test_store_rejects_content_light_false(tmp_path: Path):
    store = EventStore(path=tmp_path / "events.jsonl")
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_005",
        "event_type": "test.event",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "test",
        "correlation_id": "corr_005",
        "payload_hash": "e" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": False,
        "payload": {},
    }
    with pytest.raises(EventStoreError, match="content_light must be true"):
        store.append(event)
