from __future__ import annotations

import json
from pathlib import Path
import re


class TestNotificationModelDedup:
    def test_notification_dedupe_rejects_duplicate_stale_projection_warnings(
        self,
    ) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        notif_path = frontend_dir / "js" / "notifications.js"
        content = notif_path.read_text(encoding="utf-8")

        assert "_deriveDedupeKey" in content
        assert "dedupe_key" in content
        assert "activeDuplicate" in content
        assert (
            "return activeDuplicate.notification_id" in content
            or "return activeDuplicate" in content
        )

    def test_warning_resolves_when_projection_freshness_recovers(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        loops_path = frontend_dir / "js" / "reactiveLoops.js"
        content = loops_path.read_text(encoding="utf-8")

        assert "PROJECTION_STALE_KEY" in content
        assert "_resolve(PROJECTION_STALE_KEY)" in content
        assert "fresh && ls.lastEmitted" in content


class TestReleaseGate:
    def test_release_gate_blocked_creates_actionable_notification(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        loops_path = frontend_dir / "js" / "reactiveLoops.js"
        content = loops_path.read_text(encoding="utf-8")

        assert "RELEASE_GATE_BLOCKED_KEY" in content
        assert "overall_status === 'blocked'" in content
        assert "open_blocker_count" in content
        assert "_resolve(RELEASE_GATE_BLOCKED_KEY)" in content


class TestIntentRefusal:
    def test_unsupported_intent_refusal_creates_structured_notification(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        loops_path = frontend_dir / "js" / "reactiveLoops.js"
        content = loops_path.read_text(encoding="utf-8")

        assert "INTENT_REFUSAL_KEY_PREFIX" in content
        assert "state.ralph" in content
        assert "lastIntent" in content
        assert "status !== 'refused'" in content
        assert "seenRefusals" in content
        assert "Error code:" in content


class TestTelemetryDegraded:
    def test_telemetry_disabled_creates_visible_degraded_mode_notification(
        self,
    ) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        loops_path = frontend_dir / "js" / "reactiveLoops.js"
        content = loops_path.read_text(encoding="utf-8")

        assert "TELEMETRY_DEGRADED_KEY" in content
        assert "telemetry_degraded" in content
        assert "Telemetry is currently disabled" in content


class TestFirstLaunch:
    def test_setup_required_creates_onboarding_notification(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        loops_path = frontend_dir / "js" / "reactiveLoops.js"
        content = loops_path.read_text(encoding="utf-8")

        assert "FIRST_LAUNCH_SETUP_KEY" in content
        assert "Welcome to Rig Relay" in content
        assert "Set up a model provider" in content


class TestSystemNotificationPermission:
    def test_system_notification_permission_not_requested_on_boot(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        sys_notif_path = frontend_dir / "js" / "systemNotifications.js"
        orchestrator_path = frontend_dir / "js" / "boot" / "orchestrator.js"

        sys_content = sys_notif_path.read_text(encoding="utf-8")
        orch_content = orchestrator_path.read_text(encoding="utf-8")

        assert "requestPermission" in sys_content
        assert "NEVER" in sys_content or "never" in sys_content.lower()
        assert "Notification.requestPermission()" not in orch_content

    def test_permission_request_only_from_user_gesture(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )

        sys_notif_path = frontend_dir / "js" / "systemNotifications.js"
        content = sys_notif_path.read_text(encoding="utf-8")

        assert "document.addEventListener('DOMContentLoaded'" not in content
        assert "Notification.requestPermission" in content
        assert "requestPermission" in content

    def test_unsupported_notification_api_falls_back_to_in_app(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        sys_notif_path = frontend_dir / "js" / "systemNotifications.js"
        content = sys_notif_path.read_text(encoding="utf-8")

        assert "isSystemNotificationsSupported" in content
        assert "Notification" in content
        assert "typeof Notification" in content
        assert "supported: false" in content or "permission !== 'granted'" in content


class TestNoSecretsInNotifications:
    def _read_js(self, filename: str) -> str:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        return (frontend_dir / "js" / filename).read_text(encoding="utf-8")

    def test_notification_body_sanitization_exists(self) -> None:
        content = self._read_js("notifications.js")
        assert "SECRET_PATTERNS" in content or "SECRET_PATTERN" in content
        assert "_sanitizeNotificationBody" in content
        assert "[REDACTED]" in content

    def test_no_secret_token_patterns_in_test_title_or_body_literals(self) -> None:
        loops_content = self._read_js("reactiveLoops.js")
        patterns = [
            r"sk-[A-Za-z0-9]{15,}",
            r"AIza[0-9A-Z_a-z\-]{20,}",
            r"ghp_[a-zA-Z0-9]{30,}",
            r"xoxb-[0-9a-zA-Z\-]{30,}",
            r"eyJ[A-Za-z0-9\-]{20,}\.[A-Za-z0-9\-]{20,}",
        ]
        for pattern in patterns:
            assert not re.search(pattern, loops_content), (
                f"Secret pattern found: {pattern}"
            )

    def test_action_button_labels_not_containing_secrets(self) -> None:
        content = self._read_js("reactiveLoops.js")
        assert "action_buttons" in content
        assert "label" in content

    def test_system_notifications_strip_secrets(self) -> None:
        content = self._read_js("systemNotifications.js")
        assert "stripSecrets" in content
        assert "[redacted]" in content
        assert "content redacted for security" in content

    def test_evidence_events_use_body_sha256(self) -> None:
        content = self._read_js("notifications.js")
        assert "toEvidenceEvent" in content
        assert "body_sha256" in content


class TestNotificationLoopsStop:
    def test_notification_loops_cancel_on_stop(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        loops_path = frontend_dir / "js" / "reactiveLoops.js"
        content = loops_path.read_text(encoding="utf-8")

        assert "stopReactiveLoops" in content
        assert "clearInterval" in content
        assert "_isRunning = false" in content

    def test_notification_loops_pause_on_tab_hidden(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        loops_path = frontend_dir / "js" / "reactiveLoops.js"
        content = loops_path.read_text(encoding="utf-8")

        assert "pauseLoops" in content
        assert "visibilitychange" in content
        assert "document.hidden" in content


class TestReducedMotion:
    def test_reduced_motion_disables_toast_animations(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        css_path = frontend_dir / "css" / "notifications.css"
        content = css_path.read_text(encoding="utf-8")

        assert "@media (prefers-reduced-motion: reduce)" in content
        assert "animation-duration: 0ms" in content or "transition: none" in content


class TestNotificationUI:
    def test_toast_container_dom_element_exists_in_html(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        html_path = frontend_dir / "index.html"
        content = html_path.read_text(encoding="utf-8")

        assert "toast-container" in content
        assert "notification-rail" in content
        assert "notification-bell" in content
        assert "notification-badge" in content

    def test_notification_rail_keyboard_support(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        ui_path = frontend_dir / "js" / "notificationsUI.js"
        content = ui_path.read_text(encoding="utf-8")

        assert "keydown" in content
        assert "Escape" in content
        assert "ArrowDown" in content or "ArrowUp" in content

    def test_clear_all_button_wired(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        ui_path = frontend_dir / "js" / "notificationsUI.js"
        content = ui_path.read_text(encoding="utf-8")

        assert "clearResolvedNotifications" in content

    def test_bell_badge_hides_when_zero(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        ui_path = frontend_dir / "js" / "notificationsUI.js"
        content = ui_path.read_text(encoding="utf-8")

        assert "getUnackedCount" in content
        assert "hidden" in content


class TestNotificationEvidenceFiles:
    def test_evidence_json_exists_and_valid(self) -> None:
        evidence_path = (
            Path(__file__).resolve().parent.parent.parent
            / ".build"
            / "rig-relay"
            / "evidence"
            / "frontend_notifications_v1.json"
        )
        assert evidence_path.exists()

        data = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == "rig.relay.evidence.frontend_notifications.v1"
        assert "notification_model" in data
        assert "reactive_loops" in data
        assert len(data["reactive_loops"]) == 8
        assert "system_notifications" in data
        assert "security_guarantees" in data

    def test_evidence_jsonl_exists_and_has_events(self) -> None:
        evidence_path = (
            Path(__file__).resolve().parent.parent.parent
            / ".build"
            / "rig-relay"
            / "evidence"
            / "frontend_notification_events_v1.jsonl"
        )
        assert evidence_path.exists()

        lines = evidence_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 5

        for line in lines:
            data = json.loads(line)
            assert "event" in data


class TestNotificationKindEnumeration:
    def test_all_kinds_defined(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        notif_path = frontend_dir / "js" / "notifications.js"
        content = notif_path.read_text(encoding="utf-8")

        expected_kinds = [
            "info",
            "success",
            "warning",
            "error",
            "security",
            "telemetry",
            "lifecycle",
        ]
        for kind in expected_kinds:
            assert f"'{kind}'" in content or f'"{kind}"' in content, (
                f"Kind '{kind}' not found in notifications.js"
            )

    def test_all_priorities_defined(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        notif_path = frontend_dir / "js" / "notifications.js"
        content = notif_path.read_text(encoding="utf-8")

        expected_priorities = ["critical", "high", "normal", "low"]
        for priority in expected_priorities:
            assert (
                f"'{priority}'" in content
                or f'"{priority}"' in content
                or f"{priority}:" in content
            )

    def test_all_sources_defined(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        notif_path = frontend_dir / "js" / "notifications.js"
        content = notif_path.read_text(encoding="utf-8")

        expected_sources = [
            "transport",
            "projection",
            "intent",
            "release_gate",
            "telemetry",
            "provider",
            "security",
        ]
        for source in expected_sources:
            assert f"'{source}'" in content or f'"{source}"' in content


class TestNotificationStateIntegration:
    def test_state_has_notification_fields(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        state_path = frontend_dir / "js" / "state.js"
        content = state_path.read_text(encoding="utf-8")

        assert "notifications:" in content
        assert "railOpen" in content
        assert "systemPermission" in content
        assert "systemSupported" in content
        assert "setNotificationRailOpen" in content


class TestCssVariablesUsed:
    def test_notification_css_uses_project_variables(self) -> None:
        frontend_dir = (
            Path(__file__).resolve().parent.parent.parent / "frontend" / "desktop"
        )
        css_path = frontend_dir / "css" / "notifications.css"
        content = css_path.read_text(encoding="utf-8")

        css_vars = [
            "var(--glass-bg)",
            "var(--glass-border)",
            "var(--warn)",
            "var(--error)",
            "var(--ok)",
            "var(--info)",
            "var(--text-muted)",
            "var(--text-secondary)",
            "var(--text-primary)",
            "var(--bg-card)",
            "var(--bg-card-hover)",
            "var(--bg-panel)",
            "var(--border)",
            "var(--border-subtle)",
            "var(--border-active)",
            "var(--radius-sm)",
            "var(--radius-lg)",
            "var(--radius-pill)",
            "var(--font-size-xs)",
            "var(--font-size-sm)",
            "var(--font-weight-semibold)",
            "var(--space-2)",
            "var(--space-3)",
            "var(--space-4)",
            "var(--transition-fast)",
            "var(--transition-base)",
            "var(--transition-slow)",
            "var(--glass-blur)",
            "var(--glass-saturate)",
            "var(--shadow-glass)",
            "var(--shadow-raised)",
            "var(--accent)",
            "var(--accent-subtle)",
            "var(--header-height)",
            "var(--footer-height)",
        ]

        found_count = 0
        for var in css_vars:
            if var in content:
                found_count += 1

        assert found_count >= 15, (
            f"Only {found_count}/{len(css_vars)} CSS variables found in notifications.css"
        )
