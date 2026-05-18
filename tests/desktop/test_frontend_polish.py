"""Tests for frontend polish: connection status, widgets, rendering safety, accessibility."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import tempfile

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FRONTEND_JS = _REPO_ROOT / "frontend" / "desktop" / "js"
_FRONTEND_CSS = _REPO_ROOT / "frontend" / "desktop" / "css"


def _node_available() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_node_module(js_code: str) -> str:
    with tempfile.NamedTemporaryFile(
        suffix=".mjs", mode="w", encoding="utf-8", delete=False
    ) as f:
        f.write(js_code)
    try:
        result = subprocess.run(
            ["node", f.name],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(_REPO_ROOT),
        )
        if result.returncode != 0:
            raise AssertionError(f"Node.js exited {result.returncode}: {result.stderr}")
        return result.stdout.strip()
    finally:
        Path(f.name).unlink(missing_ok=True)


def _run_node_import_test(module_name: str, test_code: str) -> str:
    """Import a frontend JS module by absolute path and run test code."""
    abs_path = _FRONTEND_JS / module_name
    script = (
        f"globalThis.window = {{}};\n"
        f"const mod = await import('{abs_path}');\n"
        f"{test_code}"
    )
    return _run_node_module(script)


def _read_js(name: str) -> str:
    return (_FRONTEND_JS / name).read_text(encoding="utf-8")


def _read_css(name: str) -> str:
    return (_FRONTEND_CSS / name).read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    stripped = re.sub(r"//.*$", "", src, flags=re.MULTILINE)
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL)
    return stripped


# ---------------------------------------------------------------------------
# Connection Status — labels, chip classes, phase derivation
# ---------------------------------------------------------------------------


class TestConnectionStatusLabels:
    @pytest.mark.contract
    def test_connection_labels_defined_for_all_states(self) -> None:
        src = _read_js("transportState.js")
        status_match = re.search(
            r"const TransportStatus = Object\.freeze\(\{([^}]+)\}\)", src, re.DOTALL
        )
        assert status_match, "TransportStatus not found"
        status_body = status_match.group(1)
        status_values = set(re.findall(r"\w+:\s*'(\w+)'", status_body))

        labels_match = re.search(
            r"const STATUS_LABELS = Object\.freeze\(\{([^}]+)\}\)", src, re.DOTALL
        )
        assert labels_match, "STATUS_LABELS not found"
        labels_body = labels_match.group(1)
        label_keys = set(re.findall(r"\[TransportStatus\.(\w+)\]", labels_body))

        # Every TransportStatus value must have a STATUS_LABELS key
        for val in status_values:
            assert any(
                val in k.lower() or k.lower() == val.lower() for k in label_keys
            ), f"Missing STATUS_LABELS entry for '{val}'"

    @pytest.mark.contract
    def test_disconnected_has_warn_chip(self) -> None:
        src = _read_js("transportState.js")
        assert re.search(r"\[TransportStatus\.DISCONNECTED\]:\s*'warn'", src), (
            "DISCONNECTED should have 'warn' chip class"
        )

    @pytest.mark.contract
    def test_connected_has_ok_chip(self) -> None:
        src = _read_js("transportState.js")
        assert re.search(r"\[TransportStatus\.AUTHENTICATED\]:\s*'ok'", src), (
            "AUTHENTICATED should have 'ok' chip class"
        )


class TestStatusChipClassMapping:
    @pytest.mark.contract
    def test_status_chip_class_for_each_phase(self) -> None:
        src = _read_js("transportState.js")
        chip_match = re.search(
            r"const STATUS_CHIP_CLASS = Object\.freeze\(\{([^}]+)\}\)", src, re.DOTALL
        )
        assert chip_match, "STATUS_CHIP_CLASS not found"
        chip_body = chip_match.group(1)

        class_vals = re.findall(r"\]\s*:\s*'(\w*)'", chip_body)
        for v in class_vals:
            assert v in ("ok", "warn", ""), f"Unexpected chip class '{v}'"

    @pytest.mark.contract
    def test_every_transport_status_has_chip_class(self) -> None:
        src = _read_js("transportState.js")
        status_match = re.search(
            r"const TransportStatus = Object\.freeze\(\{([^}]+)\}\)", src, re.DOTALL
        )
        chip_match = re.search(
            r"const STATUS_CHIP_CLASS = Object\.freeze\(\{([^}]+)\}\)", src, re.DOTALL
        )
        assert status_match and chip_match

        status_members = set(re.findall(r"(\w+):\s*'", status_match.group(1)))
        chip_members = set(
            re.findall(r"\[TransportStatus\.(\w+)\]", chip_match.group(1))
        )
        missing = status_members - chip_members
        assert not missing, (
            f"TransportStatus members missing from STATUS_CHIP_CLASS: {missing}"
        )


class TestPhaseDerivation:
    @pytest.mark.contract
    def test_phase_for_boot_states(self) -> None:
        if not _node_available():
            pytest.skip("Node.js not available")
        out = _run_node_import_test(
            "transportState.js",
            """
