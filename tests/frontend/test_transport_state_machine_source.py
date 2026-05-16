from __future__ import annotations

from pathlib import Path
import re

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop" / "js"
APP_JS = FRONTEND_DIR.parent / "app.js"
WEBSOCKET_JS = FRONTEND_DIR.parent / "websocket.js"


def _read(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


# ── Canonical state & event definitions ──────────────────────────────


def test_transport_state_module_defines_canonical_statuses():
    source = _read("transportState.js")
    for status in [
        "IDLE",
        "CONFIGURING",
        "CONNECTING",
        "SOCKET_OPEN",
        "AUTHENTICATING",
        "AUTHENTICATED",
        "PROJECTION_WAITING",
        "READY",
        "DEGRADED",
        "DISCONNECTED",
        "FAILED",
    ]:
        assert status in source, f"Missing canonical status: {status}"


def test_transport_state_module_defines_canonical_events():
    source = _read("transportState.js")
    for event in [
        "runtime_config_loaded",
        "runtime_config_invalid",
        "websocket_connecting",
        "websocket_open",
        "auth_sent",
        "auth_ok",
        "auth_failed",
        "projection_received",
        "projection_rendered",
        "websocket_close",
        "websocket_error",
        "frontend_fatal",
    ]:
        assert event in source, f"Missing canonical event: {event}"


def test_transport_state_module_exports_status_labels():
    source = _read("transportState.js")
    for label in [
        "Configuring",
        "Authenticating",
        "Connected",
        "Ready",
        "Degraded",
        "Disconnected",
        "Failed",
    ]:
        assert label in source, f"Missing status label: {label}"


# ── Transition behavior assertions (source-level) ───────────────────


def test_auth_ok_maps_to_authenticated():
    source = _read("transportState.js")
    assert re.search(
        r"AUTH_OK.*authenticated|auth_ok.*AUTHENTICATED", source, re.IGNORECASE
    )


def test_projection_rendered_maps_to_ready():
    source = _read("transportState.js")
    assert re.search(
        r"PROJECTION_RENDERED.*ready|projection_rendered.*READY", source, re.IGNORECASE
    )


def test_websocket_close_maps_to_disconnected():
    source = _read("transportState.js")
    assert re.search(
        r"WEBSOCKET_CLOSE.*disconnected|websocket_close.*DISCONNECTED",
        source,
        re.IGNORECASE,
    )


def test_websocket_error_maps_to_degraded():
    source = _read("transportState.js")
    assert re.search(
        r"WEBSOCKET_ERROR.*degraded|websocket_error.*DEGRADED", source, re.IGNORECASE
    )


# ── Status bar derives label from reducer state ─────────────────────


def test_status_bar_renders_from_canonical_state():
    source = _read("status.js")
    assert "STATUS_LABELS" in source, "Status bar must import STATUS_LABELS"
    assert "state.transport.status" in source, (
        "Status bar must read state.transport.status"
    )
    # Must NOT branch on wsConnected for label derivation
    assert "if (state.wsConnected)" not in source, (
        "Status bar must not branch on wsConnected"
    )


def test_status_bar_does_not_use_legacy_transport_comparison():
    source = _read("status.js")
    # The old pattern: state.transport === TransportState.CONNECTED
    assert "state.transport === TransportState" not in source
    assert "_transportStatus" not in source


# ── Breadcrumb payloads use `type` field ─────────────────────────────


def test_breadcrumb_uses_type_field():
    source = _read("transportState.js")
    # The emitBreadcrumb function must send `type:` in the payload
    assert (
        "type: payload.type" in source or "type: 'transport_state_transition'" in source
    )


def test_breadcrumb_payload_does_not_use_event_field_as_primary():
    source = _read("transportState.js")
    # emitBreadcrumb builds the request payload — `type` must be the primary field
    breadcrumb_section = source[source.index("emitBreadcrumb") :]
    # `type:` should appear before any `event:` in the payload construction
    type_pos = breadcrumb_section.index("type:")
    if "event:" in breadcrumb_section:
        # event: can exist as metadata, but type: must be primary (first)
        event_pos = breadcrumb_section.index("event:")
        assert type_pos < event_pos, (
            "type: must appear before event: in breadcrumb payload"
        )


# ── Legacy app.js routes through authority ───────────────────────────


def test_legacy_app_creates_authority():
    source = APP_JS.read_text(encoding="utf-8")
    assert "createTransportStateAuthority" in source, (
        "app.js must create a transport state authority"
    )


def test_legacy_app_uses_dispatch_not_direct_write():
    source = APP_JS.read_text(encoding="utf-8")
    assert "_appAuthority.dispatch(" in source, (
        "app.js must route transitions through authority dispatch"
    )


def test_legacy_app_uses_authority_isConnected():
    source = APP_JS.read_text(encoding="utf-8")
    assert "_appAuthority.isConnected()" in source, (
        "app.js must check connection via authority.isConnected()"
    )


# ── No direct wsConnected writes outside reducer/tests/declarations ──


def test_no_direct_wsConnected_writes_in_transport_js():
    source = _read("transport.js")
    # The _applySnapshot function is allowed to write state.wsConnected
    # But there should be no other direct assignments
    lines = source.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "state.wsConnected =" in stripped and "_applySnapshot" not in stripped:
            # Check we're inside _applySnapshot
            context = "\n".join(lines[max(0, i - 10) : i + 1])
            assert "_applySnapshot" in context, (
                f"Direct wsConnected write at line {i + 1} outside _applySnapshot: {stripped}"
            )


def test_no_direct_wsConnected_writes_in_status_js():
    source = _read("status.js")
    assert "state.wsConnected =" not in source, (
        "status.js must never write to state.wsConnected"
    )
    assert "wsConnected =" not in source, (
        "status.js must never have local wsConnected assignment"
    )


def test_no_direct_wsConnected_writes_in_main_js():
    source = _read("main.js")
    lines = source.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "state.wsConnected =" in stripped:
            # Only allowed inside onTransition callback
            context = "\n".join(lines[max(0, i - 10) : i + 1])
            assert "onTransition" in context, (
                f"Direct wsConnected write at line {i + 1} outside onTransition: {stripped}"
            )


def test_no_bare_wsConnected_variable_in_legacy_app():
    source = APP_JS.read_text(encoding="utf-8")
    # The legacy `let wsConnected = false;` declaration should be removed
    assert "let wsConnected" not in source, (
        "app.js must not declare a local wsConnected variable"
    )


# ── Transport state object shape ─────────────────────────────────────


def test_state_module_defines_structured_transport_object():
    source = _read("state.js")
    assert "transport:" in source
    assert "status:" in source
    assert "phase:" in source
    assert "lastEvent:" in source
    assert "lastError:" in source
    assert "handshakeId:" in source
    assert "updatedAt:" in source


# ── Module wiring ────────────────────────────────────────────────────


def test_main_creates_transport_authority():
    source = _read("main.js")
    assert "createTransportStateAuthority" in source


def test_main_passes_authority_to_transport():
    source = _read("main.js")
    assert "initTransport(" in source
    assert "transportAuthority" in source


def test_transport_js_applies_snapshot():
    source = _read("transport.js")
    assert "_applySnapshot" in source
    assert "_dispatch" in source


def test_websocket_js_fires_transport_machine_transitions():
    source = WEBSOCKET_JS.read_text(encoding="utf-8")
    assert "transportMachine" in source
    assert "transition('websocket_open'" in source or "transition('auth_ok'" in source


def test_widgets_use_canonical_transport_status():
    source = _read("widgets.js")
    assert "TransportStatus" in source or "STATUS_LABELS" in source
    assert "state.transport.status" in source


# ── Debug panel ──────────────────────────────────────────────────────


def test_debug_panel_exists_in_main():
    source = _read("main.js")
    assert "boot-debug-panel" in source or "_createDebugPanel" in source
    assert "boot_debug" in source


def test_debug_panel_shows_required_fields():
    source = _read("main.js")
    for field in [
        "Phase",
        "wsConnected",
        "Handshake ID",
        "Last Event",
        "Last Error",
        "Breadcrumb",
        "Projection TS",
    ]:
        assert field in source, f"Debug panel missing field: {field}"


# ── Allowed transitions guard ────────────────────────────────────────


def test_allowed_transitions_defined():
    source = _read("transportState.js")
    assert "ALLOWED_TRANSITIONS" in source


def test_failed_can_recover_to_configuring():
    source = _read("transportState.js")
    # Find the ALLOWED_TRANSITIONS section, then look for FAILED within it
    at_start = source.index("ALLOWED_TRANSITIONS")
    at_section = source[at_start:]
    failed_idx = at_section.index("[TransportStatus.FAILED]")
    failed_section = at_section[failed_idx : failed_idx + 200]
    assert "CONFIGURING" in failed_section or "CONNECTING" in failed_section


# ── Legacy compatibility ─────────────────────────────────────────────


def test_legacy_transport_state_alias_exported():
    source = _read("transportState.js")
    assert "export" in source
    assert "TransportState" in source
    assert "createTransportStateMachine" in source


def test_legacy_event_map_exists():
    source = _read("transportState.js")
    assert "LEGACY_EVENT_MAP" in source
    for old_event in [
        "boot_started",
        "config_loaded",
        "websocket_closed",
        "boot_error",
    ]:
        assert old_event in source, f"Missing legacy event mapping: {old_event}"
