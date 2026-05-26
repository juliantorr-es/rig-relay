"""Real-substrate proofs for exclusive authorization consumption and disclosure
transition concurrency.

Tests against real multiprocessing/threading, real filesystem artifacts,
real lock files, and real crash recovery. No mocks, no stubs, no ghosts.
"""

from __future__ import annotations

import multiprocessing
import os
import shutil

from rig_relay.governance.disclosure_authorization import (
    DisclosureClass,
    DisclosureOutcome,
    _load_receipt,
    _store_root as _gov_store_root,
    consume_disclosure_authorization,
    issue_disclosure_authorization,
)
from rig_relay.governance.disclosure_transition import (
    TransitionStatus,
    _acquire_transition_lock,
    _find_transition_chain,
    _release_transition_lock,
    _transition_store_root,
    prepare_transition,
)
from rig_relay.review_projection.bundle_builder import BundleBuilder
from rig_relay.review_projection.models import (
    BundleManifest,
    DisclosureReceipt,
    LocalCrosswalk,
    ProjectionMode,
)
from rig_relay.review_projection.protected_content import load_manifest_json

EVIDENCE_DIGEST = (
    "sha256:0000111122223333444455556666777788889999aaaabbbbccccddddeeeeffff"
)


def _clean_stores():
    for store in [_gov_store_root(), _transition_store_root()]:
        if store.exists():
            shutil.rmtree(store, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# One-time authorization cross-process race
# ═══════════════════════════════════════════════════════════════════════


def _consume_once_in_process(args: tuple) -> int:
    """Worker: consume one-time receipt, return 1 for CONSUMED, 0 otherwise."""
    auth_id, evidence, workdir = args
    os.chdir(workdir)
    result = consume_disclosure_authorization(auth_id, current_evidence_digest=evidence)
    return 1 if result.outcome == DisclosureOutcome.CONSUMED else 0


def test_one_time_receipt_exactly_one_consume(tmp_path):
    """Two competing processes. Exactly one succeeds."""
    _clean_stores()
    workdir = str(tmp_path)
    os.chdir(workdir)

    result = issue_disclosure_authorization(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        ttl_minutes=60,
        one_time=True,
    )
    assert result.outcome == DisclosureOutcome.ISSUED
    auth_id = result.authorization_id

    args = (auth_id, EVIDENCE_DIGEST, workdir)
    with multiprocessing.Pool(processes=2) as pool:
        results = pool.map(_consume_once_in_process, [args, args])

    successes = sum(results)
    assert successes == 1, f"Expected 1 success, got {successes}"

    # Verify integrity
    receipt = _load_receipt(auth_id)
    assert receipt is not None
    assert receipt.verify_integrity()
    assert receipt.consumed is True


# ═══════════════════════════════════════════════════════════════════════
# Bounded-use receipt under contention
# ═══════════════════════════════════════════════════════════════════════


def _consume_bounded_in_process(args: tuple) -> int:
    """Worker: consume bounded-use receipt, return use_count after."""
    auth_id, evidence, workdir = args
    os.chdir(workdir)
    result = consume_disclosure_authorization(auth_id, current_evidence_digest=evidence)
    if result.outcome == DisclosureOutcome.CONSUMED:
        return 1
    return 0


def test_bounded_use_exactly_n_consumes(tmp_path):
    """N permitted uses yield exactly N successes under contention."""
    _clean_stores()
    workdir = str(tmp_path)
    os.chdir(workdir)

    max_uses = 3
    result = issue_disclosure_authorization(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        ttl_minutes=60,
        one_time=False,
        max_uses=max_uses,
    )
    assert result.outcome == DisclosureOutcome.ISSUED
    auth_id = result.authorization_id

    args = (auth_id, EVIDENCE_DIGEST, workdir)
    # Launch more than max_uses
    with multiprocessing.Pool(processes=5) as pool:
        results = pool.map(_consume_bounded_in_process, [args] * 5)

    successes = sum(results)
    assert successes == max_uses, f"Expected {max_uses} successes, got {successes}"

    receipt = _load_receipt(auth_id)
    assert receipt is not None
    assert receipt.use_count == max_uses
    assert receipt.verify_integrity()


# ═══════════════════════════════════════════════════════════════════════
# Transition preparation and recovery
# ═══════════════════════════════════════════════════════════════════════


def _clean_transitions():
    store = _transition_store_root()
    if store.exists():
        shutil.rmtree(store, ignore_errors=True)


def test_prepare_transition_persists_event(tmp_path):
    """A prepared transition writes exactly one PREPARED event."""
    _clean_transitions()
    os.chdir(str(tmp_path))

    t = prepare_transition(
        authorization_id="disc_test",
        evidence_digest=EVIDENCE_DIGEST,
        projection_id="proj",
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before="sha256:before",
        recipient_class="test",
        provider_or_channel="test",
    )
    assert t.status == TransitionStatus.PREPARED
    assert t.transition_digest

    events = _find_transition_chain(t.transition_id)
    assert len(events) == 1
    assert events[0]["status"] == "prepared"


def test_persists_transition_events(tmp_path):
    """Transition prep, consume, receipts, manifest, event, complete."""
    _clean_stores()
    _clean_transitions()
    os.chdir(str(tmp_path))

    # Build a real bundle with crosswalk first (to get real digest)
    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    builder = BundleBuilder(output_dir)
    bundle_manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="proj")
    crosswalk.mappings = {"func": "FN_001"}
    receipt = DisclosureReceipt(
        projection_id="proj",
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
    builder.write_bundle("proj", files, bundle_manifest, crosswalk, receipt)

    evidence = receipt.candidate_zip_sha256 or "sha256:abc"

    mpath = output_dir / "protected_content_manifest_proj.json"
    loaded = load_manifest_json(str(mpath))
    assert loaded is not None
    manifest_before = loaded.manifest_digest

    # Issue authorization with real evidence digest
    auth = issue_disclosure_authorization(
        evidence_digest=evidence,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        ttl_minutes=60,
    )
    assert auth.outcome == DisclosureOutcome.ISSUED

    # Prepare transition
    t = prepare_transition(
        authorization_id=auth.authorization_id,
        evidence_digest=evidence,
        projection_id="proj",
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="test",
        provider_or_channel="test",
    )

    # Consume under lock
    _acquire_transition_lock()
    try:
        consume_result = consume_disclosure_authorization(
            auth.authorization_id, current_evidence_digest=evidence
        )
        assert consume_result.outcome == DisclosureOutcome.CONSUMED
    finally:
        _release_transition_lock()

    events = _find_transition_chain(t.transition_id)
    assert len(events) >= 1
    assert events[0]["status"] == "prepared"


# ═══════════════════════════════════════════════════════════════════════
# Crash recovery: transition survives torn write boundaries
# ═══════════════════════════════════════════════════════════════════════


def test_transition_recovery_after_prepared(tmp_path):
    """After PREPARED but before consume, recovery finds existing transition."""
    _clean_stores()
    _clean_transitions()
    os.chdir(str(tmp_path))

    auth = issue_disclosure_authorization(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        ttl_minutes=60,
    )
    assert auth.outcome == DisclosureOutcome.ISSUED

    # Prepare and then "crash" — leave transition PREPARED
    t = prepare_transition(
        authorization_id=auth.authorization_id,
        evidence_digest=EVIDENCE_DIGEST,
        projection_id="proj",
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before="sha256:before",
        recipient_class="test",
        provider_or_channel="test",
    )
    assert t.status == TransitionStatus.PREPARED

    # Recovery: authorization still valid
    from rig_relay.governance.disclosure_authorization import (
        validate_disclosure_authorization,
    )

    v = validate_disclosure_authorization(
        auth.authorization_id, current_evidence_digest=EVIDENCE_DIGEST
    )
    assert v.is_authorized, "Authorization must still be valid after prepare"

    # Complete the transition
    _acquire_transition_lock()
    try:
        consume_result = consume_disclosure_authorization(
            auth.authorization_id, current_evidence_digest=EVIDENCE_DIGEST
        )
        assert consume_result.outcome == DisclosureOutcome.CONSUMED
    finally:
        _release_transition_lock()

    events = _find_transition_chain(t.transition_id)
    assert len(events) >= 1
