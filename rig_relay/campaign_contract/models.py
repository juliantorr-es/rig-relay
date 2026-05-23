from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

ProviderContextMode = Literal[
    "hosted_confidential_full_source_user_approved",
    "hosted_confidential_minimized_user_approved",
    "provider_context_refused",
]

ActualRetentionControlModeClassification = Literal[
    "zero_data_retention", "thirty_day_ephemeral", "standard_retention", "unknown"
]

MissionState = Literal[
    "queued",
    "running",
    "paused_out_of_scope_blocker",
    "resolver_promoted_forward",
    "incidental_unblock_repair_in_progress",
    "resumed_after_resolver",
    "resumed_after_incidental_repair",
    "completed",
    "failed_validation",
    "refused_policy",
    "unresolved_end_of_campaign",
    "skipped_dependency_blocked",
]

EventKind = Literal[
    "campaign_started",
    "mission_queued",
    "mission_started",
    "finding_recorded",
    "mission_paused_for_blocker",
    "resolver_candidate_evaluated",
    "resolver_promoted_forward",
    "resolver_completed",
    "incidental_repair_evaluated",
    "incidental_repair_authorized",
    "incidental_repair_refused",
    "incidental_repair_completed",
    "mission_resumed",
    "mission_completed",
    "mission_failed_validation",
    "mission_refused_policy",
    "mission_skipped_dependency_blocked",
    "campaign_completed",
    "campaign_blocked",
]

FindingClass = Literal[
    "out_of_scope_blocker_with_approved_resolver",
    "out_of_scope_blocker_without_approved_resolver",
    "bounded_incidental_unblock_repair_candidate",
    "partial_contract_gap",
    "validation_failure",
    "security_or_confidentiality_refusal",
    "future_optimization_candidate",
    "unrelated_risk",
]

RefusalCategory = Literal[
    "confidential_evidence_sink_access",
    "secret_or_credential_detection",
    "provider_disclosure_outside_approved_scope",
    "attempted_checkpoint",
    "attempted_commit",
    "attempted_git_staging_ref_history_mutation",
    "attempted_promotion",
    "attempted_push",
    "attempted_publication",
    "attempted_upload",
    "attempted_public_render",
    "attempted_release_packaging",
    "attempted_telemetry_contribution_export",
    "attempted_github_mutation",
    "lane_integrity_failure",
    "event_ledger_chain_failure",
    "incidental_repair_security_disclosure_promotion_boundary_crossing",
    "ordinary_implementation_blocker",
    "non_security_validation_failure",
]

RefusalDisposition = Literal[
    "halt_entire_campaign",
    "halt_dependent_chain_continue_independent_approved_missions",
    "record_for_next_campaign_continue_independent_approved_missions",
]

MissionOutcomeStatus = Literal["success", "failure", "refused", "blocked"]

ContinuationPolicy = Literal["halt_chain", "halt_all", "continue_independent"]

RecommendedCampaignDisposition = Literal[
    "review_ready_for_human_promotion_decision",
    "partial_useful_delta_with_unresolved_findings",
    "blocked_security_or_confidentiality_refusal",
    "blocked_validation_failure",
    "next_campaign_design_required",
]

AbsoluteExclusionCategory = Literal[
    "credentials",
    "secrets",
    "tokens",
    "private_authentication_material",
    "patent_or_counsel_material",
    "legal_strategy_material",
    "confidential_audit_artifacts",
    "confidential_build_sink",
    "local_crosswalks",
    "provider_policy_evidence_bodies",
    "encrypted_snapshots",
    "unrelated_repository_content",
    "unclassified_paths",
]

TERMINAL_MISSION_STATES: frozenset[MissionState] = frozenset({
    "completed",
    "failed_validation",
    "refused_policy",
    "unresolved_end_of_campaign",
    "skipped_dependency_blocked",
})

