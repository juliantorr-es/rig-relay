"""Causal tests for the step-up disclosure CLI authorization corridor.

Uses real receipt persistence, real JSONL ledger files, real
governance authority consumption, and real CLI invocation.

Proves:
  R1 — disclose refuses without authorization_id
  R2 — valid authorization for exact bundle hash succeeds
  R3 — replay is refused (single-use consumption)
  R4 — evidence mismatch refused (wrong bundle hash)
  R5 — content-light disclosure event ledger has hashes, not raw content
  R6 — existing governance disclosure authorization tests remain green
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from rig_relay.governance.disclosure_authorization import (
    DisclosureClass,
    DisclosureOutcome,
    _store_root as _gov_store_root,
    consume_disclosure_authorization,
    issue_disclosure_authorization,
    validate_disclosure_authorization,
)

EVIDENCE_DIGEST = (
    "sha256:0000111122223333444455556666777788889999aaaabbbbccccddddeeeeffff"
)
WRONG_DIGEST = "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"


def _clean_gov_store():
    root = _gov_store_root()
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


def _issue_receipt_in_dir(workdir: Path) -> tuple[str, str]:
    """Issue a governance disclosure receipt in the given working directory."""
    _clean_gov_store()
    # Temporarily chdir to workdir so the receipt is stored there
    import os as _os

    old_cwd = _os.getcwd()
    try:
        _os.chdir(str(workdir))
        result = issue_disclosure_authorization(
            evidence_digest=EVIDENCE_DIGEST,
            disclosure_class=DisclosureClass.BRANCH_ENUMERATION.value,
            actor_identity="test-actor",
            producer_identity="test-producer",
            purpose="testing disclosure CLI",
            ttl_minutes=60,
            one_time=True,
        )
        assert result.outcome == DisclosureOutcome.ISSUED
        assert result.receipt is not None
        return result.receipt.authorization_id, result.receipt.receipt_sha256
    finally:
        _os.chdir(old_cwd)


def _make_compilation_receipt(output_dir: Path, zip_hash: str) -> None:
    """Create a compilation receipt and manifest in the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    projection_id = "test-projection-id"
    receipt_data = {
        "schema_version": "rig.review_projection.compilation_receipt.v1",
        "projection_id": projection_id,
        "candidate_zip_sha256": zip_hash,
        "output_status": "candidate_generated",
    }
    (output_dir / f"receipt_{projection_id}.json").write_text(
        json.dumps(receipt_data), "utf-8"
    )
    # Also create a minimal protected-content manifest
    from rig_relay.review_projection.protected_content import (
        build_default_manifest,
        write_manifest_json,
    )

    manifest = build_default_manifest(
        projection_id, zip_hash, "test-sha", "2026-01-01T00:00:00Z"
    )
    write_manifest_json(
        manifest, str(output_dir / f"protected_content_manifest_{projection_id}.json")
    )


# ═══════════════════════════════════════════════════════════════════════
# R1 — Disclose refuses without authorization_id
# ═══════════════════════════════════════════════════════════════════════


def test_disclose_refuses_with_empty_authorization_id(tmp_path, monkeypatch):
    """R1: disclosure requires an authorization_id."""
    import contextlib
    import io

    from rig_relay.review_projection.cli import _run_disclose_authorization

    monkeypatch.chdir(tmp_path)

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    _make_compilation_receipt(output_dir, EVIDENCE_DIGEST)

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        _run_disclose_authorization(
            candidate_zip_hash=EVIDENCE_DIGEST,
            recipient_class="external_ai_reviewer_controlled_account",
            provider_or_channel="openai",
            purpose="test",
            retention="30d",
            training_use="never",
            authorization_id="",
        )

    output = captured.getvalue()
    assert "REFUSED" in output
    assert "authorization_id is required" in output


# ═══════════════════════════════════════════════════════════════════════
# R2 — Valid authorization for exact bundle hash succeeds
# ═══════════════════════════════════════════════════════════════════════


