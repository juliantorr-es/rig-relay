from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.events.seed_bridge_lifecycle import build_seed_events

pytestmark = [pytest.mark.adversarial]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SEED_PATH = (
    REPO_ROOT / ".build" / "rig-relay" / "events" / "seeded_bridge_lifecycle.v1.jsonl"
)

HTML_PATH = (
    REPO_ROOT / ".build" / "rig-relay" / "static" / "mission_topology_spiderweb.v1.html"
)

MANIFEST_PATH = (
    REPO_ROOT
    / ".build"
    / "rig-relay"
    / "static"
    / "mission_topology_spiderweb_manifest.v1.json"
)

TOKEN_PATTERNS = ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_")

SENSITIVE_COMBOS = ("BEGIN PRIVATE KEY", "bearer", "Bearer")
REDACT_FIELDS = ("access_token", "authorization", "api_key", "token")


def test_seeded_jsonl_has_no_token_like_strings(tmp_path: Path):
    seed_path = tmp_path / "seeded.jsonl"
    build_seed_events(seed_output_path=seed_path)
    raw_text = seed_path.read_text("utf-8")
    for pattern in TOKEN_PATTERNS:
        assert pattern not in raw_text, f"found token pattern: {pattern}"


def test_committed_seed_jsonl_has_no_token_like_strings():
    if not SEED_PATH.exists():
        pytest.skip("Committed seed JSONL not found")
    raw_text = SEED_PATH.read_text("utf-8")
    for pattern in TOKEN_PATTERNS:
        assert pattern not in raw_text, f"found token pattern: {pattern}"


def test_static_html_has_no_unsafe_innerhtml_with_topology_data():
    if not HTML_PATH.exists():
        pytest.skip("Static HTML not found")
    html = HTML_PATH.read_text("utf-8")
    inner_html_lines = [
        line.strip() for line in html.splitlines() if ".innerHTML" in line
    ]
    for line in inner_html_lines:
        assert "event_id" not in line, (
            f"unsafe innerHTML with topology data: {line[:80]}"
        )
        assert "correlation_id" not in line, (
            f"unsafe innerHTML with topology data: {line[:80]}"
        )
        assert "causation_id" not in line, (
            f"unsafe innerHTML with topology data: {line[:80]}"
        )


def test_static_html_has_no_fetch_xmlhttprequest_websocket():
    if not HTML_PATH.exists():
        pytest.skip("Static HTML not found")
    html = HTML_PATH.read_text("utf-8")
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert "new WebSocket" not in html
    assert "ws://" not in html
    assert "wss://" not in html


def test_static_html_embedded_topology_no_raw_payload_exposure():
    if not HTML_PATH.exists():
        pytest.skip("Static HTML not found")
    html = HTML_PATH.read_text("utf-8")
    script_start = html.find('id="topology-data"')
    if script_start == -1:
        return
    script_end = html.find("</script>", script_start)
    topology_block = html[script_start:script_end]
    topology_str = topology_block[topology_block.find(">") + 1 :].strip()
    try:
        topology = json.loads(topology_str)
    except json.JSONDecodeError:
        return
    serialized = json.dumps(topology)
    assert "access_token" not in serialized
    assert "api_key" not in serialized
    assert "authorization" not in serialized
    for field in topology.get("payload", {}):
        assert field not in REDACT_FIELDS


def test_static_html_has_no_remote_font_script_style_refs():
    if not HTML_PATH.exists():
        pytest.skip("Static HTML not found")
    html = HTML_PATH.read_text("utf-8")
    assert 'href="https://fonts.googleapis.com' not in html
    assert "fonts.googleapis.com" not in html
    assert 'src="https://' not in html
    assert 'href="https://cdn' not in html


def test_seeded_events_all_redaction_status_passed(tmp_path: Path):
    seed_path = tmp_path / "seeded.jsonl"
    build_seed_events(seed_output_path=seed_path)
    for line in seed_path.read_text("utf-8").strip().splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        assert event["redaction_status"] == "passed", (
            f"event {event.get('event_id')} redaction_status={event['redaction_status']}"
        )


def test_all_artifacts_pass_basic_redaction_scan(tmp_path: Path):
    seed_path = tmp_path / "seeded.jsonl"
    build_seed_events(seed_output_path=seed_path)
    for artifact_path in (seed_path,):
        content = artifact_path.read_text("utf-8")
        for pattern in SENSITIVE_COMBOS:
            assert pattern not in content, (
                f"found sensitive pattern '{pattern}' in {artifact_path}"
            )

    if HTML_PATH.exists():
        html = HTML_PATH.read_text("utf-8")
        for pattern in SENSITIVE_COMBOS:
            assert pattern not in html, f"found sensitive pattern '{pattern}' in HTML"


def test_manifest_has_raw_payloads_exposed_false():
    if not MANIFEST_PATH.exists():
        pytest.skip("Manifest not found")
    manifest = json.loads(MANIFEST_PATH.read_text("utf-8"))
    assert manifest.get("raw_payloads_exposed") is False
