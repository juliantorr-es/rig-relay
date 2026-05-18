"""Real browser integration test — proves the frontend JavaScript runs against the
real bridge server and emits correlated golden-path trace events.

Uses Playwright + Chromium. Requires: uv add --dev pytest-playwright && playwright install chromium.

This test does NOT prove pywebview; it proves the HTTP/WS/browser seam.
"""

from __future__ import annotations

import importlib.util as _importlib_util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import pytest

from tests.helpers.bridge_runner import BridgeRunner

pytestmark = pytest.mark.skipif(
    _importlib_util.find_spec("playwright") is None,
    reason="Playwright not installed. Run: uv add --dev pytest-playwright && playwright install chromium",
)


@pytest.fixture
def bridge():
    """Start the real bridge server for each test."""
    runner = BridgeRunner(auth_token="browser-integration-token-32chx")
    runner.start()
    yield runner
    runner.stop()


def test_frontend_boot_emits_started_trace(bridge, page):
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_boot_started", timeout=10)
    event_names = bridge.get_event_names()
    assert any(
        "frontend_boot_started" in n or "frontend.boot_started" in n
        for n in event_names
    ), f"Frontend boot_started not emitted. Events: {event_names}"


def test_frontend_runtime_config_loaded(bridge, page):
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_runtime_config_loaded", timeout=10)
    event_names = bridge.get_event_names()
    assert any("runtime_config_loaded" in n for n in event_names), (
        f"Runtime config loaded not emitted. Events: {event_names}"
    )


def test_frontend_websocket_connecting_emitted(bridge, page):
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_websocket_connecting", timeout=10)
    event_names = bridge.get_event_names()
    assert any("websocket_connecting" in n for n in event_names), (
        f"WebSocket connecting not emitted. Events: {event_names}"
    )


def test_backend_websocket_auth_succeeds(bridge, page):
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "desktop.websocket.auth_ok", timeout=15)
    _wait_for_event(bridge, "frontend_auth_ok", timeout=15)
    event_names = bridge.get_event_names()
    assert any("desktop.websocket.auth_ok" in n for n in event_names), (
        "Backend auth_ok not emitted"
    )
    assert any(
        "frontend_auth_ok" in n or "frontend.auth_ok" in n for n in event_names
    ), "Frontend auth_ok not emitted"


def test_projection_sent_received_rendered(bridge, page):
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "desktop.projection.sent", timeout=15)
    _wait_for_event(bridge, "frontend_projection_received", timeout=15)
    event_names = bridge.get_event_names()
    assert any("desktop.projection.sent" in n for n in event_names), (
        "Projection not sent"
    )
    assert any(
        "frontend_projection_received" in n or "frontend.projection_received" in n
        for n in event_names
    ), "Frontend projection_received not emitted"
    assert any(
        "frontend_projection_rendered" in n or "frontend.projection_rendered" in n
        for n in event_names
    ), "Frontend projection_rendered not emitted"


def test_all_events_carry_same_handshake_id(bridge, page):
    """Proves exactly 1 canonical corr_* handshake_id across all golden-path events."""
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "desktop.projection.sent", timeout=15)

    events = bridge.get_events()
    handshake_ids: set[str] = set()
    for event in events:
        corr = event.get("correlation") or {}
        hid = corr.get("handshake_id")
        if hid:
            handshake_ids.add(hid)
        attrs = event.get("payload") or event.get("attributes") or {}
        hid2 = attrs.get("handshake_id")
        if hid2 and isinstance(hid2, str):
            handshake_ids.add(hid2)

    assert len(handshake_ids) == 1, (
        f"Expected exactly 1 canonical handshake_id, got {len(handshake_ids)}: {handshake_ids}"
    )
    canonical = next(iter(handshake_ids))
    assert canonical.startswith("corr_"), (
        f"Canonical handshake_id should be backend-supplied corr_*, got {canonical}"
    )
    assert canonical == bridge.handshake_id, (
        f"Canonical handshake_id {canonical} != bridge handshake_id {bridge.handshake_id}"
    )


def test_no_token_value_in_trace_payloads(bridge, page):
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "desktop.projection.sent", timeout=15)

    events = bridge.get_events()
    for event in events:
        redact = event.get("redaction") or {}
        assert redact.get("token_value_included") in (False, None), (
            f"token_value_included is true in: {event.get('event_type') or event.get('name')}"
        )
        payload_str = json.dumps(event.get("payload") or {})
        assert "browser-integration-token" not in payload_str, (
            "Token value leaked in payload"
        )