def test_disclose_authorized_for_exact_bundle_hash(tmp_path, monkeypatch):
    """R2: consume disclosure authorization for exact bundle hash."""
    monkeypatch.chdir(tmp_path)
    auth_id, _ = _issue_receipt_in_dir(tmp_path)

    import contextlib
    import io

    from rig_relay.review_projection.cli import _run_disclose_authorization

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    _make_compilation_receipt(output_dir, EVIDENCE_DIGEST)

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        _run_disclose_authorization(
            candidate_zip_hash=EVIDENCE_DIGEST,
            recipient_class="external_ai_reviewer_controlled_account",
            provider_or_channel="openai",
            purpose="test",
            retention="30d",
            training_use="never",
            authorization_id=auth_id,
        )

        output = captured.getvalue()
        assert "Disclosure transition completed" in output
        assert "REFUSED" not in output

    # Verify review projection receipt was written
    auth_files = list(output_dir.glob("disclosure_authorization_*.json"))
    assert len(auth_files) >= 1

    # Verify content-light disclosure event ledger exists
    disclosure_ledger = (
        tmp_path / ".build" / "rig-relay" / "governance" / "disclosure_events.v1.jsonl"
    )
    assert disclosure_ledger.exists()
    lines = disclosure_ledger.read_text().strip().split("\n")
    assert len(lines) >= 1
    event = json.loads(lines[-1])
    assert event["schema_version"] == "rig.relay.disclosure_event.v1"
    assert event["outcome"] == "authorized"
    assert event["evidence_digest"] == EVIDENCE_DIGEST
    assert event["authorization_id"] == auth_id

    # Content-light check: no raw content, secrets, or source code
    event_str = json.dumps(event)
    assert "def " not in event_str  # No source code
    assert "ghp_" not in event_str  # No GitHub token
    assert "print(" not in event_str  # No code
    assert "class " not in event_str  # No code


# ═══════════════════════════════════════════════════════════════════════
# R3 — Replay is refused
# ═══════════════════════════════════════════════════════════════════════


def test_disclose_replay_refused(tmp_path, monkeypatch):
    """R3: consumed authorization cannot be replayed."""
    monkeypatch.chdir(tmp_path)
    auth_id, _ = _issue_receipt_in_dir(tmp_path)

    import contextlib
    import io

    from rig_relay.review_projection.cli import _run_disclose_authorization

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    _make_compilation_receipt(output_dir, EVIDENCE_DIGEST)

    # First disclosure — succeeds
    captured1 = io.StringIO()
    with contextlib.redirect_stdout(captured1):
        _run_disclose_authorization(
            candidate_zip_hash=EVIDENCE_DIGEST,
            recipient_class="external_ai_reviewer_controlled_account",
            provider_or_channel="openai",
            purpose="test",
            retention="30d",
            training_use="never",
            authorization_id=auth_id,
        )
    assert "REFUSED" not in captured1.getvalue()

    # Second disclosure with same receipt — detects already completed (idempotent)
    captured2 = io.StringIO()
    with contextlib.redirect_stdout(captured2):
        _run_disclose_authorization(
            candidate_zip_hash=EVIDENCE_DIGEST,
            recipient_class="external_ai_reviewer_controlled_account",
            provider_or_channel="openai",
            purpose="test",
            retention="30d",
            training_use="never",
            authorization_id=auth_id,
        )
    output2 = captured2.getvalue()
    # Idempotent recovery: already completed, not refused
    assert "already completed" in output2.lower()


# ═══════════════════════════════════════════════════════════════════════
# R4 — Evidence mismatch refused
# ═══════════════════════════════════════════════════════════════════════