PERMITTED_TRANSITIONS: dict[MissionState, frozenset[MissionState]] = {
    "queued": frozenset({"running"}),
    "running": frozenset({
        "paused_out_of_scope_blocker",
        "completed",
        "failed_validation",
        "refused_policy",
    }),
    "paused_out_of_scope_blocker": frozenset({
        "resolver_promoted_forward",
        "incidental_unblock_repair_in_progress",
        "unresolved_end_of_campaign",
    }),
    "resolver_promoted_forward": frozenset({"resumed_after_resolver"}),
    "incidental_unblock_repair_in_progress": frozenset({
        "resumed_after_incidental_repair"
    }),
    "resumed_after_resolver": frozenset({"running"}),
    "resumed_after_incidental_repair": frozenset({"running"}),
    "completed": frozenset(),
    "failed_validation": frozenset({"unresolved_end_of_campaign"}),
    "refused_policy": frozenset({"unresolved_end_of_campaign"}),
    "unresolved_end_of_campaign": frozenset({"skipped_dependency_blocked"}),
    "skipped_dependency_blocked": frozenset(),
}

REFUSAL_CATEGORY_DISPOSITION: dict[RefusalCategory, RefusalDisposition] = {
    "confidential_evidence_sink_access": "halt_entire_campaign",
    "secret_or_credential_detection": "halt_entire_campaign",
    "provider_disclosure_outside_approved_scope": "halt_entire_campaign",
    "attempted_checkpoint": "halt_entire_campaign",
    "attempted_commit": "halt_entire_campaign",
    "attempted_git_staging_ref_history_mutation": "halt_entire_campaign",
    "attempted_promotion": "halt_entire_campaign",
    "attempted_push": "halt_entire_campaign",
    "attempted_publication": "halt_entire_campaign",
    "attempted_upload": "halt_entire_campaign",
    "attempted_public_render": "halt_entire_campaign",
    "attempted_release_packaging": "halt_entire_campaign",
    "attempted_telemetry_contribution_export": "halt_entire_campaign",
    "attempted_github_mutation": "halt_entire_campaign",
    "lane_integrity_failure": "halt_entire_campaign",
    "event_ledger_chain_failure": "halt_entire_campaign",
    "incidental_repair_security_disclosure_promotion_boundary_crossing": "halt_entire_campaign",
}

# Ordinary blocker categories may use halt_dependent_chain or
# record_for_next_campaign but never halt_entire_campaign.
NON_SECURITY_REFUSAL_CATEGORIES: frozenset[RefusalCategory] = frozenset({
    "ordinary_implementation_blocker",
    "non_security_validation_failure",
})

EVIDENCE_DEPENDENT_TRANSITIONS: frozenset[tuple[MissionState, MissionState]] = (
    frozenset({
        ("resolver_promoted_forward", "resumed_after_resolver"),
        ("incidental_unblock_repair_in_progress", "resumed_after_incidental_repair"),
    })
)

_CANONICAL_EXCLUSION_CATEGORIES: list[AbsoluteExclusionCategory] = [
    "credentials",
    "secrets",
    "tokens",
    "private_authentication_material",
    "patent_or_counsel_material",
    "legal_strategy_material",
    "confidential_audit_artifacts",
    "confidential_build_sink",
    "local_crosswalks",
    "provider_policy_evidence_bodies",
    "encrypted_snapshots",
    "unrelated_repository_content",
    "unclassified_paths",
]

GENESIS_PREVIOUS_HASH = "GENESIS"


# ---- Provider disclosure attestation ---------------------------------


class ProviderApproved(BaseModel):
    mode: Literal[
        "hosted_confidential_full_source_user_approved",
        "hosted_confidential_minimized_user_approved",
    ]
    provider_family_identity: str = Field(min_length=1)
    provider_model_identity: str | None = None
    reason_model_identity_unavailable: str | None = None
    actual_retention_control_mode_classification: str = Field(min_length=1)
    campaign_scope_digest: str = Field(min_length=1)
    campaign_scope_approval_marker: Literal[True]
    mission_level_provider_scope_enforcement_marker: Literal[True]
    asserted_zdr_status: bool | None = None
    verified_zdr_marker: bool | None = None

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "actual_retention_control_mode_classification": {
                                "const": "zero_data_retention"
                            }
                        }
                    },
                    "then": {
                        "properties": {"verified_zdr_marker": {"const": True}},
                        "required": ["verified_zdr_marker"],
                    },
                },
                {
                    "if": {"properties": {"asserted_zdr_status": {"const": True}}},
                    "then": {
                        "properties": {"verified_zdr_marker": {"const": True}},
                        "required": ["verified_zdr_marker"],
                    },
                },
            ]
        },
    )

    @model_validator(mode="after")
    def check_zdr(self) -> ProviderApproved:
        if self.actual_retention_control_mode_classification == "zero_data_retention":
            if self.verified_zdr_marker is not True:
                raise ValueError(
                    "verified_zdr_marker must be True when classification is "
                    "zero_data_retention"
                )
        if self.asserted_zdr_status is True:
            if self.verified_zdr_marker is not True:
                raise ValueError(
                    "verified_zdr_marker must be True when asserted_zdr_status is True"
                )
        if (
            not self.provider_model_identity
            and not self.reason_model_identity_unavailable
        ):
            raise ValueError(
                "must provide provider_model_identity or "
                "reason_model_identity_unavailable"
            )
        return self


