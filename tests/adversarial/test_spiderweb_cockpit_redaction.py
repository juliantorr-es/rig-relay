from __future__ import annotations

import json

import pytest

from rig_relay.desktop.projection import build_projection

pytestmark = [pytest.mark.adversarial]

GITHUB_TOKEN_PATTERNS = ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_")

RAW_PAYLOAD_KEYS = {
    "raw_body",
    "raw_response",
    "raw_event",
    "raw_payload",
    "event_payload",
    "full_event",
    "full_artifact",
}


def _spiderweb_section() -> dict:
    return build_projection()["spiderweb_topology"]


def test_spiderweb_topology_section_has_no_token_like_strings():
    section = _spiderweb_section()
    serialized = json.dumps(section)
    for pattern in GITHUB_TOKEN_PATTERNS:
        assert pattern not in serialized, f"found token pattern: {pattern}"


def test_spiderweb_topology_has_no_raw_payload_exposure():
    section = _spiderweb_section()
    assert "raw_payloads_exposed" in section
    assert section["raw_payloads_exposed"] is False


def test_spiderweb_topology_raw_payloads_exposed_is_false():
    section = _spiderweb_section()
    assert section["raw_payloads_exposed"] is False


def test_spiderweb_topology_serialized_json_has_no_raw_event_payload_keys():
    section = _spiderweb_section()
    serialized = json.dumps(section)
    for key in RAW_PAYLOAD_KEYS:
        assert f'"{key}"' not in serialized, f"found raw payload key: {key}"


def test_spiderweb_topology_redaction_status_is_content_light():
    section = _spiderweb_section()
    assert section["redaction_status"] == "content_light"