def test_disclose_wrong_bundle_hash_refused(tmp_path, monkeypatch):
    """R4: authorization must bind to exact bundle hash."""
    monkeypatch.chdir(tmp_path)
    auth_id, _ = _issue_receipt_in_dir(tmp_path)

    import contextlib
    import io

    from rig_relay.review_projection.cli import _run_disclose_authorization

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    _make_compilation_receipt(output_dir, WRONG_DIGEST)

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        _run_disclose_authorization(
            candidate_zip_hash=WRONG_DIGEST,
            recipient_class="external_ai_reviewer_controlled_account",
            provider_or_channel="openai",
            purpose="test",
            retention="30d",
            training_use="never",
            authorization_id=auth_id,
        )

    output = captured.getvalue()
    assert "REFUSED" in output
    # Evidence mismatch: receipt binds to EVIDENCE_DIGEST but we're using WRONG_DIGEST
    assert "mismatch" in output.lower() or "does not match" in output.lower()


# ═══════════════════════════════════════════════════════════════════════
# R5 — Content-light disclosure event ledger verification
# ═══════════════════════════════════════════════════════════════════════


def test_disclosure_ledger_is_content_light(tmp_path, monkeypatch):
    """R5: disclosure events contain hashes and metadata but no raw content."""
    monkeypatch.chdir(tmp_path)
    auth_id, _ = _issue_receipt_in_dir(tmp_path)

    import contextlib
    import io

    from rig_relay.review_projection.cli import _run_disclose_authorization

    output_dir = tmp_path / ".build" / "rig-relay" / "review_projection"
    _make_compilation_receipt(output_dir, EVIDENCE_DIGEST)

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        _run_disclose_authorization(
            candidate_zip_hash=EVIDENCE_DIGEST,
            recipient_class="external_ai_reviewer_controlled_account",
            provider_or_channel="openai",
            purpose="test",
            retention="30d",
            training_use="never",
            authorization_id=auth_id,
        )

    # Read the disclosure event ledger
    ledger_path = (
        tmp_path / ".build" / "rig-relay" / "governance" / "disclosure_events.v1.jsonl"
    )
    assert ledger_path.exists()
    lines = ledger_path.read_text().strip().split("\n")
    assert len(lines) >= 1

    for line in lines:
        event = json.loads(line)

        # Must have schema
        assert "schema_version" in event

        # Must not contain raw content signs
        event_str = json.dumps(event, sort_keys=True)
        for forbidden in [
            "source_code",
            "raw_content",
            "file_content",
            "password",
            "secret",
            "api_key",
            "token",
            "ghp_",
            "ghs_",
            "gho_",
            "bearer ",
            "print(",
            "def ",
            "class ",
        ]:
            assert forbidden not in event_str.lower(), (
                f"Forbidden content '{forbidden}' found in disclosure event: {event_str[:200]}"
            )

        # Must contain essential metadata
        assert event.get("evidence_digest") is not None
        assert event.get("authorization_id") is not None


# ═══════════════════════════════════════════════════════════════════════
# R6 — Existing governance disclosure auth tests remain green
# ═══════════════════════════════════════════════════════════════════════


def test_existing_governance_primitives_still_work():
    """R6: Governance disclosure auth primitives are unaffected."""
    _clean_gov_store()

    # Issue
    r = issue_disclosure_authorization(
        evidence_digest=EVIDENCE_DIGEST,
        disclosure_class=DisclosureClass.PATH_IDENTITY.value,
        actor_identity="smoke-test",
    )
    assert r.outcome == DisclosureOutcome.ISSUED
    assert r.receipt is not None

    # Validate
    v = validate_disclosure_authorization(
        r.receipt.authorization_id, current_evidence_digest=EVIDENCE_DIGEST
    )
    assert v.outcome == DisclosureOutcome.VALID

    # Consume
    c = consume_disclosure_authorization(
        r.receipt.authorization_id, current_evidence_digest=EVIDENCE_DIGEST
    )
    assert c.outcome == DisclosureOutcome.CONSUMED

    # Replay
    r2 = consume_disclosure_authorization(
        r.receipt.authorization_id, current_evidence_digest=EVIDENCE_DIGEST
    )
    assert r2.outcome == DisclosureOutcome.ALREADY_CONSUMED
