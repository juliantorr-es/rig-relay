"""rig_relay.operational — read-only operational snapshot, command port,
analytics, and refinement services.

Exposes the canonical operational read boundary (snapshot), command
port (planning/validation), analytics plane (DuckDB projections),
and refinement services. Never mutates evidence.
"""

from __future__ import annotations

from rig_relay.operational.analytics import OperationalAnalytics
from rig_relay.operational.commands import (
    compute_queue_plan,
    compute_spawn_plan,
    count_active_children,
    validate_mission_packet,
)
from rig_relay.operational.refinement import (
    analyze_refinement_candidates,
    generate_refinement_packets,
    run_refinement_report,
)
from rig_relay.operational.snapshot import build_operational_snapshot

__all__ = [
    "OperationalAnalytics",
    "analyze_refinement_candidates",
    "build_operational_snapshot",
    "compute_queue_plan",
    "compute_spawn_plan",
    "count_active_children",
    "generate_refinement_packets",
    "run_refinement_report",
    "validate_mission_packet",
]
