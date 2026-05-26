"""Test recovery admission policy — risk-tiered, zero auto-execute for mutations."""

from __future__ import annotations

from rig_relay.recovery.admission_policy import (
    decide_admission,
    is_auto_execute_decision,
    is_mutation_class,
)
from rig_relay.recovery.models import (
    AdmittedToolEntry,
    RecoveryAdmissionDecision,
    RecoveryAdmissionTier,
    RecoveryIntent,
)


def _make_entry(
    canonical_name: str, tier: RecoveryAdmissionTier, mutation_class: str = "read_only"
) -> AdmittedToolEntry:
    return AdmittedToolEntry(
        canonical_name=canonical_name,
        mutation_class=mutation_class,
        determinism_class="deterministic_repo_state",
        args_schema_digest="sha256:" + "a" * 64,
        recovery_admission_tier=tier,
    )


def _make_intent(
    canonical_name: str, mutation_class: str | None = None
) -> RecoveryIntent:
    return RecoveryIntent(
        canonical_tool_name=canonical_name,
        normalized_args={},
        payload_digest="sha256:" + "b" * 64,
        manifest_digest="sha256:" + "c" * 64,
        mutation_class=mutation_class,
    )


def test_read_only_gets_auto_execute() -> None:
    entry = _make_entry("git_status", RecoveryAdmissionTier.READ_ONLY_RECOVERABLE)
    intent = _make_intent("git_status", "read_only")
    result = decide_admission(intent, entry)
    assert result.admission_decision == RecoveryAdmissionDecision.AUTO_EXECUTE_READ_ONLY
    assert result.proposal_only is False


def test_validation_gets_auto_execute() -> None:
    entry = _make_entry("validate", RecoveryAdmissionTier.VALIDATION_RECOVERABLE)
    intent = _make_intent("validate", "read_only")
    result = decide_admission(intent, entry)
    assert (
        result.admission_decision == RecoveryAdmissionDecision.AUTO_EXECUTE_VALIDATION
    )
    assert result.proposal_only is False


def test_mutation_gets_proposal_only() -> None:
    entry = _make_entry(
        "write_file", RecoveryAdmissionTier.MUTATION_PROPOSAL_ONLY, "writes_workspace"
    )
    intent = _make_intent("write_file", "writes_workspace")
    result = decide_admission(intent, entry)
    assert result.admission_decision == RecoveryAdmissionDecision.PROPOSAL_ONLY_MUTATION
    assert result.proposal_only is True


def test_external_side_effect_refused() -> None:
    entry = _make_entry(
        "github_dispatch",
        RecoveryAdmissionTier.EXTERNAL_SIDE_EFFECT_REFUSE,
        "external_side_effect",
    )
    intent = _make_intent("github_dispatch", "external_side_effect")
    result = decide_admission(intent, entry)
    assert (
        result.admission_decision
        == RecoveryAdmissionDecision.REQUIRE_REMOTE_AUTHORIZATION
    )


def test_raw_shell_refused() -> None:
    entry = _make_entry(
        "bash", RecoveryAdmissionTier.RAW_SHELL_REFUSE, "writes_workspace"
    )
    intent = _make_intent("bash", "writes_workspace")
    result = decide_admission(intent, entry)
    assert result.admission_decision == RecoveryAdmissionDecision.REFUSE_RAW_SHELL


def test_unsupported_refused() -> None:
    entry = _make_entry("something_broken", RecoveryAdmissionTier.UNSUPPORTED_REFUSE)
    intent = _make_intent("something_broken")
    result = decide_admission(intent, entry)
    assert result.admission_decision == RecoveryAdmissionDecision.REFUSE_UNSUPPORTED


def test_is_mutation_class_detects_writes() -> None:
    assert is_mutation_class("writes_workspace") is True
    assert is_mutation_class("mutates_git_state") is True
    assert is_mutation_class("external_side_effect") is True
    assert is_mutation_class("read_only") is False
    assert is_mutation_class(None) is False


def test_is_auto_execute_detects_auto_decisions() -> None:
    assert is_auto_execute_decision(RecoveryAdmissionDecision.AUTO_EXECUTE_READ_ONLY)
    assert is_auto_execute_decision(RecoveryAdmissionDecision.AUTO_EXECUTE_VALIDATION)
    assert not is_auto_execute_decision(
        RecoveryAdmissionDecision.PROPOSAL_ONLY_MUTATION
    )
    assert not is_auto_execute_decision(RecoveryAdmissionDecision.REFUSE_RAW_SHELL)


def test_zero_mutation_auto_execute_invariant() -> None:
    mutation_tiers = [
        RecoveryAdmissionTier.MUTATION_PROPOSAL_ONLY,
        RecoveryAdmissionTier.EXTERNAL_SIDE_EFFECT_REFUSE,
        RecoveryAdmissionTier.RAW_SHELL_REFUSE,
    ]
    for tier in mutation_tiers:
        entry = _make_entry("tool_x", tier, "writes_workspace")
        intent = _make_intent("tool_x", "writes_workspace")
        result = decide_admission(intent, entry)
        assert not is_auto_execute_decision(result.admission_decision), (
            f"Mutation tier {tier} produced auto-execute decision: {result.admission_decision}"
        )
