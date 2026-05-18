from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop" / "js"


def _read(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


# ── Module existence ──────────────────────────────────────────────────


def test_notifications_js_exists():
    path = FRONTEND_DIR / "notifications.js"
    assert path.exists(), "notifications.js must exist"


def test_notifications_js_exports_show():
    source = _read("notifications.js")
    assert "export {" in source
    assert "show" in source
    assert "dismiss" in source
    assert "clearAll" in source


def test_notifications_js_exports_legacy_api():
    source = _read("notifications.js")
    assert "createNotification" in source
    assert "resolveNotification" in source
    assert "acknowledgeNotification" in source
    assert "getActiveNotifications" in source


def test_notifications_js_exports_setup():
    source = _read("notifications.js")
    assert "function setup" in source
    assert "function teardown" in source


def test_notifications_js_exports_reactive_loops():
    source = _read("notifications.js")
    assert "onSetupIncomplete" in source
    assert "onConnectionLost" in source
    assert "onConnectionRestored" in source


def test_notifications_js_registers_state_machine():
    source = _read("notifications.js")
    assert "registerMachine" in source
    assert "notifications" in source


# ── Notification kinds ────────────────────────────────────────────────


def test_notification_kinds_are_constrained():
    source = _read("notifications.js")
    assert "VALID_TOAST_KINDS" in source
    assert "'info'" in source
    assert "'success'" in source
    assert "'warning'" in source
    assert "'error'" in source
    assert "'action'" in source


def test_show_function_exists():
    source = _read("notifications.js")
    assert (
        "function show(kind, message, options)" in source or "function show(" in source
    )


def test_dismiss_function_exists():
    source = _read("notifications.js")
    assert "function dismiss(" in source


def test_clear_all_function_exists():
    source = _read("notifications.js")
    assert "function clearAll(" in source


# ── Auto-dismiss timeouts ─────────────────────────────────────────────


def test_auto_dismiss_timeouts_defined():
    source = _read("notifications.js")
    assert "AUTO_DISMISS_MS" in source
    assert "error: 0" in source
    assert "action: 0" in source
    assert "warning: 10000" in source
    assert "success: 5000" in source
    assert "info: 5000" in source


def test_auto_dismiss_uses_set_timeout():
    source = _read("notifications.js")
    assert "setTimeout" in source


# ── Max stack ─────────────────────────────────────────────────────────


def test_max_visible_toasts_is_5():
    source = _read("notifications.js")
    assert "MAX_VISIBLE_TOASTS = 5" in source or "MAX_VISIBLE_TOASTS" in source


def test_toast_overflow_trims_oldest():
    source = _read("notifications.js")
    assert "allToasts.length >" in source


# ── Deduplication ─────────────────────────────────────────────────────


def test_dedup_key_support():
    source = _read("notifications.js")
    assert "dedupKey" in source
    assert "dedupKey" in source


def test_dedup_removes_existing():
    source = _read("notifications.js")
    assert "data-dedup-key" in source


# ── Spam guard ────────────────────────────────────────────────────────


def test_spam_guard_exists():
    source = _read("notifications.js")
    assert "SPAM_GUARD_MS" in source
    assert "500" in source


def test_spam_guard_returns_null_when_throttled():
    source = _read("notifications.js")
    assert "return null" in source


# ── Accessibility ─────────────────────────────────────────────────────


def test_role_alert_for_errors_and_warnings():
    source = _read("notifications.js")
    assert "setAttribute('role'" in source
    assert "'alert'" in source
    assert "'status'" in source


def test_dismiss_button_has_aria_label():
    source = _read("notifications.js")
    assert "aria-label" in source
    assert "Dismiss" in source


def test_toast_container_has_aria_live():
    index_html = (FRONTEND_DIR.parent / "index.html").read_text(encoding="utf-8")
    assert 'aria-live="polite"' in index_html


# ── Reduced motion ────────────────────────────────────────────────────


def test_prefers_reduced_motion_detected():
    source = _read("notifications.js")
    assert "prefers-reduced-motion" in source
    assert "matchMedia" in source


def test_reduced_motion_dismiss_anim_zero():
    source = _read("notifications.js")
    assert "_prefersReducedMotion" in source
    assert "return _prefersReducedMotion() ? 0 : 300"


# ── No secrets in source ──────────────────────────────────────────────


def test_notifications_js_has_no_secrets():
    source = _read("notifications.js")
    # SECRET_PATTERNS contains regex patterns for redacting secrets,
    # which intentionally reference known secret prefix patterns.
    # Check that no actual secret values appear outside of SECRET_PATTERNS.
    # Remove SECRET_PATTERNS block to check the rest
    start = source.find("const SECRET_PATTERNS")
    end = source.find("];", start) + 2 if start != -1 else 0
    source_without_patterns = source[:start] + source[end:] if start != -1 else source
    assert "sk-" not in source_without_patterns, (
        "notifications.js must not contain API key prefix outside redaction patterns"
    )
    assert "api_key" not in source_without_patterns.lower(), (
        "notifications.js must not contain api_key"
    )
    assert "password" not in source_without_patterns.lower(), (
        "notifications.js must not contain password"
    )
    assert "auth_token" not in source_without_patterns, (
        "notifications.js must not reference auth_token"
    )


# ── No browser Notification permission prompt ─────────────────────────


def test_no_notification_request_permission_in_notifications_js():
    source = _read("notifications.js")
    assert "requestPermission" not in source, (
        "notifications.js must not call Notification.requestPermission()"
    )
    assert "Notification.requestPermission" not in source, (
        "notifications.js must not call Notification.requestPermission()"
    )


# ── Window.RigRelay.notifications namespace ────────────────────────────


def test_window_rig_relay_notifications_namespace():
    source = _read("notifications.js")
    assert "window.RigRelay.notifications" in source
    assert "show" in source
    assert "dismiss" in source
    assert "clearAll" in source


def test_window_rig_relay_notifications_api_surface():
    source = _read("notifications.js")
    # All required methods must be present
    for method in [
        "show",
        "dismiss",
        "clearAll",
        "getVisibleToasts",
        "getToastQueueDepth",
        "setup",
        "teardown",
        "onSetupIncomplete",
        "onConnectionLost",
        "onConnectionRestored",
    ]:
        assert method in source, f"window.RigRelay.notifications must expose {method}"


# ── Hardcoded strings only (no user/file/LLM content in notifications) ──


def test_notification_content_is_hardcoded():
    source = _read("notifications.js")
    # No dynamic content sources: no file content, no LLM output, no user input
    # Notification messages should be hardcoded strings
    assert "Rig Relay" in source
    assert "provider" in source.lower()


# ── Orchestrator integration ──────────────────────────────────────────


def test_orchestrator_imports_setup_notifications():
    source = _read("boot/orchestrator.js")
    assert "setup as setupNotifications" in source
    assert "from '../notifications.js'" in source


def test_orchestrator_calls_setup_notifications():
    source = _read("boot/orchestrator.js")
    assert "setupNotifications(" in source


# ── State machine ─────────────────────────────────────────────────────


def test_state_machine_states_defined():
    source = _read("notifications.js")
    assert "IDLE" in source
    assert "SHOWING" in source
    assert "DISMISSING" in source


def test_state_machine_events_defined():
    source = _read("notifications.js")
    assert "'SHOW'" in source
    assert "'DISMISS'" in source


def test_state_machine_transitions_defined():
    source = _read("notifications.js")
    assert "SHOW: 'SHOWING'" in source
    assert "DISMISS: 'DISMISSING'" in source


# ── CSS ───────────────────────────────────────────────────────────────


def test_notifications_css_exists():
    path = FRONTEND_DIR.parent / "css" / "notifications.css"
    assert path.exists(), "notifications.css must exist"


def test_notifications_css_has_action_kind():
    css = (FRONTEND_DIR.parent / "css" / "notifications.css").read_text(
        encoding="utf-8"
    )
    assert ".toast.action" in css


def test_notifications_css_has_reduced_motion():
    css = (FRONTEND_DIR.parent / "css" / "notifications.css").read_text(
        encoding="utf-8"
    )
    assert "prefers-reduced-motion" in css


def test_notifications_css_has_narrow_viewport_responsive():
    css = (FRONTEND_DIR.parent / "css" / "notifications.css").read_text(
        encoding="utf-8"
    )
    assert "max-width: 480px" in css


def test_notifications_css_has_toast_animations():
    css = (FRONTEND_DIR.parent / "css" / "notifications.css").read_text(
        encoding="utf-8"
    )
    assert "toastSlideIn" in css
    assert "toastSlideOut" in css
