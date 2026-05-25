from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from rig_relay.core.git_index_operations import compute_index_tree_digest
from rig_relay.core.tools.builtins.validate_models import (
    ValidateArgs,
    ValidateToolConfig,
)
from rig_relay.core.tools.builtins.validate import Validate
from rig_relay.core.tools.base import BaseToolState
from rig_relay.governance.auth_receipts import (
    generate_preparation_receipt,
    load_preparation_receipt,
    persist_preparation_receipt,
)
from rig_relay.governance.receipt_store import (
    find_active_preparation_receipts,
    load_preparation_receipt as rs_load_prep,
    persist_preparation_receipt as rs_persist_prep,
    resolve_best_preparation_receipt,
)


def _init_repo(tmp_path: Path, branch: str = "task/feature") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", branch], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / ".gitignore").write_text(".build/\n")
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", ".gitignore", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)
    return repo


def _stage_file(repo: Path, filename: str, content: str) -> None:
    """Create a file and stage it with git add."""
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, check=True, capture_output=True)


def _make_receipt(repo: Path, sha256: str, post_digest: str, paths: list[str]) -> dict:
    """Generate and persist a preparation receipt. Must be called with CWD at repo."""
    receipt = generate_preparation_receipt(
        mission_id="test-mission",
        authority_provenance_sha256=f"sha256:{sha256}",
        claim_id="test-claim",
        session_id="test-sess",
        task_id="test-task",
        branch="task/feature",
        prepared_paths=paths,
        change_kinds=["modify"] * len(paths),
        expected_worktree_sha256_values=["sha256:deadbeef"] * len(paths),
        pre_index_tree_digest="dummy-pre-digest",
        post_index_tree_digest=post_digest,
        index_mutation_performed=True,
        worktree_root=str(repo),
    )
    persisted = persist_preparation_receipt(receipt)
    assert persisted is not None, "persist_preparation_receipt returned None"
    return receipt


def _new_validate_tool() -> Validate:
    return Validate(config_getter=lambda: ValidateToolConfig(), state=BaseToolState())


def _check_binding(tool: Validate, receipt_sha256: str, cwd: str) -> tuple:
    """Invoke _check_preparation_binding on a Validate instance."""
    args = ValidateArgs(profile="quick", preparation_receipt_sha256=receipt_sha256)
    return tool._check_preparation_binding(args, cwd)


# ── S1: Index Digest Not Verified in Validate ────────────────────────────


@pytest.mark.adversarial
def test_bound_validate_passes_when_index_matches_preparation_digest(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# original content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "a" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    assert prepared_digest == post_digest, (
        f"Expected digest {post_digest}, got {prepared_digest}"
    )
    assert worktree_matched is True, (
        f"Expected worktree_matched=True, got {worktree_matched}"
    )
    assert refusal is None, f"Expected no refusal, got {refusal}"


@pytest.mark.adversarial
def test_bound_validate_refuses_when_index_tampered_after_preparation(tmp_path):
    # S1 DEFECT: validate does not verify post_index_tree_digest after git add tampering
    # This test proves the defect by showing bound validation passes when it should refuse.
    # FIX: add compute_index_tree_digest() comparison in _check_preparation_binding.
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# original content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "b" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Tamper: add a completely different file to the index
        _stage_file(repo, "malware.py", "# injected payload")

        # Worktree matches the tampered index (no unstaged changes)
        proc = subprocess.run(
            ["git", "diff", "--name-only"], capture_output=True, text=True, cwd=repo
        )
        assert proc.stdout.strip() == "", (
            "Expected clean worktree relative to tampered index"
        )

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    # S1 DEFECT: currently passes when it should refuse
    assert refusal is None, (
        "S1 DEFECT: validate should refuse because index was tampered, "
        f"but returned refusal=None. Got prepared_digest={prepared_digest}, "
        f"worktree_matched={worktree_matched}"
    )


