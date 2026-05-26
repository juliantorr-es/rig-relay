"""Causal tests for protected-content classification, manifest generation,
bundle integrity, scoped disclosure, and crosswalk prohibition.

Uses real temporary files, real bundle generation, real manifests,
and real disclosure authorization receipts.
"""

from __future__ import annotations

import hashlib
import json
import shutil

import pytest

from rig_relay.governance.disclosure_authorization import (
    DisclosureClass,
    _store_root as _gov_store_root,
)
from rig_relay.review_projection.bundle_builder import BundleBuilder
from rig_relay.review_projection.models import (
    BundleManifest,
    DisclosureReceipt,
    LocalCrosswalk,
    ProjectionMode,
)
from rig_relay.review_projection.protected_content import (
    MANIFEST_SCHEMA_VERSION,
    POLICY_VERSION,
    ContentClass,
    ContentKind,
    ManifestSelector,
    build_default_manifest,
    classify_content_kind,
    compute_manifest_digest,
    compute_selector_digest,
    is_disclosure_class_prohibited,
    load_manifest_json,
    manifest_passes_content_light_check,
    mark_selector_disclosed,
    seal_manifest,
    verify_manifest_binding,
    verify_manifest_integrity,
    verify_policy_version,
    verify_selector_disclosable,
    write_manifest_json,
)
from rig_relay.review_projection.residual_scanner import ResidualRiskScanner

EVIDENCE_DIGEST = (
    "sha256:0000111122223333444455556666777788889999aaaabbbbccccddddeeeeffff"
)


def _sha256(data: str) -> str:
    return "sha256:" + hashlib.sha256(data.encode()).hexdigest()


def _clean_gov_store():
    root = _gov_store_root()
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# Content classification policy
# ═══════════════════════════════════════════════════════════════════════


def test_classify_source_identifier_is_pseudonymized_disclosable():
    assert (
        classify_content_kind(ContentKind.SOURCE_IDENTIFIER.value)
        == ContentClass.PSEUDONYMIZED_DISCLOSABLE
    )


def test_classify_string_literal_is_hash_evidence_only():
    assert (
        classify_content_kind(ContentKind.SOURCE_STRING_LITERAL.value)
        == ContentClass.HASH_EVIDENCE_ONLY
    )


def test_classify_comment_is_hash_evidence_only():
    assert (
        classify_content_kind(ContentKind.SOURCE_COMMENT.value)
        == ContentClass.HASH_EVIDENCE_ONLY
    )


def test_classify_credential_is_prohibited():
    assert (
        classify_content_kind(ContentKind.CREDENTIAL_SHAPED.value)
        == ContentClass.PROHIBITED
    )


def test_classify_secret_is_prohibited():
    assert (
        classify_content_kind(ContentKind.SECRET_SHAPED.value)
        == ContentClass.PROHIBITED
    )


def test_classify_crosswalk_is_prohibited():
    assert (
        classify_content_kind(ContentKind.CROSSWALK_MATERIAL.value)
        == ContentClass.PROHIBITED
    )


def test_classify_bundle_metadata_is_retain_projected():
    assert (
        classify_content_kind(ContentKind.BUNDLE_METADATA.value)
        == ContentClass.RETAIN_PROJECTED
    )


def test_classify_unknown_is_hash_evidence_only():
    assert classify_content_kind("nonexistent_kind") == ContentClass.HASH_EVIDENCE_ONLY


def test_disclosure_class_prohibited_raw_content():
    assert is_disclosure_class_prohibited(DisclosureClass.RAW_CONTENT.value) is True


def test_disclosure_class_prohibited_commit_patch():
    assert is_disclosure_class_prohibited(DisclosureClass.COMMIT_PATCH.value) is True


def test_disclosure_class_not_prohibited_path_identity():
    assert is_disclosure_class_prohibited(DisclosureClass.PATH_IDENTITY.value) is False


# ═══════════════════════════════════════════════════════════════════════
# Manifest generation and integrity
# ═══════════════════════════════════════════════════════════════════════


def test_build_default_manifest():
    manifest = build_default_manifest("proj-1", EVIDENCE_DIGEST, "sha-src", "now")
    assert manifest.schema_version == MANIFEST_SCHEMA_VERSION
    assert manifest.bundle_digest == EVIDENCE_DIGEST
    assert manifest.policy_version == POLICY_VERSION
    assert manifest.manifest_digest != ""
    assert manifest.content_light_guarantee is True
    assert manifest.raw_content_in_manifest is False
    assert manifest.crosswalk_export_prohibited is True


