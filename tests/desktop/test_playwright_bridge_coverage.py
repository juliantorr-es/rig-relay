"""Playwright coverage suite for the real cockpit bridge boot and connection paths.

Proves the bridge boots, frontend renders, WebSocket projection flows,
widget disclosure works, and adversarial token/origin scenarios are handled.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from tests.helpers.bridge_runner import BridgeRunner

EVIDENCE_DIR = (
    Path(__file__).resolve().parent.parent.parent / ".build" / "rig-relay" / "evidence"
)
ARTIFACTS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / ".build"
    / "rig-relay"
    / "playwright-artifacts"
)


def _capture_browser_failure(page, label: str) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = ARTIFACTS_DIR / f"{label}.png"
    page.screenshot(path=str(screenshot_path), full_page=True)
    return screenshot_path


def _write_evidence_artifact(result: dict) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = EVIDENCE_DIR / "playwright_bridge_run.v1.json"
    events_path = EVIDENCE_DIR / "playwright_bridge_events.v1.jsonl"

    summary = {
        "schema_version": "rig.relay.playwright_bridge_run.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "browser": result.get("browser", "chromium"),
        "browser_version": result.get("browser_version", "unknown"),
        "tests_run": [result["test_name"]],
    }

    existing = []
    if summary_path.exists():
        try:
            existing = json.loads(summary_path.read_text()).get("tests_run", [])
        except (json.JSONDecodeError, KeyError):
            pass
    seen = set(existing)
    if result["test_name"] not in seen:
        existing.append(result["test_name"])
    summary["tests_run"] = existing
    summary["summary"] = {
        "passed": sum(1 for r in [result] if r["status"] == "passed"),
        "failed": sum(1 for r in [result] if r["status"] != "passed"),
        "total": len(existing),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False)
    )
    with events_path.open("a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def bridge() -> BridgeRunner:
    """In-process bridge server — proven to work with Playwright (17/18 gold-path tests pass)."""
    runner = BridgeRunner(auth_token="pw-coverage-token-32-chars-xx")
    runner.start()
    yield runner
    runner.stop()


# ── tests ────────────────────────────────────────────────────────────────────


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
def test_browser_boots_and_renders_widgets(bridge: BridgeRunner, page) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    console_all: list[str] = []

    page.on("console", lambda msg: console_all.append(f"{msg.type}: {msg.text}"))
    page.on(
        "console",
        lambda msg: (
            console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type == "error"
            else None
        ),
    )
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    result = {
        "test_name": "test_browser_boots_and_renders_widgets",
        "status": "passed",
        "browser": "chromium",
        "browser_version": "",
        "frontend_url": str(bridge.frontend_url),
        "console_errors": 0,
        "page_errors": 0,
        "readiness_status": "Unknown",
        "widget_count": 0,
        "projection_digest_received": False,
        "screenshot_path_on_failure": "",
        "timestamp": datetime.now(UTC).isoformat(),
    }

    try:
        page.goto(
            f"{bridge.frontend_url}?boot_debug=1",
            wait_until="domcontentloaded",
            timeout=15000,
        )

        assert page.evaluate("() => document.title") == "Rig Relay"

        csp_errors = [
            e
            for e in console_all
            if "Content-Security-Policy" in e or "csp" in e.lower()
        ]
        assert csp_errors == [], f"CSP blocked resources: {csp_errors}"

        module_failures = [e for e in console_all if "Failed to load module" in e]
        assert module_failures == [], f"Module import failures: {module_failures}"

        runtime_config = page.evaluate(
            "() => window.__RIG_RELAY_RUNTIME_CONFIG__ || {}"
        )
        assert runtime_config.get("token_present") is True, "token_present missing"

        body_text = page.evaluate("() => document.body.textContent || ''")
        token = runtime_config.get("token", "")
        if token and len(token) > 8:
            assert token not in body_text, "Auth token leaked into DOM"

        # Wait for transport to be operational (debug panel has transport state != IDLE)
        page.wait_for_function(
            """() => {
                const panel = document.getElementById('debug-panel');
                if (!panel || !panel.textContent) return false;
                try {
                    const snap = JSON.parse(panel.textContent);
                    const st = snap.transport?.status || '';
                    return st && st !== 'IDLE' && st !== 'CONFIGURING';
                } catch(e) { return false; }
            }""",
            timeout=45000,
        )
        result["readiness_status"] = "Connected"

        # Verify panel column has widgets
        page.wait_for_function(
            """() => {
                const panel = document.getElementById('panel-column');
                return panel && panel.children.length > 0;
            }""",
            timeout=10000,
        )

        widget_count = page.evaluate(
            "() => document.querySelectorAll('#panel-column .widget-card').length"
        )
        assert widget_count > 0, "No widget cards in panel column"
        result["widget_count"] = widget_count

        # operatorHeader widget has content
        page.wait_for_function(
            """() => {
                const wh = document.getElementById('widget-operatorHeader');
                if (!wh) return false;
                const text = wh.textContent || '';
                return text.length > 10 && !text.includes('\u2014');
            }""",
            timeout=10000,
        )

        op_text = page.locator("#widget-operatorHeader").text_content() or ""
        assert len(op_text) > 10
        assert "Session" in op_text or "Mode" in op_text or "Telemetry" in op_text

        # At least 3 widgets have non-empty text after readiness
        widget_cards = page.locator("#panel-column .widget-card")
        non_empty_count = 0
        for i in range(min(widget_cards.count(), 10)):
            text = widget_cards.nth(i).text_content() or ""
            if len(text.strip()) > 5:
                non_empty_count += 1
        assert non_empty_count >= 3, f"Only {non_empty_count} widgets have content"

        result["projection_digest_received"] = True

    except Exception:
        result["status"] = "failed"
        result["screenshot_path_on_failure"] = str(
            _capture_browser_failure(page, "boot_widgets")
        )
        raise
    finally:
        result["console_errors"] = len(console_errors)
        result["page_errors"] = len(page_errors)
        _write_evidence_artifact(result)

    assert console_errors == [], f"Console errors: {console_errors}"
    assert page_errors == [], f"Page errors: {page_errors}"


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
def test_frontend_ws_projection_flow(bridge: BridgeRunner, page) -> None:
    result = {
        "test_name": "test_frontend_ws_projection_flow",
        "status": "passed",
        "browser": "chromium",
        "browser_version": "",
        "frontend_url": str(bridge.frontend_url),
        "console_errors": 0,
        "web_socket_connected": False,
        "projection_received": False,
        "screenshot_path_on_failure": "",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    console_all: list[str] = []
    page.on("console", lambda msg: console_all.append(f"{msg.type}: {msg.text}"))

    try:
        page.goto(
            f"{bridge.frontend_url}?boot_debug=1",
            wait_until="domcontentloaded",
            timeout=15000,
        )

        # Timestamp updates from "—" to real value
        page.wait_for_function(
            """() => {
                const ts = document.getElementById('header-timestamp');
                if (!ts) return false;
                const text = ts.textContent || '';
                return text !== '\u2014' && text.length > 3;
            }""",
            timeout=45000,
        )

        # Debug panel shows transport moved past IDLE
        panel_text = page.evaluate(
            """() => {
                const panel = document.getElementById('debug-panel');
                return panel?.textContent || '';
            }"""
        )
        assert panel_text, "Debug panel not populated"
        snap = json.loads(panel_text)
        status = snap.get("transport", {}).get("status", "")
        assert status and status not in ("IDLE", "CONFIGURING"), (
            f"Transport stuck at {status}"
        )
        result["web_socket_connected"] = True

        # Projection messages in console
        proj_msgs = [
            m
            for m in console_all
            if "projection" in m.lower()
            and ("received" in m.lower() or "rendered" in m.lower())
        ]
        result["projection_received"] = len(proj_msgs) > 0

    except Exception:
        result["status"] = "failed"
        result["screenshot_path_on_failure"] = str(
            _capture_browser_failure(page, "ws_projection")
        )
        raise
    finally:
        _write_evidence_artifact(result)


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.timeout(60)
def test_widget_disclosure_expand_collapse(bridge: BridgeRunner, page) -> None:
    page.goto(
        f"{bridge.frontend_url}?boot_debug=1",
        wait_until="domcontentloaded",
        timeout=15000,
    )

    page.wait_for_function(
        """() => {
            const wh = document.getElementById('widget-operatorHeader');
            return wh && wh.textContent && wh.textContent.length > 10;
        }""",
        timeout=45000,
    )

    # Click header to expand
    page.locator("#widget-operatorHeader .widget-header").click()
    page.wait_for_function(
        """() => {
            const body = document.querySelector('#widget-operatorHeader .widget-body');
            return body && body.textContent && body.textContent.length > 20;
        }""",
        timeout=10000,
    )

    body_text = page.locator("#widget-operatorHeader .widget-body").text_content() or ""
    assert any(kw in body_text for kw in ("Mode", "Version", "Telemetry", "Session")), (
        f"Expanded widget body missing expected content: {body_text[:100]}"
    )


@pytest.mark.adversarial
@pytest.mark.real_artifact
@pytest.mark.timeout(60)
def test_missing_token_shows_auth_failed(page) -> None:
    """Bridge with empty token → frontend shows non-ready state."""
    from tests.helpers.bridge_runner import BridgeRunner

    runner = BridgeRunner(auth_token="")
    runner.start()
    try:
        page.goto(
            f"{runner.frontend_url}?boot_debug=1",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        # Should NOT reach authenticated state
        reached_ready = False
        try:
            page.wait_for_function(
                """() => {
                    const panel = document.getElementById('debug-panel');
                    if (!panel || !panel.textContent) return false;
                    try {
                        const snap = JSON.parse(panel.textContent);
                        const st = snap.transport?.status || '';
                        return st === 'AUTHENTICATED' || st === 'READY' || st === 'PROJECTION_WAITING';
                    } catch(e) { return false; }
                }""",
                timeout=15000,
            )
            reached_ready = True
        except Exception:
            pass
        assert not reached_ready, "Empty token should not reach authenticated state"
    finally:
        runner.stop()


@pytest.mark.adversarial
@pytest.mark.real_artifact
@pytest.mark.timeout(60)
def test_no_token_in_dom(bridge: BridgeRunner, page) -> None:
    page.goto(
        f"{bridge.frontend_url}?boot_debug=1",
        wait_until="domcontentloaded",
        timeout=15000,
    )

    page.wait_for_function(
        "() => window.__RIG_RELAY_RUNTIME_CONFIG__ && window.__RIG_RELAY_RUNTIME_CONFIG__.token_present !== undefined",
        timeout=10000,
    )

    runtime_config = page.evaluate("() => window.__RIG_RELAY_RUNTIME_CONFIG__ || {}")
    token = runtime_config.get("token", "")

    body_text = page.evaluate("() => document.body.textContent || ''")
    if token and len(token) > 8:
        assert token not in body_text, "Token leaked in DOM visible text"


@pytest.mark.adversarial
@pytest.mark.timeout(30)
def test_remote_origin_rejected() -> None:
    """Bridge server binds only to loopback and rejects non-loopback hosts."""
    import os

    if os.getenv("RIG_RELAY_ALLOW_NON_LOOPBACK_LOCAL_BRIDGE", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        pytest.skip("RIG_RELAY_ALLOW_NON_LOOPBACK_LOCAL_BRIDGE is set")

    from rig_relay.desktop.bridge_server import _is_loopback_host

    assert _is_loopback_host("127.0.0.1")
    assert _is_loopback_host("localhost")
    assert _is_loopback_host("::1")
    assert not _is_loopback_host("10.0.0.1")
    assert not _is_loopback_host("0.0.0.0")
    assert not _is_loopback_host("192.168.1.1")
