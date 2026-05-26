"""Tests for the disclosure operations report — schema validation,
content-light guarantee, and evidence tier accuracy.
"""

from __future__ import annotations

import json
import os
import shutil

from rig_relay.governance.disclosure_authorization import (
    DisclosureClass,
    DisclosureOutcome,
    _store_root as _gov_store_root,
    issue_disclosure_authorization,
)
from rig_relay.governance.disclosure_operations_report import (
    REPORT_SCHEMA_VERSION,
    generate_operations_report,
)
from rig_relay.governance.disclosure_transition import (
    _transition_store_root,
    execute_disclosure_transition,
)


def _clean_all_stores():
    for store in [_gov_store_root(), _transition_store_root()]:
        if store.exists():
            shutil.rmtree(store, ignore_errors=True)


def _setup_transition(tmp_path) -> tuple[str, str, str, str, str]:
    """Set up a complete transition and return (auth_id, zip_hash, proj_id,
    comp_sha, manifest_before).
    """
    import hashlib

    from rig_relay.review_projection.bundle_builder import BundleBuilder
    from rig_relay.review_projection.models import (
        BundleManifest,
        DisclosureReceipt,
        LocalCrosswalk,
        ProjectionMode,
    )
    from rig_relay.review_projection.protected_content import load_manifest_json

    os.chdir(str(tmp_path))
    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    builder = BundleBuilder(output_dir)
    bundle_manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="proj-rpt")
    crosswalk.mappings = {"fn": "F_0001"}
    receipt = DisclosureReceipt(
        projection_id="proj-rpt",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="2026-01-01T00:00:00Z",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="abc",
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
    files = {"src.py": "def fn(): pass"}
    builder.write_bundle("proj-rpt", files, bundle_manifest, crosswalk, receipt)
    zip_hash = receipt.candidate_zip_sha256 or "sha256:abc"

    mpath = output_dir / "protected_content_manifest_proj-rpt.json"
    loaded = load_manifest_json(str(mpath))
    assert loaded is not None
    manifest_before = loaded.manifest_digest

    rcpt_path = output_dir / "receipt_proj-rpt.json"
    comp_sha = hashlib.sha256(rcpt_path.read_bytes()).hexdigest()

    auth_result = issue_disclosure_authorization(
        evidence_digest=zip_hash,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        ttl_minutes=60,
        one_time=True,
    )
    assert auth_result.outcome == DisclosureOutcome.ISSUED
    assert auth_result.receipt is not None
    auth_id = auth_result.receipt.authorization_id

    return auth_id, zip_hash, "proj-rpt", comp_sha, manifest_before


def test_report_schema_version_and_content_light(tmp_path):
    """Report validates its schema_version and content_light guarantee."""
    _clean_all_stores()
    auth_id, zip_hash, proj_id, comp_sha, manifest_before = _setup_transition(tmp_path)

    execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-report",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    report = generate_operations_report(
        recovery_window_sessions=[
            {
                "authorization_id": auth_id,
                "evidence_digest": zip_hash,
                "window_name": "w5-idempotent",
                "crash_after_status": "completed",
            }
        ],
        competition_outcomes=[
            {
                "competition_kind": "concurrent_recovery",
                "winner_transition_id": "dzt_test",
                "follower_transition_id": "dzt_test",
                "result": "both_completed_same_plan",
                "follower_outcome": "recovered_already_complete",
                "evidence_tier": "canonical",
            }
        ],
        protected_content_proof={"string_literal_crosswalk_entries": 2},
        manifest_recovery_proof={
            "precondition_matches": 1,
            "post_image_matches": 0,
            "unknown_state_refusals": 0,
        },
    )

    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["content_light_guarantee"] is True
    assert len(report["recovery_window_proofs"]) == 1
    assert len(report["competition_outcomes"]) == 1
    assert report["duplicate_prevention"]["manifest_dedup"]["mechanism"] == (
        "two_image_validation_rule"
    )
    assert report["duplicate_prevention"]["event_dedup"]["mechanism"] == (
        "transition_id_dedup_key"
    )
    assert report["duplicate_prevention"]["authorization_dedup"]["mechanism"] == (
        "single_use_atomic_consume"
    )
    assert report["duplicate_prevention"]["receipt_dedup"]["mechanism"] == (
        "stable_identity_dza_transition_id"
    )

    # Verify no raw content leaked
    report_json = json.dumps(report, sort_keys=True)
    for forbidden in [
        "source_code",
        "password",
        "secret",
        "api_key",
        "token",
        "ghp_",
        "ghs_",
        "print(",
        "def ",
        "class ",
    ]:
        assert forbidden not in report_json.lower(), (
            f"Forbidden '{forbidden}' found in report"
        )

    # Evidence tiers present
    tiers = {
        t["evidence_domain"]: t["tier"] for t in report["evidence_authority_tiers"]
    }
    assert tiers["transitions.jsonl"] == "canonical"
    assert tiers["disclosure_event.v1.jsonl"] == "canonical"
    assert tiers.get("disclosure receipt (projection model)") == "observable_durable"
    assert tiers.get("protected-content manifest") == "observable_durable"
    assert tiers.get("protected-content classification") == "proven_by_test"

    assert (
        report["protected_content_disposition"]["string_literals"]["manifest_selectors"]
        == 0
    )
    assert (
        report["protected_content_disposition"]["comments"]["manifest_selectors"] == 0
    )
    assert (
        report["protected_content_disposition"]["docstrings"]["manifest_selectors"] == 0
    )

    assert report["manifest_recovery"]["rule"] == "two_image_validation"


def test_report_canonical_source_sha256(tmp_path):
    """Report includes the SHA256 of the transitions JSONL it was derived from."""
    _clean_all_stores()
    auth_id, zip_hash, proj_id, comp_sha, manifest_before = _setup_transition(tmp_path)

    execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-source",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    report = generate_operations_report()
    assert report["canonical_source_sha256"].startswith("sha256:")
    assert len(report["canonical_source_sha256"]) == 71  # "sha256:" + 64 hex


def test_report_empty_ledger_handles_gracefully(tmp_path):
    """Report with no transition data still produces valid output."""
    _clean_all_stores()
    os.chdir(str(tmp_path))

    report = generate_operations_report()
    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["content_light_guarantee"] is True
    assert report["recovery_window_proofs"] == []
    assert report["duplicate_prevention"]["event_dedup"]["events_emitted"] == 0