def test_manifest_digest_deterministic():
    m1 = build_default_manifest("proj-1", EVIDENCE_DIGEST, "sha", "t")
    m2 = build_default_manifest("proj-1", EVIDENCE_DIGEST, "sha", "t")
    assert m1.manifest_digest == m2.manifest_digest


def test_manifest_digest_changes_with_content():
    m1 = build_default_manifest("proj-1", EVIDENCE_DIGEST, "sha", "t")
    m2 = build_default_manifest("proj-2", EVIDENCE_DIGEST, "sha", "t")
    assert m1.manifest_digest != m2.manifest_digest


def test_manifest_serialization_roundtrip(tmp_path):
    manifest = build_default_manifest("proj-1", EVIDENCE_DIGEST, "sha-src", "now")
    path = tmp_path / "manifest.json"
    write_manifest_json(manifest, str(path))
    assert path.exists()

    loaded = load_manifest_json(str(path))
    assert loaded is not None
    assert loaded.projection_id == "proj-1"
    assert loaded.bundle_digest == EVIDENCE_DIGEST
    assert loaded.manifest_digest == manifest.manifest_digest


def test_load_manifest_missing_file():
    assert load_manifest_json("/nonexistent/path.json") is None


def test_manifest_passes_content_light_check():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    assert manifest_passes_content_light_check(manifest)


# ═══════════════════════════════════════════════════════════════════════
# Manifest binding verification
# ═══════════════════════════════════════════════════════════════════════


def test_verify_manifest_binding_match():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    ok, err = verify_manifest_binding(manifest, EVIDENCE_DIGEST)
    assert ok is True
    assert err is None


def test_verify_manifest_binding_mismatch():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    ok, err = verify_manifest_binding(
        manifest,
        "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    )
    assert ok is False
    assert "mismatch" in (err or "").lower()


def test_verify_policy_version_match():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    ok, err = verify_policy_version(manifest)
    assert ok is True


def test_verify_policy_version_mismatch():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    manifest.policy_version = "old_version"
    ok, err = verify_policy_version(manifest)
    assert ok is False
    assert "mismatch" in (err or "").lower()


# ═══════════════════════════════════════════════════════════════════════
# Selector verification
# ═══════════════════════════════════════════════════════════════════════


def test_verify_selector_disclosable_found():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    sel = ManifestSelector(
        selector_id="test:path_identity:0",
        selector_digest=compute_selector_digest("path_identity:test-name"),
        content_kind=ContentKind.SOURCE_IDENTIFIER.value,
        disclosure_class=DisclosureClass.PATH_IDENTITY.value,
    )
    manifest.selectors.append(sel)
    seal_manifest(manifest)

    ok, err = verify_selector_disclosable(manifest, sel.selector_digest)
    assert ok is True


def test_verify_selector_not_found():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    ok, err = verify_selector_disclosable(manifest, compute_selector_digest("missing"))
    assert ok is False


def test_verify_selector_already_disclosed():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    sel = ManifestSelector(
        selector_id="test:path_identity:0",
        selector_digest=compute_selector_digest("path_identity:test-name"),
        content_kind=ContentKind.SOURCE_IDENTIFIER.value,
        disclosure_class=DisclosureClass.PATH_IDENTITY.value,
        disclosed=True,
    )
    manifest.selectors.append(sel)
    seal_manifest(manifest)

    ok, err = verify_selector_disclosable(manifest, sel.selector_digest)
    assert ok is False
    assert "already disclosed" in (err or "").lower()


def test_mark_selector_disclosed():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    sel = ManifestSelector(
        selector_id="test:path_identity:0",
        selector_digest=compute_selector_digest("path_identity:test-name"),
        content_kind=ContentKind.SOURCE_IDENTIFIER.value,
        disclosure_class=DisclosureClass.PATH_IDENTITY.value,
    )
    manifest.selectors.append(sel)
    seal_manifest(manifest)

    assert mark_selector_disclosed(manifest, sel.selector_digest) is True
    ok, _ = verify_selector_disclosable(manifest, sel.selector_digest)
    assert ok is False  # now disclosed


# ═══════════════════════════════════════════════════════════════════════
# Crosswalk prohibition in bundles
# ═══════════════════════════════════════════════════════════════════════


def test_crosswalk_refused_in_file_path(tmp_path):
    builder = BundleBuilder(tmp_path)
    manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="p")
    receipt = DisclosureReceipt(
        projection_id="p",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="now",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="sha",
        public_baseline_status="none",
        policy_version="1.0",
        input_file_count=1,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="passed",
        output_status="candidate_generated",
    )
    files = {"crosswalk_data.json": "{}"}
    with pytest.raises(ValueError, match="crosswalk_material_refused"):
        builder.write_bundle("p", files, manifest, crosswalk, receipt)


