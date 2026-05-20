from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.desktop.projection import _build_resources

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.event.resource_projection_snapshot.v1.schema.json"
)


def test_build_resources_output_validates_against_schema():
    result = _build_resources()
    validated = {k: v for k, v in result.items() if k != "available"}
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    jsonschema.Draft7Validator(schema).validate(validated)


def test_build_resources_output_is_content_light():
    result = _build_resources()
    assert result["redaction_status"] == "content_light"
    result_str = json.dumps(result)
    assert "ghp_" not in result_str
    assert "Bearer" not in result_str
    assert "access_token" not in result


def test_build_resources_output_has_no_credential_keys():
    result = _build_resources()
    credential_keys = {"access_token", "token_prefix", "authorization", "api_key"}
    for key in credential_keys:
        assert key not in result, f"credential key found in output: {key}"
