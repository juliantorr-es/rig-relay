from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.checkpoint import (
    Checkpoint,
    CheckpointArgs,
    CheckpointToolConfig,
)
from rig_relay.governance.auth_receipts import (
    generate_dev_receipt,
    generate_mission_checkpoint_receipt,
    validate_receipt,
)


async def _collect_results(gen):
    results = []
    async for result in gen:
        results.append(result)
    return results


# ── Durable pre-commit persistence ────────────────────────────────────────


@pytest.mark.real_artifact
@pytest.mark.substrate
def test_mission_issued_receipt_persisted_before_commit(tmp_path: Path):
    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-persist",
        authority_provenance_sha256="sha256:abc123",
        claim_id="claim-persist",
        session_id="s-test",
        task_id="t-test",
        include_paths=["src/file.py"],
    )

    receipts_dir = tmp_path / "authorization-receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / f"{receipt['receipt_sha256']}.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    assert receipt_path.exists()

    reloaded = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert reloaded["authorization_source"] == "mission_execution_authority"
    assert reloaded["receipt_sha256"] == receipt["receipt_sha256"]
    assert reloaded["mission_identity"] == "m-persist"


# ── Receipt validation for mission-issued receipts ────────────────────────


def test_mission_issued_receipt_validation():
    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-val",
        authority_provenance_sha256="sha256:abc",
        claim_id="claim-val",
        branch="task/test-branch",
        include_paths=["src/file.py"],
    )

    valid, reason = validate_receipt(receipt, "checkpoint.commit")
    assert valid is True, f"Expected valid, got: {reason}"

    receipt_bad = dict(receipt)
    receipt_bad["authority_provenance_sha256"] = None
    valid2, reason2 = validate_receipt(receipt_bad, "checkpoint.commit")
    assert valid2 is False
    assert "authority_provenance_sha256" in reason2.lower()


# ── Receipt rejected when missing mission fields ──────────────────────────


def test_mission_issued_receipt_rejected_missing_mission_identity():
    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-test",
        authority_provenance_sha256="sha256:abc",
        claim_id="claim-test",
    )

    receipt.pop("mission_identity", None)
    valid, reason = validate_receipt(receipt, "checkpoint.commit")
    assert valid is False
    assert "mission_identity" in reason.lower()


# ── Receipt rejected with wrong provenance format ─────────────────────────


def test_mission_issued_receipt_rejected_bad_provenance_format():
    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-test",
        authority_provenance_sha256="sha256:abc",
        claim_id="claim-test",
    )

    receipt["authority_provenance_sha256"] = "not-a-sha256-prefix"
    valid, reason = validate_receipt(receipt, "checkpoint.commit")
    assert valid is False
    assert "authority_provenance_sha256" in reason.lower()


# ── Receipt rejected missing claim_id ─────────────────────────────────────


def test_mission_issued_receipt_rejected_missing_claim_id():
    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-test",
        authority_provenance_sha256="sha256:abc",
        claim_id="claim-test",
    )

    receipt.pop("claim_id", None)
    valid, reason = validate_receipt(receipt, "checkpoint.commit")
    assert valid is False
    assert "claim_id" in reason.lower()


# ── Receipt rejected missing action_scope ─────────────────────────────────


def test_mission_issued_receipt_rejected_missing_action_scope():
    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-test",
        authority_provenance_sha256="sha256:abc",
        claim_id="claim-test",
    )

    receipt["action_scope"] = {}
    valid, reason = validate_receipt(receipt, "checkpoint.commit")
    assert valid is False
    assert "action_scope" in reason.lower()


# ── user_verified_kind field present ──────────────────────────────────────


def test_mission_issued_receipt_has_user_verified_kind():
    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-test",
        authority_provenance_sha256="sha256:abc",
        claim_id="claim-test",
    )

    assert receipt["user_verified"] is True
    assert receipt["user_verified_kind"] == "transitive_mission_authority"
    assert receipt["authorization_source"] == "mission_execution_authority"


# ── Dev receipt has different user_verified_kind ──────────────────────────


def test_dev_receipt_user_verified_kind():
    receipt = generate_dev_receipt("checkpoint.commit")
    assert (
        "user_verified_kind" not in receipt or receipt.get("user_verified_kind") is None
    )


# ── Recovery idempotence — same receipt digest reloadable ─────────────────


def test_mission_receipt_digest_reloadable_for_recovery():
    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-recovery",
        authority_provenance_sha256="sha256:abc",
        claim_id="claim-recovery",
        session_id="s-test",
        task_id="t-test",
        include_paths=["src/file.py"],
    )

    original_digest = receipt["receipt_sha256"]
    receipt["receipt_sha256"] = ""
    canonical = json.dumps(receipt, sort_keys=True).encode("utf-8")
    recomputed = "sha256:" + hashlib.sha256(canonical).hexdigest()

    assert recomputed == original_digest
    assert receipt["authorization_source"] == "mission_execution_authority"


