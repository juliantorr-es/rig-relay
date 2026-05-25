from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.review_projection.bundle_builder import BundleBuilder
from rig_relay.review_projection.classification import ClassificationEngine
from rig_relay.review_projection.models import (
    BundleManifest,
    DisclosureReceipt,
    FileClassification,
    InclusionManifest,
    LocalCrosswalk,
    ProjectionMode,
)
from rig_relay.review_projection.policy import PolicyEngine


def _make_receipt(projection_id: str, mode: ProjectionMode) -> DisclosureReceipt:
    return DisclosureReceipt(
        projection_id=projection_id,
        mode=mode,
        created_at="2026-05-22T00:00:00Z",
        source_root_fingerprint="sha256:root",
        branch="main",
        head_sha="d" * 12,
        public_baseline_status="none",
        policy_version="v1",
        input_file_count=0,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="pending",
        output_status="classification_incomplete",
    )


@pytest.mark.integration
@pytest.mark.sabotage
def test_classification_refuses_confidential_root_before_body_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    confidential_file = (
        repo_root / ".build" / "rig-relay" / "confidential" / "secret_mechanism.py"
    )
    confidential_file.parent.mkdir(parents=True)
    confidential_file.write_text(
        "def secret():\n    return 'hidden'\n", encoding="utf-8"
    )

    manifest = InclusionManifest(
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        approved_files=[str(confidential_file.relative_to(repo_root))],
    )
    classifier = ClassificationEngine(repo_root, PolicyEngine(), manifest)

    called = {"value": False}

    def fail_hash(_path: Path) -> str:
        called["value"] = True
        raise AssertionError("_hash_file must not be called for confidential paths")

    monkeypatch.setattr(classifier, "_hash_file", fail_hash)

    assert (
        classifier.classify_file(confidential_file)
        is FileClassification.CONFIDENTIAL_HOLDBACK
    )
    assert not called["value"]


@pytest.mark.integration
@pytest.mark.sabotage
def test_bundle_emission_refuses_confidential_descendant_even_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    builder = BundleBuilder(output_dir)
    projection_id = "proj-001"
    confidential_rel_path = ".build/rig-relay/confidential/secret_mechanism.py"

    bundle_manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id=projection_id)
    receipt = _make_receipt(projection_id, ProjectionMode.MAINTAINABILITY_REVIEW)

    called = {"value": False}

    def fail_zip(*_args: object, **_kwargs: object) -> str:
        called["value"] = True
        raise AssertionError("deterministic_zip_write must not be called")

    monkeypatch.setattr(
        "rig_relay.review_projection.bundle_builder.deterministic_zip_write", fail_zip
    )

    with pytest.raises(
        ValueError, match="confidential_artifact_refused:review_projection_bundle"
    ):
        builder.write_bundle(
            projection_id,
            {confidential_rel_path: "def secret():\n    return 'hidden'\n"},
            bundle_manifest,
            crosswalk,
            receipt,
        )

    assert not called["value"]
