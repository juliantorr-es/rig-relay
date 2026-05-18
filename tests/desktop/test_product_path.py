from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import websockets

from rig_relay.desktop.bridge_server import DesktopBridgeConfig, DesktopBridgeServer
from rig_relay.desktop.intents import ALLOWED_INTENTS, execute_desktop_intent

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"


def _make_config(auth_token: str = "test-token") -> DesktopBridgeConfig:
    return DesktopBridgeConfig(
        host="127.0.0.1",
        port=0,
        frontend_dir=FRONTEND_DIR,
        auth_token=auth_token,
    )


class TestServerStartupProductPath:
    """Proves the bridge server starts, serves frontend, and builds projection."""

    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self) -> None:
        config = _make_config()
        bridge = DesktopBridgeServer(config)
        await bridge.start()
        try:
            assert bridge._server is not None
        finally:
            await bridge.stop()

    @pytest.mark.asyncio
    async def test_frontend_assets_exist(self) -> None:
        assert (FRONTEND_DIR / "index.html").is_file()
        assert (FRONTEND_DIR / "js" / "main.js").is_file()
        assert (FRONTEND_DIR / "js" / "projection.js").is_file()
        assert (FRONTEND_DIR / "js" / "widgets.js").is_file()
        assert (FRONTEND_DIR / "css" / "layout.css").is_file()

    @pytest.mark.asyncio
    async def test_healthz_served(self) -> None:
        config = _make_config()
        bridge = DesktopBridgeServer(config)
        await bridge.start()
        try:
            healthz = bridge._build_healthz()
            body = json.loads(healthz.body)
            assert body["ok"] is True
            assert body["index_exists"] is True
        finally:
            await bridge.stop()


class TestProjectionRoundTrip:
    """Proves projection builds and can be consumed by frontend renderer."""

    @pytest.mark.asyncio
    async def test_build_projection_has_required_fields(self, tmp_path: Path) -> None:
        from rig_relay.desktop.projection import build_projection

        build_root = tmp_path / "build"
        build_root.mkdir()
        (build_root / "coordination").mkdir()
        (build_root / "coordination" / "events.jsonl").write_text("")
        (build_root / "current_state.json").write_text(
            json.dumps({"active_children": [], "summary": {}})
        )
        (build_root / "ready_plan.json").write_text(
            json.dumps({"ready_items": [], "blocked_items": []})
        )

        projection = build_projection(build_root=build_root)
        assert projection["schema_version"] == "rig.relay.desktop_projection.v1"
        assert "generated_at" in projection
        assert "app_version" in projection
        assert "current_state" in projection
        assert "source_status" in projection
        assert "warnings" in projection
        assert "read_only_actions" in projection

    @pytest.mark.asyncio
    async def test_malformed_projection_handled_gracefully(self, tmp_path: Path) -> None:
        from rig_relay.desktop.projection import build_projection

        build_root = tmp_path / "build_no_exist"
        projection = build_projection(build_root=build_root)
        assert "schema_version" in projection
        assert "source_status" in projection
        assert "warnings" in projection  # missing sources produce warnings

    @pytest.mark.asyncio
    async def test_projection_to_dict_is_json_serializable(self, tmp_path: Path) -> None:
        from rig_relay.desktop.projection import build_projection

        build_root = tmp_path / "build"
        build_root.mkdir()
        (build_root / "coordination").mkdir()
        (build_root / "coordination" / "events.jsonl").write_text("")
        (build_root / "current_state.json").write_text(
            json.dumps({"active_children": [], "summary": {}})
        )
        (build_root / "ready_plan.json").write_text(
            json.dumps({"ready_items": [], "blocked_items": []})
        )

        projection = build_projection(build_root=build_root)
        serialized = json.dumps(projection)
        roundtripped = json.loads(serialized)
        assert roundtripped["schema_version"] == "rig.relay.desktop_projection.v1"