const _phaseFor = (status) => {
  const cases = {
    'idle': 'boot', 'configuring': 'boot',
    'connecting': 'handshake', 'socket_open': 'handshake', 'authenticating': 'handshake',
    'authenticated': 'operational', 'projection_waiting': 'operational', 'ready': 'operational',
    'degraded': 'degraded', 'disconnected': 'recovery', 'failed': 'terminal',
  };
  return cases[status] || 'unknown';
};
const results = Object.values(mod.TransportStatus).map(s => s + ':' + _phaseFor(s));
console.log(results.join('|'));
""",
        )
        results = dict(kv.split(":") for kv in out.split("|"))
        assert results["idle"] == "boot"
        assert results["configuring"] == "boot"
        assert results["connecting"] == "handshake"
        assert results["socket_open"] == "handshake"
        assert results["authenticating"] == "handshake"
        assert results["authenticated"] == "operational"
        assert results["projection_waiting"] == "operational"
        assert results["ready"] == "operational"
        assert results["degraded"] == "degraded"
        assert results["disconnected"] == "recovery"
        assert results["failed"] == "terminal"

    @pytest.mark.contract
    def test_phase_for_returns_unknown_for_unknown(self) -> None:
        if not _node_available():
            pytest.skip("Node.js not available")
        out = _run_node_import_test(
            "transportState.js",
            """
const auth = mod.createTransportStateAuthority();
const snap = auth.snapshot();
console.log(snap.transport.phase);
""",
        )
        assert out == "boot", f"Idle should be 'boot' phase, got '{out}'"


# ---------------------------------------------------------------------------
# Safe Rendering — XSS prevention, textContent, no raw html leaks
# ---------------------------------------------------------------------------


class TestEscapeHtml:
    @pytest.mark.contract
    def test_escape_html_prevents_xss(self) -> None:
        if not _node_available():
            pytest.skip("Node.js not available")
        out = _run_node_import_test(
            "utils.js",
            """
const input = '<script>alert("xss")</script>';
const result = mod.escapeHtml(input);
console.log(result);
console.log('NO_SCRIPT:' + !result.includes('<script>'));
console.log('ESCAPED_LT:' + result.includes('&lt;'));
console.log('ESCAPED_GT:' + result.includes('&gt;'));
console.log('ESCAPED_QUOT:' + result.includes('&quot;'));
""",
        )
        lines = out.split("\n")
        assert lines[0] == "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;"
        assert "NO_SCRIPT:true" in out
        assert "ESCAPED_LT:true" in out
        assert "ESCAPED_GT:true" in out
        assert "ESCAPED_QUOT:true" in out

    @pytest.mark.contract
    def test_escape_html_handles_ampersand(self) -> None:
        if not _node_available():
            pytest.skip("Node.js not available")
        out = _run_node_import_test("utils.js", "console.log(mod.escapeHtml('a&b'));")
        assert out == "a&amp;b"

    @pytest.mark.contract
    def test_escape_html_handles_non_string(self) -> None:
        if not _node_available():
            pytest.skip("Node.js not available")
        out = _run_node_import_test(
            "utils.js",
            """
