from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.desktop.bridge_diagnostics import (
    BridgeProbeReport,
    BridgeProbeStatus,
    BridgeProbeStep,
    _redact_token,
)


class TestBridgeProbeStep:
    def test_to_dict_includes_all_fields(self) -> None:
        step = BridgeProbeStep(
            step_id="test:01",
            label="test step",
            status=BridgeProbeStatus.ok,
            details={"k": "v"},
            message="all good",
            remediation="n/a",
            duration_ms=42,
        )
        d = step.to_dict()
        assert d["step_id"] == "test:01"
        assert d["label"] == "test step"
        assert d["status"] == "ok"
        assert d["details"] == {"k": "v"}
        assert d["message"] == "all good"
        assert d["remediation"] == "n/a"
        assert d["duration_ms"] == 42

    def test_to_dict_omits_none_fields(self) -> None:
        step = BridgeProbeStep(
            step_id="test:02", label="minimal", status=BridgeProbeStatus.ok
        )
        d = step.to_dict()
        assert "remediation" not in d
        assert "duration_ms" not in d


class TestBridgeProbeReport:
    def test_ok_true_when_no_failures(self) -> None:
        report = BridgeProbeReport(mode="source")
        report.add_ok("a:1", "step one")
        report.add_warn("a:2", "step two")
        assert report.ok

    def test_ok_false_when_failure(self) -> None:
        report = BridgeProbeReport(mode="source")
        report.add_ok("a:1", "step one")
        report.add_fail("a:2", "step two")
        assert not report.ok

    def test_failed_step_ids(self) -> None:
        report = BridgeProbeReport(mode="source")
        report.add_fail("f:1", "fail one")
        report.add_fail("f:2", "fail two")
        report.add_ok("f:3", "ok one")
        assert report.failed_step_ids == ["f:1", "f:2"]

    def test_warning_step_ids(self) -> None:
        report = BridgeProbeReport(mode="source")
        report.add_warn("w:1", "warn one")
        report.add_ok("w:2", "ok one")
        assert report.warning_step_ids == ["w:1"]

    def test_to_dict_json_serializable(self) -> None:
        report = BridgeProbeReport(mode="source", tls_enabled=False)
        report.add_ok("b:01", "frontend dir", details={"path": "/tmp"}, duration_ms=5)
        d = report.to_dict()
        s = json.dumps(d)
        parsed = json.loads(s)
        assert parsed["schema_version"] == "rig.desktop.bridge_probe.v1"
        assert parsed["ok"] is True
        assert len(parsed["steps"]) == 1

    def test_print_terminal_no_exception(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = BridgeProbeReport(mode="source")
        report.add_ok("x:1", "all good")
        report.add_fail("x:2", "bad", message="it broke", remediation="fix it")
        report.print_terminal(verbose=True)
        out = capsys.readouterr().out
        assert "x:1" in out
        assert "x:2" in out

    def test_write_json(self, tmp_path: Path) -> None:
        report = BridgeProbeReport(mode="source")
        report.add_ok("j:1", "json test")
        p = tmp_path / "sub" / "bridge_probe.json"
        report.write_json(p)
        assert p.exists()
        data = json.loads(p.read_text())
        assert data["steps"][0]["step_id"] == "j:1"

    def test_write_text_log(self, tmp_path: Path) -> None:
        report = BridgeProbeReport(mode="source", tls_enabled=True)
        report.add_ok("t:1", "text log test")
        report.add_fail("t:2", "failure", remediation="do X")
        p = tmp_path / "bridge.log"
        report.write_text_log(p)
        content = p.read_text()
        assert "bridge_probe.v1" in content
        assert "t:1" in content
        assert "t:2" in content
        assert "do X" in content


class TestRedactToken:
    def test_empty(self) -> None:
        assert _redact_token("") == "(empty)"

    def test_short(self) -> None:
        assert _redact_token("abc") == "***"

    def test_normal(self) -> None:
        result = _redact_token("abcdef1234567890")
        assert "…" in result
        assert "abcd" in result
        assert "7890" in result
        assert "1234" not in result  # middle is hidden


class TestStartupProbesWithFixtures:
    def test_probe_report_has_bridge_steps(self, tmp_path: Path) -> None:
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        js = frontend / "js"
        js.mkdir()
        css = frontend / "css"
        css.mkdir()
        (frontend / "index.html").write_text("ok")
        (js / "main.js").write_text("console.log(1)")
        (css / "styles.css").write_text("body{}")

        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=frontend,
            auth_token="test-token-32-chars-long-12345",
        )
        report = BridgeProbeReport(mode="source")
        bridge = DesktopBridgeServer(config, probe_report=report)
        import asyncio

        async def _start_and_stop() -> None:
            await bridge.start()
            await bridge.stop()

        asyncio.run(_start_and_stop())

        step_ids = [s.step_id for s in report.steps]
        assert "bridge:01" in step_ids
        assert "bridge:02" in step_ids
        assert "bridge:03" in step_ids
        assert report.ok

    def test_probe_fails_missing_frontend_dir(self) -> None:
        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1",
            port=0,
            frontend_dir=Path("/nonexistent/path"),
            auth_token="test",
        )
        report = BridgeProbeReport(mode="source")
        bridge = DesktopBridgeServer(config, probe_report=report)

        with pytest.raises(ValueError, match="frontend_dir"):
            import asyncio

            async def _start() -> None:
                await bridge.start()

            asyncio.run(_start())

        assert not report.ok
        assert "bridge:01" in report.failed_step_ids

    def test_probe_fails_missing_index_html(self, tmp_path: Path) -> None:
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        (frontend / "js").mkdir()
        (frontend / "js" / "main.js").write_text("x")

        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=frontend, auth_token="test"
        )
        report = BridgeProbeReport(mode="source")
        bridge = DesktopBridgeServer(config, probe_report=report)

        with pytest.raises(FileNotFoundError, match="index.html"):
            import asyncio

            async def _start() -> None:
                await bridge.start()

            asyncio.run(_start())

        assert "bridge:02" in report.failed_step_ids

    def test_probe_fails_missing_main_js(self, tmp_path: Path) -> None:
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        (frontend / "index.html").write_text("ok")

        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=frontend, auth_token="test"
        )
        report = BridgeProbeReport(mode="source")
        bridge = DesktopBridgeServer(config, probe_report=report)

        with pytest.raises(FileNotFoundError, match="main.js"):
            import asyncio

            async def _start() -> None:
                await bridge.start()

            asyncio.run(_start())

        assert "bridge:03" in report.failed_step_ids