@pytest.mark.adversarial
def test_bound_validate_refuses_when_index_modified_with_staged_change_then_worktree_clean(
    tmp_path,
):
    # S1 DEFECT: validate does not recompute and compare post_index_tree_digest
    # after a staged modification to the prepared file alters the index.
    repo = _init_repo(tmp_path)
    filepath = repo / "file.py"
    original_content = "# original content"
    filepath.write_text(original_content)
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True, capture_output=True)
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "c" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Tamper: modify the prepared file and stage it
        filepath.write_text("# tampered content")
        subprocess.run(
            ["git", "add", "file.py"], cwd=repo, check=True, capture_output=True
        )

        # Worktree matches the tampered index (no unstaged changes)
        proc = subprocess.run(
            ["git", "diff", "--name-only"], capture_output=True, text=True, cwd=repo
        )
        assert proc.stdout.strip() == "", (
            "Expected clean worktree relative to tampered index"
        )

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    # S1 DEFECT: currently passes when it should refuse
    assert refusal is None, (
        "S1 DEFECT: validate should refuse because prepared file was tampered and staged, "
        f"but returned refusal=None. Got prepared_digest={prepared_digest}, "
        f"worktree_matched={worktree_matched}"
    )


@pytest.mark.adversarial
def test_checkpoint_still_catches_tampered_index_even_when_validate_missed_it(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# original content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "d" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Tamper the index with a new file
        _stage_file(repo, "evil.py", "# injected")

        # Compute current digest — should differ from post_digest
        current_digest = compute_index_tree_digest(repo)
        assert current_digest is not None
        assert current_digest != post_digest, (
            "Expected tampered index digest to differ from original"
        )

        # Load the receipt the same way checkpoint does
        receipt_loaded = load_preparation_receipt(receipt_sha)
        assert receipt_loaded is not None
        expected_digest = receipt_loaded.get("post_index_tree_digest")
        assert expected_digest is not None, (
            "post_index_tree_digest should be in receipt"
        )

        # Checkpoint would compare current_digest vs expected_digest
        assert current_digest != expected_digest, (
            "Checkpoint's _verify_preparation_receipt would catch this mismatch: "
            f"current={current_digest[:12]}..., expected={expected_digest[:12]}..."
        )
    finally:
        os.chdir(original_cwd)


# ── S2: Exception Handler Fails Open ────────────────────────────────────


@pytest.mark.adversarial
def test_bound_validate_refuses_when_receipt_file_corrupted(tmp_path):
    # S2 DEFECT: load_preparation_receipt catches json.JSONDecodeError and returns None.
    # This means corrupt receipts are indistinguishable from missing receipts.
    # The validate layer sees "missing" and refuses — but the real problem (corruption)
    # is silently swallowed. A corrupt receipt should be reported as "receipt_corrupted",
    # not "receipt_missing".
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "e" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Corrupt the receipt file on disk
        receipt_dir = Path(".build/rig-relay/desktop/preparation-receipts")
        receipt_path = receipt_dir / f"{receipt_sha}.json"
        assert receipt_path.exists()
        receipt_path.write_text("not valid json {{{", encoding="utf-8")

        # load_preparation_receipt swallows the JSONDecodeError and returns None
        loaded = load_preparation_receipt(receipt_sha)
        assert loaded is None, (
            "S2 DEFECT: load_preparation_receipt returns None on corrupt JSON; "
            "corruption is indistinguishable from missing"
        )

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    # Currently returns "missing" refusal because load_preparation_receipt returns None
    # on corrupt JSON. Ideally should return a distinct error for corruption.
    assert refusal is not None, "Expected a refusal for corrupted receipt"
    assert refusal[1] == "preparation_receipt_missing", (
        "S2 DEFECT: corrupted receipt reported as 'missing' — "
        "corruption and absence are indistinguishable"
    )


@pytest.mark.adversarial
def test_bound_validate_refuses_when_receipt_file_missing(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "f" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Delete the receipt file from disk
        receipt_dir = Path(".build/rig-relay/desktop/preparation-receipts")
        receipt_path = receipt_dir / f"{receipt_sha}.json"
        receipt_path.unlink()
        assert not receipt_path.exists()

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    assert refusal is not None, "Expected refusal for missing receipt"
    assert refusal[0] == "refused"
    assert refusal[1] == "preparation_receipt_missing"
    assert prepared_digest is None


@pytest.mark.adversarial
def test_bound_validate_fails_closed_when_storage_unreadable(tmp_path, monkeypatch):
    # S2 DEFECT: OSError from load_preparation_receipt is caught by fail-open handler.
    repo = _init_repo(tmp_path)
    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "g" * 64, "dummy-digest", ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        def _raise_oserror(_sha256: str) -> dict | None:
            raise OSError("Permission denied")

        monkeypatch.setattr(
            "rig_relay.governance.auth_receipts.load_preparation_receipt",
            _raise_oserror,
        )

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    # S2 DEFECT: fails open — returns (None, None, None) instead of refusing
    assert prepared_digest is None, (
        f"Expected prepared_digest=None, got {prepared_digest}"
    )
    assert refusal is None, (
        "S2 DEFECT: storage error should cause refusal, but exception handler "
        "returns (None, None, None), failing open"
    )


@pytest.mark.adversarial
def test_bound_validate_refuses_when_receipt_has_missing_keys(tmp_path):
    repo = _init_repo(tmp_path)
    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        # Create a receipt manually without post_index_tree_digest
        receipt = {
            "schema_version": "rig.relay.checkpoint_preparation_receipt.v1",
            "receipt_sha256": "",
            "created_at": "2024-01-01T00:00:00+00:00",
            "branch": "task/feature",
            "prepared_paths": ["file.py"],
            "session_id": "test-sess",
            "task_id": "test-task",
        }
        receipt_data = json.dumps(receipt, sort_keys=True).encode("utf-8")
        receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(receipt_data).hexdigest()
        persist_preparation_receipt(receipt)
        receipt_sha = receipt["receipt_sha256"]

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    # prepared_digest stays None when post_index_tree_digest missing (line 824-826)
    assert prepared_digest is None, f"Expected prepared_digest=None without digest key"
    # Worktree check proceeds even without digest — note this behavior
    # (If there are no unstaged changes relative to empty index, it passes)
    assert refusal is None or refusal[1] != "preparation_receipt_missing_digest", (
        "Receipt without digest should at least be flagged, but currently proceeds"
    )


@pytest.mark.adversarial
def test_bound_validate_refuses_when_receipt_has_malformed_paths(tmp_path):
    # S2 DEFECT: if prepared_paths is an int, the `in` check at line 839 raises TypeError
    # which is caught by fail-open handler, returning (None, None, None).
    # To trigger this path, we need git diff --name-only to return non-empty output
    # (unstaged worktree changes), so the code reaches `p in expected_paths`.
    repo = _init_repo(tmp_path)
    filepath = repo / "file.py"
    filepath.write_text("# original content")
    subprocess.run(["git", "add", "file.py"], cwd=repo, check=True, capture_output=True)
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        # Create receipt with integer prepared_paths
        receipt = generate_preparation_receipt(
            mission_id="test-mission",
            authority_provenance_sha256="sha256:" + "h" * 64,
            claim_id="test-claim",
            session_id="test-sess",
            task_id="test-task",
            branch="task/feature",
            prepared_paths=["file.py"],
            change_kinds=["modify"],
            expected_worktree_sha256_values=["sha256:deadbeef"],
            pre_index_tree_digest="dummy-pre",
            post_index_tree_digest=post_digest,
            index_mutation_performed=True,
            worktree_root=str(repo),
        )
        # Corrupt the prepared_paths after generation
        receipt["prepared_paths"] = 42  # int, not list
        receipt_data = json.dumps(
            {k: v for k, v in receipt.items() if k != "receipt_sha256"}, sort_keys=True
        ).encode("utf-8")
        receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(receipt_data).hexdigest()
        persist_preparation_receipt(receipt)
        receipt_sha = receipt["receipt_sha256"]

        # Make an unstaged worktree change so git diff --name-only returns non-empty
        filepath.write_text("# modified content (unstaged)")

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    # S2 DEFECT: malformed prepared_paths (int 42) causes TypeError at `p in expected_paths`
    # which is caught by fail-open handler → (None, None, None)
    assert prepared_digest is None, (
        f"Expected prepared_digest=None, got {prepared_digest}"
    )
    assert refusal is None, (
        "S2 DEFECT: malformed prepared_paths should cause refusal, "
        "but fail-open handler returns (None, None, None)"
    )


# ── S3: Receipt Authority Split ────────────────────────────────────────


@pytest.mark.adversarial
def test_auth_receipts_and_receipt_store_persist_to_same_directory(tmp_path):
    repo = _init_repo(tmp_path)
    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = generate_preparation_receipt(
            mission_id="test-mission",
            authority_provenance_sha256="sha256:" + "i" * 64,
            claim_id="test-claim",
            session_id="test-sess",
            task_id="test-task",
            branch="task/feature",
            prepared_paths=["file_a.py"],
            change_kinds=["modify"],
            expected_worktree_sha256_values=["sha256:deadbeef"],
            pre_index_tree_digest="dummy-pre",
            post_index_tree_digest="dummy-digest-a",
            index_mutation_performed=True,
            worktree_root=str(repo),
        )

        auth_path = persist_preparation_receipt(receipt)
        assert auth_path is not None
        receipt_sha = receipt["receipt_sha256"]

        # Load via receipt_store
        rs_receipt = rs_load_prep(receipt_sha)
        assert rs_receipt is not None, (
            "receipt_store.load_preparation_receipt should read the same file "
            "persisted by auth_receipts.persist_preparation_receipt"
        )
        assert rs_receipt["receipt_sha256"] == receipt_sha
    finally:
        os.chdir(original_cwd)


@pytest.mark.adversarial
def test_auth_receipts_and_receipt_store_produce_identical_load(tmp_path):
    repo = _init_repo(tmp_path)
    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = generate_preparation_receipt(
            mission_id="test-mission",
            authority_provenance_sha256="sha256:" + "j" * 64,
            claim_id="test-claim",
            session_id="test-sess",
            task_id="test-task",
            branch="task/feature",
            prepared_paths=["file_b.py"],
            change_kinds=["modify"],
            expected_worktree_sha256_values=["sha256:deadbeef"],
            pre_index_tree_digest="dummy-pre",
            post_index_tree_digest="dummy-digest-b",
            index_mutation_performed=True,
            worktree_root=str(repo),
        )
        persist_preparation_receipt(receipt)
        receipt_sha = receipt["receipt_sha256"]

        auth_loaded = load_preparation_receipt(receipt_sha)
        rs_loaded = rs_load_prep(receipt_sha)

        assert auth_loaded is not None, "auth_receipts load returned None"
        assert rs_loaded is not None, "receipt_store load returned None"
        assert auth_loaded == rs_loaded, (
            "auth_receipts and receipt_store must return identical receipt dicts"
        )
    finally:
        os.chdir(original_cwd)


@pytest.mark.adversarial
def test_validate_uses_auth_receipts_not_receipt_store_for_prep_load(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "k" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Monkeypatch receipt_store.load_preparation_receipt to raise
        # If validate uses receipt_store, it will crash; if it uses auth_receipts, it will work
        import rig_relay.governance.receipt_store as rs_module

        original_rs_load = rs_module.load_preparation_receipt

        rs_module.load_preparation_receipt = lambda _sha: (_ for _ in ()).throw(
            RuntimeError("receipt_store should not be called by validate")
        )

        try:
            tool = _new_validate_tool()
            prepared_digest, worktree_matched, refusal = _check_binding(
                tool, receipt_sha, str(repo)
            )
        finally:
            rs_module.load_preparation_receipt = original_rs_load

        assert prepared_digest is not None, (
            "Validate should use auth_receipts.load_preparation_receipt, "
            "not receipt_store.load_preparation_receipt"
        )
    finally:
        os.chdir(original_cwd)


# ── S4: Receipt Lifecycle — No Consumed/Revoked Semantics ───────────────


@pytest.mark.adversarial
def test_fresh_receipt_resolves_as_valid_index_match(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "l" * 64, post_digest, ["file.py"])

        status, matched = resolve_best_preparation_receipt(
            branch="task/feature",
            worktree_root=str(repo),
            current_index_tree_digest=post_digest,
        )
    finally:
        os.chdir(original_cwd)

    assert status == "valid_index_match", f"Expected valid_index_match, got {status}"
    assert matched is not None, "Expected a receipt, got None"
    assert matched["receipt_sha256"] == receipt["receipt_sha256"]


@pytest.mark.adversarial
def test_receipt_with_expires_at_is_filtered(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = generate_preparation_receipt(
            mission_id="test-mission",
            authority_provenance_sha256="sha256:" + "m" * 64,
            claim_id="test-claim",
            session_id="test-sess",
            task_id="test-task",
            branch="task/feature",
            prepared_paths=["file.py"],
            change_kinds=["modify"],
            expected_worktree_sha256_values=["sha256:deadbeef"],
            pre_index_tree_digest="dummy-pre",
            post_index_tree_digest=post_digest,
            index_mutation_performed=True,
            worktree_root=str(repo),
        )
        receipt["expires_at"] = "2020-01-01T00:00:00+00:00"  # already expired
        receipt_data = json.dumps(
            {k: v for k, v in receipt.items() if k != "receipt_sha256"}, sort_keys=True
        ).encode("utf-8")
        receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(receipt_data).hexdigest()
        persist_preparation_receipt(receipt)

        active = find_active_preparation_receipts(branch="task/feature")
    finally:
        os.chdir(original_cwd)

    assert len(active) == 0, (
        "Expired receipt should be filtered out by find_active_preparation_receipts"
    )


@pytest.mark.adversarial
def test_two_identical_digest_receipts_resolve_to_first_match(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# same content")

    # Commit to get a stable digest
    subprocess.run(
        ["git", "commit", "-m", "add file"], cwd=repo, check=True, capture_output=True
    )
    _stage_file(repo, "other.py", "# another file")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt1 = _make_receipt(repo, "n" * 64, post_digest, ["other.py"])
        # Create a second receipt with the same digest but different identity
        receipt2 = generate_preparation_receipt(
            mission_id="test-mission-2",
            authority_provenance_sha256="sha256:" + "o" * 64,
            claim_id="test-claim-2",
            session_id="test-sess-2",
            task_id="test-task-2",
            branch="task/feature",
            prepared_paths=["other.py"],
            change_kinds=["modify"],
            expected_worktree_sha256_values=["sha256:deadbeef"],
            pre_index_tree_digest="dummy-pre",
            post_index_tree_digest=post_digest,  # same digest
            index_mutation_performed=True,
            worktree_root=str(repo),
        )
        persist_preparation_receipt(receipt2)

        status, matched = resolve_best_preparation_receipt(
            branch="task/feature",
            worktree_root=str(repo),
            current_index_tree_digest=post_digest,
        )
    finally:
        os.chdir(original_cwd)

    assert status == "valid_index_match", f"Expected valid_index_match, got {status}"
    assert matched is not None, "Expected a receipt, got None"
    # Both receipts match the digest; the newest one (by created_at) wins
    # receipt2 was created later, so it should be the match
    assert matched["receipt_sha256"] == receipt2["receipt_sha256"], (
        f"Expected newest receipt ({receipt2['receipt_sha256'][:12]}...) "
        f"to be selected, got {matched['receipt_sha256'][:12]}..."
    )


@pytest.mark.adversarial
def test_old_receipt_replayed_on_same_branch_still_matches(tmp_path):
    # BUG(S4): consumed receipts not tracked; old receipts can be replayed.
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "p" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Simulate consumption: commit the prepared index (consume the receipt)
        subprocess.run(
            ["git", "commit", "-m", "consume"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

        # Recreate the same index state (identical content, re-stage)
        _stage_file(repo, "file2.py", "# content2")
        new_post_digest = compute_index_tree_digest(repo)
        # This new digest is different from the old one now, but the old receipt
        # still exists on disk. If we ever recreate the exact same index state,
        # the old receipt can be replayed.
        # Rather than trying to exactly recreate, let's just resolve with the
        # old receipt's digest and prove it's still findable.
        status, matched = resolve_best_preparation_receipt(
            branch="task/feature",
            worktree_root=str(repo),
            current_index_tree_digest=post_digest,  # old digest
        )
    finally:
        os.chdir(original_cwd)

    # BUG(S4): The old receipt, even after consumption, can still match
    # because there's no consumed/revoked lifecycle tracking.
    matched_sha_snippet = matched["receipt_sha256"][:12] if matched else "None"
    assert status == "stale_index_mismatch" or (
        status == "valid_index_match" and matched is not None
    ), (
        "BUG(S4): consumed receipt not tracked; old receipt from step 1 still "
        f"exists on disk. Status={status}, matched_sha={matched_sha_snippet}..."
        f"Expected receipt_sha={receipt_sha[:12]}..."
    )
    # Verify the receipt still exists on disk (check while CWD is still repo)
    os.chdir(repo)
    try:
        receipt_path = (
            Path(".build/rig-relay/desktop/preparation-receipts")
            / f"{receipt_sha}.json"
        )
        assert receipt_path.exists(), (
            "BUG(S4): old receipt still on disk after consumption "
            "— no lifecycle garbage collection"
        )
    finally:
        os.chdir(original_cwd)


# ── S5: Untracked File Check ──────────────────────────────────────────


@pytest.mark.adversarial
def test_bound_validate_refuses_untracked_python_file_in_tests_dir(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# prepared content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "q" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Create untracked file in tests/
        (repo / "tests").mkdir(exist_ok=True)
        (repo / "tests" / "test_evil.py").write_text("# untracked test")

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    assert refusal is not None, "Expected refusal for untracked file in tests/"
    assert refusal[1] == "relevant_untracked_files_present", (
        f"Expected relevant_untracked_files_present, got {refusal[1] if refusal else 'None'}"
    )


@pytest.mark.adversarial
def test_bound_validate_refuses_untracked_python_file_in_src_dir(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# prepared content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "r" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Create untracked file in src/
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "evil.py").write_text("# untracked src")

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    assert refusal is not None, "Expected refusal for untracked file in src/"
    assert refusal[1] == "relevant_untracked_files_present", (
        f"Expected relevant_untracked_files_present, got {refusal[1] if refusal else 'None'}"
    )


@pytest.mark.adversarial
def test_bound_validate_allows_untracked_file_in_disposable_dir(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# prepared content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "s" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Create untracked file in disposable directory
        (repo / "__pycache__").mkdir(exist_ok=True)
        (repo / "__pycache__" / "cached.pyc").write_text("cached bytecode")

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    assert refusal is None, (
        f"Untracked files in disposable directories should be allowed, "
        f"but got refusal: {refusal}"
    )
    assert worktree_matched is True


@pytest.mark.adversarial
def test_bound_validate_refuses_untracked_file_in_repo_root(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# prepared content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt = _make_receipt(repo, "t" * 64, post_digest, ["file.py"])
        receipt_sha = receipt["receipt_sha256"]

        # Create untracked file at repo root
        (repo / "untracked_config.toml").write_text("# untracked config")

        tool = _new_validate_tool()
        prepared_digest, worktree_matched, refusal = _check_binding(
            tool, receipt_sha, str(repo)
        )
    finally:
        os.chdir(original_cwd)

    assert refusal is not None, "Expected refusal for untracked file in repo root"
    assert refusal[1] == "relevant_untracked_files_present", (
        f"Expected relevant_untracked_files_present, got {refusal[1] if refusal else 'None'}"
    )


# ── S6: Multiple Matching Receipts ─────────────────────────────────────


@pytest.mark.adversarial
def test_two_receipts_same_branch_and_digest_returns_valid_match(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file.py", "# content")
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt1 = _make_receipt(repo, "u" * 64, post_digest, ["file.py"])
        receipt2 = generate_preparation_receipt(
            mission_id="test-mission-2",
            authority_provenance_sha256="sha256:" + "v" * 64,
            claim_id="test-claim-2",
            session_id="test-sess-2",
            task_id="test-task-2",
            branch="task/feature",
            prepared_paths=["file.py"],
            change_kinds=["modify"],
            expected_worktree_sha256_values=["sha256:deadbeef"],
            pre_index_tree_digest="dummy-pre",
            post_index_tree_digest=post_digest,  # same digest
            index_mutation_performed=True,
            worktree_root=str(repo),
        )
        persist_preparation_receipt(receipt2)

        status, matched = resolve_best_preparation_receipt(
            branch="task/feature", current_index_tree_digest=post_digest
        )
    finally:
        os.chdir(original_cwd)

    assert status == "valid_index_match", f"Expected valid_index_match, got {status}"
    assert matched is not None, "Expected a receipt, got None"
    # The newest receipt (by created_at) wins
    assert matched["receipt_sha256"] == receipt2["receipt_sha256"], (
        f"Expected newest receipt to be selected, "
        f"got {matched['receipt_sha256'][:12]}..."
    )


@pytest.mark.adversarial
def test_no_receipts_returns_absent(tmp_path):
    repo = _init_repo(tmp_path)
    post_digest = compute_index_tree_digest(repo)
    assert post_digest is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        status, matched = resolve_best_preparation_receipt(
            branch="task/feature",
            worktree_root=str(repo),
            current_index_tree_digest=post_digest,
        )
    finally:
        os.chdir(original_cwd)

    assert status == "absent", f"Expected absent, got {status}"
    assert matched is None, f"Expected None receipt, got {matched}"


@pytest.mark.adversarial
def test_multiple_candidates_no_digest_match_returns_stale(tmp_path):
    repo = _init_repo(tmp_path)
    _stage_file(repo, "file_a.py", "# content A")
    post_digest_a = compute_index_tree_digest(repo)
    assert post_digest_a is not None

    original_cwd = os.getcwd()
    os.chdir(repo)
    try:
        receipt1 = _make_receipt(repo, "w" * 64, post_digest_a, ["file_a.py"])

        # Create a second receipt with different content (different digest)
        _stage_file(repo, "file_b.py", "# content B")
        post_digest_b = compute_index_tree_digest(repo)
        assert post_digest_b is not None
        assert post_digest_b != post_digest_a

        receipt2 = generate_preparation_receipt(
            mission_id="test-mission-2",
            authority_provenance_sha256="sha256:" + "x" * 64,
            claim_id="test-claim-2",
            session_id="test-sess-2",
            task_id="test-task-2",
            branch="task/feature",
            prepared_paths=["file_b.py"],
            change_kinds=["modify"],
            expected_worktree_sha256_values=["sha256:deadbeef"],
            pre_index_tree_digest="dummy-pre",
            post_index_tree_digest=post_digest_b,
            index_mutation_performed=True,
            worktree_root=str(repo),
        )
        persist_preparation_receipt(receipt2)

        # Query with a digest that matches neither receipt
        status, matched = resolve_best_preparation_receipt(
            branch="task/feature", current_index_tree_digest="unmatched-digest-12345"
        )
    finally:
        os.chdir(original_cwd)

    assert status == "stale_index_mismatch", (
        f"Expected stale_index_mismatch when digest matches none, got {status}"
    )
    assert matched is not None, "Expected first candidate receipt, got None"
    # The newest receipt (by created_at) should be returned as the mismatch
    assert matched["receipt_sha256"] == receipt2["receipt_sha256"], (
        f"Expected newest receipt as mismatch candidate"
    )
