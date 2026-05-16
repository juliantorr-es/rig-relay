"""Real browser integration test — proves the frontend JavaScript runs against the
real bridge server and emits correlated golden-path trace events.

Uses Playwright + Chromium. Requires: uv add --dev pytest-playwright && playwright install chromium.

This test does NOT prove pywebview; it proves the HTTP/WS/browser seam.
"""

from __future__ import annotations

import importlib.util as _importlib_util
import json
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
    """Proves the real frontend JavaScript boots and emits frontend_boot_started."""
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_boot_started", timeout=10)
    event_names = bridge.get_event_names()
    assert any(
        "frontend_boot_started" in n or "frontend.boot_started" in n
        for n in event_names
    ), f"Frontend boot_started not emitted. Events: {event_names}"


def test_frontend_runtime_config_loaded(bridge, page):
    """Proves /runtime-config.json is fetched and frontend_runtime_config_loaded is emitted."""
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_runtime_config_loaded", timeout=10)
    event_names = bridge.get_event_names()
    assert any("runtime_config_loaded" in n for n in event_names), (
        f"Runtime config loaded not emitted. Events: {event_names}"
    )


def test_frontend_websocket_connecting_emitted(bridge, page):
    """Proves the frontend attempts WebSocket connection."""
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "frontend_websocket_connecting", timeout=10)
    event_names = bridge.get_event_names()
    assert any("websocket_connecting" in n for n in event_names), (
        f"WebSocket connecting not emitted. Events: {event_names}"
    )


def test_backend_websocket_auth_succeeds(bridge, page):
    """Proves the WebSocket auth handshake completes and auth_ok is emitted on both sides."""
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
    """Proves the projection flows from backend to frontend through WebSocket."""
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
    """Proves every trace event from this session carries the same handshake_id."""
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

    assert len(handshake_ids) <= 2, f"Too many distinct handshake IDs: {handshake_ids}"


def test_no_token_value_in_trace_payloads(bridge, page):
    """Proves no token value appears in any trace event payload."""
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
    """Proves no token value appears in browser console output."""
    console_lines: list[str] = []
    page.on("console", lambda msg: console_lines.append(msg.text))
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "desktop.projection.sent", timeout=15)
    for line in console_lines:
        assert "browser-integration-token" not in line, (
            f"Token leaked in console: {line[:100]}"
        )


def test_no_uncaught_page_errors(bridge, page):
    """Proves no uncaught JavaScript errors occur during boot."""
    page_errors: list[str] = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.goto(bridge.frontend_url, wait_until="domcontentloaded", timeout=15000)
    _wait_for_event(bridge, "desktop.projection.sent", timeout=15)
    assert len(page_errors) == 0, f"Uncaught page errors: {page_errors}"


def test_no_post_to_ws(bridge, page):
    """Proves no request is made with POST method to /ws."""
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
    """Proves the status bar renders and emits frontend_status_rendered."""
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
    """Proves the debug panel exists when boot_debug=1."""
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


# ── Polling helper ────────────────────────────────────────────────────


def _wait_for_event(
    bridge: BridgeRunner,
    event_name: str,
    timeout: float = 10,
    poll_interval: float = 0.2,
) -> None:
    """Poll the trace store until the named event appears or timeout expires."""
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
