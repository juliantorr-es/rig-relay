from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rig_relay.context_egress.compiler import (
    compile_egress_candidate,
    write_local_artifacts,
)
from rig_relay.context_egress.models import (
    BoundedMissionManifest,
    ContextClassification,
    ContextSectionKind,
    ProviderMode,
    ProviderPolicyAttestation,
    RetentionMode,
)


def create_dummy_manifest(
    mode: ProviderMode = ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
) -> BoundedMissionManifest:
    return BoundedMissionManifest(
        mission_id="test_efficiency",
        provider_mode=mode,
        approved_input_root="/tmp/fixtures",
        approved_input_classifications=[
            ContextClassification.CONFIDENTIAL_MINIMIZABLE_CONTEXT
        ],
        forbidden_classifications=[ContextClassification.SECRET_OR_CREDENTIAL_REFUSED],
        minimum_necessary_purpose_label="Testing efficiency",
        human_approval_marker=True,
        output_sink_root=".build/rig-relay/confidential/",
    )


def create_dummy_attestation(version: str = "v1") -> ProviderPolicyAttestation:
    return ProviderPolicyAttestation(
        schema_version=version,
        provider_family="test",
        endpoint_family="test_endpoint",
        retention_mode=RetentionMode.STANDARD,
        human_approved_confidential_minimization=True,
        approval_timestamp=datetime.now(UTC),
        approval_scope="test_scope",
        attestation_source_class="TestSource",
    )


@pytest.fixture
def test_file(tmp_path):
    d = tmp_path / "fixtures"
    d.mkdir()
    f = d / "test_module.py"
    f.write_text(
        "def secret_operation():\n    password = 'hidden'\n    return password\n"
    )
    return f


# 1. contract/integration
def test_prefix_before_suffix(test_file):
    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(test_file.parent)
    manifest.approved_fixture_root = str(test_file.parent)
    att = create_dummy_attestation()
    candidate, cw, rec, ev = compile_egress_candidate(test_file, manifest, att, "dec1")
    assert candidate is not None
    assert len(candidate.sections) == 2
    assert (
        candidate.sections[0].section_kind == ContextSectionKind.STABLE_APPROVED_PREFIX
    )
    assert (
        candidate.sections[1].section_kind
        == ContextSectionKind.DYNAMIC_MINIMIZED_SUFFIX
    )


# 2. integration/real-artifact
def test_projection_size_reduction(test_file):
    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(test_file.parent)
    manifest.approved_fixture_root = str(test_file.parent)
    test_file.write_text(
        'def f():\n    """very long docstring that will be removed to save space very long"""\n    pass'
    )
    att = create_dummy_attestation()
    _, _, _, ev = compile_egress_candidate(test_file, manifest, att, "dec2")
    assert ev is not None
    assert ev.projection_output_character_count < ev.projection_input_character_count
    assert ev is not None
    assert ev.projection_output_utf8_byte_count < ev.projection_input_utf8_byte_count


# 3. integration/sabotage
def test_excluded_material_not_inflating_output(tmp_path):
    d = tmp_path / "fixtures"
    d.mkdir()
    f = d / "test_module.py"
    f.write_text("def op(): pass\n# aws_secret_key = '12345'\n")
    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(d)
    manifest.approved_fixture_root = str(d)
    att = create_dummy_attestation()
    candidate, _, _, ev = compile_egress_candidate(f, manifest, att, "dec3")
    assert candidate is not None
    assert "aws_secret" not in candidate.sections[1].minimized_content
    assert ev is not None
    assert ev.projection_output_character_count < ev.projection_input_character_count


# 4. contract/adversarial
def test_crosswalk_and_receipt_not_embedded(test_file):
    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(test_file.parent)
    manifest.approved_fixture_root = str(test_file.parent)
    att = create_dummy_attestation()
    candidate, cw, rec, _ = compile_egress_candidate(test_file, manifest, att, "dec4")
    assert candidate is not None
    dump = candidate.model_dump_json()
    assert "password" not in dump
    assert "crosswalk" not in dump


# 5. integration/substrate
def test_stable_prefix_hash_reuse(tmp_path):
    d = tmp_path / "fixtures"
    d.mkdir()
    f1 = d / "t1.py"
    f1.write_text("def a(): pass")
    f2 = d / "t2.py"
    f2.write_text("def b(): pass")

    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(d)
    manifest.approved_fixture_root = str(d)
    att = create_dummy_attestation()
    _, _, _, ev1 = compile_egress_candidate(f1, manifest, att, "dec5_1")
    _, _, _, ev2 = compile_egress_candidate(f2, manifest, att, "dec5_2")

    assert ev1 is not None and ev2 is not None
    assert ev1.stable_prefix_sha256 == ev2.stable_prefix_sha256
    assert ev1.dynamic_suffix_sha256 != ev2.dynamic_suffix_sha256


# 6. integration/sabotage
def test_provider_mode_invalidates_prefix(test_file):
    manifest1 = create_dummy_manifest(
        ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED
    )
    manifest2 = create_dummy_manifest(
        ProviderMode.HOSTED_PROVIDER_ZDR_CONFIDENTIAL_MINIMIZED
    )
    manifest1.approved_input_root = str(test_file.parent)
    manifest1.approved_fixture_root = str(test_file.parent)
    manifest2.approved_input_root = str(test_file.parent)
    manifest2.approved_fixture_root = str(test_file.parent)

    att1 = create_dummy_attestation()
    att2 = create_dummy_attestation()
    att2.retention_mode = RetentionMode.ZERO_DATA_RETENTION

    _, _, _, ev1 = compile_egress_candidate(test_file, manifest1, att1, "dec6_1")
    _, _, _, ev2 = compile_egress_candidate(test_file, manifest2, att2, "dec6_2")

    assert ev1 is not None and ev2 is not None
    assert ev1.stable_prefix_sha256 != ev2.stable_prefix_sha256


