from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest

from rig_relay.desktop.projection import _build_resources

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.real_artifact]

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.event.resource_projection_snapshot.v1.schema.json"
)

REQUIRED_FIELDS = {
    "bridge_backend_health",
    "projection_freshness",
    "reconnect_pressure",
    "event_queue_pressure",
    "consumer_error_count",
    "redaction_status",
}

GITHUB_TOKEN_PATTERNS = ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_")

CREDENTIAL_FIELDS = {"access_token", "token_prefix", "authorization"}


def _validate_against_schema(data: dict, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text("utf-8"))
    jsonschema.Draft7Validator(schema).validate(data)


def test_build_resources_returns_dict_with_available_true():
    result = _build_resources()
    assert isinstance(result, dict)
    assert result["available"] is True


def test_result_includes_all_required_resource_fields():
    result = _build_resources()
    for field in REQUIRED_FIELDS:
        assert field in result, f"missing required field: {field}"


def test_result_validates_against_resource_projection_snapshot_schema():
    result = _build_resources()
    validated = {k: v for k, v in result.items() if k != "available"}
    _validate_against_schema(validated, SCHEMA_PATH)


def test_result_contains_no_raw_event_payload_data():
    result = _build_resources()
    result_str = json.dumps(result)
    for pattern in GITHUB_TOKEN_PATTERNS:
        assert pattern not in result_str, f"found token pattern: {pattern}"
    for field in CREDENTIAL_FIELDS:
        assert field not in result, f"found credential field: {field}"
    secret_indicators = ("Bearer ", "sk-or-", "x-api-key")
    for indicator in secret_indicators:
        assert indicator not in result_str, f"found secret indicator: {indicator}"


def test_build_resources_returns_valid_fallback_on_import_failure():
    with patch(
        "rig_relay.events.resource_projection_feed.ResourceProjectionFeed",
        side_effect=Exception("Boom"),
    ):
        result = _build_resources()
    assert result["available"] is False
    assert result["bridge_backend_health"] == "unknown"
    assert result["projection_freshness"] == "unknown"
    assert result["reconnect_pressure"] == "none"
    assert result["event_queue_pressure"] == "none"
    assert result["consumer_error_count"] == 0
    assert result["redaction_status"] == "content_light"
