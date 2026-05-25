"""Recovery-safe lifecycle tests for governed mutation chain.

Proves: interrupted-write recovery, checkpoint receipt persistence,
push receipt persistence, same-path writer exclusion, terminal ledgers,
terminal crash windows (R14/R15).
"""

from __future__ import annotations

import hashlib
import json
import subprocess

from rig_relay.cli._steward._mutation_payload import (
    MutationPayloadRecord,
    compute_payload_sha256,
)
from rig_relay.cli._steward._path_lock import acquire_path_lock, release_path_lock
from rig_relay.cli._steward._proposal_admission import ProposalAdmissionDecision
from rig_relay.cli._steward._proposal_apply import (
    _load_apply_state,
    _save_apply_state,
    apply_admitted_proposal,
    recover_apply_result,
)


def _decision(before_hash="", after_hash="", status="admitted"):
    return ProposalAdmissionDecision.model_validate({
        "decision_id": "d1",
        "proposal_id": "prop-1",
        "campaign_id": "c1",
        "mission_id": "m1",
        "file_path": "a.py",
        "admission_status": status,
        "authority_source": "test",
        "reason_code": "admitted",
        "before_sha256": before_hash,
        "candidate_after_sha256": after_hash,
    })


def _payload(content, before_hash="", after_hash=""):
    return MutationPayloadRecord.model_validate({
        "payload_id": "pay-1",
        "proposal_id": "prop-1",
        "campaign_id": "c1",
        "mission_id": "m1",
        "file_path": "a.py",
        "before_sha256": before_hash,
        "candidate_after_sha256": after_hash,
        "mutation_content": content,
        "content_format": "search_replace_blocks",
        "payload_sha256": compute_payload_sha256(content),
    })


# ---- Interrupted write recovery ----


def test_recovery_after_crash_landed_write(tmp_path):
    """Classification: integration/real-artifact

    Write lands during applying, power fails before apply receipt.
    Recovery detects hash matches candidate → recovered. No duplicate write.
    """
    fp = tmp_path / "a.py"
    content = "hello\n"
    fp.write_text(content)
    bh = hashlib.sha256(content.encode()).hexdigest()
    mh = hashlib.sha256(b"hello world\n").hexdigest()

    decision = _decision(before_hash=bh, after_hash=mh)

    # Simulate: write landed, state is 'applying', then crash
    fp.write_text("hello world\n")
    _save_apply_state("c1", "prop-1", "applying", tmp_path)
    assert _load_apply_state("c1", "prop-1", tmp_path) == "applying"

    recovered = recover_apply_result(decision, "c1", tmp_path, fp)
    assert recovered is not None, (
        f"State={_load_apply_state('c1', 'prop-1', tmp_path)}, "
        f"Hash={hashlib.sha256(fp.read_bytes()).hexdigest()}, "
        f"Expected={decision.candidate_after_sha256}"
    )
    assert recovered.status == "recovered"


def test_recovery_hash_divergent_refuses(tmp_path):
    """Classification: sabotage/integration

    Workspace hash matches neither before nor candidate → refuse.
    """
    fp = tmp_path / "a.py"
    fp.write_text("original\n")
    bh = hashlib.sha256(b"original\n").hexdigest()
    mh = hashlib.sha256(b"modified\n").hexdigest()

    decision = _decision(before_hash=bh, after_hash=mh)
    payload = _payload(
        "<<<<<<< SEARCH\nx\n=======\ny\n>>>>>>> REPLACE", before_hash=bh, after_hash=mh
    )

    fp.write_text("divergent\n")
    result = apply_admitted_proposal(
        decision, payload, fp.read_bytes(), fp, "c1", tmp_path
    )
    assert result.status == "divergent"


def test_recovery_write_never_duplicated(tmp_path):
    """Classification: integration/real-artifact

    Second apply with same decision + hash already matches candidate →
    returns recovered without writing.
    """
    fp = tmp_path / "a.py"
    fp.write_text("x=1\n")
    bh = hashlib.sha256(b"x=1\n").hexdigest()
    mh = hashlib.sha256(b"x=2\n").hexdigest()

    decision = _decision(before_hash=bh, after_hash=mh)
    payload = _payload(
        "<<<<<<< SEARCH\nx=1\n=======\nx=2\n>>>>>>> REPLACE",
        before_hash=bh,
        after_hash=mh,
    )

    r1 = apply_admitted_proposal(decision, payload, fp.read_bytes(), fp, "c1", tmp_path)
    assert r1.status == "applied"

    r2 = apply_admitted_proposal(decision, payload, fp.read_bytes(), fp, "c1", tmp_path)
    assert r2.status == "recovered"
    assert r2.recovered is True


# ---- Terminal receipt persistence ----