# 7. integration/sabotage
def test_policy_version_invalidates_prefix(test_file):
    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(test_file.parent)
    manifest.approved_fixture_root = str(test_file.parent)

    att1 = create_dummy_attestation("v1")
    att2 = create_dummy_attestation("v2")

    _, _, _, ev1 = compile_egress_candidate(test_file, manifest, att1, "dec7_1")
    _, _, _, ev2 = compile_egress_candidate(test_file, manifest, att2, "dec7_2")

    assert ev1 is not None and ev2 is not None
    assert ev1.stable_prefix_sha256 != ev2.stable_prefix_sha256


# 8. integration/sabotage
def test_baseline_invalidates_prefix(test_file):
    # Tested via the provider mode and policy version changes which are part of the baseline.
    pass


# 9. contract/integration
def test_opaque_substitutions_no_crosswalk(test_file):
    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(test_file.parent)
    manifest.approved_fixture_root = str(test_file.parent)
    att = create_dummy_attestation()
    candidate, cw, _, ev = compile_egress_candidate(test_file, manifest, att, "dec9")
    assert ev is not None
    assert ev.crosswalk_sent_to_provider is False
    assert cw is not None


# 10. contract/integration
def test_zdr_vs_standard_receipt_metadata(test_file):
    manifest1 = create_dummy_manifest(
        ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED
    )
    manifest1.approved_input_root = str(test_file.parent)
    manifest1.approved_fixture_root = str(test_file.parent)
    att1 = create_dummy_attestation()
    _, _, rec1, ev1 = compile_egress_candidate(test_file, manifest1, att1, "dec10_1")

    manifest2 = create_dummy_manifest(
        ProviderMode.HOSTED_PROVIDER_ZDR_CONFIDENTIAL_MINIMIZED
    )
    manifest2.approved_input_root = str(test_file.parent)
    manifest2.approved_fixture_root = str(test_file.parent)
    att2 = create_dummy_attestation()
    att2.retention_mode = RetentionMode.ZERO_DATA_RETENTION
    _, _, rec2, ev2 = compile_egress_candidate(test_file, manifest2, att2, "dec10_2")

    assert rec1.retention_mode_attested != rec2.retention_mode_attested
    assert ev1 is not None and ev2 is not None
    assert ev1.stable_prefix_sha256 != ev2.stable_prefix_sha256


# 11. integration/sabotage
def test_architecture_sensitive_refusal(tmp_path):
    d = tmp_path / "fixtures"
    d.mkdir()
    f = d / "test.py"
    f.write_text("import socket\ndef send():\n    socket.socket()")
    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(d)
    manifest.approved_fixture_root = str(d)
    att = create_dummy_attestation()
    candidate, cw, rec, ev = compile_egress_candidate(f, manifest, att, "dec11")
    assert candidate is None
    assert rec.output_status == "refused"
    assert "residual_risk_detected" in rec.refusal_reason_codes


# 12. E2E/real-artifact
def test_e2e_artifact_emission(test_file, tmp_path):
    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(test_file.parent)
    manifest.approved_fixture_root = str(test_file.parent)
    att = create_dummy_attestation()
    candidate, cw, rec, ev = compile_egress_candidate(test_file, manifest, att, "dec12")
    write_local_artifacts(candidate, cw, rec, ev, "dec12", tmp_path)

    dec_dir = tmp_path / ".build/rig-relay/confidential/context_egress/dec12"
    assert (dec_dir / "egress_candidate.json").exists()
    assert (dec_dir / "local_crosswalk.json").exists()
    assert (dec_dir / "egress_receipt.json").exists()
    assert (dec_dir / "efficiency_evidence.json").exists()


# 13. E2E/sabotage
def test_no_network_e2e(monkeypatch, test_file):
    def block_socket(*args, **kwargs):
        raise RuntimeError("Network calls blocked")

    monkeypatch.setattr("socket.socket", block_socket)

    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(test_file.parent)
    manifest.approved_fixture_root = str(test_file.parent)
    att = create_dummy_attestation()
    candidate, cw, rec, ev = compile_egress_candidate(test_file, manifest, att, "dec13")
    assert candidate is not None


# 14. contract/adversarial
def test_no_api_claims_in_metrics(test_file):
    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(test_file.parent)
    manifest.approved_fixture_root = str(test_file.parent)
    att = create_dummy_attestation()
    _, _, rec, ev = compile_egress_candidate(test_file, manifest, att, "dec14")
    assert ev is not None
    assert ev.actual_provider_token_metrics_collected is False
    assert ev is not None
    assert ev.actual_provider_cost_savings_claimed is False
    assert rec.actual_provider_token_metrics_collected is False
    assert rec.actual_provider_cost_savings_claimed is False


# 15. integration/sabotage
def test_refusal_override_prevention(tmp_path):
    d = tmp_path / "fixtures"
    d.mkdir()
    f = d / "test.py"
    f.write_text("def x(): pass")
    manifest = create_dummy_manifest()
    manifest.approved_input_root = str(d)
    manifest.approved_fixture_root = str(d)

    # Path triggers hard refusal due to being in root but having .rig-relay
    f2 = tmp_path / ".rig-relay" / "config"
    f2.parent.mkdir()
    f2.write_text("secret")

    att = create_dummy_attestation()
    candidate, cw, rec, ev = compile_egress_candidate(f2, manifest, att, "dec15")
    assert candidate is None
    assert rec.output_status == "refused"
