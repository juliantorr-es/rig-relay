from __future__ import annotations

from datetime import UTC, datetime

from rig_relay.context_egress.compiler import compile_egress_candidate
from rig_relay.context_egress.models import (
    BoundedMissionManifest,
    ProviderMode,
    ProviderPolicyAttestation,
    RetentionMode,
)


def test_crosswalk_separated_contract(tmp_path):
    """contract/integration: Local crosswalk is written separately and cannot appear in provider-bound candidate output."""
    source_file = tmp_path / "foo.py"
    source_file.write_text("def my_secret_func(): pass")

    manifest = BoundedMissionManifest(
        mission_id="test",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(tmp_path),
        approved_fixture_root=str(tmp_path),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root="sink",
    )

    attestation = ProviderPolicyAttestation(
        provider_family="openai",
        endpoint_family="chat",
        retention_mode=RetentionMode.STANDARD,
        human_approved_confidential_minimization=True,
        approval_timestamp=datetime.now(UTC),
        approval_scope="test",
        attestation_source_class="fixture",
    )

    candidate, crosswalk, receipt, ev = compile_egress_candidate(
        source_file, manifest, attestation, "decision_1"
    )

    assert candidate is not None
    assert crosswalk is not None
    assert "my_secret_func" in crosswalk.original_to_opaque_mapping

    cand_json = candidate.model_dump_json()
    assert "my_secret_func" not in cand_json
    assert crosswalk.local_only_warning == "LOCAL ONLY. DO NOT EXPORT."


def test_receipt_content_light_contract(tmp_path):
    """contract/integration: Egress receipt is content-light, records the provider mode, not_transmitted: true."""
    source_file = tmp_path / "foo.py"
    source_file.write_text("def my_secret_func(): pass")

    manifest = BoundedMissionManifest(
        mission_id="test_mission",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(tmp_path),
        approved_fixture_root=str(tmp_path),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root="sink",
    )

    attestation = ProviderPolicyAttestation(
        provider_family="openai",
        endpoint_family="chat",
        retention_mode=RetentionMode.STANDARD,
        human_approved_confidential_minimization=True,
        approval_timestamp=datetime.now(UTC),
        approval_scope="test",
        attestation_source_class="fixture",
    )

    _, _, receipt, _ = compile_egress_candidate(
        source_file, manifest, attestation, "decision_1"
    )

    assert receipt.not_transmitted is True
    assert receipt.output_remains_confidential is True
    assert receipt.declassified is False
    assert receipt.raw_source_in_receipt is False
    assert receipt.mission_id == "test_mission"

    receipt_json = receipt.model_dump_json()
    assert "my_secret_func" not in receipt_json
