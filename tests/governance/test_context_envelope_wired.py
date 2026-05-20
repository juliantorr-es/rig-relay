from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.governance.context_envelope_bridge import compile_governed_context


def _init_git_repo(tmp_path: Path) -> Path:
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True
    )
    (tmp_path / "AGENTS.md").write_text("# agent instructions\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# readme\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_governed_context_compiles_valid_packet(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path)
    packet, receipt, issues = compile_governed_context(repo_root=repo)

    assert packet.packet_id
    assert packet.mission_id
    assert packet.title
    assert packet.branch == "main"
    assert packet.head
    assert packet.repo_root
    assert isinstance(receipt.packet_sha256, str)
    assert receipt.packet_sha256.startswith("sha256:")


def test_packet_includes_git_branch_and_head(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path)
    packet, _, _ = compile_governed_context(repo_root=repo)

    assert packet.branch == "main"
    assert packet.head
    assert len(packet.head) >= 7


def test_dirty_file_state_is_captured(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path)
    dirty = repo / "new_file.txt"
    dirty.write_text("unsaved changes\n", encoding="utf-8")

    packet, _, _ = compile_governed_context(repo_root=repo)

    untracked_paths = {s.path for s in packet.dirty_file_states if s.status == "??"}
    assert "new_file.txt" in untracked_paths

    for state in packet.dirty_file_states:
        if state.path == "new_file.txt":
            assert state.after_sha256
            assert state.after_sha256.startswith("sha256:")


def test_missing_instructions_no_blocker(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path)
    (repo / "AGENTS.md").unlink()
    subprocess = __import__("subprocess")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "rm"], cwd=repo, check=True)

    _, _, issues = compile_governed_context(repo_root=repo)

    assert issues


def test_content_light_only_sha256_hashes(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path)
    packet, _, _ = compile_governed_context(repo_root=repo)

    forbidden = {
        "stdout",
        "stderr",
        "content",
        "chunk_text",
        "old_text",
        "new_text",
        "diff",
        "patch",
        "prompt",
        "secret",
        "argv",
    }
    assert forbidden.isdisjoint(packet.model_dump(mode="json"))


def test_bridge_does_not_leak_raw_file_content(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path)
    (repo / "AGENTS.md").write_text("secret-api-key: deadbeef\n", encoding="utf-8")

    packet, _, _ = compile_governed_context(repo_root=repo)

    raw_dump = __import__("json").dumps(packet.model_dump(mode="json"))
    assert "secret-api-key" not in raw_dump
    assert "deadbeef" not in raw_dump


def test_acceptance_checks_are_preserved(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path)
    checks = ["uv run pytest -q", "uv run pyright"]
    packet, _, _ = compile_governed_context(repo_root=repo, acceptance_checks=checks)

    assert packet.acceptance_checks == checks


def test_handoff_required_flag(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path)
    packet, _, _ = compile_governed_context(repo_root=repo, handoff_required=True)

    assert packet.handoff_required is True
