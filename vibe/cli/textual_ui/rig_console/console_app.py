"""Standalone preview app for Rig Console widgets.

Run with: uv run python -m vibe.cli.textual_ui.rig_console.console_app

Modes:
    single  — individual SessionPaneWidget and EvidenceRailWidget
    dashboard — DashboardScreen with header, session, evidence, footer (default)
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.screen import Screen

from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    EvidenceRailItemProjection,
    EvidenceRailProjection,
    SessionPaneProjection,
)
from vibe.cli.textual_ui.rig_console.providers import FixtureDashboardProjectionProvider
from vibe.cli.textual_ui.rig_console.screens.dashboard import DashboardScreen
from vibe.cli.textual_ui.rig_console.widgets.evidence_rail import EvidenceRailWidget
from vibe.cli.textual_ui.rig_console.widgets.session_pane import SessionPaneWidget


def _sample_projection(
    session_id: str,
    status: str = "active",
    task_title: str | None = None,
    branch_name: str | None = None,
    receipt_count: int = 0,
    latest_receipt_kind: str | None = None,
    validate_status: str | None = None,
    blocker_summary: dict[str, int] | None = None,
    changed_paths: list[str] | None = None,
    pending_user_action: str | None = None,
) -> SessionPaneProjection:
    return SessionPaneProjection(
        session_id=session_id,
        lane_id="main",
        task_title=task_title,
        status=status,
        branch_name=branch_name,
        worktree_path="/Users/user/project",
        last_heartbeat_at="2026-05-14T15:30:00",
        current_step="Processing task delegation",
        validate_status=validate_status,
        blocker_summary=blocker_summary or {},
        receipt_count=receipt_count,
        latest_receipt_kind=latest_receipt_kind
        or ("bash" if receipt_count > 0 else None),
        changed_paths=changed_paths or [],
        pending_user_action=pending_user_action,
    )


def _sample_evidence(session_id: str) -> EvidenceRailProjection:
    return EvidenceRailProjection(
        session_id=session_id,
        receipt_count=5,
        mutation_count=2,
        refusal_count=1,
        timeout_count=0,
        items=[
            EvidenceRailItemProjection(
                tool_name="bash",
                status="success",
                captured_at="2026-05-14T15:31:00",
                duration_ms=1200.0,
            ),
            EvidenceRailItemProjection(
                tool_name="search_replace",
                status="success",
                changed=True,
                path="src/auth/login.py",
                captured_at="2026-05-14T15:30:30",
                duration_ms=450.0,
            ),
            EvidenceRailItemProjection(
                tool_name="validate",
                status="success",
                captured_at="2026-05-14T15:30:00",
                duration_ms=300.0,
            ),
            EvidenceRailItemProjection(
                tool_name="write_file",
                status="refused",
                error_kind="dirty_file_guard",
                path="src/config.py",
                captured_at="2026-05-14T15:29:00",
            ),
            EvidenceRailItemProjection(
                tool_name="search_replace",
                status="success",
                changed=True,
                path="tests/test_auth.py",
                captured_at="2026-05-14T15:28:00",
                duration_ms=250.0,
            ),
        ],
    )


def _sample_dashboard() -> DashboardProjection:
    return DashboardProjection(
        title="Rig Relay Operator",
        subtitle="Session overview",
        session=_sample_projection(
            session_id="abc123-def456",
            status="active",
            task_title="Refactor auth module",
            branch_name="feature/auth-refactor",
            receipt_count=7,
            changed_paths=[
                "src/auth/login.py",
                "src/auth/tokens.py",
                "tests/test_auth.py",
                "src/auth/session.py",
                "src/auth/middleware.py",
                "src/auth/__init__.py",
            ],
        ),
        evidence=_sample_evidence("abc123-def456"),
        safety_state="active",
        footer_hint="q: quit  r: refresh  ?: help",
        backlog_items=[
            "Approve search_replace on src/auth/login.py",
            "Resolve dirty file guard for src/config.py",
            "Review validate report for task-0042",
        ],
    )


def _sample_altered_dashboard() -> DashboardProjection:
    """Alternate fixture data for testing refresh swaps projection."""
    return DashboardProjection(
        title="Rig Relay Operator",
        subtitle="Alternate session",
        session=_sample_projection(
            session_id="alt789-xyz012",
            status="blocked",
            task_title="Implement search_replace",
            branch_name="main",
            validate_status="blocked",
            blocker_summary={"dirty_files": 2, "policy_guard": 1},
            receipt_count=3,
            latest_receipt_kind="validate",
            pending_user_action="resolve_dirty_files",
            changed_paths=["src/config.py", "src/main.py"],
        ),
        evidence=_sample_evidence("alt789-xyz012"),
        safety_state="blocked",
        footer_hint="q: quit  r: refresh  ?: help",
        backlog_items=["Resolve dirty file guard for src/config.py"],
    )


class RigConsolePreview(App):
    """Standalone preview app — toggle between single-widget and dashboard views."""

    CSS = """
Screen {
    background: #06110B;
}

RigConsolePreview {
    padding: 1 2;
}
"""

    MODE: str = "dashboard"

    def __init__(self, mode: str = "dashboard") -> None:
        super().__init__()
        self.MODE = mode
        self._provider = None

    def on_mount(self) -> None:
        if self.MODE == "dashboard":
            initial = _sample_dashboard()
            self._provider = FixtureDashboardProjectionProvider(initial)
            screen = DashboardScreen(initial, provider=self._provider)
            self.push_screen(screen)
        else:
            self.push_screen(_SingleWidgetsScreen())


class _SingleWidgetsScreen(Screen):
    """Legacy single-widget preview for SessionPaneWidget and EvidenceRailWidget."""

    def compose(self) -> ComposeResult:
        yield SessionPaneWidget(
            _sample_projection(
                session_id="abc123-def456",
                status="active",
                task_title="Refactor auth module",
                branch_name="feature/auth-refactor",
                receipt_count=7,
                changed_paths=[
                    "src/auth/login.py",
                    "src/auth/tokens.py",
                    "tests/test_auth.py",
                    "src/auth/session.py",
                    "src/auth/middleware.py",
                    "src/auth/__init__.py",
                ],
            )
        )
        yield SessionPaneWidget(
            _sample_projection(
                session_id="def789-ghi012",
                status="blocked",
                task_title="Implement search_replace",
                branch_name="main",
                validate_status="blocked",
                blocker_summary={"dirty_files": 3, "leases": 2},
                receipt_count=3,
                latest_receipt_kind="validate",
                pending_user_action="resolve_dirty_files",
            )
        )
        yield SessionPaneWidget(
            _sample_projection(
                session_id="jkl345-mno678", status="idle", receipt_count=0
            )
        )
        yield SessionPaneWidget(
            _sample_projection(
                session_id="pqr901-stu234",
                status="active",
                task_title="Update docs",
                branch_name="docs/readme-update",
                receipt_count=1,
                validate_status="passed",
                changed_paths=["README.md"],
            )
        )
        yield EvidenceRailWidget(_sample_evidence("abc123-def456"))


if __name__ == "__main__":
    app = RigConsolePreview(mode="dashboard")
    app.run()
