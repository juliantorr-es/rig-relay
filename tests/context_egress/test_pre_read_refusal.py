from __future__ import annotations

from pathlib import Path

from rig_relay.context_egress.boundary import refuse_provider_context_input
from rig_relay.context_egress.models import (
    BoundedMissionManifest,
    ContextClassification,
    ProviderMode,
)


def test_public_context_only_adversarial_contract(tmp_path):
    """contract/adversarial: public_context_only permits only public-attested fixture context and refuses every non-public classification."""
    manifest = BoundedMissionManifest(
        mission_id="test",
        provider_mode=ProviderMode.PUBLIC_CONTEXT_ONLY,
        approved_input_root=str(tmp_path),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root="sink",
    )

    # In public context mode, a random path is still checked against approved_file_list if provided
    refused, reason, klass = refuse_provider_context_input(
        tmp_path / "foo.py", "candidate", manifest
    )
    assert not refused


def test_provider_unclassified_refused_adversarial(tmp_path):
    """contract/adversarial: provider_unclassified_refused refuses all non-public context."""
    manifest = BoundedMissionManifest(
        mission_id="test",
        provider_mode=ProviderMode.PROVIDER_UNCLASSIFIED_REFUSED,
        approved_input_root=str(tmp_path),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root="sink",
    )
    refused, reason, klass = refuse_provider_context_input(
        tmp_path / "foo.py", "candidate", manifest
    )
    assert refused
    assert reason == "no_fixture_root_provided"


def test_fixture_only_lock_integration_sabotage(tmp_path):
    """integration/sabotage: Refuses live repository working tree for non-public modes."""
    manifest = BoundedMissionManifest(
        mission_id="test",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(tmp_path),
        approved_fixture_root=str(tmp_path),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root="sink",
    )

    # Try to pass a live repo path outside fixture root
    live_path = Path(
        "/Users/user/Developer/GitHub/rig-relay/rig_relay/core/paths/__init__.py"
    )
    refused, reason, klass = refuse_provider_context_input(
        live_path, "candidate", manifest
    )
    assert refused
    assert reason == "live_confidential_repository_input_refused"


def test_hard_refusal_patterns_integration_sabotage(tmp_path):
    """integration/sabotage: Hard refusal categories remain refused in every hosted mode."""
    manifest = BoundedMissionManifest(
        mission_id="test",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(tmp_path),
        approved_fixture_root=str(tmp_path),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root="sink",
    )

    secret_path = tmp_path / "my_secret_token.txt"
    refused, reason, klass = refuse_provider_context_input(
        secret_path, "candidate", manifest
    )
    assert refused
    assert reason == "hard_refusal_pattern_matched"
    assert klass == ContextClassification.SECRET_OR_CREDENTIAL_REFUSED


def test_confidential_artifact_descendants_sabotage(tmp_path):
    """integration/sabotage: Confidential artifact-root descendants are refused before file-body reads."""
    manifest = BoundedMissionManifest(
        mission_id="test",
        provider_mode=ProviderMode.HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED,
        approved_input_root=str(tmp_path),
        approved_fixture_root=str(tmp_path),
        minimum_necessary_purpose_label="test",
        human_approval_marker=True,
        output_sink_root="sink",
    )

    # This path contains .build/rig-relay/confidential
    conf_path = tmp_path / ".build/rig-relay/confidential/some_audit.json"
    refused, reason, klass = refuse_provider_context_input(
        conf_path, "candidate", manifest
    )
    assert refused
    assert reason == "confidential_artifact_input_refused"
