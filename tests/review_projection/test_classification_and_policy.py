from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from rig_relay.review_projection.classification import ClassificationEngine
from rig_relay.review_projection.models import (
    FileClassification,
    InclusionManifest,
    ProjectionMode,
)
from rig_relay.review_projection.policy import PolicyEngine
from rig_relay.review_projection.public_baseline import PublicBaselineValidator


def test_adversarial_confidential_holdback():
    # Even if an inclusion manifest explicitly requests a file,
    # if it's marked confidential, it must fail closed.
    with TemporaryDirectory() as td:
        root = Path(td)
        conf_file = root / "secret_mechanism.py"
        conf_file.write_text("def secret(): pass")

        rules_path = root / "local_rules.json"
        rules_path.write_text(
            json.dumps({"confidential_paths": ["secret_mechanism.py"]})
        )

        manifest = InclusionManifest(
            mode=ProjectionMode.MAINTAINABILITY_REVIEW,
            approved_files=["secret_mechanism.py"],  # Adversarial override attempt
        )

        policy = PolicyEngine(rules_path)
        classifier = ClassificationEngine(root, policy, manifest)

        result = classifier.classify_file(conf_file)
        assert result == FileClassification.CONFIDENTIAL_HOLDBACK


def test_secret_bearing_fixture_refused():
    with TemporaryDirectory() as td:
        root = Path(td)
        env_file = root / ".env"
        env_file.write_text("API_KEY=foo")

        manifest = InclusionManifest(
            mode=ProjectionMode.MAINTAINABILITY_REVIEW, approved_files=[".env"]
        )

        policy = PolicyEngine()
        classifier = ClassificationEngine(root, policy, manifest)

        assert (
            classifier.classify_file(env_file)
            == FileClassification.EXCLUDED_SECRET_OR_PRIVATE_MATERIAL
        )


def test_public_baseline_offline_attestation():
    with TemporaryDirectory() as td:
        root = Path(td)
        pub_file = root / "public.py"
        pub_file.write_text("def public(): pass")

        # calculate hash to mock attestation
        import hashlib

        pub_hash = hashlib.sha256(pub_file.read_bytes()).hexdigest()

        attestation_path = root / "attestation.json"
        attestation_path.write_text(
            json.dumps({
                "schema_version": "rig.review_projection.public_attestation.v1",
                "commit_sha": "abc1234",
                "verified_files": {"public.py": pub_hash},
                "verification_timestamp": "2026-05-22T00:00:00Z",
                "source": "github_app",
            })
        )

        manifest = InclusionManifest(mode=ProjectionMode.PUBLIC_BASELINE_REVIEW)

        policy = PolicyEngine()
        pub_val = PublicBaselineValidator(attestation_path)
        classifier = ClassificationEngine(root, policy, manifest, pub_val)

        assert (
            classifier.classify_file(pub_file)
            == FileClassification.PUBLIC_ALREADY_DISCLOSED
        )

        # Check tampering fails closed
        tampered_file = root / "public2.py"
        tampered_file.write_text("def public2(): pass")
        assert (
            classifier.classify_file(tampered_file)
            == FileClassification.UNCLASSIFIED_REFUSED
        )