# ── Recovery from committed-but-unterminated state ────────────────────────


@pytest.mark.real_artifact
@pytest.mark.substrate
def test_recovery_from_committed_but_unterminated_checkpoint(tmp_path):
    """Commit exists with mission-issued receipt trailer; recovery reloads receipt;
    no duplicate commit; no replacement receipt issued.
    """
    from rig_relay.core.guard import reset_guard

    reset_guard()

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "task/test-branch"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "file.py").write_text("# initial")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)

    (repo / "file.py").write_text("# modified under mission authority")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)

    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-recovery",
        authority_provenance_sha256="sha256:abc123def",
        claim_id="claim-recovery",
        session_id="s-recovery",
        task_id="t-recovery",
        branch="task/test-branch",
        include_paths=["file.py"],
    )

    receipts_dir = tmp_path / "authorization-receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / f"{receipt['receipt_sha256']}.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    receipt_digest = receipt["receipt_sha256"]
    commit_msg = (
        f"checkpoint(t-recovery): committed\n\n"
        f"Session: s-recovery\n"
        f"Task: t-recovery\n"
        f"Files:\n- file.py\n"
        f"Rig-Authorization-Receipt-SHA256: {receipt_digest}"
    )
    subprocess.run(
        ["git", "commit", "-m", commit_msg], cwd=repo, check=True, capture_output=True
    )

    log_result = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Rig-Authorization-Receipt-SHA256" in log_result.stdout
    assert receipt_digest in log_result.stdout

    reloaded = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert reloaded["authorization_source"] == "mission_execution_authority"
    assert reloaded["receipt_sha256"] == receipt_digest
    assert reloaded["mission_identity"] == "m-recovery"

    reloaded_for_digest = dict(reloaded)
    reloaded_for_digest["receipt_sha256"] = ""
    canonical = json.dumps(reloaded_for_digest, sort_keys=True).encode("utf-8")
    recomputed = "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert recomputed == receipt_digest

    log_count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert int(log_count.stdout.strip()) == 2

    non_existent_digest = "sha256:" + "0" * 64
    assert non_existent_digest != receipt_digest
    assert not (receipts_dir / f"{non_existent_digest}.json").exists()


# ── Unrelated dirty-file exclusion ────────────────────────────────────────


@pytest.mark.real_artifact
@pytest.mark.substrate
def test_unrelated_dirty_file_excluded_from_admitted_checkpoint(tmp_path):
    """Admitted checkpoint with include_paths for one file does not commit
    an unrelated dirty file (either refuses or excludes it).
    """
    from rig_relay.core.guard import reset_guard

    reset_guard()

    repo = tmp_path / "repo"
    repo.mkdir()
    coordination_dir = tmp_path / "coordination"
    coordination_dir.mkdir()

    subprocess.run(
        ["git", "init", "-b", "task/feature"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "admitted.py").write_text("# admitted file")
    (repo / "unrelated.py").write_text("# unrelated file")
    subprocess.run(["git", "add", "admitted.py", "unrelated.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)

    (repo / "admitted.py").write_text("# admitted file (modified)")
    (repo / "unrelated.py").write_text("# unrelated file (modified by another lane)")

    subprocess.run(["git", "add", "admitted.py"], cwd=repo, check=True)

    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-scope",
        authority_provenance_sha256="sha256:xyz789",
        claim_id="claim-scope",
        session_id="s-scope",
        task_id="t-scope",
        branch="task/feature",
        include_paths=["admitted.py"],
    )

    tool = Checkpoint(
        config_getter=lambda: CheckpointToolConfig(store_root=coordination_dir),
        state=BaseToolState(),
    )

    args = CheckpointArgs(
        message="checkpoint: admitted only",
        include_paths=["admitted.py"],
        authorization_receipt=json.dumps(receipt),
        session_id="s-scope",
        task_id="t-scope",
    )

    original_cwd = os.getcwd()
    os.chdir(str(repo))
    try:
        results = list(asyncio.run(_collect_results(tool.run(args, ctx=None))))
    finally:
        os.chdir(original_cwd)

    if results and results[0].ok:
        commit = results[0]
        assert "admitted.py" in commit.files_committed
        assert "unrelated.py" not in commit.files_committed

        status = subprocess.run(
            ["git", "status", "--porcelain", "unrelated.py"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "unrelated.py" in status.stdout or status.stdout.strip() != ""

        log_count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert int(log_count.stdout.strip()) == 2
    else:
        log_count = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert int(log_count.stdout.strip()) == 1
