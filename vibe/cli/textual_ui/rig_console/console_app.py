"""Rig Console Textual application."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path

from textual.app import App, ComposeResult, SystemCommand
from textual.screen import Screen

from vibe.cli.textual_ui.rig_console.commands import build_rig_console_commands
from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    EvidenceRailItemProjection,
    EvidenceRailProjection,
    SessionPaneProjection,
)
from vibe.cli.textual_ui.rig_console.providers import (
    FixtureDashboardProjectionProvider,
    RuntimeDashboardProjectionProvider,
)
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


class RigConsoleApp(App[None]):
    """Textual Rig Console."""

    CSS = """
Screen {
    background: #06110B;
}

RigConsoleApp {
    padding: 1 2;
}
"""

    def __init__(
        self,
        mode: str = "fixture",
        session_id: str = "unknown",
        session_path: Path | None = None,
        workspace_root: Path | None = None,
        coordination_root: Path | None = None,
        audit_root: Path | None = None,
        refresh_interval: float = 5.0,
    ) -> None:
        super().__init__()
        self._mode = mode
        self._session_id = session_id
        self._session_path = session_path
        self._workspace_root = workspace_root
        self._coordination_root = coordination_root
        self._audit_root = audit_root
        self._refresh_interval = refresh_interval
        self._provider: (
            FixtureDashboardProjectionProvider
            | RuntimeDashboardProjectionProvider
            | None
        ) = None
        self._projection = _sample_dashboard()

    def on_mount(self) -> None:
        self._provider = self._build_provider()
        if isinstance(self._provider, FixtureDashboardProjectionProvider):
            self._projection = _sample_dashboard()
        elif self._mode == "runtime":
            self._projection = self._runtime_projection()
        self.push_screen(DashboardScreen(self._projection, provider=self._provider))
        if self._mode == "runtime" and self._refresh_interval > 0:
            self.set_interval(self._refresh_interval, self._poll_refresh)

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        if isinstance(screen, DashboardScreen):
            yield from build_rig_console_commands(screen)

    def _build_provider(
        self,
    ) -> FixtureDashboardProjectionProvider | RuntimeDashboardProjectionProvider:
        if self._mode == "runtime":
            return RuntimeDashboardProjectionProvider(
                session_id=self._session_id,
                session_path=self._session_path,
                workspace_root=self._workspace_root,
                coordination_root=self._coordination_root,
                audit_root=self._audit_root,
            )
        return FixtureDashboardProjectionProvider(_sample_dashboard())

    def _runtime_projection(self) -> DashboardProjection:
        return DashboardProjection(
            title="Rig Console",
            subtitle="Read-only runtime mode",
            session=_sample_projection(
                session_id=self._session_id,
                status="idle",
                branch_name=None,
                receipt_count=0,
                changed_paths=[],
            ),
            evidence=EvidenceRailProjection(session_id=self._session_id),
            safety_state="read-only",
            footer_hint="q: quit  r: refresh  ?: help  t: details",
            backlog_items=[],
        )

    async def _poll_refresh(self) -> None:
        try:
            screen = self.screen
        except Exception:
            return
        if isinstance(screen, DashboardScreen):
            await screen.action_refresh()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rig-console")
    parser.add_argument("--mode", choices=("fixture", "runtime"), default="fixture")
    parser.add_argument("--session-id", default="unknown")
    parser.add_argument("--session-path")
    parser.add_argument("--workspace-root")
    parser.add_argument("--coordination-root")
    parser.add_argument("--audit-root")
    parser.add_argument("--refresh-interval", type=float, default=5.0)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    app = RigConsoleApp(
        mode=args.mode,
        session_id=args.session_id,
        session_path=Path(args.session_path) if args.session_path else None,
        workspace_root=Path(args.workspace_root) if args.workspace_root else None,
        coordination_root=(
            Path(args.coordination_root) if args.coordination_root else None
        ),
        audit_root=Path(args.audit_root) if args.audit_root else None,
        refresh_interval=args.refresh_interval,
    )
    app.run()


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


def run_app() -> None:
    main()


if __name__ == "__main__":
    main()