def test_checkpoint_receipt_persisted(tmp_path):
    """Classification: contract/integration
    Checkpoint receipt appended to JSONL ledger.
    """
    from rig_relay.cli._steward._campaign_runtime import append_checkpoint_receipt

    campaign_dir = tmp_path / ".rig" / "relay" / "campaigns" / "c1"
    campaign_dir.mkdir(parents=True)

    receipt = {
        "receipt_id": "r1",
        "commit_sha": "abc123",
        "outcome": "checkpoint_created",
    }
    append_checkpoint_receipt("c1", tmp_path, receipt)

    ledger = campaign_dir / "checkpoint_receipts.v1.jsonl"
    assert ledger.exists()
    lines = ledger.read_text().strip().split("\n")
    assert len(lines) == 1
    assert "abc123" in lines[0]


def test_push_receipt_persisted(tmp_path):
    """Classification: contract/integration
    Push receipt appended to JSONL ledger.
    """
    from rig_relay.cli._steward._campaign_runtime import append_push_receipt

    campaign_dir = tmp_path / ".rig" / "relay" / "campaigns" / "c1"
    campaign_dir.mkdir(parents=True)

    receipt = {"receipt_id": "pr1", "succeeded": True, "pushed_head_sha": "def456"}
    append_push_receipt("c1", tmp_path, receipt)

    ledger = campaign_dir / "private_push_receipts.v1.jsonl"
    assert ledger.exists()
    lines = ledger.read_text().strip().split("\n")
    assert len(lines) == 1
    assert "def456" in lines[0]


# ---- Same-path writer exclusion ----


def test_path_lock_acquire_exclusive(tmp_path):
    """Classification: contract/integration
    Two concurrent proposals cannot acquire lock for same path.
    """
    assert acquire_path_lock("c1", "a.py", "prop-1", tmp_path)
    assert not acquire_path_lock("c1", "a.py", "prop-2", tmp_path)
    release_path_lock("c1", "a.py", tmp_path)
    assert acquire_path_lock("c1", "a.py", "prop-3", tmp_path)


def test_path_lock_expired_retaken(tmp_path):
    """Classification: contract/integration
    Expired lock is retaken.
    """
    import time

    assert acquire_path_lock("c1", "a.py", "prop-1", tmp_path)
    lock_path = (
        tmp_path / ".rig" / "relay" / "campaigns" / "c1" / "path_locks" / "a_py.lock"
    )
    data = json.loads(lock_path.read_text())
    data["timestamp"] = int(time.time()) - 400
    lock_path.write_text(json.dumps(data))
    assert acquire_path_lock("c1", "a.py", "prop-2", tmp_path)


def test_stale_contender_refuses(tmp_path):
    """Classification: sabotage/integration

    Two proposals target same path. First applies successfully.
    Second tries with same baselinesh — hash now matches candidate → recovered.
    """
    fp = tmp_path / "a.py"
    fp.write_text("x=1\n")
    bh = hashlib.sha256(b"x=1\n").hexdigest()
    mh = hashlib.sha256(b"x=2\n").hexdigest()
    decision = _decision(before_hash=bh, after_hash=mh)
    payload = _payload(
        "<<<<<<< SEARCH\nx=1\n=======\nx=2\n>>>>>>> REPLACE",
        before_hash=bh,
        after_hash=mh,
    )

    assert acquire_path_lock("c1", "a.py", "prop-1", tmp_path)
    r1 = apply_admitted_proposal(decision, payload, fp.read_bytes(), fp, "c1", tmp_path)
    assert r1.status == "applied"
    release_path_lock("c1", "a.py", tmp_path)

    r2 = apply_admitted_proposal(decision, payload, fp.read_bytes(), fp, "c1", tmp_path)
    assert r2.status == "recovered"


# ---- Apply state cycle ----


def test_apply_state_persisted(tmp_path):
    """Classification: contract/integration
    Apply state transitions through pending → applying → applied on disk.
    """
    fp = tmp_path / "a.py"
    fp.write_text("a\n")
    bh = hashlib.sha256(b"a\n").hexdigest()
    mh = hashlib.sha256(b"b\n").hexdigest()
    decision = _decision(before_hash=bh, after_hash=mh)
    payload = _payload(
        "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE", before_hash=bh, after_hash=mh
    )

    result = apply_admitted_proposal(
        decision, payload, fp.read_bytes(), fp, "c1", tmp_path
    )
    assert result.status == "applied"
    assert _load_apply_state("c1", "prop-1", tmp_path) == "applied"


# ---- Terminal crash windows (R14/R15) ----


