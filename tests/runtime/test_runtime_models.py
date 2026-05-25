"""Tests for rig_relay.runtime.models — P1c Runtime Model Types."""

from __future__ import annotations

from enum import StrEnum

from pydantic import ValidationError
import pytest

from rig_relay.runtime.models import (
    RuntimeCapability,
    RuntimeCapabilityKind,
    RuntimeInvocationStatus,
    RuntimeProviderDescriptor,
    RuntimeProviderKind,
    RuntimeProviderStatus,
    RuntimeProviderTrustTier,
)


class TestRuntimeProviderKind:
    def test_values_match_rig(self):
        assert list(RuntimeProviderKind) == [
            RuntimeProviderKind.LOCAL,
            RuntimeProviderKind.CLI,
            RuntimeProviderKind.CUSTOM,
            RuntimeProviderKind.DRY_RUN,
            RuntimeProviderKind.STUB,
            RuntimeProviderKind.LOCAL_INFERENCE,
        ]

    def test_string_values(self):
        assert RuntimeProviderKind.LOCAL.value == "local"
        assert RuntimeProviderKind.CLI.value == "cli"
        assert RuntimeProviderKind.CUSTOM.value == "custom"
        assert RuntimeProviderKind.DRY_RUN.value == "dry_run"
        assert RuntimeProviderKind.STUB.value == "stub"

    def test_is_str_enum(self):
        assert issubclass(RuntimeProviderKind, StrEnum)

    def test_from_string(self):
        assert RuntimeProviderKind("local") is RuntimeProviderKind.LOCAL
        assert RuntimeProviderKind("dry_run") is RuntimeProviderKind.DRY_RUN

    def test_rejects_invalid_string(self):
        with pytest.raises(ValueError):
            RuntimeProviderKind("invalid")


class TestRuntimeProviderTrustTier:
    def test_all_tiers_present(self):
        assert list(RuntimeProviderTrustTier) == [
            RuntimeProviderTrustTier.BLOCKED,
            RuntimeProviderTrustTier.ADVISORY,
            RuntimeProviderTrustTier.REVIEWER,
            RuntimeProviderTrustTier.PLANNER,
            RuntimeProviderTrustTier.EXECUTOR_CANDIDATE,
            RuntimeProviderTrustTier.VALIDATOR,
        ]

    def test_string_values(self):
        assert RuntimeProviderTrustTier.BLOCKED.value == "blocked"
        assert RuntimeProviderTrustTier.ADVISORY.value == "advisory"
        assert RuntimeProviderTrustTier.REVIEWER.value == "reviewer"
        assert RuntimeProviderTrustTier.PLANNER.value == "planner"
        assert RuntimeProviderTrustTier.EXECUTOR_CANDIDATE.value == "executor_candidate"
        assert RuntimeProviderTrustTier.VALIDATOR.value == "validator"

    def test_order_is_monotonic(self):
        """Tiers should be ordered from least to most permissive."""
        tiers = list(RuntimeProviderTrustTier)
        assert tiers.index(RuntimeProviderTrustTier.ADVISORY) < tiers.index(
            RuntimeProviderTrustTier.VALIDATOR
        )

    def test_from_string(self):
        assert (
            RuntimeProviderTrustTier("executor_candidate")
            is RuntimeProviderTrustTier.EXECUTOR_CANDIDATE
        )


class TestRuntimeProviderStatus:
    def test_all_statuses_present(self):
        assert list(RuntimeProviderStatus) == [
            RuntimeProviderStatus.AVAILABLE,
            RuntimeProviderStatus.UNAVAILABLE,
            RuntimeProviderStatus.DEGRADED,
            RuntimeProviderStatus.BLOCKED,
            RuntimeProviderStatus.ERROR,
        ]

    def test_string_values(self):
        assert RuntimeProviderStatus.AVAILABLE.value == "available"
        assert RuntimeProviderStatus.DEGRADED.value == "degraded"
        assert RuntimeProviderStatus.ERROR.value == "error"

    def test_from_string(self):
        assert RuntimeProviderStatus("degraded") is RuntimeProviderStatus.DEGRADED