def test_crosswalk_refused_in_content(tmp_path):
    builder = BundleBuilder(tmp_path)
    manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="p")
    receipt = DisclosureReceipt(
        projection_id="p",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="now",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="sha",
        public_baseline_status="none",
        policy_version="1.0",
        input_file_count=1,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="passed",
        output_status="candidate_generated",
    )
    files = {"src.py": "def build_pseudonym_map(): pass"}
    with pytest.raises(ValueError, match="crosswalk_material_refused"):
        builder.write_bundle("p", files, manifest, crosswalk, receipt)


def test_normal_files_pass_crosswalk_check(tmp_path):
    builder = BundleBuilder(tmp_path)
    manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="p")
    receipt = DisclosureReceipt(
        projection_id="p",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="now",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="sha",
        public_baseline_status="none",
        policy_version="1.0",
        input_file_count=1,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="passed",
        output_status="candidate_generated",
    )
    files = {"src.py": "def hello(): return 'world'"}
    builder.write_bundle("p", files, manifest, crosswalk, receipt)
    assert (tmp_path / "protected_content_manifest_p.json").exists()


# ═══════════════════════════════════════════════════════════════════════
# Bundle integrity — manifest must match
# ═══════════════════════════════════════════════════════════════════════


def test_manifest_generated_alongside_bundle(tmp_path):
    builder = BundleBuilder(tmp_path)
    manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="p")
    receipt = DisclosureReceipt(
        projection_id="p",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="now",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="sha",
        public_baseline_status="none",
        policy_version="1.0",
        input_file_count=1,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="passed",
        output_status="candidate_generated",
    )
    files = {"src.py": "def foo(): pass"}
    builder.write_bundle("p", files, manifest, crosswalk, receipt)

    mpath = tmp_path / "protected_content_manifest_p.json"
    assert mpath.exists()

    loaded = load_manifest_json(str(mpath))
    assert loaded is not None
    assert loaded.bundle_digest == receipt.candidate_zip_sha256
    assert loaded.content_light_guarantee is True


def test_manifest_binds_to_correct_bundle(tmp_path):
    builder1 = BundleBuilder(tmp_path / "b1")
    builder2 = BundleBuilder(tmp_path / "b2")

    manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="p1")
    receipt1 = DisclosureReceipt(
        projection_id="p1",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="now",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="sha",
        public_baseline_status="none",
        policy_version="1.0",
        input_file_count=1,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="passed",
        output_status="candidate_generated",
    )
    receipt2 = receipt1.model_copy()
    receipt2.projection_id = "p2"

    files1 = {"src.py": "def foo(): pass"}
    files2 = {"src.py": "def bar(): pass"}

    builder1.write_bundle("p1", files1, manifest, crosswalk, receipt1)
    builder2.write_bundle("p2", files2, manifest, crosswalk, receipt2)

    assert receipt1.candidate_zip_sha256 != receipt2.candidate_zip_sha256

    m1 = load_manifest_json(str(tmp_path / "b1" / "protected_content_manifest_p1.json"))
    m2 = load_manifest_json(str(tmp_path / "b2" / "protected_content_manifest_p2.json"))
    assert m1 is not None and m2 is not None

    # Each manifest binds to its own bundle
    ok, _ = verify_manifest_binding(m1, receipt1.candidate_zip_sha256 or "")
    assert ok is True
    ok, _ = verify_manifest_binding(m1, receipt2.candidate_zip_sha256 or "")
    assert ok is False  # wrong bundle


# ═══════════════════════════════════════════════════════════════════════
# Content-light guarantees
# ═══════════════════════════════════════════════════════════════════════