class ProviderRefused(BaseModel):
    mode: Literal["provider_context_refused"]
    transmission_prohibited: Literal[True]

    model_config = ConfigDict(extra="forbid")


ProviderDisclosureAttestation = Annotated[
    ProviderApproved | ProviderRefused, Field(discriminator="mode")
]


# ---- Lane policy -----------------------------------------------------


class PersistentCampaignLanePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lane_identity: str = Field(min_length=1)
    additive_accumulated_delta_marker: Literal[True]
    write_scope: Literal["isolated_campaign_lane_only"]
    checkpoint_prohibited: Literal[True]
    commit_prohibited: Literal[True]
    promotion_prohibited: Literal[True]
    push_prohibited: Literal[True]
    publication_prohibited: Literal[True]
    git_history_mutation_prohibited: Literal[True]
    upload_prohibited: Literal[True]
    public_render_prohibited: Literal[True]
    telemetry_export_prohibited: Literal[True]
    human_promotion_marker: Literal[True]


# ---- Mission definition ----------------------------------------------


class MissionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_id: str = Field(min_length=1)
    owned_path_scope: list[str]
    read_context_scope: list[str]
    provider_context_scope: list[str]
    validation_commands: list[str]
    prerequisites: list[str]
    resolver_scope_declarations: list[str]
    completion_contract: dict[str, Any]
    blocked_continuation_policy: ContinuationPolicy
    steward_authored_mission_insertion_prohibited: Literal[True]


# ---- Campaign manifest -----------------------------------------------


class CampaignManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ordered_missions: list[MissionDefinition] = Field(min_length=1)
    user_approval_marker: Literal[True]
    operating_mode: Literal["confidential_autonomous_campaign_nonpromoting"]
    provider_disclosure_attestation: ProviderDisclosureAttestation
    absolute_exclusions: list[AbsoluteExclusionCategory] = Field(
        min_length=1,
        description=(
            "List of forbidden categories. "
            "'confidential_build_sink' maps to '.build/rig-relay/confidential/'."
        ),
    )
    mission_universe_immutable_after_execution_begins: Literal[True]

    @model_validator(mode="after")
    def check_exclusions(self) -> CampaignManifest:
        present = frozenset(self.absolute_exclusions)
        missing = [c for c in _CANONICAL_EXCLUSION_CATEGORIES if c not in present]
        if missing:
            raise ValueError(f"missing required exclusion categories: {missing}")
        return self


# ---- Mission outcome -------------------------------------------------


class MissionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_id: str = Field(min_length=1)
    status: MissionOutcomeStatus
    validation_result: str = Field(min_length=1)


# ---- Blocking finding ------------------------------------------------


class BlockingFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_class: FindingClass
    blocking_status: bool
    affected_contract_clause: str = Field(min_length=1)
    resolution_scope: str = Field(min_length=1)
    candidate_approved_resolvers: list[str]
    incidental_repair_eligibility: bool
    end_of_campaign_disposition: str = Field(min_length=1)


# ---- Resolver evaluation decision ------------------------------------


class ResolverEvaluationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_id: str = Field(min_length=1)
    resolver_mission_id: str = Field(min_length=1)
    is_approved: bool
    reason_code: str = Field(min_length=1)
    requested_owned_paths: list[str] = Field(default_factory=list)
    requested_read_context_paths: list[str] = Field(default_factory=list)
    requested_provider_context_paths: list[str] = Field(default_factory=list)
    requested_resolution_scope: str = ""


# ---- Bounded incidental repair decision ------------------------------


class BoundedIncidentalUnblockRepairDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_kind: Literal["bounded_incidental_unblock_repair"]
    no_eligible_manifest_resolver_marker: Literal[True]
    low_blast_radius: Literal[True]
    non_architectural: Literal[True]
    compatibility_preserving: Literal[True]
    no_security_boundary_change: Literal[True]
    no_disclosure_boundary_change: Literal[True]
    no_dependency_change: Literal[True]
    no_policy_config_schema_family_change: Literal[True]
    no_shared_module_refactor: Literal[True]
    no_unsafe_fallback: Literal[True]
    no_test_weakening: Literal[True]
    pre_edit_decision_recorded: Literal[True]
    targeted_validation_plan: str = Field(min_length=1)
    validation_result_required_before_resume: Literal[True]
    out_of_scope_source_path_count: int = Field(ge=0, le=3)
    broad_refactor_prohibited: Literal[True]
    bypass_prohibited: Literal[True]
    global_fixture_prohibited: Literal[True]
    lint_suppression_prohibited: Literal[True]


# ---- Campaign execution event ----------------------------------------


class CampaignExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_identity: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    event_kind: EventKind
    prior_state: MissionState
    current_state: MissionState
    reason_code: str = Field(min_length=1)
    previous_event_hash: str = Field(min_length=1)
    event_hash: str = Field(min_length=1)
    raw_source_bodies_prohibited: Literal[True] = True
    raw_provider_context_bodies_prohibited: Literal[True] = True
    mission_identity: str | None = None


def compute_event_hash_payload(event: CampaignExecutionEvent) -> bytes:
    """Deterministic canonical payload for event hashing.

    Includes previous_event_hash so the hash binds the chain link.
    Excludes event_hash (the output being computed).
    """
    data = event.model_dump(exclude={"event_hash"})
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return canonical.encode("utf-8")


def compute_event_hash(event: CampaignExecutionEvent) -> str:
    """Return SHA-256 hex digest of the canonical event payload."""
    return hashlib.sha256(compute_event_hash_payload(event)).hexdigest()


# ---- Stop or refusal decision ----------------------------------------


class StopOrRefusalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: RefusalDisposition
    refusal_category: RefusalCategory
    reason_code: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_refusal(self) -> StopOrRefusalDecision:
        if self.refusal_category in REFUSAL_CATEGORY_DISPOSITION:
            # Security/confidentiality category: must be halt_entire_campaign ONLY
            required = REFUSAL_CATEGORY_DISPOSITION[self.refusal_category]
            if self.decision != required:
                raise ValueError(
                    f"refusal_category '{self.refusal_category}' requires "
                    f"decision '{required}', got '{self.decision}'"
                )
        elif self.refusal_category in NON_SECURITY_REFUSAL_CATEGORIES:
            # Ordinary blocker: must NOT be halt_entire_campaign
            if self.decision == "halt_entire_campaign":
                raise ValueError(
                    f"refusal_category '{self.refusal_category}' cannot use "
                    "halt_entire_campaign (security/confidentiality only)"
                )
        else:
            raise ValueError(f"unknown refusal_category: '{self.refusal_category}'")
        return self


# ---- Campaign completion packet --------------------------------------


class CampaignCompletionPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actual_execution_order: list[str]
    resolver_reorder_events: list[str]
    incidental_repair_outcomes: list[str]
    unresolved_findings: list[str]
    cumulative_delta_digest: str = Field(min_length=1)
    cumulative_changed_path_identities: list[str]
    validation_summary: str = Field(min_length=1)
    provider_disclosure_modes_used: list[str]
    refused_operation_counts: dict[str, int]
    checkpoint_performed: Literal[False]
    commit_performed: Literal[False]
    promotion_performed: Literal[False]
    push_performed: Literal[False]
    publication_performed: Literal[False]
    external_transmission_outside_approved_provider_context: Literal[False]
    human_promotion_marker: Literal[True]
    recommended_disposition: RecommendedCampaignDisposition


# ---- Implementation entry gate ---------------------------------------


class GateEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required_gate_identity: str = Field(min_length=1)
    required_status: str = Field(min_length=1)
    current_satisfaction_status: bool
    content_light_evidence_reference: str = Field(min_length=1)
    blocks_runtime_implementation: bool
    blocks_live_steward_execution: bool
    blocks_real_campaign_execution: bool
    blocks_promotion_authority: bool


class ImplementationEntryGate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[GateEntry]


# ---- Discriminated lifecycle stage roots -----------------------------

CampaignRecordStage = Literal["approved_definition", "in_progress", "completed"]