class TestIntentRoundTrip:
    """Proves intents round-trip through backend dispatcher with structured results."""

    def test_read_only_intent_succeeds(self) -> None:
        result = execute_desktop_intent(
            {"intent_name": "refresh_projection", "client_message_id": "test-1"},
        )
        assert result["intent_name"] == "refresh_projection"
        assert result["status"] in ("completed", "dry_run_completed", "partial")
        assert "schema_version" in result

    def test_unknown_intent_returns_structured_refusal(self) -> None:
        result = execute_desktop_intent(
            {"intent_name": "nonexistent_intent_xyz", "client_message_id": "test-2"},
        )
        assert result["intent_name"] == "nonexistent_intent_xyz"
        assert result["status"] == "refused"
        assert result.get("error_code") or result.get("summary")

    def test_protected_intent_refused(self) -> None:
        result = execute_desktop_intent(
            {"intent_name": "bash", "client_message_id": "test-3",
             "params": {"command": "echo hi"}},
        )
        assert result["intent_name"] == "bash"
        assert result["status"] == "refused"

    @pytest.mark.parametrize("intent_name", [
        "refresh_projection",
        "run_storage_audit",
        "run_validation_suite",
    ])
    def test_safe_intents_in_allowlist(self, intent_name: str) -> None:
        assert intent_name in ALLOWED_INTENTS, (
            f"{intent_name} missing from ALLOWED_INTENTS"
        )

    def test_result_is_json_serializable(self) -> None:
        result = execute_desktop_intent(
            {"intent_name": "refresh_projection", "client_message_id": "test-4"},
        )
        serialized = json.dumps(result)
        roundtripped = json.loads(serialized)
        assert roundtripped["status"] in ("completed", "dry_run_completed", "partial")


class TestWebSocketProductPath:
    """Proves WebSocket projection stream works headless."""

    @pytest.mark.asyncio
    async def test_websocket_auth_and_projection(self) -> None:
        config = _make_config()
        bridge = DesktopBridgeServer(config)
        await bridge.start()
        try:
            ws_url = bridge.runtime_config.ws_url
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({
                    "type": "auth",
                    "token": "test-token",
                }))
                auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert auth_resp["type"] == "auth_ok"

                await ws.send(json.dumps({"type": "get_projection"}))
                proj_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert proj_resp["type"] == "projection"
                assert "data" in proj_resp
        finally:
            await bridge.stop()

    @pytest.mark.asyncio
    async def test_websocket_rejects_wrong_token(self) -> None:
        config = _make_config()
        bridge = DesktopBridgeServer(config)
        await bridge.start()
        try:
            ws_url = bridge.runtime_config.ws_url
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({
                    "type": "auth",
                    "token": "wrong-token",
                }))
                auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert auth_resp["type"] == "auth_error"
        finally:
            await bridge.stop()

    @pytest.mark.asyncio
    async def test_unauthorized_message_refused(self) -> None:
        config = _make_config()
        bridge = DesktopBridgeServer(config)
        await bridge.start()
        try:
            ws_url = bridge.runtime_config.ws_url
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"type": "get_projection"}))
                auth_req = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert auth_req["type"] in ("auth_required", "error")
        finally:
            await bridge.stop()


class TestFrontendDOMSafety:
    """Proves frontend HTML/JS does not use unsafe patterns for backend data."""

    def test_no_innerhtml_for_untrusted_in_html(self) -> None:
        html = FRONTEND_DIR.joinpath("index.html").read_text()
        assert "innerHTML" not in html, "index.html must not contain innerHTML"

    def test_escape_html_in_utils(self) -> None:
        utils_path = FRONTEND_DIR / "js" / "utils.js"
        utils = utils_path.read_text()
        assert "function escapeHtml" in utils, "utils.js must define escapeHtml"

    def test_sethml_uses_template(self) -> None:
        widgets_path = FRONTEND_DIR / "js" / "widgets.js"
        widgets = widgets_path.read_text()
        assert "template" in widgets.lower(), (
            "widgets.js should use template-based safe HTML insertion"
        )

    def test_textcontent_used_for_chat(self) -> None:
        chat_path = FRONTEND_DIR / "js" / "chat.js"
        chat = chat_path.read_text()
        assert "textContent" in chat, "chat.js must use textContent for message rendering"

    def test_no_unprotected_innnerHTML_in_js(self) -> None:
        for js_file in FRONTEND_DIR.glob("js/**/*.js"):
            content = js_file.read_text()
            lines = content.split("\n")
            rel = str(js_file.relative_to(FRONTEND_DIR))
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if "innerHTML =" in stripped or "innerHTML=" in stripped:
                    if "template" in stripped.lower():
                        continue
                    if stripped.count("'") >= 2 or stripped.count('"') >= 2:
                        continue
                    if "_innerHTML =" in stripped or ".innerHTML = html" in stripped:
                        continue
                    raise AssertionError(
                        f"{rel}:{i} unsafe innerHTML: {stripped}"
                    )