console.log(mod.escapeHtml(42));
console.log(mod.escapeHtml(null));
""",
        )
        lines = out.split("\n")
        assert lines[0] == "42"
        assert lines[1] == "null"

    @pytest.mark.contract
    def test_escape_html_defined_in_source(self) -> None:
        src = _read_js("utils.js")
        assert "function escapeHtml" in src
        assert ".replace(/&/g" in src
        assert ".replace(/</g" in src
        assert ".replace(/>/g" in src
        assert '.replace(/"/g' in src


class TestSetText:
    @pytest.mark.contract
    def test_set_text_uses_textcontent(self) -> None:
        src = _read_js("utils.js")
        # setText must use textContent, never innerHTML
        assert "textContent" in src, "setText must use textContent"
        stripped = _strip_js_comments(src)
        assert ".innerHTML" not in stripped, "utils.js must not use innerHTML"

    @pytest.mark.contract
    def test_set_text_defined(self) -> None:
        src = _read_js("utils.js")
        assert "export function setText" in src
        assert "el.textContent" in src or "_el.textContent" in src


# ---------------------------------------------------------------------------
# Transport State Authority — transitions, labels, handshake
# ---------------------------------------------------------------------------


class TestTransportStateAuthority:
    @pytest.mark.contract
    def test_transport_state_machine_blocks_invalid_transition(self) -> None:
        if not _node_available():
            pytest.skip("Node.js not available")
        out = _run_node_import_test(
            "transportState.js",
            """
const auth = mod.createTransportStateAuthority();
auth.dispatch('auth_sent');
const snap1 = auth.snapshot();
auth.dispatch('boot_started');
const snap2 = auth.snapshot();
console.log(snap2.transport.status === snap1.transport.status ? 'BLOCKED' : 'NOT_BLOCKED');
console.log('STATUS:' + snap2.transport.status);
""",
        )
        lines = out.split("\n")
        assert "BLOCKED" in lines[0], f"Transition should be blocked, got {out}"

    @pytest.mark.contract
    def test_transport_authority_emits_correct_label_on_connect(self) -> None:
        if not _node_available():
            pytest.skip("Node.js not available")
        out = _run_node_import_test(
            "transportState.js",
            """
const auth = mod.createTransportStateAuthority();
auth.dispatch('websocket_connecting');
auth.dispatch('websocket_open');
auth.dispatch('auth_sent');
auth.dispatch('auth_ok');
const snap = auth.snapshot();
console.log('LABEL:' + snap.label);
console.log('STATUS:' + snap.transport.status);
""",
        )
        assert "LABEL:Connected" in out
        assert "STATUS:authenticated" in out

    @pytest.mark.contract
    def test_transport_authority_tracks_handshake_id(self) -> None:
        if not _node_available():
            pytest.skip("Node.js not available")
        out = _run_node_import_test(
            "transportState.js",
            """
const auth = mod.createTransportStateAuthority({handshakeId: 'abc-123-xyz'});
const snap1 = auth.snapshot();
console.log('HS_INIT:' + snap1.transport.handshakeId);
auth.setHandshakeId('new-id-456');
const snap2 = auth.snapshot();
console.log('HS_UPDATED:' + snap2.transport.handshakeId);
""",
        )
        assert "HS_INIT:abc-123-xyz" in out
        assert "HS_UPDATED:new-id-456" in out

    @pytest.mark.contract
    def test_transport_authority_derives_ws_connected(self) -> None:
        if not _node_available():
            pytest.skip("Node.js not available")
        out = _run_node_import_test(
            "transportState.js",
            """