def test_no_token_in_console(bridge, page):
    console_lines: list[str] = []
    page.on("console", lambda msg: console_lines.append(msg.text))
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "desktop.projection.sent", timeout=15)
    for line in console_lines:
        assert "browser-integration-token" not in line, (
            f"Token leaked in console: {line[:100]}"
        )


def test_no_uncaught_page_errors(bridge, page):
    page_errors: list[str] = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "desktop.projection.sent", timeout=15)
    assert len(page_errors) == 0, f"Uncaught page errors: {page_errors}"


def test_no_post_to_ws(bridge, page):
    post_ws_requests: list[str] = []

    def _on_request(request):
        if request.method == "POST" and "/ws" in request.url:
            post_ws_requests.append(f"{request.method} {request.url}")

    page.on("request", _on_request)
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "desktop.projection.sent", timeout=15)
    assert len(post_ws_requests) == 0, (
        f"POST requests to /ws detected: {post_ws_requests}"
    )


def test_frontend_status_rendered(bridge, page):
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_status_rendered", timeout=15)
    event_names = bridge.get_event_names()
    assert any(
        "frontend_status_rendered" in n or "frontend.status_rendered" in n
        for n in event_names
    ), f"Status rendered not emitted. Events: {event_names}"

    for event in bridge.get_events():
        name = event.get("event_type") or event.get("name") or ""
        if "status_rendered" in name:
            payload = event.get("payload") or {}
            detail_str = payload.get("detail") or "{}"
            try:
                detail = (
                    json.loads(detail_str)
                    if isinstance(detail_str, str)
                    else detail_str
                )
            except json.JSONDecodeError:
                detail = {}
            assert detail.get("connection_state") or detail.get("label"), (
                "Status rendered event has no connection_state or label"
            )
            break


def test_debug_panel_receives_state(bridge, page):
    frontend_url = f"{bridge.frontend_url}?boot_debug=1"
    page.goto(frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_transport_state", timeout=15)

    debug_panel = page.query_selector("#debug-panel")
    assert debug_panel is not None, "Debug panel #debug-panel not found in DOM"
    debug_text = debug_panel.text_content() or ""
    assert len(debug_text) > 2, f"Debug panel empty: '{debug_text}'"
    assert "browser-integration-token" not in debug_text, (
        "Token value leaked in debug panel"
    )


def test_canonical_handshake_id_in_frontend_events(bridge, page):
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_boot_started", timeout=10)
    _wait_for_event(bridge, "desktop.projection.sent", timeout=15)

    events = bridge.get_events()
    frontend_hid = None
    for event in events:
        name = event.get("event_type") or event.get("name") or ""
        if "frontend_boot_started" in name or "frontend.boot_started" in name:
            corr = event.get("correlation") or {}
            frontend_hid = corr.get("handshake_id")
            if frontend_hid:
                break

    assert frontend_hid is not None, (
        "frontend_boot_started event has no correlation.handshake_id"
    )
    assert frontend_hid == bridge.handshake_id, (
        f"Frontend handshake_id {frontend_hid} != bridge handshake_id {bridge.handshake_id}"
    )


def test_websocket_auth_uses_canonical_handshake_id(bridge, page):
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "desktop.websocket.auth_ok", timeout=15)

    events = bridge.get_events()
    auth_hid = None
    for event in events:
        name = event.get("event_type") or event.get("name") or ""
        if "desktop.websocket.auth_received" in name and "golden" not in name.lower():
            corr = event.get("correlation") or {}
            auth_hid = corr.get("handshake_id")
            if auth_hid:
                break

    assert auth_hid is not None, (
        "WebSocket auth_received event has no correlation.handshake_id"
    )
    assert auth_hid.startswith("corr_"), (
        f"WebSocket auth should use canonical corr_* handshake_id, got {auth_hid}"
    )
    assert auth_hid == bridge.handshake_id, (
        f"WebSocket auth handshake_id {auth_hid} != bridge handshake_id {bridge.handshake_id}"
    )


# ── Blind spot closure tests ──────────────────────────────────────────