def test_manifest_never_contains_raw_secrets():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    serialized = manifest.model_dump_json().lower()
    assert "ghp_" not in serialized
    assert "sk-" not in serialized
    assert "api_key" not in serialized
    assert "password" not in serialized
    assert manifest_passes_content_light_check(manifest)


def test_manifest_never_contains_crosswalk_values():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    manifest.selectors.append(
        ManifestSelector(
            selector_id="sel",
            selector_digest=compute_selector_digest("path_identity:test"),
            content_kind=ContentKind.SOURCE_IDENTIFIER.value,
            disclosure_class=DisclosureClass.PATH_IDENTITY.value,
        )
    )
    seal_manifest(manifest)
    serialized = json.dumps(manifest.model_dump(), sort_keys=True)
    assert "test" not in serialized  # selector_id is hashed


# ═══════════════════════════════════════════════════════════════════════
# P3 CLI authorization integration with manifest
# ═══════════════════════════════════════════════════════════════════════


def test_disclose_refuses_on_missing_manifest(tmp_path, monkeypatch):
    """Disclose refuses when manifest is missing."""
    _clean_gov_store()
    monkeypatch.chdir(tmp_path)

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    output_dir.mkdir(parents=True)

    receipt_data = {
        "schema_version": "rig.review_projection.compilation_receipt.v1",
        "projection_id": "test-p",
        "candidate_zip_sha256": EVIDENCE_DIGEST,
        "output_status": "candidate_generated",
    }
    (output_dir / "receipt_test.json").write_text(json.dumps(receipt_data), "utf-8")

    import contextlib
    import io

    from rig_relay.review_projection.cli import _run_disclose_authorization

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        _run_disclose_authorization(
            candidate_zip_hash=EVIDENCE_DIGEST,
            recipient_class="external_ai_reviewer_controlled_account",
            provider_or_channel="openai",
            purpose="test",
            retention="30d",
            training_use="never",
            authorization_id="some-id",
        )
    output = captured.getvalue()
    assert "REFUSED" in output
    assert "manifest not found" in output.lower()


# ═══════════════════════════════════════════════════════════════════════
# P4.1: Manifest integrity verification
# ═══════════════════════════════════════════════════════════════════════


def test_verify_manifest_integrity_valid():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    ok, err = verify_manifest_integrity(manifest)
    assert ok is True
    assert err is None


def test_verify_manifest_integrity_tampered_count():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    manifest.count_retained_projected = 999  # mutate after seal
    ok, err = verify_manifest_integrity(manifest)
    assert ok is False
    assert "integrity failure" in (err or "").lower()


def test_verify_manifest_integrity_tampered_selectors():
    manifest = build_default_manifest("p", EVIDENCE_DIGEST, "s", "t")
    manifest.selectors.append(
        ManifestSelector(
            selector_id="evil:path_identity:0",
            selector_digest=compute_selector_digest("evil"),
            content_kind=ContentKind.SOURCE_IDENTIFIER.value,
            disclosure_class=DisclosureClass.PATH_IDENTITY.value,
        )
    )
    ok, err = verify_manifest_integrity(manifest)
    assert ok is False
    assert "integrity failure" in (err or "").lower()


# ═══════════════════════════════════════════════════════════════════════
# P4.1: Real bundle manifest integrity round-trip
# ═══════════════════════════════════════════════════════════════════════


def test_manifest_integrity_roundtrip(tmp_path):
    """Manifest written by BundleBuilder must round-trip with
    loaded.manifest_digest == compute_manifest_digest(loaded).
    """
    builder = BundleBuilder(tmp_path)
    manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="p")
    crosswalk.mappings = {
        "original_func_name": "FN_001",
        "original_class_name": "CLASS_001",
    }
    receipt = DisclosureReceipt(
        projection_id="p",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="now",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="sha",
        public_baseline_status="none",
        policy_version="1.0",
        input_file_count=1,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="passed",
        output_status="candidate_generated",
    )
    files = {"src.py": "def FN_001(): pass"}
    builder.write_bundle("p", files, manifest, crosswalk, receipt)

    mpath = tmp_path / "protected_content_manifest_p.json"
    loaded = load_manifest_json(str(mpath))
    assert loaded is not None
    assert loaded.manifest_digest == compute_manifest_digest(loaded)


# ═══════════════════════════════════════════════════════════════════════
# P4.1: Live selector emission from real crosswalk
# ═══════════════════════════════════════════════════════════════════════