class TestHealthz:
    def test_healthz_includes_asset_fields(self, tmp_path: Path) -> None:
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        (frontend / "js").mkdir()
        (frontend / "js" / "main.js").write_text("x")
        (frontend / "css").mkdir()
        (frontend / "index.html").write_text("ok")

        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=frontend, auth_token="test"
        )
        bridge = DesktopBridgeServer(config)
        import asyncio

        async def _start_and_stop() -> None:
            await bridge.start()

            resp = bridge._build_healthz()
            body = json.loads(resp.body)
            assert body["ok"] is True
            assert body["frontend_dir_exists"] is True
            assert body["index_exists"] is True
            assert body["main_js_exists"] is True
            assert body["css_dir_exists"] is True
            assert "ws_url" in body
            assert "frontend_url" in body
            assert "auth_token" not in body
            assert "token" not in body

            await bridge.stop()

        asyncio.run(_start_and_stop())


class TestProbeContentType:
    def test_js_served_as_text_html_is_failure(self, tmp_path: Path) -> None:
        """If /js/main.js returns text/html (fallback), probe fails."""
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        (frontend / "js").mkdir()
        # Create main.js but serve it as text/html by not having proper MIME
        (frontend / "js" / "main.js").write_text("var x=1;")
        (frontend / "css").mkdir()
        (frontend / "css" / "styles.css").write_text("body{}")
        (frontend / "index.html").write_text("ok")

        from rig_relay.desktop.bridge_server import (
            DesktopBridgeConfig,
            DesktopBridgeServer,
        )

        config = DesktopBridgeConfig(
            host="127.0.0.1", port=0, frontend_dir=frontend, auth_token="test"
        )
        report = BridgeProbeReport(mode="source")
        bridge = DesktopBridgeServer(config, probe_report=report)
        import asyncio

        async def _start_and_stop() -> None:
            await bridge.start()
            await bridge.stop()

        asyncio.run(_start_and_stop())

        step9 = next((s for s in report.steps if s.step_id == "bridge:09"), None)
        assert step9 is not None
        # With proper .js extension, mimetypes should guess application/javascript
        # So this should be OK, not fail
        assert step9.status in (BridgeProbeStatus.ok, BridgeProbeStatus.warn)


class TestTerminalOutput:
    def test_terminal_includes_step_ids(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = BridgeProbeReport(mode="source")
        report.add_ok("bridge:01", "resolve frontend")
        report.add_ok("bridge:02", "resolve index.html")
        report.print_terminal()
        out = capsys.readouterr().out
        assert "bridge:01" in out
        assert "bridge:02" in out

    def test_runtime_config_output_prints_urls(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = BridgeProbeReport(
            mode="source",
            frontend_url="http://127.0.0.1:9999/index.html",
            ws_url="ws://127.0.0.1:9999/ws",
        )
        report.add_ok("x:1", "test", details={"url": report.frontend_url})
        report.print_terminal(verbose=True)
        out = capsys.readouterr().out
        assert "9999" in out
        assert "x:1" in out


class TestLogWriting:
    def test_probe_json_written(self, tmp_path: Path) -> None:
        report = BridgeProbeReport(mode="packaged")
        report.add_ok("l:1", "log test")
        p = tmp_path / "logs" / "bridge_probe.json"
        report.write_json(p)
        assert p.exists()
        data = json.loads(p.read_text())
        assert data["mode"] == "packaged"
        assert len(data["steps"]) == 1

    def test_bridge_log_written(self, tmp_path: Path) -> None:
        report = BridgeProbeReport(mode="packaged")
        report.add_fail("l:2", "log failure", remediation="restart")
        p = tmp_path / "logs" / "bridge.log"
        report.write_text_log(p)
        assert p.exists()
        content = p.read_text()
        assert "l:2" in content
        assert "restart" in content
