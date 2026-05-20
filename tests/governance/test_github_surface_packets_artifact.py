from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.real_artifact]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    REPO_ROOT / "docs" / "schemas" / "rig.github.surface_packets.v1.schema.json"
)
REPORT_PATH = (
    REPO_ROOT / "docs" / "json" / "governance" / "github_surface_packets_v1.v1.json"
)


def test_surface_packets_artifact_validates_and_stays_content_light():
    assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"
    assert REPORT_PATH.exists(), f"Report file not found at {REPORT_PATH}"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(instance=report, schema=schema)

    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        "ghp_",
        "gho_",
        "ghu_",
        "ghs_",
        "github_pat_",
        "token_prefix",
        "access_token",
        "authorization",
        "raw_response",
        "raw_body",
    ):
        assert forbidden not in serialized

    assert report["schema_version"] == "rig.github.surface_packets.v1"
    assert report["content_light"] is True
    assert report["remote_mutation"] is False
    assert report["local_mutation"] is False
    assert isinstance(report["packets"], list)
    assert isinstance(report["summary"], dict)

    for packet in report["packets"]:
        assert packet["apply_ready"] is False
        assert packet["local_mutation"] is False
        assert packet["remote_mutation"] is False
        assert packet["generated_public_text_allowed"] is False
        assert len(packet["packet_id"]) == 64