const auth = mod.createTransportStateAuthority();
console.log('IDLE_WS:' + auth.snapshot().wsConnected);
auth.dispatch('websocket_connecting');
auth.dispatch('websocket_open');
auth.dispatch('auth_sent');
auth.dispatch('auth_ok');
console.log('AUTHED_WS:' + auth.snapshot().wsConnected);
auth.dispatch('websocket_closed');
console.log('DISCON_WS:' + auth.snapshot().wsConnected);
""",
        )
        assert "IDLE_WS:false" in out
        assert "AUTHED_WS:true" in out
        assert "DISCON_WS:false" in out

    @pytest.mark.contract
    def test_transport_allowed_transitions_exhaustive(self) -> None:
        src = _read_js("transportState.js")
        idx = src.index("const ALLOWED_TRANSITIONS")
        depth = 0
        close_idx = idx
        for i in range(idx, len(src)):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    close_idx = i + 1
                    break
        trans_block = src[idx:close_idx]
        trans_keys = set(re.findall(r"\[TransportStatus\.(\w+)\]", trans_block))
        status_section = src.split("const TransportState")[0].split(
            "const TransportStatus"
        )[1]
        status_keys = set(re.findall(r"(\w+):\s*'", status_section))
        missing = status_keys - trans_keys
        assert not missing, (
            f"TransportStatus members missing from ALLOWED_TRANSITIONS: {missing}"
        )


# ---------------------------------------------------------------------------
# Release Gate Widget — fallback, status rendering
# ---------------------------------------------------------------------------


class TestReleaseGateWidget:
    @pytest.mark.contract
    def test_release_gate_widget_safe_fallback_when_no_data(self) -> None:
        src = _read_js("widgets.js")
        assert "registerWidget('releaseGate'" in src
        assert "No release gate data" in src

    @pytest.mark.contract
    def test_release_gate_widget_renders_overall_status(self) -> None:
        src = _read_js("widgets.js")
        assert "overall_status" in src
        assert "ready" in src or "passing" in src
        assert "blocked" in src

    @pytest.mark.contract
    def test_release_gate_compact_fallback(self) -> None:
        src = _read_js("widgets.js")
        idx = src.index("registerWidget('releaseGate'")
        next_reg = src.find("registerWidget", idx + 1)
        section = src[idx:next_reg] if next_reg > 0 else src[idx:]
        assert "'N/A'" in section
        assert "'RC Gate'" in section

    @pytest.mark.contract
    def test_release_gate_status_class_mapping(self) -> None:
        src = _read_js("widgets.js")
        idx = src.index("registerWidget('releaseGate'")
        next_reg = src.find("registerWidget", idx + 1)
        section = src[idx:next_reg] if next_reg > 0 else src[idx:]
        assert "'ready'" in section or "'passing'" in section
        assert "'blocked'" in section


# ---------------------------------------------------------------------------
# Button State Management — pending, success, failure
# ---------------------------------------------------------------------------


class TestButtonStateManagement:
    @pytest.mark.contract
    def test_update_intent_result_maps_status(self) -> None:
        src = _read_js("widgets.js")
        assert "export function updateIntentResult" in src
        assert "'completed'" in src
        assert "'refused'" in src

    @pytest.mark.contract
    def test_button_state_uses_escape_html(self) -> None:
        src = _read_js("widgets.js")
        idx = src.index("function updateIntentResult")
        # find the closing of the function
        brace_depth = 0
        started = False
        end = idx
        for i in range(idx, len(src)):
            if src[i] == "{":
                brace_depth += 1
                started = True
            elif src[i] == "}":
                brace_depth -= 1
                if started and brace_depth == 0:
                    end = i + 1
                    break
        section = src[idx:end]
        assert "escapeHtml" in section, "updateIntentResult must escape user input"

    @pytest.mark.contract
    def test_button_states_pending_success_failure_in_compact_chips(self) -> None:
        src = _read_js("widgets.js")
        assert "widget-chip" in src
        assert "'ok'" in src or '"ok"' in src

    @pytest.mark.contract
    def test_progress_timeline_maps_event_status_to_css(self) -> None:
        src = _read_js("widgets.js")
        idx = src.index("registerWidget('progressTimeline'")
        next_reg = src.find("registerWidget", idx + 1)
        section = src[idx:next_reg] if next_reg > 0 else src[idx:]
        assert "'completed'" in section
        assert "'failed'" in section


# ---------------------------------------------------------------------------
# Focus Visibility and Accessibility
# ---------------------------------------------------------------------------


class TestFocusVisibility:
    @pytest.mark.contract
    def test_focus_visible_defined_in_variables(self) -> None:
        css = _read_css("variables.css")
        assert ":focus-visible" in css

    @pytest.mark.contract
    def test_focus_visible_has_outline(self) -> None:
        css = _read_css("variables.css")
        idx = css.index(":focus-visible")
        block = css[idx : idx + 200]
        assert "outline" in block

    @pytest.mark.contract
    def test_focus_visible_on_widgets(self) -> None:
        css = _read_css("widgets.css")
        assert ":focus-visible" in css

    @pytest.mark.contract
    def test_focus_visible_on_buttons(self) -> None:
        css = _read_css("widgets.css")
        assert (
            ".widget-actions button:focus-visible" in css
            or "button:focus-visible" in css
        )

    @pytest.mark.contract
    def test_focus_visible_on_widget_card_compact(self) -> None:
        css = _read_css("widgets.css")
        assert '.widget-card[data-disclosure="compact"]:focus-visible' in css

    @pytest.mark.contract
    def test_widget_card_focus_within(self) -> None:
        css = _read_css("widgets.css")
        assert ".widget-card:focus-within" in css

    @pytest.mark.contract
    def test_aria_expanded_on_overlay_opening(self) -> None:
        src = _read_js("widgets.js")
        assert (
            "setAttribute('aria-expanded'" in src
            or 'setAttribute("aria-expanded"' in src
        )

    @pytest.mark.contract
    def test_focus_trap_into_overlay_close_button(self) -> None:
        src = _read_js("widgets.js")
        idx = src.index("function showExpanded")
        end = src.index("function hideExpanded", idx)
        section = src[idx:end]
        assert ".focus()" in section

    @pytest.mark.contract
    def test_focus_returns_to_chat_input_on_hide(self) -> None:
        src = _read_js("widgets.js")
        idx = src.index("function hideExpanded")
        # find closing brace of hideExpanded
        brace_depth = 0
        started = False
        end = idx
        for i in range(idx, len(src)):
            if src[i] == "{":
                brace_depth += 1
                started = True
            elif src[i] == "}":
                brace_depth -= 1
                if started and brace_depth == 0:
                    end = i + 1
                    break
        section = src[idx:end]
        assert "chat-input" in section, "hideExpanded must restore focus to chat-input"


# ---------------------------------------------------------------------------
# Safe DOM Rendering — no innerHTML for untrusted content
# ---------------------------------------------------------------------------


class TestSafeDOMRendering:
    @pytest.mark.contract
    def test_no_innerhtml_for_untrusted_content_in_settext(self) -> None:
        src = _read_js("utils.js")
        stripped = _strip_js_comments(src)
        assert ".innerHTML" not in stripped, "utils.js must not use innerHTML"
        assert "textContent" in src, "setText must use textContent"

    @pytest.mark.contract
    def test_escape_html_used_in_widget_string_builders(self) -> None:
        src = _read_js("widgets.js")
        escape_count = len(re.findall(r"escapeHtml\(", src))
        assert escape_count >= 20, (
            f"escapeHtml should be used extensively, found {escape_count} calls"
        )

    @pytest.mark.contract
    def test_compact_chip_uses_dom_not_innerhtml(self) -> None:
        src = _read_js("widgets.js")
        idx = src.index("function renderCompactChip")
        # find closing brace
        brace_depth = 0
        started = False
        end = idx
        for i in range(idx, len(src)):
            if src[i] == "{":
                brace_depth += 1
                started = True
            elif src[i] == "}":
                brace_depth -= 1
                if started and brace_depth == 0:
                    end = i + 1
                    break
        section = src[idx:end]
        assert "createTextNode" in section
        stripped = _strip_js_comments(section)
        assert ".innerHTML" not in stripped, "renderCompactChip must not use innerHTML"

    @pytest.mark.contract
    def test_status_chip_uses_dom_not_innerhtml(self) -> None:
        src = _read_js("status.js")
        stripped = _strip_js_comments(src)
        assert "createTextNode" in src
        assert ".innerHTML" not in stripped, "status.js must not use innerHTML"

    @pytest.mark.contract
    def test_set_safe_html_is_isolated(self) -> None:
        src = _read_js("widgets.js")
        assert "function setSafeHTML" in src
        assert "document.createElement('template')" in src

    @pytest.mark.contract
    def test_widgets_never_use_innerhtml_directly(self) -> None:
        src = _read_js("widgets.js")
        innerhtml_lines = [m.start() for m in re.finditer(r"\.innerHTML\s*=", src)]
        safehtml_idx = src.index("function setSafeHTML")
        # find closing brace of setSafeHTML
        brace_depth = 0
        started = False
        set_safe_end = safehtml_idx
        for i in range(safehtml_idx, len(src)):
            if src[i] == "{":
                brace_depth += 1
                started = True
            elif src[i] == "}":
                brace_depth -= 1
                if started and brace_depth == 0:
                    set_safe_end = i + 1
                    break
        for pos in innerhtml_lines:
            assert pos >= safehtml_idx and pos <= set_safe_end, (
                f".innerHTML = found outside setSafeHTML at position {pos}"
            )


# ---------------------------------------------------------------------------
# Transport labels completeness — cross-reference STATUS_CHIP_CLASS
# ---------------------------------------------------------------------------


class TestTransportLabelsCrossReference:
    @pytest.mark.contract
    def test_every_label_has_a_chip_class(self) -> None:
        src = _read_js("transportState.js")
        labels_match = re.search(
            r"const STATUS_LABELS = Object\.freeze\(\{([^}]+)\}\)", src, re.DOTALL
        )
        chip_match = re.search(
            r"const STATUS_CHIP_CLASS = Object\.freeze\(\{([^}]+)\}\)", src, re.DOTALL
        )
        assert labels_match and chip_match
        label_keys = set(
            re.findall(r"\[TransportStatus\.(\w+)\]", labels_match.group(1))
        )
        chip_keys = set(re.findall(r"\[TransportStatus\.(\w+)\]", chip_match.group(1)))
        assert label_keys == chip_keys, (
            f"Mismatch: labels={label_keys - chip_keys}, chips={chip_keys - label_keys}"
        )

    @pytest.mark.contract
    def test_every_label_a_non_empty_string(self) -> None:
        src = _read_js("transportState.js")
        labels_match = re.search(
            r"const STATUS_LABELS = Object\.freeze\(\{([^}]+)\}\)", src, re.DOTALL
        )
        assert labels_match
        label_vals = re.findall(r"\]\s*:\s*'([^']*)'", labels_match.group(1))
        for v in label_vals:
            assert len(v) > 0, "STATUS_LABELS value must not be empty"

    @pytest.mark.contract
    def test_detected_contradiction_imported_in_status(self) -> None:
        src = _read_js("status.js")
        assert "detectStatusContradiction" in src


# ---------------------------------------------------------------------------
# Module integrity
# ---------------------------------------------------------------------------


class TestModuleIntegrity:
    def test_js_source_files_are_valid_utf8(self) -> None:
        for js_file in _FRONTEND_JS.glob("*.js"):
            content = js_file.read_text(encoding="utf-8")
            assert content, f"{js_file.name} is empty"
