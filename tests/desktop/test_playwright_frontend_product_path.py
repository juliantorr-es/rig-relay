from __future__ import annotations

from pathlib import Path
import re

import pytest

from tests.helpers.rc_live_harness import RCLiveServer


def _capture_browser_failure(page, artifact_root: Path, label: str) -> Path:
    artifact_root.mkdir(parents=True, exist_ok=True)
    screenshot_path = artifact_root / f"{label}.png"
    page.screenshot(path=str(screenshot_path), full_page=True)
    return screenshot_path


@pytest.fixture(scope="module")
def browser_server(tmp_path_factory: pytest.TempPathFactory) -> RCLiveServer:
    home_root = tmp_path_factory.mktemp("rc-browser-home")
    evidence_root = tmp_path_factory.mktemp("rc-browser-evidence")
    with RCLiveServer(
        home_root=home_root, evidence_root=evidence_root, telemetry_enabled=False
    ) as server:
        yield server


@pytest.fixture(scope="module")
def browser_artifacts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("rc-browser-artifacts")


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
def test_frontend_boots_primary_surface_and_shows_gate_and_telemetry(
    browser_server: RCLiveServer, browser_artifacts: Path, page
) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []

    page.on(
        "console",
        lambda msg: (
            console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type == "error"
            else None
        ),
    )
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    try:
        page.goto(
            browser_server.frontend_url, wait_until="domcontentloaded", timeout=15000
        )
        page.wait_for_function(
            "() => (document.querySelector('#widget-releaseGate')?.textContent || '').includes('RC Gate')",
            timeout=15000,
        )

        assert page.locator("#main-grid").is_visible()
        assert page.locator("#chat-transcript").is_visible()

        page.locator("#widget-operatorHeader").click()
        page.wait_for_function(
            "() => (document.querySelector('#widget-operatorHeader')?.textContent || '').includes('Telemetry')",
            timeout=10000,
        )
        operator_text = page.locator("#widget-operatorHeader").text_content() or ""
        assert "Telemetry" in operator_text
        assert "disabled" in operator_text.lower()

        page.locator("#widget-releaseGate").click()
        page.wait_for_function(
            "() => (document.querySelector('#widget-releaseGate')?.textContent || '').includes('Dogfood Operational Readiness')",
            timeout=10000,
        )
        release_gate_text = page.locator("#widget-releaseGate").text_content() or ""
        assert "Dogfood Operational Readiness" in release_gate_text
        assert "not_verified" in release_gate_text or "blocked" in release_gate_text
    except Exception:
        _capture_browser_failure(page, browser_artifacts, "frontend_boot")
        raise

    assert console_errors == [], f"Console errors during boot: {console_errors}"
    assert page_errors == [], f"Page errors during boot: {page_errors}"


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
def test_frontend_read_only_intent_round_trip_is_visible(
    browser_server: RCLiveServer, browser_artifacts: Path, page
) -> None:
    try:
        page.goto(
            browser_server.frontend_url, wait_until="domcontentloaded", timeout=15000
        )
        page.wait_for_function(
            "() => !!window.RigRelay && typeof window.RigRelay.dispatchIntent === 'function'",
            timeout=15000,
        )

        page.evaluate("window.RigRelay.dispatchIntent('worktree_list')")

        page.wait_for_function(
            "() => (document.querySelector('#widget-intentResult')?.textContent || '').includes('worktree_list')",
            timeout=15000,
        )

        intent_text = page.locator("#widget-intentResult").text_content() or ""
        assert "worktree_list" in intent_text
        assert "completed" in intent_text or "dry_run_completed" in intent_text
        assert "No intents executed yet." not in intent_text
    except Exception:
        _capture_browser_failure(page, browser_artifacts, "intent_round_trip")
        raise