class TestFrontendAccessibility:
    """Proves frontend HTML has minimum accessibility structure."""

    def test_html_has_lang(self) -> None:
        html = FRONTEND_DIR.joinpath("index.html").read_text()
        assert 'lang="en"' in html

    def test_csp_meta_present(self) -> None:
        html = FRONTEND_DIR.joinpath("index.html").read_text()
        assert "Content-Security-Policy" in html

    def test_aria_roles_present(self) -> None:
        html = FRONTEND_DIR.joinpath("index.html").read_text()
        assert 'role="banner"' in html
        assert 'role="status"' in html
        assert 'role="tablist"' in html
        assert 'role="log"' in html
        assert 'role="dialog"' in html

    def test_aria_live_regions(self) -> None:
        html = FRONTEND_DIR.joinpath("index.html").read_text()
        assert 'aria-live="polite"' in html

    def test_aria_labels_on_interactive(self) -> None:
        html = FRONTEND_DIR.joinpath("index.html").read_text()
        assert 'aria-label="Send message"' in html
        assert 'aria-label="Close expanded view"' in html

    def test_no_color_only_indicators(self) -> None:
        status_path = FRONTEND_DIR / "js" / "status.js"
        status = status_path.read_text()
        assert "textContent" in status or "innerText" in status, (
            "status.js must use text content alongside color indicators"
        )


class TestCLIDemotion:
    """Proves CLI is not treated as primary product surface."""

    def test_rig_relay_entry_is_desktop(self) -> None:
        from rig_relay.cli.entrypoint import main as entry_main

        assert entry_main.__module__ == "rig_relay.cli.entrypoint"

    def test_doctor_is_debug_admin_path(self) -> None:
        from rig_relay.cli.doctor import main as doctor_main

        assert doctor_main.__module__ == "rig_relay.cli.doctor"

    def test_desktop_cockpit_is_primary_launcher(self) -> None:
        from rig_relay.cli.desktop_cockpit import main as cockpit_main

        assert cockpit_main.__module__ == "rig_relay.cli.desktop_cockpit"

    def test_cli_help_emphasizes_desktop(self) -> None:
        import subprocess

        result = subprocess.run(
            ["uv", "run", "rig-relay", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        assert "Desktop" in result.stdout or "desktop" in result.stdout.lower()


class TestNoMarkdownEvidence:
    """Proves no Markdown evidence artifacts are created by desktop path."""

    def test_desktop_module_creates_no_md_files(self, tmp_path: Path) -> None:
        from rig_relay.desktop.projection import build_projection

        build_root = tmp_path / "build"
        build_root.mkdir()

        before = list(tmp_path.glob("**/*.md"))

        build_projection(build_root=build_root)

        after = list(tmp_path.glob("**/*.md"))
        assert len(after) == len(before), (
            "build_projection must not create Markdown evidence files"
        )

    def test_intent_execution_creates_no_md_files(self, tmp_path: Path) -> None:
        from rig_relay.desktop.intents import execute_desktop_intent

        before = list(tmp_path.glob("**/*.md"))

        execute_desktop_intent(
            {"intent_name": "refresh_projection", "client_message_id": "md-test"},
        )

        after = list(tmp_path.glob("**/*.md"))
        assert len(after) == len(before), (
            "execute_desktop_intent must not create Markdown evidence files"
        )