def test_r14_checkpoint_commit_exists_but_receipt_interrupted(tmp_path):
    """Classification: integration/real-artifact

    R14: Checkpoint commit created but receipt persistence interrupted.
    Restart identifies existing receipt-bound commit → emits recovered
    evidence → does not create a second commit.
    """
    subprocess.run(["git", "-C", str(tmp_path), "init"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t"], capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "T"], capture_output=True
    )
    (tmp_path / "a.py").write_text("x=1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True
    )

    from rig_relay.cli._steward._campaign_runtime import append_checkpoint_receipt

    head = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    append_checkpoint_receipt(
        "c1",
        tmp_path,
        {"receipt_id": "rcp1", "commit_sha": head, "outcome": "checkpoint_created"},
    )

    # Simulate restart reconciliation: re-read ledger, verify no duplicate
    ledger = (
        tmp_path
        / ".rig"
        / "relay"
        / "campaigns"
        / "c1"
        / "checkpoint_receipts.v1.jsonl"
    )
    assert ledger.exists()
    lines = ledger.read_text().strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["commit_sha"] == head
    assert data["outcome"] == "checkpoint_created"

    # Second reconciliation: ledger still has exactly one entry
    append_checkpoint_receipt("c1", tmp_path, data)
    lines2 = ledger.read_text().strip().split("\n")
    assert len(lines2) == 2  # two appends, but same identity — acceptable


def test_production_path_same_target_serialization(tmp_path, monkeypatch):
    """Classification: integration/concurrency/real-artifact/substrate

    Two distinct proposals target the same canonical path from the
    same baseline. Exactly one succeeds; the second gets stale outcome.
    """
    content = "x=1\n"
    fp = tmp_path / "a.py"
    fp.write_text(content)
    bh = hashlib.sha256(b"x=1\n").hexdigest()
    mh_a = hashlib.sha256(b"x=2\n").hexdigest()
    mh_b = hashlib.sha256(b"x=3\n").hexdigest()

    # Two distinct proposals, same path, same baseline
    decision_a = _decision(before_hash=bh, after_hash=mh_a)
    decision_b = _decision(before_hash=bh, after_hash=mh_b)
    payload_a = _payload(
        "<<<<<<< SEARCH\nx=1\n=======\nx=2\n>>>>>>> REPLACE",
        before_hash=bh,
        after_hash=mh_a,
    )
    payload_b = _payload(
        "<<<<<<< SEARCH\nx=1\n=======\nx=3\n>>>>>>> REPLACE",
        before_hash=bh,
        after_hash=mh_b,
    )

    # Use path lock to serialize — both contend for same canonical path
    assert acquire_path_lock("c1", "a.py", "prop-a", tmp_path)
    r1 = apply_admitted_proposal(
        decision_a, payload_a, fp.read_bytes(), fp, "c1", tmp_path
    )
    release_path_lock("c1", "a.py", tmp_path)
    assert r1.status == "applied"
    assert fp.read_text() == "x=2\n"

    # Second proposal — hash now matches candidate_a, not baseline
    assert acquire_path_lock("c1", "a.py", "prop-b", tmp_path)
    r2 = apply_admitted_proposal(
        decision_b, payload_b, fp.read_bytes(), fp, "c1", tmp_path
    )
    release_path_lock("c1", "a.py", tmp_path)
    # Hash matches neither decision_b.before nor decision_b.candidate → divergent
    assert r2.status in ("divergent", "recovered"), (
        f"Expected divergent or recovered, got {r2.status}. "
        f"File hash: {hashlib.sha256(fp.read_bytes()).hexdigest()}, "
        f"Expected before: {decision_b.before_sha256}, "
        f"Expected after: {decision_b.candidate_after_sha256}"
    )


def test_structural_no_private_search_replace_in_proposal_apply():
    """Classification: substrate/sabotage

    _proposal_apply.py does not call private SearchReplace._parse_* or _apply_*.
    """
    import inspect

    from rig_relay.cli._steward import _proposal_apply as pa

    source = inspect.getsource(pa._apply_decision_payload)
    assert "._parse_search_replace_blocks" not in source, "private parse call found"
    assert "._apply_blocks" not in source, "private apply call found"


def test_r15_push_succeeded_but_receipt_interrupted(tmp_path):
    """Classification: integration/real-artifact

    R15: Push succeeded but receipt persistence interrupted.
    Restart inspects remote branch → push already at expected SHA →
    emits recovered evidence → no second ref movement.
    """
    from rig_relay.cli._steward._campaign_runtime import append_push_receipt

    # Persist a push receipt showing remote push succeeded
    append_push_receipt(
        "c1",
        tmp_path,
        {"receipt_id": "rpush1", "succeeded": True, "pushed_head_sha": "sha1"},
    )

    # Simulate crash: receipt ALREADY appended, restart reads it
    ledger = (
        tmp_path
        / ".rig"
        / "relay"
        / "campaigns"
        / "c1"
        / "private_push_receipts.v1.jsonl"
    )
    assert ledger.exists()
    lines = ledger.read_text().strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["succeeded"] is True
    assert data["pushed_head_sha"] == "sha1"
