from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop" / "js"


def _read(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


def test_transport_state_module_defines_explicit_states() -> None:
    source = _read("transportState.js")
    for token in [
        "WAITING_FOR_PYWEBVIEW",
        "LOADING_CONFIG",
        "CONFIG_LOADED",
        "TOKEN_MISSING",
        "CONNECTING",
        "AUTHENTICATING",
        "CONNECTED",
        "PROJECTION_READY",
        "BACKEND_UNAVAILABLE",
        "AUTH_FAILED",
        "FAILED",
    ]:
        assert token in source


def test_transport_state_module_defines_required_events() -> None:
    source = _read("transportState.js")
    for token in [
        "boot_started",
        "pywebview_wait_started",
        "config_requested",
        "config_loaded",
        "config_token_missing",
        "websocket_connecting",
        "websocket_open",
        "auth_sent",
        "auth_ok",
        "auth_failed",
        "websocket_closed",
        "projection_received",
        "projection_rendered",
        "boot_error",
    ]:
        assert token in source


def test_transport_state_module_exports_status_copy() -> None:
    source = _read("transportState.js")
    for token in [
        "Token Missing",
        "Authenticating…",
        "Connected",
        "Backend Unavailable",
        "Projection Ready",
    ]:
        assert token in source


def test_main_and_transport_wire_transport_machine() -> None:
    main_source = _read("main.js")
    transport_source = _read("transport.js")
    websocket_source = (FRONTEND_DIR.parent / "websocket.js").read_text(encoding="utf-8")
    status_source = _read("status.js")
    widgets_source = _read("widgets.js")

    assert "createTransportStateMachine" in main_source
    assert "initTransport(wsUrl, token, handleMessage, transportMachine)" in main_source
    assert "transportMachine" in transport_source
    assert "transition('auth_ok'" in transport_source or "transition('auth_ok'" in websocket_source
    assert "transition('websocket_open'" in websocket_source
    assert "TransportState.AUTHENTICATING" in status_source
    assert "TransportState.CONNECTED" in widgets_source
