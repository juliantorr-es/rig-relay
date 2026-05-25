from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.telemetry.tool_contract import ToolMutationClass
from rig_relay.core.tool_runtime_models import ToolRuntimeResult, ToolRuntimeStatus


class MutationDisposition(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    NOT_PERFORMED = "not_performed"
    PERFORMED = "performed"
    PREVIOUSLY_PERFORMED = "previously_performed"
    UNKNOWN = "unknown"


class RetryabilityBasis(StrEnum):
    """Content-light provenance for retryable classification.
    Values are taxonomy-like identifiers, not prose policy. Telemetry safe.
    """

    READ_ONLY_TRANSIENT_FAILURE = "read_only_transient_failure"
    STALE_PRECONDITION_REQUIRES_REBUILD = "stale_precondition_requires_rebuild"
    MUTATION_EFFECT_ALREADY_ESTABLISHED = "mutation_effect_already_established"
    POLICY_REFUSAL_REQUIRES_AUTHORIZATION = "policy_refusal_requires_authorization"
    AMBIGUOUS_EFFECT_REQUIRES_INSPECTION = "ambiguous_effect_requires_inspection"
    CACHED_READ_ONLY_SAFE_REPLAY = "cached_read_only_safe_replay"
    UNSUPPORTED_NO_SAFE_REPLAY_RULE = "unsupported_no_safe_replay_rule"


class AgentToolOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="rig.relay.agent_tool_outcome.v1")
    tool_name: str
    tool_call_id: str
    correlation_id: str | None = None
    causation_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    status: str
    error_kind: str | None = None
    refusal_code: str | None = None
    recoverable: bool | None = None
    retryable: bool = Field(
        default=False,
        description=(
            "Whether replaying the same invocation payload (unchanged arguments, "
            "no state reconstruction) is safe. Safe does not mean meaningful or "
            "recommended. Cached results are safe to replay but usually unnecessary. "
            "The agent should consult suggested_next_action for guidance."
        ),
    )
    retryability_basis: str | None = None
    authority_decision: str | None = None
    authority_source: str | None = None
    mission_identity: str | None = None
    matched_rule_kind: str | None = None
    suggested_next_action: str | None = None
    suggested_next_action_source: str | None = None
    degraded_capabilities: list[str] = Field(default_factory=list)
    mutation_disposition: str = "not_applicable"
    cache_hit: bool = False
    warnings: list[str] = Field(default_factory=list)


_NON_MUTATION_CLASSES: frozenset[ToolMutationClass] = frozenset({
    ToolMutationClass.READ_ONLY,
    ToolMutationClass.WRITES_EVIDENCE_ONLY,
    ToolMutationClass.WRITES_TEMP_ONLY,
})

_REFUSED_FAILED_SET: frozenset[str] = frozenset({
    ToolRuntimeStatus.REFUSED.value,
    ToolRuntimeStatus.FAILED.value,
})


def _derive_mutation_disposition(result: ToolRuntimeResult, is_mutation: bool) -> str:
    if not is_mutation:
        return MutationDisposition.NOT_APPLICABLE.value

    if result.mutation_performed:
        if result.cache_hit:
            return MutationDisposition.PREVIOUSLY_PERFORMED.value
        return MutationDisposition.PERFORMED.value

    if result.status in {ToolRuntimeStatus.REFUSED, ToolRuntimeStatus.FAILED}:
        return MutationDisposition.NOT_PERFORMED.value

    if result.cache_hit:
        return MutationDisposition.NOT_PERFORMED.value

    return MutationDisposition.UNKNOWN.value


_STALE_PRECONDITION_ERRORS: frozenset[str] = frozenset({
    "expected_hash_mismatch",
    "dirty_file_protected",
    "old_text_not_found",
    "multiple_matches_when_single_required",
    "replacement_count_mismatch",
    "overwrite_required",
})

_POLICY_REFUSAL_PREFIXES: tuple[str, ...] = (
    "tool_permission_",
    "approval_",
    "capability_gated",
    "dirty_guard_",
)

_TRANSIENT_ERRORS: frozenset[str] = frozenset({"timeout", "provider_error"})


def _derive_retryability(
    is_mutation: bool,
    disposition: str,
    error_kind: str | None,
    refusal_code: str | None,
    cache_hit: bool,
) -> tuple[bool, str | None]:
    if disposition in {
        MutationDisposition.PERFORMED.value,
        MutationDisposition.PREVIOUSLY_PERFORMED.value,
    }:
        return False, RetryabilityBasis.MUTATION_EFFECT_ALREADY_ESTABLISHED.value
    if disposition == MutationDisposition.UNKNOWN.value:
        return False, RetryabilityBasis.AMBIGUOUS_EFFECT_REQUIRES_INSPECTION.value

    if (
        is_mutation
        and error_kind is not None
        and error_kind in _STALE_PRECONDITION_ERRORS
    ):
        return False, RetryabilityBasis.STALE_PRECONDITION_REQUIRES_REBUILD.value

    if refusal_code is not None and refusal_code.startswith(_POLICY_REFUSAL_PREFIXES):
        return False, RetryabilityBasis.POLICY_REFUSAL_REQUIRES_AUTHORIZATION.value

    if not is_mutation:
        retryable, basis = _read_only_retryability(error_kind, cache_hit)
        if basis is not None:
            return retryable, basis

    return False, RetryabilityBasis.UNSUPPORTED_NO_SAFE_REPLAY_RULE.value


