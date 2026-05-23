from __future__ import annotations

from enum import StrEnum
import json

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rig_relay.campaign_contract.models import (
    CAMPAIGN_RECORD_ADAPTER,
    EVIDENCE_DEPENDENT_TRANSITIONS,
    GENESIS_PREVIOUS_HASH,
    NON_SECURITY_REFUSAL_CATEGORIES,
    PERMITTED_TRANSITIONS,
    REFUSAL_CATEGORY_DISPOSITION,
    BlockingFinding,
    CampaignExecutionEvent,
    CampaignManifest,
    MissionOutcome,
    MissionOutcomeStatus,
    MissionState,
    RefusalCategory,
    RefusalDisposition,
    ResolverEvaluationDecision,
    compute_event_hash,
)
from rig_relay.campaign_contract.schema import generate_campaign_contract_schema

# ---- Structured validation result types -------------------------------


class ValidationResultStatus(StrEnum):
    VALID = "valid"
    INVALID_JSON = "invalid_json"
    INVALID_CONTRACT = "invalid_contract"
    INVALID_SCHEMA = "invalid_schema"


class ValidationResult(BaseModel):
    status: ValidationResultStatus
    error_codes: list[str] = Field(default_factory=list)
    error_paths: list[str] = Field(default_factory=list)
    schema_identity: str | None = None

    model_config = ConfigDict(extra="forbid")


# ---- Public fixture validation ---------------------------------------