@pytest.mark.adversarial
@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
def test_frontend_refuses_unsupported_intent_without_html_injection(
    browser_server: RCLiveServer, browser_artifacts: Path, page
) -> None:
    malicious_intent = "<script>alert(1)</script>"

    try:
        page.goto(
            browser_server.frontend_url, wait_until="domcontentloaded", timeout=15000
        )
        page.wait_for_function(
            "() => !!window.RigRelay && typeof window.RigRelay.dispatchIntent === 'function'",
            timeout=15000,
        )

        page.evaluate(
            "intent => window.RigRelay.dispatchIntent(intent)", malicious_intent
        )

        page.wait_for_function(
            f"""() => (document.querySelector('#widget-intentResult')?.textContent || '').includes({malicious_intent!r})""",
            timeout=15000,
        )

        intent_text = page.locator("#widget-intentResult").text_content() or ""
        assert malicious_intent in intent_text
        assert "unsupported_intent" in intent_text
        assert page.locator("#widget-intentResult script").count() == 0
        assert page.locator("#widget-intentResult img").count() == 0
    except Exception:
        _capture_browser_failure(page, browser_artifacts, "unsupported_intent")
        raise


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
def test_frontend_shows_ready_state_from_healthz(
    browser_server: RCLiveServer, browser_artifacts: Path, page
) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []

    page.on(
        "console",
        lambda msg: (
            console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type == "error"
            else None
        ),
    )
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    try:
        page.goto(
            browser_server.frontend_url, wait_until="domcontentloaded", timeout=15000
        )
        page.wait_for_function(
            """() => {
                const el = document.querySelector('#status-connection');
                if (!el) return false;
                const text = el.textContent || '';
                return text.length > 0 && text !== 'Idle' && text !== 'Disconnected';
            }""",
            timeout=30000,
        )

        status_text = page.locator("#status-connection").text_content() or ""
        assert "Idle" not in status_text
        assert "Disconnected" not in status_text
        assert len(status_text.strip()) > 0
    except Exception:
        _capture_browser_failure(page, browser_artifacts, "ready_state")
        raise

    assert console_errors == [], (
        f"Console errors during readiness check: {console_errors}"
    )
    assert page_errors == [], f"Page errors during readiness check: {page_errors}"


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.real_artifact
@pytest.mark.timeout(120)
def test_frontend_widgets_render_non_empty_content(
    browser_server: RCLiveServer, browser_artifacts: Path, page
) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []

    page.on(
        "console",
        lambda msg: (
            console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type == "error"
            else None
        ),
    )
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    try:
        page.goto(
            browser_server.frontend_url, wait_until="domcontentloaded", timeout=15000
        )
        page.wait_for_function(
            "() => document.querySelector('#main-grid') !== null", timeout=15000
        )
        assert page.locator("#main-grid").is_visible()

        widget_ids = [
            "#widget-operatorHeader",
            "#widget-safetyState",
            "#widget-connectionStatus",
        ]
        for widget_id in widget_ids:
            page.wait_for_function(
                f"""() => document.querySelector('{widget_id}') !== null""",
                timeout=15000,
            )

        page.wait_for_function(
            """() => {
                const ids = ['#widget-operatorHeader', '#widget-safetyState', '#widget-connectionStatus'];
                let nonEmpty = 0;
                for (const id of ids) {
                    const el = document.querySelector(id);
                    if (!el) continue;
                    const text = (el.textContent || '').trim();
                    if (text.length > 0 && text !== 'No data') nonEmpty++;
                }
                return nonEmpty >= 3;
            }""",
            timeout=30000,
        )

        for widget_id in widget_ids:
            text = (page.locator(widget_id).text_content() or "").strip()
            assert len(text) > 0, f"{widget_id} is empty"
            assert "No data" not in text, f"{widget_id} shows placeholder"
    except Exception:
        _capture_browser_failure(page, browser_artifacts, "widgets_render")
        raise

    assert console_errors == [], (
        f"Console errors during widget render: {console_errors}"
    )
    assert page_errors == [], f"Page errors during widget render: {page_errors}"


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.adversarial
@pytest.mark.timeout(120)
def test_frontend_console_module_errors_captured(
    browser_server: RCLiveServer, browser_artifacts: Path, page
) -> None:
    all_console: list[str] = []
    page_errors: list[str] = []

    page.on("console", lambda msg: all_console.append(f"{msg.type}: {msg.text}"))
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    try:
        page.goto(
            browser_server.frontend_url, wait_until="domcontentloaded", timeout=15000
        )
        page.wait_for_function(
            "() => document.querySelector('#main-grid') !== null", timeout=15000
        )
        page.wait_for_function(
            "() => document.querySelector('#status-connection') !== null", timeout=15000
        )
    except Exception:
        _capture_browser_failure(page, browser_artifacts, "console_audit")
        raise

    assert page_errors == [], f"Page errors: {page_errors}"

    error_messages = [m for m in all_console if m.startswith("error:")]
    assert error_messages == [], f"Console error-level messages: {error_messages}"

    bridge_logs = [m for m in all_console if "[bridge:frontend]" in m]
    assert len(bridge_logs) > 0, "No [bridge:frontend] log lines found in console"

    hex_pattern = re.compile(r"[0-9a-fA-F]{64,}")
    token_messages = [m for m in all_console if hex_pattern.search(m)]
    assert token_messages == [], (
        f"Console messages with 64-char hex patterns: {token_messages}"
    )


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.adversarial
@pytest.mark.timeout(120)
def test_static_probe_alone_cannot_mark_ready(
    browser_server: RCLiveServer, browser_artifacts: Path, page
) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []

    page.on(
        "console",
        lambda msg: (
            console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type == "error"
            else None
        ),
    )
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    try:
        page.goto(
            browser_server.frontend_url, wait_until="domcontentloaded", timeout=15000
        )

        page.wait_for_function(
            """() => {
                const el = document.querySelector('#status-connection');
                if (!el) return false;
                const text = el.textContent || '';
                return text.length > 0 && text !== 'Idle' && text !== 'Disconnected';
            }""",
            timeout=30000,
        )

        snapshot = page.evaluate("""() => {
            const statusEl = document.querySelector('#status-connection');
            const widgetEl = document.querySelector('#widget-operatorHeader');
            return {
                status: (statusEl?.textContent || '').trim(),
                widget: (widgetEl?.textContent || '').trim(),
            };
        }""")
        assert "Ready" not in snapshot["status"], (
            f"Status shows Ready before projection: {snapshot['status']}"
        )

        page.wait_for_function(
            """() => {
                const el = document.querySelector('#widget-operatorHeader');
                if (!el) return false;
                const text = (el.textContent || '').trim();
                return text.length > 5 && text !== 'No data';
            }""",
            timeout=60000,
        )

        final_status = page.locator("#status-connection").text_content() or ""
        assert "Idle" not in final_status
        assert "Disconnected" not in final_status
        assert len(final_status.strip()) > 0
    except Exception:
        _capture_browser_failure(page, browser_artifacts, "static_probe_readiness")
        raise

    assert console_errors == [], f"Console errors: {console_errors}"
    assert page_errors == [], f"Page errors: {page_errors}"