class TestRuntimeCapabilityKind:
    def test_includes_rig_originals(self):
        """All 8 Rig-original capability kinds are present."""
        assert RuntimeCapabilityKind.FILE_READ.value == "file_read"
        assert RuntimeCapabilityKind.FILE_WRITE_PROPOSAL.value == "file_write_proposal"
        assert RuntimeCapabilityKind.SHELL_PROPOSAL.value == "shell_proposal"
        assert RuntimeCapabilityKind.PATCH_PROPOSAL.value == "patch_proposal"
        assert RuntimeCapabilityKind.REPLAY_ACCESS.value == "replay_access"
        assert (
            RuntimeCapabilityKind.NETWORK_FETCH_PROPOSAL.value
            == "network_fetch_proposal"
        )
        assert RuntimeCapabilityKind.DOCS_FETCH_PROPOSAL.value == "docs_fetch_proposal"
        assert (
            RuntimeCapabilityKind.TELEMETRY_EXPORT_PROPOSAL.value
            == "telemetry_export_proposal"
        )

    def test_includes_relay_extensions(self):
        """6 Rig Relay extension capability kinds are present."""
        assert RuntimeCapabilityKind.VALIDATION.value == "validation"
        assert RuntimeCapabilityKind.RECEIPT_READ.value == "receipt_read"
        assert RuntimeCapabilityKind.COORDINATION_READ.value == "coordination_read"
        assert RuntimeCapabilityKind.COORDINATION_WRITE.value == "coordination_write"
        assert RuntimeCapabilityKind.WORKTREE_READ.value == "worktree_read"
        assert RuntimeCapabilityKind.WORKTREE_WRITE.value == "worktree_write"

    def test_total_count(self):
        assert len(list(RuntimeCapabilityKind)) == 14

    def test_from_string(self):
        assert (
            RuntimeCapabilityKind("network_fetch_proposal")
            is RuntimeCapabilityKind.NETWORK_FETCH_PROPOSAL
        )
        assert (
            RuntimeCapabilityKind("coordination_read")
            is RuntimeCapabilityKind.COORDINATION_READ
        )


class TestRuntimeInvocationStatus:
    def test_all_statuses_present(self):
        assert list(RuntimeInvocationStatus) == [
            RuntimeInvocationStatus.PENDING,
            RuntimeInvocationStatus.STARTING,
            RuntimeInvocationStatus.RUNNING,
            RuntimeInvocationStatus.SUCCEEDED,
            RuntimeInvocationStatus.FAILED,
            RuntimeInvocationStatus.TIMED_OUT,
            RuntimeInvocationStatus.CANCELLED,
            RuntimeInvocationStatus.BLOCKED,
            RuntimeInvocationStatus.BUDGET_EXCEEDED,
        ]

    def test_string_values(self):
        assert RuntimeInvocationStatus.PENDING.value == "pending"
        assert RuntimeInvocationStatus.SUCCEEDED.value == "succeeded"
        assert RuntimeInvocationStatus.TIMED_OUT.value == "timed_out"
        assert RuntimeInvocationStatus.CANCELLED.value == "cancelled"

    def test_from_string(self):
        assert RuntimeInvocationStatus("timed_out") is RuntimeInvocationStatus.TIMED_OUT
        assert RuntimeInvocationStatus("cancelled") is RuntimeInvocationStatus.CANCELLED


