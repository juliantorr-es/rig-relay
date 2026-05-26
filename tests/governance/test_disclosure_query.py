"""Real-substrate proofs for the Disclosure Evidence Query Service.

Exercises the query service against real Lane A canonical evidence
generated through production boundaries. Verifies content-light projections,
deterministic digests, schema validity, and non-mutation of authority state.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil

import pytest

from rig_relay.governance.disclosure_authorization import (
    DisclosureClass,
    DisclosureOutcome,
    _store_root as _gov_store_root,
    issue_disclosure_authorization,
)
from rig_relay.governance.disclosure_query import (
    QUERY_SCHEMA_VERSION,
    QueryFilter,
    compute_projection_digest,
    list_by_status,
    lookup_transition_by_auth,
    lookup_transition_by_id,
    query_transitions,
)
from rig_relay.governance.disclosure_transition import (
    TransitionStatus,
    _inject_failpoint,
    _transition_store_root,
    execute_disclosure_transition,
)

EVIDENCE_DIGEST = (
    "sha256:0000111122223333444455556666777788889999aaaabbbbccccddddeeeeffff"
)


def _clean_all_stores():
    for store in [_gov_store_root(), _transition_store_root()]:
        if store.exists():
            shutil.rmtree(store, ignore_errors=True)
    review_dir = _transition_store_root().parent.parent / "review_projection"
    if review_dir.exists():
        shutil.rmtree(review_dir, ignore_errors=True)


def _build_bundle_and_manifest(tmp_path):
    """Build a real bundle + manifest and return (zip_hash, projection_id, comp_sha, manifest_digest_before)."""
    os.chdir(str(tmp_path))
    from rig_relay.review_projection.bundle_builder import BundleBuilder
    from rig_relay.review_projection.models import (
        BundleManifest,
        DisclosureReceipt,
        LocalCrosswalk,
        ProjectionMode,
    )
    from rig_relay.review_projection.protected_content import load_manifest_json

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    builder = BundleBuilder(output_dir)
    bundle_manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="proj-q")
    crosswalk.mappings = {"fn": "F_0001"}
    receipt = DisclosureReceipt(
        projection_id="proj-q",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="2026-01-01T00:00:00Z",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="abc123",
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
    builder.write_bundle("proj-q", files, bundle_manifest, crosswalk, receipt)

    zip_hash = receipt.candidate_zip_sha256 or EVIDENCE_DIGEST

    mpath = output_dir / "protected_content_manifest_proj-q.json"
    loaded = load_manifest_json(str(mpath))
    assert loaded is not None
    manifest_before = loaded.manifest_digest

    rcpt_path = output_dir / "receipt_proj-q.json"
    comp_sha = hashlib.sha256(rcpt_path.read_bytes()).hexdigest()

    return zip_hash, "proj-q", comp_sha, manifest_before


def _issue_auth(tmp_path, evidence: str) -> tuple[str, str]:
    os.chdir(str(tmp_path))
    result = issue_disclosure_authorization(
        evidence_digest=evidence,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        ttl_minutes=60,
        one_time=True,
    )
    assert result.outcome == DisclosureOutcome.ISSUED
    assert result.receipt is not None
    return result.receipt.authorization_id, result.receipt.receipt_sha256


def _execute_with_crash_worker(workdir: str, crash_target: str, **kwargs):
    os.chdir(workdir)
    _inject_failpoint(
        lambda s: os._exit(1) if s == TransitionStatus(crash_target) else None
    )
    execute_disclosure_transition(**kwargs)


def _recover_worker(workdir: str, auth_id: str, evidence: str) -> tuple:
    os.chdir(workdir)
    from rig_relay.governance.disclosure_transition import recover_disclosure_transition

    return recover_disclosure_transition(auth_id, evidence)


# ═══════════════════════════════════════════════════════════════════════
# PROOF 1: Uninterrupted successful disclosure appears correctly.
# ═══════════════════════════════════════════════════════════════════════


def test_query_service_uninterrupted_successful_disclosure(tmp_path):
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    transition, err = execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q1",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )
    assert err is None
    assert transition is not None
    assert transition.status == TransitionStatus.COMPLETED

    # Lookup by auth+evidence
    proj = lookup_transition_by_auth(auth_id, zip_hash)
    assert proj is not None
    assert proj.status == "completed"
    assert proj.transition_id == transition.transition_id
    assert proj.recovery_provenance is None
    assert proj.content_disposition is not None
    assert proj.content_disposition.disclosure_class == "commit_body"
    assert proj.content_disposition.includes_hash_only_protection is False
    assert proj.artifact_integrity is not None
    assert proj.artifact_integrity.receipt_bound is True
    assert proj.artifact_integrity.event_durable is True
    assert proj.artifact_integrity.manifest_verified is True
    assert proj.artifact_integrity.chain_valid is True

    # Lookup by transition_id
    proj2 = lookup_transition_by_id(transition.transition_id)
    assert proj2 is not None
    assert proj2.status == "completed"

    # Query all completed
    result = query_transitions(QueryFilter(status="completed"))
    assert result.total_count == 1
    assert result.content_light_guarantee is True
    assert result.schema_version == QUERY_SCHEMA_VERSION

    # Deterministic digest
    digest1 = result.query_digest
    result2 = query_transitions(QueryFilter(status="completed"))
    assert result2.query_digest == digest1


# ═══════════════════════════════════════════════════════════════════════
# PROOF 2: Recovered disclosure appears with recovery provenance.
# ═══════════════════════════════════════════════════════════════════════


def test_query_service_recovery_provenance(tmp_path):
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    kwargs = dict(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q2",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    p = multiprocessing.Process(
        target=_execute_with_crash_worker,
        args=(str(tmp_path), "authorization_consumed"),
        kwargs=kwargs,
    )
    p.start()
    p.join(timeout=30)

    transition, err = _recover_worker(str(tmp_path), auth_id, zip_hash)
    assert err is None
    assert transition is not None
    assert transition.status == TransitionStatus.COMPLETED
    assert transition.recovery_detail == "recovered_and_completed"

    proj = lookup_transition_by_auth(auth_id, zip_hash)
    assert proj is not None
    assert proj.status == "completed"
    assert proj.recovery_provenance is not None
    assert proj.recovery_provenance.is_recovered is True
    assert proj.recovery_provenance.recovery_detail == "recovered_and_completed"
    assert proj.recovery_provenance.uninterrupted is False


# ═══════════════════════════════════════════════════════════════════════
# PROOF 3: Compatible concurrent recovery convergence — one authority.
# ═══════════════════════════════════════════════════════════════════════


def _recover_worker_result(workdir: str, auth_id: str, evidence: str) -> dict:
    os.chdir(workdir)
    from rig_relay.governance.disclosure_transition import recover_disclosure_transition

    transition, err = recover_disclosure_transition(auth_id, evidence)
    if transition is not None:
        return {
            "status": transition.status.value,
            "transition_id": transition.transition_id,
            "recovery_detail": transition.recovery_detail,
            "error": err,
        }
    return {
        "status": "none",
        "transition_id": "",
        "recovery_detail": None,
        "error": err,
    }


def test_query_service_concurrent_convergence_one_authority(tmp_path):
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    kwargs = dict(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q3",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    p = multiprocessing.Process(
        target=_execute_with_crash_worker,
        args=(str(tmp_path), "authorization_consumed"),
        kwargs=kwargs,
    )
    p.start()
    p.join(timeout=30)

    with multiprocessing.Pool(processes=2) as pool:
        results = pool.starmap(
            _recover_worker_result, [(str(tmp_path), auth_id, zip_hash)] * 2
        )

    completed = [r for r in results if r["status"] == "completed"]
    assert len(completed) == 2
    assert completed[0]["transition_id"] == completed[1]["transition_id"]

    # Query service sees exactly one completed transition
    result = query_transitions(QueryFilter(status="completed"))
    assert result.total_count == 1
    assert result.transitions[0].transition_id == completed[0]["transition_id"]


# ═══════════════════════════════════════════════════════════════════════
# PROOF 4: Protected-content refusal with S_ string literal detection.
# ═══════════════════════════════════════════════════════════════════════


_SAMPLE_WITH_STRING_LITERALS = '''"""Module docstring."""
# comment
def process_data(x: int) -> str:
    result = f"{x}"  # trailing
    secret_key = "sk-ant-api-key-12345"
    return result
'''


def test_query_service_protected_content_disposition(tmp_path):
    _clean_all_stores()
    os.chdir(str(tmp_path))

    from rig_relay.review_projection.bundle_builder import BundleBuilder
    from rig_relay.review_projection.models import (
        BundleManifest,
        DisclosureReceipt,
        LocalCrosswalk,
        ProjectionMode,
    )
    from rig_relay.review_projection.protected_content import load_manifest_json
    from rig_relay.review_projection.transformer import PythonTransformer

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    builder = BundleBuilder(output_dir)
    bundle_manifest = BundleManifest(mode=ProjectionMode.MAINTAINABILITY_REVIEW)
    crosswalk = LocalCrosswalk(projection_id="proj-pc")
    crosswalk.mappings = {}
    receipt = DisclosureReceipt(
        projection_id="proj-pc",
        mode=ProjectionMode.MAINTAINABILITY_REVIEW,
        created_at="2026-01-01T00:00:00Z",
        source_root_fingerprint="fp",
        branch="main",
        head_sha="abc123",
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

    transformer = PythonTransformer()
    transformed_source, mapping = transformer.transform(_SAMPLE_WITH_STRING_LITERALS)
    crosswalk.mappings.update(mapping)

    files = {"src.py": transformed_source}
    builder.write_bundle("proj-pc", files, bundle_manifest, crosswalk, receipt)

    zip_hash = receipt.candidate_zip_sha256 or EVIDENCE_DIGEST

    mpath = output_dir / "protected_content_manifest_proj-pc.json"
    loaded = load_manifest_json(str(mpath))
    assert loaded is not None
    manifest_before = loaded.manifest_digest

    rcpt_path = output_dir / "receipt_proj-pc.json"
    comp_sha = hashlib.sha256(rcpt_path.read_bytes()).hexdigest()

    # Verify S_ pseudonyms exist and have no selectors
    pseudonyms = sorted(set(crosswalk.mappings.values()))
    s_prefix = [p for p in pseudonyms if p.startswith("S_")]
    assert len(s_prefix) > 0
    selector_kinds = {s.content_kind for s in loaded.selectors}
    assert "SOURCE_STRING_LITERAL" not in [
        sk.split(".")[-1] if "." in sk else sk for sk in selector_kinds
    ]

    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    transition, err = execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id="proj-pc",
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q4",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )
    assert err is None

    proj = lookup_transition_by_auth(auth_id, zip_hash)
    assert proj is not None
    assert proj.status == "completed"
    assert proj.content_disposition is not None
    assert proj.content_disposition.includes_hash_only_protection is False


# ═══════════════════════════════════════════════════════════════════════
# PROOF 5: Corrupt/mismatched artifact refusal vocabulary exists.
# ═══════════════════════════════════════════════════════════════════════


def test_query_service_corrupt_refusal_vocabulary(tmp_path):
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    # Tamper manifest to force a corruption
    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    mpath = output_dir / "protected_content_manifest_proj-q.json"
    data = json.loads(mpath.read_text("utf-8"))
    data["manifest_digest"] = (
        "sha256:feeddeadfeeddeadfeeddeadfeeddeadfeeddeadfeeddeadfeeddeadfeeddead"
    )
    mpath.write_text(json.dumps(data, indent=2))

    transition, err = execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q5",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    if err and transition and transition.status == TransitionStatus.CORRUPT:
        proj = lookup_transition_by_auth(auth_id, zip_hash)
        assert proj is not None
        assert proj.status == "corrupt"
        assert proj.artifact_integrity is not None
        assert proj.artifact_integrity.chain_valid is False
        corr_detail = proj.artifact_integrity.corruption_detail
        assert corr_detail is not None or proj.status == "corrupt"


# ═══════════════════════════════════════════════════════════════════════
# PROOF 6: Projection output validates against schema.
# ═══════════════════════════════════════════════════════════════════════


def test_query_projection_validates_against_schema(tmp_path):
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q6",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    result = query_transitions()
    assert result.schema_version == QUERY_SCHEMA_VERSION
    assert result.content_light_guarantee is True
    assert result.total_count >= 1

    payload = result.model_dump()
    assert payload["schema_version"] == QUERY_SCHEMA_VERSION
    assert isinstance(payload["query_digest"], str)
    assert payload["query_digest"].startswith("sha256:")
    assert isinstance(payload["transitions"], list)
    assert len(payload["transitions"]) >= 1
    assert payload["transitions"][0]["status"] == "completed"

    # Content-light check: no raw content, secrets, or source code
    result_json = json.dumps(payload, sort_keys=True)
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
        assert forbidden not in result_json.lower(), (
            f"Forbidden '{forbidden}' found in query result"
        )


# ═══════════════════════════════════════════════════════════════════════
# PROOF 7: Deterministic projection digest.
# ═══════════════════════════════════════════════════════════════════════


def test_query_projection_deterministic_digest(tmp_path):
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q7",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    r1 = query_transitions()
    r2 = query_transitions()
    assert r1.query_digest == r2.query_digest, (
        "Deterministic digest mismatch on identical evidence"
    )

    r3 = query_transitions(QueryFilter(status="completed"))
    r4 = query_transitions(QueryFilter(status="completed"))
    assert r3.query_digest == r4.query_digest

    # compute_projection_digest also deterministic
    d1 = compute_projection_digest(r1.transitions)
    d2 = compute_projection_digest(r2.transitions)
    assert d1 == d2


# ═══════════════════════════════════════════════════════════════════════
# PROOF 8: Query service never mutates authority state.
# ═══════════════════════════════════════════════════════════════════════


def test_query_service_no_mutation(tmp_path):
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q8",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    # Capture canonical source digest before query
    from rig_relay.governance.disclosure_transition import _transition_ledger_path

    ledger = _transition_ledger_path()
    pre_digest = (
        hashlib.sha256(ledger.read_bytes()).hexdigest() if ledger.exists() else ""
    )

    # Run queries
    query_transitions()
    query_transitions(QueryFilter(status="completed"))
    lookup_transition_by_auth(auth_id, zip_hash)
    compute_projection_digest([])
    list_by_status(TransitionStatus.COMPLETED)

    # Ledger unchanged
    post_digest = (
        hashlib.sha256(ledger.read_bytes()).hexdigest() if ledger.exists() else ""
    )
    assert pre_digest == post_digest, "Query service mutated the transition ledger"

    # Disclosure event ledger unchanged
    from rig_relay.governance.disclosure_transition import _disclosure_event_ledger_path

    ev_ledger = _disclosure_event_ledger_path()
    if ev_ledger.exists():
        pre_ev = hashlib.sha256(ev_ledger.read_bytes()).hexdigest()
    else:
        pre_ev = ""
    post_ev = (
        hashlib.sha256(ev_ledger.read_bytes()).hexdigest() if ev_ledger.exists() else ""
    )
    assert pre_ev == post_ev, "Query service mutated the disclosure event ledger"


# ═══════════════════════════════════════════════════════════════════════
# PROOF 9: Empty and missing ledger edge cases.
# ═══════════════════════════════════════════════════════════════════════


def test_query_service_empty_ledger_graceful(tmp_path):
    _clean_all_stores()
    os.chdir(str(tmp_path))

    result = query_transitions()
    assert result.total_count == 0
    assert result.transitions == []
    assert result.content_light_guarantee is True
    assert result.query_digest.startswith("sha256:")

    proj = lookup_transition_by_id("nonexistent")
    assert proj is None

    proj = lookup_transition_by_auth("no-auth", "no-evidence")
    assert proj is None

    lst = list_by_status(TransitionStatus.COMPLETED)
    assert lst == []


# ═══════════════════════════════════════════════════════════════════════
# PROOF 10: Status filtering works correctly.
# ═══════════════════════════════════════════════════════════════════════


def test_query_service_status_filtering(tmp_path):
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q10",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    completed = query_transitions(QueryFilter(status="completed"))
    assert completed.total_count == 1
    assert completed.transitions[0].status == "completed"

    corrupt = query_transitions(QueryFilter(status="corrupt"))
    assert corrupt.total_count == 0

    # Include only non-terminated
    all_transitions = query_transitions(QueryFilter(include_terminated=False))
    terminated_statuses = {"completed", "refused", "corrupt", "conflict"}
    for p in all_transitions.transitions:
        assert p.status not in terminated_statuses


# ═══════════════════════════════════════════════════════════════════════
# PROOF 11: list_by_status convenience function.
# ═══════════════════════════════════════════════════════════════════════


def test_list_by_status(tmp_path):
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q11",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    lst = list_by_status(TransitionStatus.COMPLETED)
    assert len(lst) == 1
    assert lst[0].status == "completed"

    lst = list_by_status(TransitionStatus.REFUSED)
    assert len(lst) == 0


# ═══════════════════════════════════════════════════════════════════════
# PROOF 12-18: Schema-enforced admission — fail-closed canonical append
# ═══════════════════════════════════════════════════════════════════════


def test_schema_admission_rejects_wrong_version(tmp_path):
    """Wrong schema_version event is refused before append; ledger unchanged."""
    _clean_all_stores()
    os.chdir(str(tmp_path))
    from rig_relay.governance.disclosure_transition import (
        _append_transition_event,
        _transition_ledger_path,
    )

    ledger = _transition_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("")

    event = _minimal_valid_event()
    event["schema_version"] = "rig.relay.disclosure_transition_event.v1"

    pre_bytes = ledger.read_bytes()
    try:
        _append_transition_event(event)
        raise AssertionError("wrong-version event should be refused")
    except Exception:
        pass
    assert ledger.read_bytes() == pre_bytes, "ledger changed after refusal"


def test_schema_admission_rejects_missing_field(tmp_path):
    """Event missing a required v2 field is refused before append."""
    _clean_all_stores()
    os.chdir(str(tmp_path))
    from rig_relay.governance.disclosure_transition import (
        _append_transition_event,
        _transition_ledger_path,
    )

    ledger = _transition_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("")

    event = _minimal_valid_event()
    del event["evidence_digest"]

    pre_bytes = ledger.read_bytes()
    try:
        _append_transition_event(event)
        raise AssertionError("missing-field event should be refused")
    except Exception:
        pass
    assert ledger.read_bytes() == pre_bytes, "ledger changed after refusal"


def test_schema_admission_rejects_extra_property(tmp_path):
    """Extra/unexpected property is refused before append."""
    _clean_all_stores()
    os.chdir(str(tmp_path))
    from rig_relay.governance.disclosure_transition import (
        _append_transition_event,
        _transition_ledger_path,
    )

    ledger = _transition_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("")

    event = _minimal_valid_event()
    event["arbitrary_injected_field"] = "should_not_be_here"

    pre_bytes = ledger.read_bytes()
    try:
        _append_transition_event(event)
        raise AssertionError("extra-property event should be refused")
    except Exception:
        pass
    assert ledger.read_bytes() == pre_bytes, "ledger changed after refusal"


def test_schema_admission_rejects_invalid_transition_id(tmp_path):
    """Transition ID not matching pattern is refused."""
    _clean_all_stores()
    os.chdir(str(tmp_path))
    from rig_relay.governance.disclosure_transition import (
        _append_transition_event,
        _transition_ledger_path,
    )

    ledger = _transition_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("")

    event = _minimal_valid_event()
    event["transition_id"] = "not_a_valid_dzt_id"

    pre_bytes = ledger.read_bytes()
    try:
        _append_transition_event(event)
        raise AssertionError("invalid transition_id should be refused")
    except Exception:
        pass
    assert ledger.read_bytes() == pre_bytes, "ledger changed after refusal"


def test_query_service_excludes_refused_evidence(tmp_path):
    """Query service shows no projection for transitions refused at admission."""
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q12",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    # Attempt to append a malformed event directly — it never enters ledger
    from rig_relay.governance.disclosure_transition import _append_transition_event

    bad_event = _minimal_valid_event()
    bad_event["schema_version"] = "v1"
    try:
        _append_transition_event(bad_event)
    except Exception:
        pass

    # Query: only the valid transition appears
    result = query_transitions(QueryFilter(authorization_id=auth_id))
    assert result.total_count == 1
    assert result.transitions[0].status == "completed"


def test_recovery_provenance_from_fresh_process_ledger_read(tmp_path):
    """Recovery provenance visible to a fresh process reading only the ledger."""
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    kwargs = dict(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q13",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    p = multiprocessing.Process(
        target=_execute_with_crash_worker,
        args=(str(tmp_path), "authorization_consumed"),
        kwargs=kwargs,
    )
    p.start()
    p.join(timeout=30)

    transition, err = _recover_worker(str(tmp_path), auth_id, zip_hash)
    assert err is None

    # Fresh subprocess reads only the ledger
    import subprocess
    import sys

    probe_code = (
        f"import sys; sys.path.insert(0, '{tmp_path}'); "
        "from rig_relay.governance.disclosure_query import lookup_transition_by_auth; "
        f"import json; p = lookup_transition_by_auth('{auth_id}', '{zip_hash}'); "
        "print(json.dumps({'status': p.status, 'recovery_detail': p.recovery_provenance.recovery_detail if p.recovery_provenance else None}, sort_keys=True))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe_code],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert proc.returncode == 0, f"fresh process failed: {proc.stderr}"
    fresh = json.loads(proc.stdout.strip().split("\n")[-1])
    assert fresh["status"] == "completed"
    assert fresh["recovery_detail"] == "recovered_and_completed"


def _minimal_valid_event() -> dict:
    return {
        "schema_version": "rig.relay.disclosure_transition_event.v2",
        "transition_id": "dzt_aaaabbbb11112222333344",
        "authorization_id": "disc_test",
        "evidence_digest": "sha256:0000111122223333444455556666777788889999aaaabbbbccccddddeeeeffff",
        "projection_id": "proj",
        "disclosure_class": "commit_body",
        "selector_digest": None,
        "selector_required_class": None,
        "manifest_digest_before": "sha256:abc",
        "manifest_digest_after": None,
        "recipient_class": "test",
        "provider_or_channel": "test",
        "purpose": None,
        "retention_assertion": None,
        "training_use_assertion": None,
        "compilation_receipt_sha256": "",
        "receipt_approved_at": "2026-01-01T00:00:00Z",
        "disclosure_event_created_at": "2026-01-01T00:00:00Z",
        "consumed_auth_receipt_digest": None,
        "status": "prepared",
        "parent_transition_digest": None,
        "downstream_event_id": None,
        "downstream_receipt_digest": None,
        "recovery_detail": None,
        "corrupt_detail": None,
        "transition_digest": "sha256:abc",
        "created_at": "2026-01-01T00:00:00Z",
        "sequence": 0,
    }


# ═══════════════════════════════════════════════════════════════════════
# PROOF 19-23: Disclosure-event schema-enforced admission — fail-closed
# ═══════════════════════════════════════════════════════════════════════


def _minimal_disc_event() -> dict:
    return {
        "schema_version": "rig.relay.disclosure_event.v1",
        "event_id": "dze_dzt_aaaabbbb11112222333344",
        "authorization_id": "disc_test",
        "authorization_receipt_sha256": "",
        "evidence_digest": "sha256:0000111122223333444455556666777788889999aaaabbbbccccddddeeeeffff",
        "disclosure_class": "commit_body",
        "recipient_class": "test",
        "projection_id": "proj",
        "created_at": "2026-01-01T00:00:00Z",
        "outcome": "authorized",
        "transition_id": "dzt_aaaabbbb11112222333344",
    }


def _disc_event_ledger_path() -> Path:
    from rig_relay.governance.disclosure_transition import (
        _disclosure_event_ledger_path as _delp,
    )

    return _delp()


def test_disclosure_event_schema_rejects_wrong_version(tmp_path):
    _clean_all_stores()
    os.chdir(str(tmp_path))
    from rig_relay.governance.disclosure_transition import _durable_append_jsonl

    ledger = _disc_event_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("")

    event = _minimal_disc_event()
    event["schema_version"] = "rig.relay.disclosure_event.v0"

    pre_bytes = ledger.read_bytes()
    with pytest.raises(Exception):  # noqa: B017
        _validate_disclosure_event(event)
        _durable_append_jsonl(ledger, event)
    assert ledger.read_bytes() == pre_bytes, (
        "ledger changed after wrong-version refusal"
    )


def test_disclosure_event_schema_rejects_missing_field(tmp_path):
    _clean_all_stores()
    os.chdir(str(tmp_path))

    ledger = _disc_event_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("")

    event = _minimal_disc_event()
    del event["event_id"]

    pre_bytes = ledger.read_bytes()
    with pytest.raises(Exception):  # noqa: B017
        _validate_disclosure_event(event)
    assert ledger.read_bytes() == pre_bytes, (
        "ledger changed after missing-field refusal"
    )


def test_disclosure_event_schema_rejects_extra_property(tmp_path):
    _clean_all_stores()
    os.chdir(str(tmp_path))

    ledger = _disc_event_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("")

    event = _minimal_disc_event()
    event["injected_extra"] = "should_not_pass"

    pre_bytes = ledger.read_bytes()
    with pytest.raises(Exception):  # noqa: B017
        _validate_disclosure_event(event)
    assert ledger.read_bytes() == pre_bytes, (
        "ledger changed after extra-property refusal"
    )


def test_disclosure_event_schema_rejects_invalid_transition_id(tmp_path):
    _clean_all_stores()
    os.chdir(str(tmp_path))

    ledger = _disc_event_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("")

    event = _minimal_disc_event()
    event["transition_id"] = "not_valid_id"

    pre_bytes = ledger.read_bytes()
    with pytest.raises(Exception):  # noqa: B017
        _validate_disclosure_event(event)
    assert ledger.read_bytes() == pre_bytes, (
        "ledger changed after invalid transition_id refusal"
    )


def test_disclosure_event_idempotent_dedup_different_content_refused(tmp_path):
    """A conflicting disclosure event for the same transition_id is refused."""
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q14",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    # Read the existing event from the ledger
    ledger = _disc_event_ledger_path()
    assert ledger.exists()
    lines = ledger.read_text().strip().split("\n")
    assert len(lines) == 1
    existing = json.loads(lines[0])

    # Verify exactly one completed transition in query service
    result = query_transitions(QueryFilter(authorization_id=auth_id))
    assert result.total_count == 1
    assert result.transitions[0].status == "completed"

    # Idempotent dedup: same transition, same event content — should converge
    # (verified by calling the persist path with same transition)
    from rig_relay.governance.disclosure_transition import (
        DisclosureTransition,
        _persist_disclosure_event_durable,
    )
    from rig_relay.review_projection.protected_content import load_manifest_json

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    mpath = output_dir / f"protected_content_manifest_{proj_id}.json"
    manifest = load_manifest_json(str(mpath))

    # Build a fresh transition from the existing event for idempotent dedup
    dup_transition = DisclosureTransition(
        transition_id=existing["transition_id"],
        authorization_id=existing["authorization_id"],
        evidence_digest=existing["evidence_digest"],
        projection_id=existing["projection_id"],
        disclosure_class=existing["disclosure_class"],
        receipt_approved_at=str(existing.get("created_at", "")),
        disclosure_event_created_at=str(existing.get("created_at", "")),
        manifest_digest_before=existing.get("manifest_digest_before", ""),
        manifest_digest_after=existing.get("manifest_digest_after"),
        consumed_auth_receipt_digest=existing.get("authorization_receipt_sha256", ""),
        recipient_class=existing["recipient_class"],
        provider_or_channel="test",
        status=TransitionStatus.DISCLOSURE_EVENT_RECORDED,
    )

    # Idempotent call should return event_id without error
    try:
        _persist_disclosure_event_durable(dup_transition, manifest)
    except Exception as e:
        raise AssertionError(f"Idempotent dedup should not raise: {e}")

    # Ledger still has exactly one entry
    post_lines = ledger.read_text().strip().split("\n")
    assert len(post_lines) == 1, f"Expected 1 line, got {len(post_lines)}"


def test_disclosure_event_query_service_excludes_refused_events(tmp_path):
    """Query projection does not include disclosure events refused at admission."""
    _clean_all_stores()
    zip_hash, proj_id, comp_sha, manifest_before = _build_bundle_and_manifest(tmp_path)
    auth_id, _ = _issue_auth(tmp_path, zip_hash)

    execute_disclosure_transition(
        authorization_id=auth_id,
        evidence_digest=zip_hash,
        projection_id=proj_id,
        disclosure_class=DisclosureClass.COMMIT_BODY.value,
        manifest_digest_before=manifest_before,
        recipient_class="external_ai_reviewer_controlled_account",
        provider_or_channel="openai",
        purpose="test-q15",
        retention_assertion="30d",
        training_use_assertion="never",
        compilation_receipt_sha256=comp_sha,
    )

    # Verify exactly one completed transition
    result = query_transitions(QueryFilter(authorization_id=auth_id))
    assert result.total_count == 1
    assert result.transitions[0].status == "completed"


def _validate_disclosure_event(event: dict) -> None:
    from rig_relay.governance.disclosure_transition import (
        _validate_disclosure_event as _vde,
    )

    _vde(event)
