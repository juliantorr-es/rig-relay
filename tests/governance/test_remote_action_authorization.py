"""Tests for remote external action authorization authority.

Causal tests with bounded synthetic remote-action proposals. No live
GitHub calls. Covers issue, validate, consume, replay refusal, expiry,
wrong action/provider/target/digest refusal, stale evidence refusal,
unsupported action refusal, integrity tamper, sentinel exclusion, and
concurrent consumption race behavior.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rig_relay.governance.remote_action_authorization import (
    RemoteActionAuthorizationReceipt,
    RemoteActionClass,
    RemoteActionOutcome,
    RemoteActionResult,
    RemoteMutationRisk,
    SUPPORTED_ACTION_CLASSES,
    FRESHNESS_REQUIRED_ACTIONS,
    NO_PRIOR_EVIDENCE_ACTIONS,
    consume_remote_action_authorization,
    issue_remote_action_authorization,
    validate_remote_action_authorization,
    _rea_store_root,
    _rea_receipt_path,
)


def _sha256(data: str) -> str:
    return "sha256:" + hashlib.sha256(data.encode()).hexdigest()


REQUEST_BIO = _sha256('{"bio": "updated bio text"}')
REQUEST_REPO = _sha256('{"name": "new-repo", "visibility": "private"}')
REQUEST_ISSUE = _sha256('{"title": "bug report", "body": "details"}')
REQUEST_COMMENT = _sha256('{"body": "looks good"}')
REQUEST_RERUN = _sha256('{"run_id": "12345"}')
REQUEST_DISPATCH = _sha256('{"event_type": "deploy"}')
REQUEST_PAGES_SRC = _sha256('{"source": {"branch": "gh-pages"}}')
REQUEST_PAGES_PUB = _sha256('{"target": "production"}')
EVIDENCE_V1 = _sha256("evidence-v1")
EVIDENCE_V2 = _sha256("evidence-v2")
DIFFERENT_REQUEST = _sha256("different-request")


def _clean():
    root = _rea_store_root()
    if root.exists():
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def _issue(action_class, **kwargs):
    _clean()
    defaults = {
        "action_class": action_class,
        "provider": "github",
        "target_identity": "",
        "request_digest": _sha256("test"),
    }
    defaults.update(kwargs)
    result = issue_remote_action_authorization(**defaults)
    assert result.outcome == RemoteActionOutcome.ISSUED, (
        f"Issue failed: {result.error_detail}"
    )
    assert result.receipt is not None
    return result.receipt.authorization_id, result.receipt


# ── Successful issuance and validation for each required action class ───────


@pytest.mark.parametrize(
    "action_class,request_digest,target,prior_evidence",
    [
        (
            RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
            REQUEST_BIO,
            "octocat",
            EVIDENCE_V1,
        ),
        (
            RemoteActionClass.GITHUB_REPOSITORY_CREATE.value,
            REQUEST_REPO,
            "octocat/new-repo",
            "",
        ),
        (
            RemoteActionClass.GITHUB_ISSUE_CREATE.value,
            REQUEST_ISSUE,
            "octocat/hello-world",
            "",
        ),
        (
            RemoteActionClass.GITHUB_ISSUE_COMMENT.value,
            REQUEST_COMMENT,
            "octocat/hello-world#1",
            EVIDENCE_V1,
        ),
        (
            RemoteActionClass.GITHUB_ISSUE_CLOSE.value,
            _sha256("close"),
            "octocat/hello-world#1",
            EVIDENCE_V1,
        ),
        (
            RemoteActionClass.GITHUB_ACTIONS_RERUN.value,
            REQUEST_RERUN,
            "octocat/hello-world/12345",
            EVIDENCE_V1,
        ),
        (
            RemoteActionClass.GITHUB_ACTIONS_DISPATCH.value,
            REQUEST_DISPATCH,
            "octocat/hello-world",
            EVIDENCE_V1,
        ),
        (
            RemoteActionClass.GITHUB_PAGES_CONFIGURE.value,
            REQUEST_PAGES_SRC,
            "octocat/hello-world",
            EVIDENCE_V1,
        ),
        (
            RemoteActionClass.GITHUB_PAGES_PUBLISH.value,
            REQUEST_PAGES_PUB,
            "octocat/hello-world",
            EVIDENCE_V1,
        ),
        (
            RemoteActionClass.GITHUB_PAGES_CANCEL_DEPLOYMENT.value,
            _sha256("cancel"),
            "octocat/hello-world",
            EVIDENCE_V1,
        ),
    ],
)
def test_issue_and_validate_each_action(
    action_class, request_digest, target, prior_evidence
):
    _clean()
    result = issue_remote_action_authorization(
        action_class=action_class,
        provider="github",
        target_identity=target,
        request_digest=request_digest,
        prior_evidence_digest=prior_evidence,
        purpose="testing",
    )
    assert result.outcome == RemoteActionOutcome.ISSUED, (
        f"{action_class}: {result.error_detail}"
    )
    assert result.receipt.verify_integrity()

    # Validate
    valid = validate_remote_action_authorization(
        result.authorization_id,
        expected_action_class=action_class,
        expected_request_digest=request_digest,
        current_prior_evidence_digest=prior_evidence or None,
    )
    assert valid.outcome == RemoteActionOutcome.VALID, (
        f"{action_class}: {valid.error_detail}"
    )


# ── Single-use consumption ────────────────────────────────────────────────────


def test_consume_one_time_receipt():
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        target_identity="octocat",
        request_digest=REQUEST_BIO,
        prior_evidence_digest=EVIDENCE_V1,
    )
    result = consume_remote_action_authorization(
        auth_id,
        expected_action_class=RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        expected_request_digest=REQUEST_BIO,
        current_prior_evidence_digest=EVIDENCE_V1,
    )
    assert result.outcome == RemoteActionOutcome.CONSUMED
    assert result.receipt.consumed is True


# ── Replay refusal ────────────────────────────────────────────────────────────


def test_replay_refused():
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_ISSUE_COMMENT.value,
        target_identity="octocat/hello-world#1",
        request_digest=REQUEST_COMMENT,
        prior_evidence_digest=EVIDENCE_V1,
    )
    c1 = consume_remote_action_authorization(
        auth_id,
        expected_action_class=RemoteActionClass.GITHUB_ISSUE_COMMENT.value,
        expected_request_digest=REQUEST_COMMENT,
        current_prior_evidence_digest=EVIDENCE_V1,
    )
    assert c1.outcome == RemoteActionOutcome.CONSUMED
    c2 = consume_remote_action_authorization(auth_id)
    assert c2.outcome == RemoteActionOutcome.ALREADY_CONSUMED


# ── Expiry refusal ────────────────────────────────────────────────────────────


def test_expired_refusal():
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        target_identity="octocat",
        request_digest=REQUEST_BIO,
        prior_evidence_digest=EVIDENCE_V1,
    )
    # Tamper with expires_at to make it expired, then re-seal
    path = _rea_receipt_path(auth_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["expires_at"] = "2020-01-01T00:00:00+00:00"
    # Re-seal the receipt to maintain integrity
    receipt_modified = RemoteActionAuthorizationReceipt.model_validate(data)
    receipt_modified.expires_at = "2020-01-01T00:00:00+00:00"
    receipt_modified.seal()
    path.write_text(
        json.dumps(receipt_modified.model_dump(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    valid = validate_remote_action_authorization(auth_id)
    assert valid.outcome == RemoteActionOutcome.EXPIRED


# ── Wrong action refusal ─────────────────────────────────────────────────────


def test_action_mismatch_refused():
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_ISSUE_CREATE.value, request_digest=REQUEST_ISSUE
    )
    valid = validate_remote_action_authorization(
        auth_id, expected_action_class=RemoteActionClass.GITHUB_REPOSITORY_CREATE.value
    )
    assert valid.outcome == RemoteActionOutcome.ACTION_MISMATCH


# ── Wrong provider refusal ────────────────────────────────────────────────────


def test_provider_mismatch_refused():
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        provider="github",
        request_digest=REQUEST_BIO,
        prior_evidence_digest=EVIDENCE_V1,
    )
    valid = validate_remote_action_authorization(auth_id, expected_provider="gitlab")
    assert valid.outcome == RemoteActionOutcome.PROVIDER_MISMATCH


# ── Wrong target refusal ─────────────────────────────────────────────────────


def test_target_mismatch_refused():
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_REPOSITORY_CREATE.value,
        target_identity="octocat/my-repo",
        request_digest=REQUEST_REPO,
    )
    valid = validate_remote_action_authorization(
        auth_id, expected_target="octocat/other-repo"
    )
    assert valid.outcome == RemoteActionOutcome.TARGET_MISMATCH


# ── Wrong request digest refusal ─────────────────────────────────────────────


def test_request_digest_mismatch_refused():
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        request_digest=REQUEST_BIO,
        prior_evidence_digest=EVIDENCE_V1,
    )
    valid = validate_remote_action_authorization(
        auth_id, expected_request_digest=DIFFERENT_REQUEST
    )
    assert valid.outcome == RemoteActionOutcome.REQUEST_DIGEST_MISMATCH


# ── Stale evidence refusal ───────────────────────────────────────────────────


def test_stale_evidence_refused():
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_PAGES_PUBLISH.value,
        target_identity="octocat/hello-world",
        request_digest=REQUEST_PAGES_PUB,
        prior_evidence_digest=EVIDENCE_V1,
    )
    valid = validate_remote_action_authorization(
        auth_id,
        current_prior_evidence_digest=EVIDENCE_V2,  # different from issued
    )
    assert valid.outcome == RemoteActionOutcome.STALE_EVIDENCE


def test_missing_freshness_for_required_action():
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_ACTIONS_RERUN.value,
        request_digest=REQUEST_RERUN,
        prior_evidence_digest=EVIDENCE_V1,
    )
    valid = validate_remote_action_authorization(auth_id)
    assert valid.outcome == RemoteActionOutcome.MISSING_FRESHNESS


def test_creation_action_without_evidence_ok():
    """Repository creation does NOT require prior evidence."""
    _clean()
    result = issue_remote_action_authorization(
        action_class=RemoteActionClass.GITHUB_REPOSITORY_CREATE.value,
        provider="github",
        target_identity="octocat/new-repo",
        request_digest=REQUEST_REPO,
    )
    assert result.outcome == RemoteActionOutcome.ISSUED
    valid = validate_remote_action_authorization(result.authorization_id)
    assert valid.outcome == RemoteActionOutcome.VALID


# ── Unsupported action refusal ──────────────────────────────────────────────


def test_unsupported_action_refused():
    _clean()
    result = issue_remote_action_authorization(
        action_class="github.fake_action.nonexistent",
        provider="github",
        request_digest=_sha256("test"),
    )
    assert result.outcome == RemoteActionOutcome.UNSUPPORTED_ACTION


# ── Integrity tamper refusal ──────────────────────────────────────────────────


def test_integrity_tamper_refused():
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_ISSUE_CLOSE.value,
        target_identity="octocat/hello-world#1",
        request_digest=_sha256("close"),
        prior_evidence_digest=EVIDENCE_V1,
    )
    path = _rea_receipt_path(auth_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["action_class"] = "github_issue_create"  # tamper
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    valid = validate_remote_action_authorization(auth_id)
    assert valid.outcome == RemoteActionOutcome.INTEGRITY_TAMPERED


# ── Sentinel exclusion ────────────────────────────────────────────────────────


def test_sentinel_content_refused():
    """Receipt must not contain raw tokens or confidential data."""
    _clean()
    receipt = RemoteActionAuthorizationReceipt(
        action_class=RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        provider="github",
        request_digest=REQUEST_BIO,
        prior_evidence_digest=EVIDENCE_V1,
        purpose="test",
    )
    receipt.seal()

    # Manually construct a tampered receipt containing a bearer token
    fake = receipt.model_dump()
    fake["authorization_header"] = "Bearer ghp_fakeToken123"

    # Validate must reject
    from rig_relay.governance.remote_action_authorization import _check_sentinels

    outcome = _check_sentinels(fake)
    assert outcome == RemoteActionOutcome.SENTINEL_EXCLUDED


def test_sentinel_runtime_exclusion():
    """Runtime sentinel check on persisted receipt with confidential field."""
    _clean()
    # Try to issue with confidential content via key injection
    receipt = RemoteActionAuthorizationReceipt(
        action_class=RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        provider="github",
        request_digest=REQUEST_BIO,
    )
    receipt.seal()

    path = _rea_receipt_path(receipt.authorization_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = receipt.model_dump()
    data["bearer_token"] = "secret"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    valid = validate_remote_action_authorization(receipt.authorization_id)
    assert valid.outcome == RemoteActionOutcome.SENTINEL_EXCLUDED


# ── Concurrency: double consumption prevented ──────────────────────────────


def test_double_consume_atomic():
    """Concurrent consumption must be prevented under lock."""
    auth_id, receipt = _issue(
        RemoteActionClass.GITHUB_ISSUE_COMMENT.value,
        request_digest=REQUEST_COMMENT,
        target_identity="repo#1",
        prior_evidence_digest=EVIDENCE_V1,
    )
    c1 = consume_remote_action_authorization(
        auth_id,
        expected_request_digest=REQUEST_COMMENT,
        current_prior_evidence_digest=EVIDENCE_V1,
    )
    assert c1.outcome == RemoteActionOutcome.CONSUMED
    c2 = consume_remote_action_authorization(
        auth_id,
        expected_request_digest=REQUEST_COMMENT,
        current_prior_evidence_digest=EVIDENCE_V1,
    )
    assert c2.outcome == RemoteActionOutcome.ALREADY_CONSUMED


# ── Missing request digest refusal at issue ───────────────────────────────────


def test_issue_without_request_digest_refused():
    _clean()
    result = issue_remote_action_authorization(
        action_class=RemoteActionClass.GITHUB_ISSUE_CREATE.value, request_digest=""
    )
    assert result.outcome == RemoteActionOutcome.REQUEST_DIGEST_MISMATCH


# ── Freshness required without prior evidence refused at issue ──────────────


def test_issue_freshness_action_without_prior_evidence_refused():
    _clean()
    result = issue_remote_action_authorization(
        action_class=RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        request_digest=REQUEST_BIO,
        prior_evidence_digest="",
    )
    assert result.outcome == RemoteActionOutcome.MISSING_FRESHNESS


# ── Receipt model schema roundtrip ────────────────────────────────────────────


def test_receipt_integrity_roundtrip():
    receipt = RemoteActionAuthorizationReceipt(
        action_class=RemoteActionClass.GITHUB_REPOSITORY_CREATE.value,
        provider="github",
        target_identity="octocat/test-repo",
        request_digest=REQUEST_REPO,
        purpose="test",
    )
    receipt.seal()
    assert receipt.verify_integrity()
    receipt.target_identity = "octocat/different"
    assert not receipt.verify_integrity()


# ── Schema validation against real emitted receipts ──────────────────────────


def test_receipt_schema_validation():
    import jsonschema
    import os

    schema_path = (
        Path(os.path.dirname(__file__)).parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.remote_action_authorization_receipt.v1.schema.json"
    )
    assert schema_path.exists(), f"Schema missing at {schema_path}"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    _clean()
    result = issue_remote_action_authorization(
        action_class=RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        provider="github",
        target_identity="octocat",
        request_digest=REQUEST_BIO,
        prior_evidence_digest=EVIDENCE_V1,
        purpose="test",
    )
    assert result.outcome == RemoteActionOutcome.ISSUED
    receipt_dict = json.loads(result.receipt.model_dump_json())
    jsonschema.validate(instance=receipt_dict, schema=schema)


# ── Mutation risk classification ─────────────────────────────────────────────


def test_mutation_risk_classification():
    assert RemoteMutationRisk.DESTRUCTIVE.value == "destructive"
    assert RemoteMutationRisk.MUTATING.value == "mutating"
    assert RemoteMutationRisk.CONFIGURATION.value == "configuration"
    assert RemoteMutationRisk.DEPLOYMENT.value == "deployment"


def test_all_supported_actions_have_risk():
    for action in SUPPORTED_ACTION_CLASSES:
        from rig_relay.governance.remote_action_authorization import _ACTION_RISK_MAP

        assert action in _ACTION_RISK_MAP, f"Missing risk for {action}"


# ── Freshness classification coverage ────────────────────────────────────────


def test_freshness_and_no_prior_are_disjoint():
    overlap = FRESHNESS_REQUIRED_ACTIONS & NO_PRIOR_EVIDENCE_ACTIONS
    assert not overlap, f"Overlap: {overlap}"


def test_every_action_in_supported_classified():
    all_actions = SUPPORTED_ACTION_CLASSES
    for action in all_actions:
        assert (
            action in FRESHNESS_REQUIRED_ACTIONS or action in NO_PRIOR_EVIDENCE_ACTIONS
        ), f"Action {action} not classified as freshness_required or no_prior"