def _read_only_retryability(
    error_kind: str | None, cache_hit: bool
) -> tuple[bool, str | None]:
    if error_kind is not None and error_kind in _TRANSIENT_ERRORS:
        return True, RetryabilityBasis.READ_ONLY_TRANSIENT_FAILURE.value
    if cache_hit:
        return True, RetryabilityBasis.CACHED_READ_ONLY_SAFE_REPLAY.value
    return False, None


def _collect_tool_event_warnings(result: ToolRuntimeResult) -> list[str]:
    warnings: list[str] = []
    for event in result.tool_events:
        event_warnings = getattr(event, "warnings", None)
        if isinstance(event_warnings, list) and all(
            isinstance(w, str) for w in event_warnings
        ):
            warnings.extend(event_warnings)
    return warnings


def derive_agent_outcome(
    result: ToolRuntimeResult, mutation_class: ToolMutationClass | type | None = None
) -> AgentToolOutcome:
    # ── Resolve mutation class ─────────────────────────────────────────
    mutation_class_value: ToolMutationClass = ToolMutationClass.UNKNOWN
    if isinstance(mutation_class, ToolMutationClass):
        mutation_class_value = mutation_class
    elif mutation_class is not None and hasattr(mutation_class, "mutation_class"):
        mutation_class_value = mutation_class.mutation_class
    elif mutation_class is not None:
        mutation_class_value = getattr(
            mutation_class, "mutation_class", ToolMutationClass.UNKNOWN
        )

    outcome = AgentToolOutcome(
        tool_name=result.tool_name,
        tool_call_id=result.tool_call_id,
        correlation_id=getattr(result, "correlation_id", None) or None,
        causation_id=getattr(result, "causation_id", None) or None,
        session_id=getattr(result, "session_id", None) or None,
        turn_id=getattr(result, "turn_id", None) or None,
        status=result.status.value,
        error_kind=result.error_kind,
        cache_hit=result.cache_hit,
        degraded_capabilities=list(result.degraded_capabilities),
    )

    if result.refusal:
        outcome.refusal_code = result.refusal.refusal_code.value
        outcome.recoverable = result.refusal.recoverable
        if result.refusal.suggested_next_action:
            outcome.suggested_next_action = result.refusal.suggested_next_action
            outcome.suggested_next_action_source = "runtime_refusal"

    if outcome.suggested_next_action is None and outcome.error_kind is not None:
        try:
            from rig_relay.core.tools._advice import suggested_next_action_for_error

            advice = suggested_next_action_for_error(
                result.tool_name, outcome.error_kind
            )
        except ImportError:
            advice = None
        if advice:
            outcome.suggested_next_action = advice
            outcome.suggested_next_action_source = "error_advice_mapping"

    if outcome.recoverable is None and outcome.status in _REFUSED_FAILED_SET:
        outcome.recoverable = False

    # mutation_class_value is already resolved above
    is_mutation = mutation_class_value not in _NON_MUTATION_CLASSES

    outcome.mutation_disposition = _derive_mutation_disposition(result, is_mutation)

    outcome.retryable, outcome.retryability_basis = _derive_retryability(
        is_mutation=is_mutation,
        disposition=outcome.mutation_disposition,
        error_kind=outcome.error_kind,
        refusal_code=outcome.refusal_code,
        cache_hit=outcome.cache_hit,
    )

    outcome.authority_decision = getattr(result, "authority_decision", None)
    outcome.authority_source = getattr(result, "authority_source", None)
    outcome.mission_identity = getattr(result, "mission_id", None)
    outcome.matched_rule_kind = getattr(result, "matched_rule_kind", None)

    if outcome.authority_decision is None:
        outcome.authority_decision = "not_evaluated_under_mission_authority"
        outcome.authority_source = "none"

    if outcome.mutation_disposition == MutationDisposition.UNKNOWN.value:
        outcome.warnings.append(
            "Runtime cannot establish mutation outcome. "
            "Re-read affected files to verify state before proceeding."
        )
        if result.status is ToolRuntimeStatus.CACHED and is_mutation:
            outcome.warnings.append(
                "Cached result for mutation tool — cannot verify whether prior "
                "mutation effect was applied. Re-read affected files."
            )

    outcome.warnings.extend(_collect_tool_event_warnings(result))

    return outcome


def format_agent_outcome(outcome: AgentToolOutcome) -> str:
    json_str = outcome.model_dump_json(exclude_none=True)
    return f"<rig-tool-outcome>{json_str}</rig-tool-outcome>"


def neutralize_reserved_delimiters(text: str) -> str:
    text = text.replace("<rig-tool-outcome>", "&lt;rig-tool-outcome&gt;")
    text = text.replace("</rig-tool-outcome>", "&lt;/rig-tool-outcome&gt;")
    return text


__all__ = [
    "AgentToolOutcome",
    "MutationDisposition",
    "RetryabilityBasis",
    "derive_agent_outcome",
    "format_agent_outcome",
    "neutralize_reserved_delimiters",
]