class TestRuntimeCapabilityModel:
    def test_required_fields(self):
        cap = RuntimeCapability(capability_kind=RuntimeCapabilityKind.FILE_READ)
        assert cap.capability_kind == RuntimeCapabilityKind.FILE_READ
        assert cap.scope == "request"

    def test_explicit_scope(self):
        cap = RuntimeCapability(
            capability_kind=RuntimeCapabilityKind.SHELL_PROPOSAL, scope="session"
        )
        assert cap.scope == "session"

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            RuntimeCapability(
                capability_kind=RuntimeCapabilityKind.FILE_READ,
                extra_field="nope",  # pyright: ignore[reportCallIssue]
            )

    def test_serializes_to_json(self):
        cap = RuntimeCapability(
            capability_kind=RuntimeCapabilityKind.COORDINATION_WRITE, scope="workspace"
        )
        data = cap.model_dump(mode="json")
        assert data == {"capability_kind": "coordination_write", "scope": "workspace"}

    def test_deserializes_from_dict(self):
        data = {"capability_kind": "patch_proposal", "scope": "global"}
        cap = RuntimeCapability.model_validate(data)
        assert cap.capability_kind == RuntimeCapabilityKind.PATCH_PROPOSAL
        assert cap.scope == "global"

    def test_deserialization_rejects_unknown_kind(self):
        with pytest.raises(ValueError):
            RuntimeCapability.model_validate({"capability_kind": "nonexistent"})


class TestRuntimeProviderDescriptorModel:
    def test_required_fields(self):
        desc = RuntimeProviderDescriptor(provider_id="test-provider")
        assert desc.provider_id == "test-provider"
        assert desc.kind == RuntimeProviderKind.CUSTOM
        assert desc.trust_tier == RuntimeProviderTrustTier.ADVISORY
        assert desc.status == RuntimeProviderStatus.UNAVAILABLE
        assert desc.version == "unknown"

    def test_explicit_values(self):
        desc = RuntimeProviderDescriptor(
            provider_id="openai",
            kind=RuntimeProviderKind.CLI,
            trust_tier=RuntimeProviderTrustTier.VALIDATOR,
            status=RuntimeProviderStatus.AVAILABLE,
            version="1.2.0",
        )
        assert desc.provider_id == "openai"
        assert desc.kind == RuntimeProviderKind.CLI
        assert desc.trust_tier == RuntimeProviderTrustTier.VALIDATOR
        assert desc.status == RuntimeProviderStatus.AVAILABLE
        assert desc.version == "1.2.0"

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            RuntimeProviderDescriptor(provider_id="p", extra_field="nope")  # pyright: ignore[reportCallIssue]

    def test_serializes_to_json(self):
        desc = RuntimeProviderDescriptor(
            provider_id="dry-runner",
            kind=RuntimeProviderKind.DRY_RUN,
            trust_tier=RuntimeProviderTrustTier.BLOCKED,
            status=RuntimeProviderStatus.ERROR,
            version="0.0.0",
        )
        data = desc.model_dump(mode="json")
        assert data == {
            "provider_id": "dry-runner",
            "kind": "dry_run",
            "trust_tier": "blocked",
            "status": "error",
            "version": "0.0.0",
        }

    def test_deserializes_from_dict(self):
        data = {
            "provider_id": "stubby",
            "kind": "stub",
            "trust_tier": "planner",
            "status": "degraded",
            "version": "3.0.0",
        }
        desc = RuntimeProviderDescriptor.model_validate(data)
        assert desc.provider_id == "stubby"
        assert desc.kind == RuntimeProviderKind.STUB
        assert desc.trust_tier == RuntimeProviderTrustTier.PLANNER
        assert desc.status == RuntimeProviderStatus.DEGRADED
        assert desc.version == "3.0.0"

    def test_deserialization_rejects_unknown_enum_values(self):
        with pytest.raises(ValueError):
            RuntimeProviderDescriptor.model_validate({
                "provider_id": "bad",
                "kind": "nonexistent",
            })

    def test_round_trip_through_json(self):
        original = RuntimeProviderDescriptor(
            provider_id="round-tripper",
            kind=RuntimeProviderKind.LOCAL,
            trust_tier=RuntimeProviderTrustTier.REVIEWER,
            status=RuntimeProviderStatus.AVAILABLE,
            version="2.1.0",
        )
        raw = original.model_dump(mode="json")
        restored = RuntimeProviderDescriptor.model_validate(raw)
        assert restored == original
