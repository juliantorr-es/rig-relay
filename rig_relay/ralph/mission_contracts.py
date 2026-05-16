"""Read-only mission executor contract — future capability definitions.

Defines what a read-only Ralph mission is allowed/forbidden to do.
No execution is implemented. All mission requests return
implementation_status=contract_only.

This contract is the target for future desktop-approved Ralph missions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ReadOnlyMissionCapability(str):
    READ_FILES = "read_files"
    SEARCH_FILES = "search_files"
    INSPECT_GIT_STATUS = "inspect_git_status"
    INSPECT_REPORT_PROJECTIONS = "inspect_report_projections"
    INSPECT_BASH_ANALYTICS = "inspect_bash_analytics"
    RUN_READ_ONLY_VALIDATORS = "run_read_only_validators"
    WRITE_FINAL_REPORT_AFTER_APPROVAL = "write_final_report_after_approval"


READ_ONLY_CAPABILITIES = frozenset({
    ReadOnlyMissionCapability.READ_FILES,
    ReadOnlyMissionCapability.SEARCH_FILES,
    ReadOnlyMissionCapability.INSPECT_GIT_STATUS,
    ReadOnlyMissionCapability.INSPECT_REPORT_PROJECTIONS,
    ReadOnlyMissionCapability.INSPECT_BASH_ANALYTICS,
    ReadOnlyMissionCapability.RUN_READ_ONLY_VALIDATORS,
    ReadOnlyMissionCapability.WRITE_FINAL_REPORT_AFTER_APPROVAL,
})

FORBIDDEN_CAPABILITIES = frozenset({
    "source_code_mutation",
    "canonical_finding_promotion",
    "canonical_finding_deletion",
    "git_commit",
    "git_checkout",
    "git_reset",
    "git_stash",
    "git_merge",
    "git_rebase",
    "git_clean",
    "external_network_calls",
    "credential_access",
    "arbitrary_bash_mutation",
    "background_recursion",
    "scheduling_daemon_launch",
})


class RalphReadOnlyMissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_read_only_mission_request.v1"
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str = ""
    scan_id: str = ""
    candidate_id: str = ""
    panel_sha256: str = ""
    mission_candidate_sha256: str = ""
    capabilities: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def validate_capabilities(self) -> list[str]:
        violations: list[str] = []
        for cap in self.capabilities:
            if cap in FORBIDDEN_CAPABILITIES:
                violations.append(cap)
        return violations


class RalphReadOnlyMissionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_read_only_mission_plan.v1"
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    request_id: str = ""
    run_id: str = ""
    scan_id: str = ""
    allowed_capabilities: list[str] = Field(default_factory=list)
    forbidden_capabilities: list[str] = Field(
        default_factory=lambda: list(FORBIDDEN_CAPABILITIES)
    )
    required_approvals: list[str] = Field(default_factory=list)
    execution_enabled: bool = False
    implementation_status: str = "contract_only"


class RalphReadOnlyMissionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_read_only_mission_result.v1"
    result_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str = ""
    status: str = "not_implemented"
    implementation_status: str = "contract_only"
    execution_enabled: bool = False
    summary: str = ""
    report_sha256: str = ""


class RalphMissionExecutionRefusal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.ralph_mission_refusal.v1"
    refusal_id: str = Field(default_factory=lambda: str(uuid4()))
    request_id: str = ""
    reason: str = "execution_not_implemented"
    message: str = "Mission execution is not yet implemented."
    forbidden_capabilities_triggered: list[str] = Field(default_factory=list)


__all__ = [
    "FORBIDDEN_CAPABILITIES",
    "READ_ONLY_CAPABILITIES",
    "RalphMissionExecutionRefusal",
    "RalphReadOnlyMissionPlan",
    "RalphReadOnlyMissionRequest",
    "RalphReadOnlyMissionResult",
    "ReadOnlyMissionCapability",
]