class ApprovedCampaignDefinition(BaseModel):
    """Valid pre-execution approved campaign manifest.

    Requires manifest, lane policy, and implementation entry gate.
    Forbids execution history, outcomes, and completion packet.
    """

    model_config = ConfigDict(extra="forbid")

    record_stage: Literal["approved_definition"]
    manifest: CampaignManifest
    lane_policy: PersistentCampaignLanePolicy
    implementation_entry_gate: ImplementationEntryGate


class InProgressCampaignRecord(BaseModel):
    """Valid in-progress campaign with chained event history.

    Requires manifest, lane policy, lane identity, and at least one
    valid campaign event. Forbids completion packet unless terminal.
    """

    model_config = ConfigDict(extra="forbid")

    record_stage: Literal["in_progress"]
    manifest: CampaignManifest
    lane_policy: PersistentCampaignLanePolicy
    campaign_execution_events: list[CampaignExecutionEvent] = Field(min_length=1)
    lane_identity: str = Field(min_length=1)
    blocking_findings: list[BlockingFinding] = Field(default_factory=list)
    resolver_evaluation_decisions: list[ResolverEvaluationDecision] = Field(
        default_factory=list
    )
    bounded_incidental_repair_decisions: list[
        BoundedIncidentalUnblockRepairDecision
    ] = Field(default_factory=list)
    mission_outcomes: list[MissionOutcome] = Field(default_factory=list)
    stop_or_refusal_decisions: list[StopOrRefusalDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_in_progress(self) -> InProgressCampaignRecord:
        last = self.campaign_execution_events[-1]
        if last.current_state in TERMINAL_MISSION_STATES:
            raise ValueError(
                "terminal campaign event belongs in CompletedCampaignRecord, "
                "not InProgressCampaignRecord"
            )
        return self


class CompletedCampaignRecord(BaseModel):
    """Valid completed campaign with terminal event and completion packet.

    Requires chained event history ending in a terminal state, a
    completion packet with non-empty execution order, and all
    protected-history markers set to False.
    """

    model_config = ConfigDict(extra="forbid")

    record_stage: Literal["completed"]
    manifest: CampaignManifest
    lane_policy: PersistentCampaignLanePolicy
    campaign_execution_events: list[CampaignExecutionEvent] = Field(min_length=1)
    lane_identity: str = Field(min_length=1)
    blocking_findings: list[BlockingFinding] = Field(default_factory=list)
    resolver_evaluation_decisions: list[ResolverEvaluationDecision] = Field(
        default_factory=list
    )
    bounded_incidental_repair_decisions: list[
        BoundedIncidentalUnblockRepairDecision
    ] = Field(default_factory=list)
    mission_outcomes: list[MissionOutcome] = Field(default_factory=list)
    stop_or_refusal_decisions: list[StopOrRefusalDecision] = Field(default_factory=list)
    campaign_completion_packet: CampaignCompletionPacket

    @model_validator(mode="after")
    def check_completed(self) -> CompletedCampaignRecord:
        last = self.campaign_execution_events[-1]
        if last.current_state not in TERMINAL_MISSION_STATES:
            raise ValueError(
                "completed campaign requires a terminal event state; "
                f"last event has state '{last.current_state}'"
            )
        pkt = self.campaign_completion_packet
        if not pkt.actual_execution_order:
            raise ValueError("actual_execution_order must be non-empty")
        if not pkt.cumulative_changed_path_identities:
            raise ValueError("cumulative_changed_path_identities must be non-empty")
        if pkt.checkpoint_performed is not False:
            raise ValueError("checkpoint_performed must be false")
        if pkt.commit_performed is not False:
            raise ValueError("commit_performed must be false")
        if pkt.promotion_performed is not False:
            raise ValueError("promotion_performed must be false")
        if pkt.push_performed is not False:
            raise ValueError("push_performed must be false")
        if pkt.publication_performed is not False:
            raise ValueError("publication_performed must be false")
        if pkt.external_transmission_outside_approved_provider_context is not False:
            raise ValueError(
                "external_transmission_outside_approved_provider_context must be false"
            )
        return self


CampaignRecord = Annotated[
    ApprovedCampaignDefinition | InProgressCampaignRecord | CompletedCampaignRecord,
    Field(discriminator="record_stage"),
]

CAMPAIGN_RECORD_ADAPTER: TypeAdapter[CampaignRecord] = TypeAdapter(CampaignRecord)
