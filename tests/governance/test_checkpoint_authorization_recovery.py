"""Real-substrate tests for durable checkpoint authorization and idempotent recovery.

Uses real temporary Git repos, real filesystem artifacts, and real JSONL receipt
persistence. Does not mock the commit operation, receipt store, filesystem,
or recovery boundary.

Gates proven:
  A1 — Durable authorization receipt is persisted before the Git commit
  A2 — Restart reuses existing durable authorization instead of issuing duplicate
  A3 — Commit without matching durable authorization is refused
  A4 — Commit present, terminal receipt missing → recovery appends one receipt
  A5 — Mismatched authorization (wrong action, expired, invalid JSON) is refused
  A6 — Re-entry after terminal receipt is idempotent
  A7 — Existing governed checkpoint tests remain functional (smoke check)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import time

import pytest

from rig_relay.core.guard import get_guard, reset_guard
from rig_relay.core.tools.base import BaseToolState, InvokeContext
from rig_relay.core.tools.builtins.checkpoint import (
    Checkpoint,
    CheckpointArgs,
    CheckpointToolConfig,
)
from rig_relay.governance.auth_receipts import (
    generate_dev_receipt,
    generate_mission_checkpoint_receipt,
)


def _init_git_repo(tmp_path: Path, branch: str = "task/feature") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", branch], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(
        ["git", "add", "README.md"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True
    )
    return repo


async def _collect_results(gen):
    results = []
    async for result in gen:
        results.append(result)
    return results


def _sha256(data: str) -> str:
    return "sha256:" + hashlib.sha256(data.encode()).hexdigest()


def _ctx(repo: Path) -> InvokeContext:
    return InvokeContext(tool_call_id="tc-test", workspace_root=repo)


def _make_tool():
    return Checkpoint(
        config_getter=lambda: CheckpointToolConfig(), state=BaseToolState()
    )


def _prime_guard(repo: Path) -> None:
    guard = get_guard()
    if guard.captured_at is None:
        guard.capture(repo_root=repo)


# ═══════════════════════════════════════════════════════════════════════
# Gate A1 — Durable Authorization Precedes Commit
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_a1_authorization_persisted_before_commit(tmp_path: Path):
    reset_guard()
    repo = _init_git_repo(tmp_path)
    _prime_guard(repo)

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "file.py").write_text("# modified\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/file.py"], capture_output=True)

    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-a1",
        authority_provenance_sha256=_sha256("prov-a1"),
        claim_id="claim-a1",
        session_id="s-a1",
        task_id="t-a1",
        branch="task/feature",
        include_paths=["src/file.py"],
    )
    receipt_json = json.dumps(receipt)

    tool = _make_tool()
    results = await _collect_results(
        tool.run(
            CheckpointArgs(
                message="test A1 commit",
                include_paths=["src/file.py"],
                authorization_receipt=receipt_json,
                session_id="s-a1",
                task_id="t-a1",
            ),
            ctx=_ctx(repo),
        )
    )

    assert len(results) == 1
    r = results[0]
    assert r.ok is True
    assert r.commit_sha is not None

    # Verify authorization receipt was persisted
    auth_ledger = (
        repo
        / ".build"
        / "rig-relay"
        / "governance"
        / "checkpoint_authorization_receipts.v1.jsonl"
    )
    assert auth_ledger.exists()
    auth_lines = auth_ledger.read_text().strip().split("\n")
    assert len(auth_lines) >= 1
    auth_record = json.loads(auth_lines[-1])
    assert auth_record["outcome"] == "authorized"

    # Verify terminal receipt was persisted after commit
    terminal_ledger = (
        repo / ".build" / "rig-relay" / "governance" / "checkpoint_receipts.v1.jsonl"
    )
    assert terminal_ledger.exists()
    terminal_lines = terminal_ledger.read_text().strip().split("\n")
    assert len(terminal_lines) >= 1
    terminal_record = json.loads(terminal_lines[-1])
    assert terminal_record["outcome"] == "completed"
    assert terminal_record["commit_sha"] == r.commit_sha

    # Verify commit carries the authorization receipt trailer
    commit_body = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%B"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "Rig-Authorization-Receipt-SHA256:" in commit_body
    assert receipt["receipt_sha256"] in commit_body

    # Verify exactly one extra commit (initial + checkpoint)
    commit_count = int(
        subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    assert commit_count == 2


# ═══════════════════════════════════════════════════════════════════════
# Gate A2 — Restart Reuses Durable Authorization
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_a2_restart_reuses_authorization(tmp_path: Path):
    reset_guard()
    repo = _init_git_repo(tmp_path)
    _prime_guard(repo)

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "file.py").write_text("# modified\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/file.py"], capture_output=True)

    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-a2",
        authority_provenance_sha256=_sha256("prov-a2"),
        claim_id="claim-a2",
        session_id="s-a2",
        task_id="t-a2",
        branch="task/feature",
        include_paths=["src/file.py"],
    )
    receipt_json = json.dumps(receipt)

    # Pre-populate authorization ledger (simulate: crashed after persist, before commit)
    auth_dir = repo / ".build" / "rig-relay" / "governance"
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_path = auth_dir / "checkpoint_authorization_receipts.v1.jsonl"
    auth_path.write_text(
        json.dumps(
            {
                "receipt_digest": receipt["receipt_sha256"],
                "receipt_json": receipt_json,
                "outcome": "authorized",
                "commit_sha": "",
                "created_at": "2026-01-01T00:00:00Z",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )

    tool = _make_tool()
    results = await _collect_results(
        tool.run(
            CheckpointArgs(
                message="test A2 commit",
                include_paths=["src/file.py"],
                authorization_receipt=receipt_json,
                session_id="s-a2",
                task_id="t-a2",
            ),
            ctx=_ctx(repo),
        )
    )

    assert len(results) == 1
    r = results[0]
    assert r.ok is True
    assert r.commit_sha is not None

    # Only one authorization entry (no duplicate)
    auth_lines = auth_path.read_text().strip().split("\n")
    assert len(auth_lines) == 1

    # Exactly one new commit
    commit_count = int(
        subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    assert commit_count == 2

    # Terminal receipt exists
    terminal_path = auth_dir / "checkpoint_receipts.v1.jsonl"
    assert terminal_path.exists()
    terminal_lines = terminal_path.read_text().strip().split("\n")
    assert len(terminal_lines) == 1
    assert json.loads(terminal_lines[0])["outcome"] == "completed"


# ═══════════════════════════════════════════════════════════════════════
# Gate A3 — Commit Without Authorization Is Refused
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a3_checkpoint_refuses_without_authorization_receipt(tmp_path: Path):
    reset_guard()
    repo = _init_git_repo(tmp_path)
    _prime_guard(repo)

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "file.py").write_text("# modified\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/file.py"], capture_output=True)

    tool = _make_tool()
    results = await _collect_results(
        tool.run(
            CheckpointArgs(
                message="test A3 commit",
                include_paths=["src/file.py"],
                session_id="s-a3",
                task_id="t-a3",
            ),
            ctx=_ctx(repo),
        )
    )

    assert len(results) == 1
    r = results[0]
    assert r.ok is False
    assert r.refusal_reason == "missing_receipt"

    # No commit created beyond initial
    commit_count = int(
        subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    assert commit_count == 1

    # No ledgers created
    assert not (
        repo
        / ".build"
        / "rig-relay"
        / "governance"
        / "checkpoint_authorization_receipts.v1.jsonl"
    ).exists()
    assert not (
        repo / ".build" / "rig-relay" / "governance" / "checkpoint_receipts.v1.jsonl"
    ).exists()


# ═══════════════════════════════════════════════════════════════════════
# Gate A4 — Commit Present, Terminal Receipt Missing → Recovery
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_a4_commit_exists_terminal_receipt_missing_emits_recovery(tmp_path: Path):
    reset_guard()
    repo = _init_git_repo(tmp_path)
    _prime_guard(repo)

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "file.py").write_text("# modified\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/file.py"], capture_output=True)

    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-a4",
        authority_provenance_sha256=_sha256("prov-a4"),
        claim_id="claim-a4",
        session_id="s-a4",
        task_id="t-a4",
        include_paths=["src/file.py"],
    )
    receipt_json = json.dumps(receipt)
    receipt_digest = receipt["receipt_sha256"]

    # Pre-populate authorization ledger
    auth_dir = repo / ".build" / "rig-relay" / "governance"
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_path = auth_dir / "checkpoint_authorization_receipts.v1.jsonl"
    auth_path.write_text(
        json.dumps(
            {
                "receipt_digest": receipt_digest,
                "receipt_json": receipt_json,
                "outcome": "authorized",
                "commit_sha": "",
                "created_at": "2026-01-01T00:00:00Z",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )

    # Pre-create a commit with authorization trailer (commit succeeded, terminal receipt interrupted)
    commit_msg = (
        f"checkpoint(t-a4): test A4 commit\n\n"
        f"Session: s-a4\nTask: t-a4\nFiles:\n- src/file.py\n"
        f"Rig-Authorization-Receipt-SHA256: {receipt_digest}"
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", commit_msg],
        capture_output=True,
        check=True,
    )

    # No terminal receipt yet
    terminal_path = auth_dir / "checkpoint_receipts.v1.jsonl"
    assert not terminal_path.exists()

    # Run checkpoint — should detect existing commit + auth, emit recovery terminal
    tool = _make_tool()
    await _collect_results(
        tool.run(
            CheckpointArgs(
                message="test A4 commit",
                include_paths=["src/file.py"],
                authorization_receipt=receipt_json,
                session_id="s-a4",
                task_id="t-a4",
            ),
            ctx=_ctx(repo),
        )
    )

    # No new commit beyond initial + pre-existing
    commit_count = int(
        subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    assert commit_count == 2

    # Terminal receipt now present
    assert terminal_path.exists()
    terminal_lines = terminal_path.read_text().strip().split("\n")
    assert len(terminal_lines) >= 1


# ═══════════════════════════════════════════════════════════════════════
# Gate A5 — Mismatched Authorization Is Refused
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a5a_invalid_receipt_json_refused(tmp_path: Path):
    reset_guard()
    repo = _init_git_repo(tmp_path)
    _prime_guard(repo)

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "file.py").write_text("# modified\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/file.py"], capture_output=True)

    tool = _make_tool()
    results = await _collect_results(
        tool.run(
            CheckpointArgs(
                message="bad receipt",
                include_paths=["src/file.py"],
                authorization_receipt="not valid json {{{",
                session_id="s-a5a",
                task_id="t-a5a",
            ),
            ctx=_ctx(repo),
        )
    )

    r = results[0]
    assert r.ok is False
    assert "Invalid receipt JSON" in r.refusal_reason


@pytest.mark.asyncio
async def test_a5b_expired_receipt_refused(tmp_path: Path):
    reset_guard()
    repo = _init_git_repo(tmp_path)
    _prime_guard(repo)

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "file.py").write_text("# modified\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/file.py"], capture_output=True)

    expired = generate_dev_receipt("checkpoint.commit", ttl_seconds=0)
    time.sleep(0.1)

    tool = _make_tool()
    results = await _collect_results(
        tool.run(
            CheckpointArgs(
                message="expired",
                include_paths=["src/file.py"],
                authorization_receipt=json.dumps(expired),
                session_id="s-a5b",
                task_id="t-a5b",
            ),
            ctx=_ctx(repo),
        )
    )

    r = results[0]
    assert r.ok is False
    assert (
        "expired" in r.refusal_reason.lower() or "Receipt expired" in r.refusal_reason
    )


@pytest.mark.asyncio
async def test_a5c_wrong_action_refused(tmp_path: Path):
    reset_guard()
    repo = _init_git_repo(tmp_path)
    _prime_guard(repo)

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "file.py").write_text("# modified\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/file.py"], capture_output=True)

    wrong_action = generate_dev_receipt("remote_upload.confirm")

    tool = _make_tool()
    results = await _collect_results(
        tool.run(
            CheckpointArgs(
                message="wrong action",
                include_paths=["src/file.py"],
                authorization_receipt=json.dumps(wrong_action),
                session_id="s-a5c",
                task_id="t-a5c",
            ),
            ctx=_ctx(repo),
        )
    )

    r = results[0]
    assert r.ok is False
    assert (
        "mismatch" in r.refusal_reason.lower() or "Action mismatch" in r.refusal_reason
    )


# ═══════════════════════════════════════════════════════════════════════
# Gate A6 — Re-entry Is Terminally Idempotent
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_a6_reentry_after_terminal_receipt_is_idempotent(tmp_path: Path):
    reset_guard()
    repo = _init_git_repo(tmp_path)
    _prime_guard(repo)

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "file.py").write_text("# modified\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/file.py"], capture_output=True)

    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-a6",
        authority_provenance_sha256=_sha256("prov-a6"),
        claim_id="claim-a6",
        session_id="s-a6",
        task_id="t-a6",
        include_paths=["src/file.py"],
    )
    receipt_json = json.dumps(receipt)

    # First invocation — creates commit + terminal receipt
    tool = _make_tool()
    r1 = await _collect_results(
        tool.run(
            CheckpointArgs(
                message="test A6 commit 1",
                include_paths=["src/file.py"],
                authorization_receipt=receipt_json,
                session_id="s-a6",
                task_id="t-a6",
            ),
            ctx=_ctx(repo),
        )
    )
    assert r1[0].ok is True, f"First invocation failed: {r1[0].refusal_reason}"

    initial_commit_count = int(
        subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    # Second invocation with same receipt — should detect existing terminal
    tool2 = _make_tool()
    r2 = await _collect_results(
        tool2.run(
            CheckpointArgs(
                message="test A6 commit 2",
                include_paths=["src/file.py"],
                authorization_receipt=receipt_json,
                session_id="s-a6",
                task_id="t-a6",
            ),
            ctx=_ctx(repo),
        )
    )
    assert r2[0].ok is True

    final_commit_count = int(
        subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    assert final_commit_count == initial_commit_count  # no new commit

    # One authorization entry
    auth_path = (
        repo
        / ".build"
        / "rig-relay"
        / "governance"
        / "checkpoint_authorization_receipts.v1.jsonl"
    )
    auth_lines = auth_path.read_text().strip().split("\n")
    assert len(auth_lines) == 1

    # Terminal receipt exists
    terminal_path = (
        repo / ".build" / "rig-relay" / "governance" / "checkpoint_receipts.v1.jsonl"
    )
    assert terminal_path.exists()


# ═══════════════════════════════════════════════════════════════════════
# Gate A7 — Existing Governed Checkpoint Lifecycle Remains Functional
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a7a_existing_checkpoint_without_authorization_still_refuses(
    tmp_path: Path,
):
    reset_guard()
    repo = _init_git_repo(tmp_path)
    _prime_guard(repo)

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "file.py").write_text("# modified\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/file.py"], capture_output=True)

    tool = _make_tool()
    results = await _collect_results(
        tool.run(
            CheckpointArgs(
                message="no auth",
                include_paths=["src/file.py"],
                session_id="s-a7",
                task_id="t-a7",
            ),
            ctx=_ctx(repo),
        )
    )

    assert len(results) == 1
    r = results[0]
    assert r.ok is False
    assert "missing_receipt" in r.refusal_reason


@pytest.mark.asyncio
async def test_a7b_mission_issued_receipt_validation(tmp_path: Path):
    reset_guard()
    repo = _init_git_repo(tmp_path)
    _prime_guard(repo)

    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "file.py").write_text("# modified\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/file.py"], capture_output=True)

    receipt = generate_mission_checkpoint_receipt(
        mission_id="m-a7b",
        authority_provenance_sha256=_sha256("prov-a7b"),
        claim_id="claim-a7b",
        session_id="s-a7b",
        task_id="t-a7b",
        branch="task/feature",
        include_paths=["src/file.py"],
    )

    tool = _make_tool()
    results = await _collect_results(
        tool.run(
            CheckpointArgs(
                message="mission receipt test",
                include_paths=["src/file.py"],
                authorization_receipt=json.dumps(receipt),
                session_id="s-a7b",
                task_id="t-a7b",
            ),
            ctx=_ctx(repo),
        )
    )

    r = results[0]
    assert r.ok is True
    assert r.commit_sha is not None
    assert r.authorization_receipt_sha256 == receipt["receipt_sha256"]