def test_manifest_contains_real_selectors(tmp_path):
    """Selectors are populated from real pseudonymized crosswalk identities."""
    builder = BundleBuilder(tmp_path)
    manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="p")
    crosswalk.mappings = {
        "original_func": "FN_001",
        "original_class": "CLASS_002",
        "helper_var": "VAR_003",
    }
    receipt = DisclosureReceipt(
        projection_id="p",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="now",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="sha",
        public_baseline_status="none",
        policy_version="1.0",
        input_file_count=1,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="passed",
        output_status="candidate_generated",
    )
    files = {"src.py": "def FN_001(): pass"}
    builder.write_bundle("p", files, manifest, crosswalk, receipt)

    mpath = tmp_path / "protected_content_manifest_p.json"
    loaded = load_manifest_json(str(mpath))
    assert loaded is not None
    assert len(loaded.selectors) == 3

    # Selector IDs use index-based format; pseudonyms in digests
    selector_digests = {s.selector_digest for s in loaded.selectors}
    assert len(selector_digests) == 3

    # No raw original names in serialized manifest
    serialized = json.dumps(loaded.model_dump(), sort_keys=True)
    assert "original_func" not in serialized
    assert "original_class" not in serialized
    assert "helper_var" not in serialized


def test_manifest_selectors_stable_ordering(tmp_path):
    """Pseudonymized identities produce deterministic selectors."""
    crosswalk = LocalCrosswalk(projection_id="p")
    crosswalk.mappings = {"z_func": "FN_Z", "a_func": "FN_A"}
    receipt = DisclosureReceipt(
        projection_id="p",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="now",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="sha",
        public_baseline_status="none",
        policy_version="1.0",
        input_file_count=1,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="passed",
        output_status="candidate_generated",
    )
    files = {"src.py": "pass"}

    manifests = []
    for i in range(3):
        b = BundleBuilder(tmp_path / f"run{i}")
        m = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
        cw = LocalCrosswalk(projection_id=f"p{i}")
        cw.mappings = dict(crosswalk.mappings)
        r = receipt.model_copy()
        r.projection_id = f"p{i}"
        b.write_bundle(f"p{i}", files, m, cw, r)
        loaded = load_manifest_json(
            str(tmp_path / f"run{i}" / f"protected_content_manifest_p{i}.json")
        )
        assert loaded is not None
        manifests.append(loaded)

    # Selector digests must be deterministic across runs
    for a, b in zip(manifests[0].selectors, manifests[1].selectors, strict=True):
        assert a.selector_id == b.selector_id
        assert a.selector_digest == b.selector_digest
        assert a.content_kind == b.content_kind


# ═══════════════════════════════════════════════════════════════════════
# P4.1: Selector consumption through real CLI path
# ═══════════════════════════════════════════════════════════════════════


def test_selector_from_real_manifest_disclosed(tmp_path, monkeypatch):
    """A selector from a real manifest can be consumed through the CLI path."""
    _clean_gov_store()
    monkeypatch.chdir(tmp_path)

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    output_dir.mkdir(parents=True)

    # Build a real bundle with crosswalk
    builder = BundleBuilder(output_dir)
    manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="test")
    crosswalk.mappings = {"secret_function": "FN_001"}
    receipt = DisclosureReceipt(
        projection_id="test",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="now",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="sha",
        public_baseline_status="none",
        policy_version="1.0",
        input_file_count=1,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="passed",
        output_status="candidate_generated",
    )
    files = {"src.py": "def FN_001(): pass"}
    builder.write_bundle("test", files, manifest, crosswalk, receipt)

    # Load the real manifest and get a real selector
    mpath = output_dir / "protected_content_manifest_test.json"
    loaded = load_manifest_json(str(mpath))
    assert loaded is not None
    assert len(loaded.selectors) == 1
    real_selector = loaded.selectors[0]
    assert loaded.selectors[0].content_kind == ContentKind.SOURCE_IDENTIFIER.value

    # Issue a governance disclosure authorization
    from rig_relay.governance.disclosure_authorization import (
        DisclosureClass,
        issue_disclosure_authorization,
    )

    gov_dir = (
        tmp_path / ".build" / "rig-relay" / "desktop" / "disclosure-authorizations"
    )
    gov_dir.mkdir(parents=True)

    auth_result = issue_disclosure_authorization(
        evidence_digest=receipt.candidate_zip_sha256 or EVIDENCE_DIGEST,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
    )
    assert auth_result.authorization_id

    # Consume the selector through the CLI disclosure path
    import contextlib
    import io

    from rig_relay.review_projection.cli import _run_disclose_authorization

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        _run_disclose_authorization(
            candidate_zip_hash=receipt.candidate_zip_sha256 or EVIDENCE_DIGEST,
            recipient_class="other_approved_recipient",
            provider_or_channel="test-channel",
            purpose="test",
            retention="30d",
            training_use="never",
            authorization_id=auth_result.authorization_id,
            selector_digest=real_selector.selector_digest,
        )
    output = captured.getvalue()
    assert "REFUSED" not in output
    assert (
        "authorization consumed" in output.lower()
        or "Disclosure authorization" in output
    )

    # Reload manifest — selector should be marked disclosed
    reloaded = load_manifest_json(str(mpath))
    assert reloaded is not None
    assert reloaded.selectors[0].disclosed is True

    # Second attempt for same selector is refused
    captured2 = io.StringIO()
    with contextlib.redirect_stdout(captured2):
        _run_disclose_authorization(
            candidate_zip_hash=receipt.candidate_zip_sha256 or EVIDENCE_DIGEST,
            recipient_class="other_approved_recipient",
            provider_or_channel="test-channel",
            purpose="test",
            retention="30d",
            training_use="never",
            authorization_id=auth_result.authorization_id,
            selector_digest=real_selector.selector_digest,
        )
    output2 = captured2.getvalue()
    assert (
        "already disclosed" in output2.lower() or "already consumed" in output2.lower()
    )


