"""Rig Console — projection-only widgets for the Rig Relay operator surface.

This package is separate from the legacy VibeApp chat UI. It provides
content-light projection models and widgets that render backend-derived
state without raw logs, file contents, or diffs.

Usage:
    from vibe.cli.textual_ui.rig_console.projections import (
        SessionPaneProjection,
        EvidenceRailProjection,
        EvidenceRailItemProjection,
        DashboardProjection,
        evidence_rail_from_receipt_index,
    )
    from vibe.cli.textual_ui.rig_console.providers import (
        DashboardProjectionProvider,
        FixtureDashboardProjectionProvider,
        RuntimeDashboardProjectionProvider,
    )
    from vibe.cli.textual_ui.rig_console.intents import DashboardActionResult
    from vibe.cli.textual_ui.rig_console.widgets.session_pane import SessionPaneWidget
    from vibe.cli.textual_ui.rig_console.widgets.evidence_rail import EvidenceRailWidget
    from vibe.cli.textual_ui.rig_console.widgets.operator_header import (
        OperatorHeaderWidget,
    )
    from vibe.cli.textual_ui.rig_console.widgets.footer_status import FooterStatusWidget
    from vibe.cli.textual_ui.rig_console.screens.dashboard import DashboardScreen
"""

from __future__ import annotations

from vibe.cli.textual_ui.rig_console.intents import DashboardActionResult
from vibe.cli.textual_ui.rig_console.projections import (
    DashboardProjection,
    EvidenceRailItemProjection,
    EvidenceRailProjection,
    SessionPaneProjection,
    evidence_rail_from_receipt_index,
)
from vibe.cli.textual_ui.rig_console.providers import (
    DashboardProjectionProvider,
    FixtureDashboardProjectionProvider,
    RuntimeDashboardProjectionProvider,
)
from vibe.cli.textual_ui.rig_console.screens.dashboard import DashboardScreen
from vibe.cli.textual_ui.rig_console.widgets.evidence_rail import EvidenceRailWidget
from vibe.cli.textual_ui.rig_console.widgets.footer_status import FooterStatusWidget
from vibe.cli.textual_ui.rig_console.widgets.operator_header import OperatorHeaderWidget
from vibe.cli.textual_ui.rig_console.widgets.session_pane import SessionPaneWidget

__all__ = [
    "DashboardActionResult",
    "DashboardProjection",
    "DashboardProjectionProvider",
    "DashboardScreen",
    "EvidenceRailItemProjection",
    "EvidenceRailProjection",
    "EvidenceRailWidget",
    "FixtureDashboardProjectionProvider",
    "FooterStatusWidget",
    "OperatorHeaderWidget",
    "RuntimeDashboardProjectionProvider",
    "SessionPaneProjection",
    "SessionPaneWidget",
    "evidence_rail_from_receipt_index",
]
