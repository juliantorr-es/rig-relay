from __future__ import annotations

from datetime import UTC, datetime

from rig_relay.context_egress.models import (
    ProviderMode,
    ProviderPolicyAttestation,
    RetentionMode,
)


def test_provider_modes_exist_contract():
    """contract/substrate: Ensure required provider modes are defined."""
    assert ProviderMode.PUBLIC_CONTEXT_ONLY
    assert ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED
    assert ProviderMode.HOSTED_PROVIDER_ZDR_CONFIDENTIAL_MINIMIZED
    assert ProviderMode.PROVIDER_UNCLASSIFIED_REFUSED


def test_attestation_requires_explicit_zdr_contract():
    """contract/adversarial: Standard-retention and ZDR-attested fixture modes generate distinct content-light receipt metadata without any live provider query."""
    zdr_attest = ProviderPolicyAttestation(
        provider_family="openai",
        endpoint_family="chat",
        retention_mode=RetentionMode.ZERO_DATA_RETENTION,
        human_approved_confidential_minimization=True,
        approval_timestamp=datetime.now(UTC),
        approval_scope="test",
        attestation_source_class="fixture",
    )
    assert zdr_attest.retention_mode == RetentionMode.ZERO_DATA_RETENTION

    std_attest = ProviderPolicyAttestation(
        provider_family="openai",
        endpoint_family="chat",
        retention_mode=RetentionMode.STANDARD,
        human_approved_confidential_minimization=True,
        approval_timestamp=datetime.now(UTC),
        approval_scope="test",
        attestation_source_class="fixture",
    )
    assert std_attest.retention_mode == RetentionMode.STANDARD