def test_fallback_handshake_when_backend_omits_id(bridge, page):
    """Part 1: Proves frontend generates hs_* when backend handshake_id is stripped from HTML + runtime-config."""
    import httpx

    # Pre-fetch and strip handshake_id from HTML
    real_html = httpx.get(bridge.frontend_url).text
    html_stripped = re.sub(r'"handshake_id"\s*:\s*"[^"]*"\s*,?\s*', "", real_html)

    def _handle_index(route):
        route.fulfill(status=200, content_type="text/html", body=html_stripped)

    # Pre-fetch and strip handshake_id from runtime-config
    runtime_config_url = bridge.frontend_url.replace("/index.html", "/runtime-config")
    real_config = httpx.get(runtime_config_url).json()
    real_config.pop("handshake_id", None)

    def _handle_runtime_config(route):
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(real_config)
        )

    page.route("**/index.html", _handle_index)
    page.route("**/runtime-config", _handle_runtime_config)

    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_runtime_config_loaded", timeout=10)
    _wait_for_event(bridge, "frontend_websocket_connecting", timeout=15)

    events = bridge.get_events()
    handshake_ids: set[str] = set()
    for event in events:
        corr = event.get("correlation") or {}
        hid = corr.get("handshake_id")
        if hid:
            handshake_ids.add(hid)

    hs_ids = [h for h in handshake_ids if h.startswith("hs_")]
    assert len(hs_ids) >= 1, (
        f"Expected hs_* fallback handshake when backend provides none. Got: {handshake_ids}"
    )

    for event in events:
        redact = event.get("redaction") or {}
        assert redact.get("token_value_included") in (False, None), (
            "token_value_included in fallback path"
        )
        payload_str = json.dumps(event.get("payload") or {})
        assert "browser-integration-token" not in payload_str, (
            "Token leaked in fallback path"
        )


def test_pywebview_runtime_config_handshake_contract(bridge, page):
    """Part 2: Proves the pywebview API config path propagates handshake_id when injected."""
    pywebview_config = {
        "ws_url": bridge.ws_url,
        "auth_token": "browser-integration-token-32chx",
        "token": "browser-integration-token-32chx",
        "handshake_id": "corr_pywebview_test",
        "transport_label": "Loopback Token Bridge",
        "tls_enabled": False,
        "local_mode": True,
        "frontend_url": bridge.frontend_url,
    }

    page.add_init_script(
        f"""
        window.pywebview = {{
            api: {{
                get_runtime_config: async function() {{
                    return {json.dumps(pywebview_config)};
                }},
                record_frontend_event: async function(payload) {{
                    var detail = encodeURIComponent(JSON.stringify(payload));
                    var url = '/frontend-event?type=' + encodeURIComponent(payload.type || '') +
                        '&handshake_id=' + encodeURIComponent(payload.handshake_id || '') +
                        '&detail=' + detail;
                    try {{ await fetch(url, {{ method: 'GET', cache: 'no-store', keepalive: true }}); }} catch(e) {{}}
                }}
            }}
        }};
        """
    )

    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_runtime_config_loaded", timeout=10)
    _wait_for_event(bridge, "desktop.websocket.auth_ok", timeout=15)

    events = bridge.get_events()
    handshake_ids: set[str] = set()
    for event in events:
        corr = event.get("correlation") or {}
        hid = corr.get("handshake_id")
        if hid:
            handshake_ids.add(hid)

    assert "corr_pywebview_test" in handshake_ids, (
        f"Pywebview handshake_id not found. Got: {handshake_ids}"
    )

    auth_hid = None
    for event in events:
        name = event.get("event_type") or event.get("name") or ""
        if "desktop.websocket.auth_received" in name:
            corr = event.get("correlation") or {}
            auth_hid = corr.get("handshake_id")
            if auth_hid:
                break

    assert auth_hid == "corr_pywebview_test", (
        f"WebSocket auth should use pywebview handshake_id, got {auth_hid}"
    )

    for event in events:
        redact = event.get("redaction") or {}
        assert redact.get("token_value_included") in (False, None), (
            "token_value_included in pywebview path"
        )
        payload_str = json.dumps(event.get("payload") or {})
        assert "browser-integration-token" not in payload_str, (
            "Token leaked in pywebview path"
        )


def test_frontend_session_id_emitted_as_supplemental(bridge, page):
    """Part 3: Proves frontend_session_id is supplemental and does not replace canonical handshake_id."""
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_boot_started", timeout=10)
    _wait_for_event(bridge, "desktop.projection.sent", timeout=15)

    events = bridge.get_events()
    event_names = bridge.get_event_names()
    assert any("frontend_boot_started" in n for n in event_names), (
        "Boot started missing"
    )

    handshake_ids: set[str] = set()
    session_ids: set[str] = set()
    for event in events:
        corr = event.get("correlation") or {}
        hid = corr.get("handshake_id")
        if hid:
            handshake_ids.add(hid)
        fsid = corr.get("frontend_session_id")
        if fsid:
            session_ids.add(fsid)
        payload = event.get("payload") or {}
        detail_str = payload.get("detail", "{}")
        try:
            detail = json.loads(detail_str) if isinstance(detail_str, str) else {}
        except json.JSONDecodeError:
            detail = {}
        fsid2 = detail.get("frontend_session_id")
        if fsid2 and isinstance(fsid2, str):
            session_ids.add(fsid2)

    assert len(handshake_ids) == 1, (
        f"Expected exactly 1 canonical handshake_id, got {handshake_ids}"
    )
    canonical = next(iter(handshake_ids))
    assert canonical == bridge.handshake_id, (
        f"Canonical {canonical} != bridge {bridge.handshake_id}"
    )

    for sid in session_ids:
        assert sid.startswith("hs_"), f"session_id {sid} should start with hs_"
        assert sid != canonical, f"session_id {sid} must not equal handshake_id"


