from __future__ import annotations

import json

import pytest

from rig_relay.events.resource_projection_feed import ResourceProjectionFeed

pytestmark = [pytest.mark.adversarial]

GITHUB_TOKEN_PATTERNS = ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_")

CREDENTIAL_FIELDS = {"access_token", "token_prefix", "authorization"}


def make_event(event_type: str, payload: dict | None = None) -> dict:
    return {"event_type": event_type, "payload": payload or {}}


def test_snapshot_has_no_token_like_strings():
    feed = ResourceProjectionFeed()
    snapshot_str = json.dumps(feed.snapshot())
    for pattern in GITHUB_TOKEN_PATTERNS:
        assert pattern not in snapshot_str, f"found token pattern: {pattern}"


def test_snapshot_has_no_credential_fields():
    feed = ResourceProjectionFeed()
    snapshot = feed.snapshot()
    for field in CREDENTIAL_FIELDS:
        assert field not in snapshot, f"found credential field: {field}"


def test_snapshot_has_redaction_status_content_light():
    feed = ResourceProjectionFeed()
    assert feed.snapshot()["redaction_status"] == "content_light"


@pytest.mark.asyncio
async def test_handle_event_with_unknown_event_type_does_not_crash():
    feed = ResourceProjectionFeed()
    await feed.handle_event({
        "event_type": "dismiss_alert",
        "payload": {"destructive": True},
    })
    snapshot = feed.snapshot()
    assert snapshot["redaction_status"] == "content_light"
    assert snapshot["schema_version"] == "rig.event.resource_projection_snapshot.v1"
    assert snapshot["bridge_backend_health"] == "unknown"


@pytest.mark.asyncio
async def test_snapshot_serialized_json_has_no_raw_api_bodies_or_secrets():
    feed = ResourceProjectionFeed()
    await feed.handle_event(
        make_event(
            "bridge.status.updated",
            {"runtime_state": "active", "access_token": "ghp_deadbeef1234"},
        )
    )
    await feed.handle_event(
        make_event(
            "bridge.reconnect_failed", {"error_body": '{"access_token":"secret"}'}
        )
    )
    snapshot = feed.snapshot()
    snapshot_str = json.dumps(snapshot)
    for pattern in GITHUB_TOKEN_PATTERNS:
        assert pattern not in snapshot_str, (
            f"found token pattern in serialized snapshot: {pattern}"
        )
    for field in ("access_token", "token_prefix", "authorization"):
        assert field not in snapshot, f"found {field} in snapshot keys"
    assert "ghp_deadbeef1234" not in snapshot_str
    assert snapshot["bridge_backend_health"] == "active"


@pytest.mark.asyncio
async def test_deeply_nested_event_payloads_do_not_leak_secrets():
    feed = ResourceProjectionFeed()
    await feed.handle_event(
        make_event(
            "projection.stale",
            {"nested": {"deep": {"authorization": "Bearer ghx_super_secret"}}},
        )
    )
    snapshot_str = json.dumps(feed.snapshot())
    assert "Bearer" not in snapshot_str
    assert "ghx_super_secret" not in snapshot_str
    assert "authorization" not in snapshot_str
