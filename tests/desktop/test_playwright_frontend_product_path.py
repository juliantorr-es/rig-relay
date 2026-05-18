from __future__ import annotations

from pathlib import Path

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
        home_root=home_root,
        evidence_root=evidence_root,
        telemetry_enabled=False,
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
    browser_server: RCLiveServer,
    browser_artifacts: Path,
    page,
) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []

    page.on(
        "console",
        lambda msg: console_errors.append(f"{msg.type}: {msg.text}")
        if msg.type == "error"
        else None,
    )
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    try:
        page.goto(
            browser_server.frontend_url,
            wait_until="domcontentloaded",
            timeout=15000,
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
    browser_server: RCLiveServer,
    browser_artifacts: Path,
    page,
) -> None:
    try:
        page.goto(
            browser_server.frontend_url,
            wait_until="domcontentloaded",
            timeout=15000,
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
    browser_server: RCLiveServer,
    browser_artifacts: Path,
    page,
) -> None:
    malicious_intent = "<script>alert(1)</script>"

    try:
        page.goto(
            browser_server.frontend_url,
            wait_until="domcontentloaded",
            timeout=15000,
        )
        page.wait_for_function(
            "() => !!window.RigRelay && typeof window.RigRelay.dispatchIntent === 'function'",
            timeout=15000,
        )

        page.evaluate(
            "intent => window.RigRelay.dispatchIntent(intent)",
            malicious_intent,
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
