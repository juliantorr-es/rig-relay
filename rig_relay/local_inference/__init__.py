"""Local Project Inference Service — M0 Integration Corridor.

Capability-admitted local assistance for project and portfolio workflows.
Consumes Lane D's enforcement class and capability admission. Owns
assistance task definitions, sanitized project context packets (fixture
until L0 publishes), and Gridline projections.

Release boundary:
  LocalProjectInferenceService: execute admitted local-model assistance
  tasks over sanitized project context, producing reviewable content-light
  evidence and draft projections.

Freeze condition:
  A real local model produces one constrained, receipt-bound, human-
  reviewable project-page assistance result from a context packet, with
  refusal proven for an unsupported stronger requirement.
"""

from __future__ import annotations

from rig_relay.local_inference._models import (
    AssistanceExecutionStatus,
    AssistanceRefusal,
    AssistanceResult,
    AssistanceTask,
    AssistanceTaskKind,
    OutputDisposition,
    ProjectContextPacket,
    PublicationApplicability,
    build_rig_relay_project_packet,
)
from rig_relay.local_inference._projection import build_assistance_projection
from rig_relay.local_inference._service import (
    LocalProjectInferenceService,
    get_inference_service,
    reset_inference_service,
)

__all__ = [
    "AssistanceExecutionStatus",
    "AssistanceRefusal",
    "AssistanceResult",
    "AssistanceTask",
    "AssistanceTaskKind",
    "LocalProjectInferenceService",
    "OutputDisposition",
    "ProjectContextPacket",
    "PublicationApplicability",
    "build_assistance_projection",
    "build_rig_relay_project_packet",
    "get_inference_service",
    "reset_inference_service",
]