def test_reconnect_cycle_count_classification():
    """Part 4: Proves trace summary classifies 1 cycle normal, >3 as reconnect loop."""
    _REPO = Path(__file__).resolve().parent.parent.parent
    _SCRIPT = _REPO / "scripts" / "rig_relay_trace_golden_path.py"

    from rig_relay.tracing.golden_path import build_golden_path_event
    from rig_relay.tracing.models import new_trace_id

    def _make_events(cycle_count):
        tid = new_trace_id()
        events = [
            build_golden_path_event(
                event_type="desktop.bridge.launch_requested",
                handshake_id="hs_test",
                trace_id=tid,
            ),
            build_golden_path_event(
                event_type="desktop.bridge.frontend_resolved",
                handshake_id="hs_test",
                trace_id=tid,
            ),
            build_golden_path_event(
                event_type="desktop.bridge.runtime_config_built",
                handshake_id="hs_test",
                trace_id=tid,
            ),
            build_golden_path_event(
                event_type="desktop.bridge.server_bound",
                handshake_id="hs_test",
                trace_id=tid,
            ),
            build_golden_path_event(
                event_type="desktop.bridge.health_probe_passed",
                handshake_id="hs_test",
                trace_id=tid,
            ),
            build_golden_path_event(
                event_type="desktop.websocket.accepted",
                handshake_id="hs_test",
                trace_id=tid,
            ),
            build_golden_path_event(
                event_type="desktop.websocket.auth_received",
                handshake_id="hs_test",
                trace_id=tid,
            ),
            build_golden_path_event(
                event_type="desktop.websocket.auth_ok",
                handshake_id="hs_test",
                trace_id=tid,
            ),
            build_golden_path_event(
                event_type="desktop.projection.sent",
                handshake_id="hs_test",
                trace_id=tid,
            ),
        ]
        for _ in range(cycle_count):
            events.extend([
                build_golden_path_event(
                    event_type="frontend_websocket_connecting",
                    handshake_id="hs_test",
                    trace_id=tid,
                ),
                build_golden_path_event(
                    event_type="frontend_auth_ok", handshake_id="hs_test", trace_id=tid
                ),
            ])
        return events

    for cycle_count, expect_fail in [(1, False), (2, False), (4, True)]:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for e in _make_events(cycle_count):
                f.write(json.dumps(e.to_dict(), default=str) + "\n")
            tpath = f.name

        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                str(_SCRIPT),
                "--path",
                tpath,
                "--latest",
                "--fail-on-reconnect-loop",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(_REPO),
        )
        os.unlink(tpath)

        if expect_fail:
            assert result.returncode != 0, (
                f"{cycle_count} cycles should fail with --fail-on-reconnect-loop. stdout: {result.stdout[:300]}"
            )
            assert "reconnect loop" in result.stdout.lower() or "reconnect_loop" in str(
                result
            ), (
                f"Expected reconnect loop in output for {cycle_count} cycles. Got: {result.stdout[:300]}"
            )
        else:
            assert result.returncode == 0, (
                f"{cycle_count} cycles should pass. stdout: {result.stdout[:300]}\nstderr: {result.stderr[:300]}"
            )


# ── Polling helper ────────────────────────────────────────────────────


def _wait_for_event(
    bridge: BridgeRunner,
    event_name: str,
    timeout: float = 10,
    poll_interval: float = 0.2,
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        names = bridge.get_event_names()
        if event_name in names:
            return
        normalized = event_name.replace(".", "_")
        for n in names:
            if (
                n == event_name
                or n == normalized
                or (normalized in n and len(normalized) > 5)
            ):
                return
        time.sleep(poll_interval)
    names = bridge.get_event_names()
    raise AssertionError(
        f"Timed out waiting for event '{event_name}' after {timeout}s. "
        f"Events seen: {names}"
    )