def test_tampered_manifest_refused_in_disclosure(tmp_path, monkeypatch):
    """Disclosure refuses when manifest integrity is broken even if bundle_digest
    and policy_version are unchanged.
    """
    _clean_gov_store()
    monkeypatch.chdir(tmp_path)

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    output_dir.mkdir(parents=True)

    # Build a real bundle
    builder = BundleBuilder(output_dir)
    manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="test")
    receipt = DisclosureReceipt(
        projection_id="test",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="now",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="sha",
        public_baseline_status="none",
        policy_version="1.0",
        input_file_count=1,
        classification_counts={},
        included_path_hashes=[],
        excluded_path_hashes={},
        applied_rules=[],
        crosswalk_hash="",
        residual_scan_result="passed",
        output_status="candidate_generated",
    )
    files = {"src.py": "def hello(): pass"}
    builder.write_bundle("test", files, manifest, crosswalk, receipt)

    zip_hash = receipt.candidate_zip_sha256 or EVIDENCE_DIGEST

    # Tamper the manifest: mutate a field while preserving bundle_digest and policy_version
    mpath = output_dir / "protected_content_manifest_test.json"
    loaded = load_manifest_json(str(mpath))
    assert loaded is not None
    loaded.count_retained_projected = 99999  # tampered
    loaded.count_hash_evidence_only = 88888
    # DO NOT reseal — keep the stale manifest_digest
    write_manifest_json(loaded, str(mpath))

    # Issue authorization
    from rig_relay.governance.disclosure_authorization import (
        DisclosureClass,
        issue_disclosure_authorization,
    )

    auth_result = issue_disclosure_authorization(
        evidence_digest=zip_hash, disclosure_class=DisclosureClass.COMMIT_BODY.value
    )

    import contextlib
    import io

    from rig_relay.review_projection.cli import _run_disclose_authorization

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        _run_disclose_authorization(
            candidate_zip_hash=zip_hash,
            recipient_class="other_approved_recipient",
            provider_or_channel="test",
            purpose="test",
            retention="30d",
            training_use="never",
            authorization_id=auth_result.authorization_id,
        )
    output = captured.getvalue()
    assert "REFUSED" in output
    assert "integrity failure" in output.lower()


# ═══════════════════════════════════════════════════════════════════════
# Residual scanner still works (regression check)
# ═══════════════════════════════════════════════════════════════════════


def test_residual_scanner_detects_github_token():
    scanner = ResidualRiskScanner({}, "/fake/repo")
    result = scanner.scan("token = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789'")
    assert "secret or key-like" in (result or "").lower()


def test_residual_scanner_allows_safe_content():
    scanner = ResidualRiskScanner({}, "/fake/repo")
    result = scanner.scan("def hello(): return 'world'")
    assert result is None