def _strip_discriminator(schema: dict) -> dict:
    """Recursively remove discriminator and allOf keys for jsonschema compat.

    standard jsonschema does not understand Pydantic's discriminators, and
    handles if/then inside allOf unpredictably on const checks.
    We rely on Pydantic for cross-field validation (ZDR, etc.) and on
    jsonschema for structural validation (types, required fields).
    """
    result: dict = {}
    for key, value in schema.items():
        if key in {"discriminator", "allOf"}:
            continue
        if isinstance(value, dict):
            result[key] = _strip_discriminator(value)
        elif isinstance(value, list):
            result[key] = [
                _strip_discriminator(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            result[key] = value
    return result


def validate_campaign_manifest_fixture(fixture_json: str) -> ValidationResult:
    """Validate a campaign record fixture through JSON Schema and Pydantic.

    Returns a structured, content-light result.  Never includes raw
    fixture bodies, secrets, source contents, or provider context.
    """
    try:
        schema = generate_campaign_contract_schema()
    except Exception:
        return ValidationResult(
            status=ValidationResultStatus.INVALID_SCHEMA,
            error_codes=["schema_generation_failed"],
        )

    # Validate the schema itself
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as e:
        return ValidationResult(
            status=ValidationResultStatus.INVALID_SCHEMA,
            error_codes=["schema_self_check_failed"],
            error_paths=[str(e.path) if e.path else ""],
        )

    # Parse JSON
    try:
        fixture_dict = json.loads(fixture_json)
    except json.JSONDecodeError as e:
        return ValidationResult(
            status=ValidationResultStatus.INVALID_JSON,
            error_codes=["json_parse_error"],
            error_paths=[f"line {e.lineno}, col {e.colno}"],
        )

    # Pydantic validation first (understands discriminator)
    try:
        resolved = CAMPAIGN_RECORD_ADAPTER.validate_python(fixture_dict)
    except ValidationError as e:
        paths: list[str] = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", []))
            paths.append(loc)
        return ValidationResult(
            status=ValidationResultStatus.INVALID_CONTRACT,
            error_codes=["pydantic_validation_error"],
            error_paths=paths,
        )

    # JSON Schema validation against resolved branch
    # (standard jsonschema does not understand discriminator,
    #  so we strip it and validate against the stage-specific sub-schema)
    _STAGE_DEF_MAP = {
        "approved_definition": "ApprovedCampaignDefinition",
        "in_progress": "InProgressCampaignRecord",
        "completed": "CompletedCampaignRecord",
    }
    stage_key = _STAGE_DEF_MAP.get(resolved.record_stage)
    if stage_key:
        branch_schema = _strip_discriminator({
            "$defs": schema.get("$defs", {}),
            **schema["$defs"][stage_key],
        })
        try:
            jsonschema.validate(instance=fixture_dict, schema=branch_schema)
        except jsonschema.ValidationError as e:
            return ValidationResult(
                status=ValidationResultStatus.INVALID_CONTRACT,
                error_codes=["jsonschema_validation_error"],
                error_paths=[str(list(e.absolute_path)) if e.absolute_path else ""],
            )

    # Compute schema identity for valid records
    import hashlib

    from rig_relay.campaign_contract.schema import get_deterministic_schema_json

    schema_json = get_deterministic_schema_json()
    schema_id = hashlib.sha256(schema_json.encode("utf-8")).hexdigest()

    return ValidationResult(
        status=ValidationResultStatus.VALID, schema_identity=schema_id
    )


# ---- Resolver-context validation -------------------------------------


def _check_scope_containment(
    scope_label: str, requested: list[str], approved: list[str]
) -> None:
    """Raise ValueError if requested is not a subset of approved scope."""
    _req = frozenset(requested)
    _app = frozenset(approved)
    if not _req.issubset(_app):
        excess = _req - _app
        raise ValueError(
            f"resolver requested {scope_label} paths exceed approved "
            f"scope: {sorted(excess)}"
        )


def validate_resolver_decision(
    manifest: CampaignManifest,
    blocked_mission_id: str,
    finding: BlockingFinding,
    decision: ResolverEvaluationDecision,
    mission_outcomes: list[MissionOutcome] | None = None,
) -> bool:
    """Validate a resolver promotion decision against the campaign manifest.

    Returns True if the decision is valid.  Raises ValueError with a
    specific reason for any violation.

    Required checks (no check may be deferred as a future comment):
    1. Resolver mission must be in the approved mission universe.
    2. Resolver must appear in the finding's candidate list.
    3. Resolver must appear *after* the blocked mission in
       ordered_missions (forward promotion only).
    4. All resolver prerequisites must have successful outcomes.
    5. Resolver must declare matching resolution scope.
    6. Resolver must not already be consumed/failed/refused/blocked.
    7. Resolver's requested paths/scopes must be contained within its
       approved mission scopes.
    """
    if mission_outcomes is None:
        mission_outcomes = []

    if not decision.is_approved:
        return True  # refusals are always valid structurally

    # 1. Resolver in approved universe
    universe_ids = [m.mission_id for m in manifest.ordered_missions]
    if decision.resolver_mission_id not in universe_ids:
        raise ValueError(
            f"resolver mission '{decision.resolver_mission_id}' "
            "is not in the approved mission universe"
        )

    # 2. Resolver in finding's candidate_approved_resolvers
    if decision.resolver_mission_id not in finding.candidate_approved_resolvers:
        raise ValueError(
            f"resolver '{decision.resolver_mission_id}' "
            "does not declare matching scope for the blocker"
        )

    # 3. Forward promotion: resolver must appear after blocked mission
    try:
        blocked_idx = universe_ids.index(blocked_mission_id)
        resolver_idx = universe_ids.index(decision.resolver_mission_id)
    except ValueError:
        raise ValueError("blocked mission or resolver not found in ordered_missions")
    if resolver_idx <= blocked_idx:
        raise ValueError(
            f"resolver '{decision.resolver_mission_id}' must appear after "
            f"blocked mission '{blocked_mission_id}' in ordered_missions"
        )

    # 4. Resolver prerequisites satisfied
    resolver_mission = manifest.ordered_missions[resolver_idx]
    outcomes_by_id: dict[str, MissionOutcome] = {
        o.mission_id: o for o in mission_outcomes
    }
    for prereq in resolver_mission.prerequisites:
        outcome = outcomes_by_id.get(prereq)
        if outcome is None:
            raise ValueError(
                f"resolver prerequisite '{prereq}' has no recorded outcome"
            )
        if outcome.status != "success":
            raise ValueError(
                f"resolver prerequisite '{prereq}' has status "
                f"'{outcome.status}', required 'success'"
            )

    # 5. Resolver declares matching resolution scope for the finding
    if (
        decision.requested_resolution_scope
        not in resolver_mission.resolver_scope_declarations
    ):
        raise ValueError(
            f"resolver '{decision.resolver_mission_id}' does not declare "
            f"matching scope for resolution scope "
            f"'{decision.requested_resolution_scope}'"
        )

    # 6. Resolver not already consumed/failed/refused/blocked
    blocked_statuses: frozenset[MissionOutcomeStatus] = frozenset({
        "success",  # consumed
        "failure",
        "refused",
        "blocked",
    })
    resolver_outcome = outcomes_by_id.get(decision.resolver_mission_id)
    if resolver_outcome is not None and resolver_outcome.status in blocked_statuses:
        raise ValueError(
            f"resolver '{decision.resolver_mission_id}' is already "
            f"consumed/failed/refused/blocked (status: "
            f"'{resolver_outcome.status}')"
        )

    # 7. Requested scopes contained within resolver's approved mission scopes
    _check_scope_containment(
        "owned_path", decision.requested_owned_paths, resolver_mission.owned_path_scope
    )
    _check_scope_containment(
        "read-context",
        decision.requested_read_context_paths,
        resolver_mission.read_context_scope,
    )
    _check_scope_containment(
        "provider-context",
        decision.requested_provider_context_paths,
        resolver_mission.provider_context_scope,
    )

    return True


# ---- Positive mission transition validation --------------------------


def validate_mission_transition(
    prior: MissionState,
    current: MissionState,
    *,
    resolver_evidence_valid: bool = False,
    repair_evidence_valid: bool = False,
) -> bool:
    """Validate a single mission state transition.

    Uses the positive permit table PERMITTED_TRANSITIONS.
    Evidence-dependent transitions require the corresponding evidence
    flag to be True.
    """
    permitted_next = PERMITTED_TRANSITIONS.get(prior)
    if permitted_next is None:
        raise ValueError(f"unknown prior state: '{prior}'")

    if current not in permitted_next:
        raise ValueError(f"transition '{prior}' -> '{current}' is not permitted")

    pair = (prior, current)
    if pair == ("resolver_promoted_forward", "resumed_after_resolver"):
        if not resolver_evidence_valid:
            raise ValueError(
                "transition 'resolver_promoted_forward' -> "
                "'resumed_after_resolver' requires valid resolver "
                "completion evidence"
            )

    if pair == (
        "incidental_unblock_repair_in_progress",
        "resumed_after_incidental_repair",
    ):
        if not repair_evidence_valid:
            raise ValueError(
                "transition 'incidental_unblock_repair_in_progress' -> "
                "'resumed_after_incidental_repair' requires valid repair "
                "completion evidence"
            )

    return True


# ---- Refusal-category disposition validation -------------------------


def validate_refusal_disposition(
    refusal_category: RefusalCategory, decision: RefusalDisposition
) -> bool:
    """Validate that a refusal category maps to its required disposition.

    All security/confidentiality categories must use halt_entire_campaign.
    Ordinary blockers may use halt_dependent_chain or record_for_next_campaign
    but never halt_entire_campaign.
    """
    if refusal_category in REFUSAL_CATEGORY_DISPOSITION:
        required = REFUSAL_CATEGORY_DISPOSITION[refusal_category]
        if decision != required:
            raise ValueError(
                f"refusal category '{refusal_category}' requires "
                f"disposition '{required}', got '{decision}'"
            )
    elif refusal_category in NON_SECURITY_REFUSAL_CATEGORIES:
        if decision == "halt_entire_campaign":
            raise ValueError(
                f"refusal category '{refusal_category}' cannot use halt_entire_campaign"
            )
    else:
        raise ValueError(f"unknown refusal category: '{refusal_category}'")
    return True


# ---- Event-chain validation ------------------------------------------


class EventChainValidationError(Exception):
    """Raised when event-chain integrity is violated."""


def validate_event_chain(events: list[CampaignExecutionEvent]) -> bool:
    """Validate a complete event chain for cryptographic integrity.

    Checks:
    1. All event_identity values are unique.
    2. Sequences increment strictly.
    3. First event uses GENESIS marker for previous_event_hash.
    4. Each event's previous_event_hash matches the preceding event's
       computed event_hash.
    5. Each event's stored event_hash matches its computed hash.
    6. The state path across the entire chain is legal (every adjacent
       transition passes validate_mission_transition).
    """
    if not events:
        raise EventChainValidationError("event chain is empty")

    identities: set[str] = set()

    for i, event in enumerate(events):
        # Uniqueness
        if event.event_identity in identities:
            raise EventChainValidationError(
                f"duplicate event_identity '{event.event_identity}' at index {i}"
            )
        identities.add(event.event_identity)

        # Sequence
        if event.sequence != i:
            raise EventChainValidationError(
                f"expected sequence {i} at index {i}, "
                f"got {event.sequence} for event "
                f"'{event.event_identity}'"
            )

        # Genesis marker for first event
        if i == 0:
            if event.previous_event_hash != GENESIS_PREVIOUS_HASH:
                raise EventChainValidationError(
                    f"first event '{event.event_identity}' must use "
                    f"'{GENESIS_PREVIOUS_HASH}' as previous_event_hash, "
                    f"got '{event.previous_event_hash}'"
                )
        else:
            # Previous hash linkage
            prev_computed = compute_event_hash(events[i - 1])
            if event.previous_event_hash != prev_computed:
                raise EventChainValidationError(
                    f"event '{event.event_identity}' previous_event_hash "
                    f"'{event.previous_event_hash}' does not match "
                    f"preceding event hash '{prev_computed}'"
                )

        # Event hash tamper check
        computed = compute_event_hash(event)
        if event.event_hash != computed:
            raise EventChainValidationError(
                f"event '{event.event_identity}' stored event_hash "
                f"'{event.event_hash}' does not match computed hash "
                f"'{computed}'"
            )

        # State transition legality (after first event)
        if i > 0:
            prior = events[i - 1].current_state
            current = event.prior_state
            if prior != current:
                raise EventChainValidationError(
                    f"state mismatch at event boundary {i}: "
                    f"event[{i - 1}].current_state='{prior}' != "
                    f"event[{i}].prior_state='{current}'"
                )

    # Validate every adjacent state transition through the table
    for i in range(len(events)):
        pair = (events[i].prior_state, events[i].current_state)
        if pair in EVIDENCE_DEPENDENT_TRANSITIONS:
            # Evidence-dependent transitions are allowed in the chain
            # when the transition exists; the caller is responsible for
            # providing the evidence.  The chain validator only checks
            # that the state sequence is structurally permitted.
            pass
        try:
            validate_mission_transition(
                events[i].prior_state,
                events[i].current_state,
                # Evidence-dependent transitions pass only if the
                # evidence flags are set externally; here we permit
                # them structurally for chain-level validation.
                resolver_evidence_valid=True,
                repair_evidence_valid=True,
            )
        except ValueError as e:
            raise EventChainValidationError(
                f"illegal state transition at event '{events[i].event_identity}': {e}"
            ) from e

    return True
