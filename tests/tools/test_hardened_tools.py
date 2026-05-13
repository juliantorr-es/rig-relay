from __future__ import annotations

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, ToolError, ToolPermission
from vibe.core.tools.builtins.bash import Bash, BashArgs, BashToolConfig
from vibe.core.tools.builtins.search_replace import (
    SearchReplace,
    SearchReplaceArgs,
    SearchReplaceConfig,
)
from vibe.core.tools.builtins.write_file import (
    WriteFile,
    WriteFileArgs,
    WriteFileConfig,
)
from vibe.core.tools.permissions import PermissionContext


@pytest.fixture
def bash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = BashToolConfig()
    return Bash(config_getter=lambda: config, state=BaseToolState())


def test_bash_allowlist_no_longer_silently_allows_git_status_diff_log(bash):
    # git status used to be in _get_default_allowlist()
    # Now it should require ASK permission (resolve_permission returns None)

    status_perm = bash.resolve_permission(BashArgs(command="git status"))
    # None means fall through to config.permission (ASK)
    assert status_perm is None or status_perm.permission == ToolPermission.ASK

    diff_perm = bash.resolve_permission(BashArgs(command="git diff"))
    assert diff_perm is None or diff_perm.permission == ToolPermission.ASK

    log_perm = bash.resolve_permission(BashArgs(command="git log"))
    assert log_perm is None or log_perm.permission == ToolPermission.ASK


def test_bash_blocks_dangerous_commands(bash):
    dangerous = [
        "git reset",
        "git reset --hard HEAD",
        "git clean",
        "git clean -fd",
        "git restore",
        "git checkout",
        "git checkout main",
        "git stash",
        "git rebase",
        "git merge",
        "git push --force",
        "git push --force-with-lease",
        "rm -rf /",
        "rm -fr .",
        "rm -rf subdir",
    ]
    for cmd in dangerous:
        perm = bash.resolve_permission(BashArgs(command=cmd))
        assert isinstance(perm, PermissionContext)
        assert perm.permission == ToolPermission.NEVER, f"Failed to block {cmd}"


def test_bash_malformed_command_does_not_crash(bash):
    # Test with characters that might confuse parsers
    malformed = [
        "git status; ) ( ; rm -rf",
        'echo "unclosed quote',
        "$(cat /etc/passwd)",
        "`rm -rf /`",
        "| | |",
    ]
    for cmd in malformed:
        # Should not raise exception
        bash.resolve_permission(BashArgs(command=cmd))


@pytest.mark.asyncio
async def test_write_file_rejects_outside_workdir_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    outside_path = str(tmp_path.parent / "escape.txt")
    with pytest.raises(ToolError, match="outside the project directory"):
        await collect_result(tool.run(WriteFileArgs(path=outside_path, content="test")))


@pytest.mark.asyncio
async def test_write_file_rejects_directory_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    dir_path = tmp_path / "subdir"
    dir_path.mkdir()

    with pytest.raises(ToolError, match="Path is a directory"):
        await collect_result(tool.run(WriteFileArgs(path="subdir", content="test")))


@pytest.mark.asyncio
async def test_search_replace_rejects_outside_workdir_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    outside_path = str(tmp_path.parent / "escape.txt")
    with pytest.raises(ToolError, match="outside the project directory"):
        await collect_result(
            tool.run(SearchReplaceArgs(file_path=outside_path, content="test"))
        )


@pytest.mark.asyncio
async def test_search_replace_does_not_write_when_block_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "file.txt"
    target.write_text("Hello World", encoding="utf-8")

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    content = "<<<<<<< SEARCH\nNon-existent\n=======\nNew\n>>>>>>> REPLACE"

    with pytest.raises(ToolError, match="SEARCH/REPLACE blocks failed"):
        await collect_result(
            tool.run(SearchReplaceArgs(file_path="file.txt", content=content))
        )

    # Verify file content is unchanged
    assert target.read_text(encoding="utf-8") == "Hello World"


# ── write_file mutation evidence ──────────────────────────────────────


@pytest.mark.asyncio
async def test_write_file_new_file_hashes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(WriteFileArgs(path="new.txt", content="hello"))
    )

    assert result.before_sha256 is None
    assert result.after_sha256.startswith("sha256:")
    assert len(result.after_sha256) == 64 + len("sha256:")  # sha256: + 64 hex chars
    assert result.created_file is True
    assert result.overwrote_existing_file is False
    assert result.bytes_written == 5
    assert result.file_existed is False


@pytest.mark.asyncio
async def test_write_file_overwrite_hashes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "existing.txt"
    target.write_text("old content", encoding="utf-8")

    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(
            WriteFileArgs(path="existing.txt", content="new content", overwrite=True)
        )
    )

    assert result.before_sha256 is not None
    assert result.before_sha256.startswith("sha256:")
    assert result.after_sha256.startswith("sha256:")
    assert result.before_sha256 != result.after_sha256
    assert result.created_file is False
    assert result.overwrote_existing_file is True
    assert result.file_existed is True


@pytest.mark.asyncio
async def test_write_file_same_content_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = "same stuff"
    target = tmp_path / "same.txt"
    target.write_text(content, encoding="utf-8")

    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(
            WriteFileArgs(path="same.txt", content=content, overwrite=True)
        )
    )

    assert result.before_sha256 == result.after_sha256
    assert result.overwrote_existing_file is True


@pytest.mark.asyncio
async def test_write_file_overwrite_false_on_existing_does_not_emit_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "protected.txt"
    target.write_text("do not touch", encoding="utf-8")

    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    with pytest.raises(ToolError, match="exists"):
        await collect_result(
            tool.run(WriteFileArgs(path="protected.txt", content="overwrite attempt"))
        )

    assert target.read_text(encoding="utf-8") == "do not touch"


@pytest.mark.asyncio
async def test_write_file_parent_dirs_created_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = WriteFileConfig(create_parent_dirs=True)
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(WriteFileArgs(path="a/b/c/file.txt", content="nested"))
    )

    assert result.parent_dirs_created is True
    assert result.created_file is True
    assert result.after_sha256.startswith("sha256:")

    # Second write to same path should not re-create dirs
    result2 = await collect_result(
        tool.run(
            WriteFileArgs(path="a/b/c/file.txt", content="replaced", overwrite=True)
        )
    )
    assert result2.parent_dirs_created is False


@pytest.mark.asyncio
async def test_write_file_result_serializes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(WriteFileArgs(path="out.json", content='{"k":1}'))
    )

    dump = result.model_dump()
    assert "before_sha256" in dump
    assert "after_sha256" in dump
    assert "created_file" in dump
    assert "overwrote_existing_file" in dump
    assert "parent_dirs_created" in dump
    assert dump["created_file"] is True
    assert dump["after_sha256"].startswith("sha256:")


# ── search_replace mutation evidence ──────────────────────────────────


@pytest.mark.asyncio
async def test_search_replace_successful_records_hashes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "code.py"
    target.write_text("x = 1\ny = 2\n", encoding="utf-8")

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    content = "<<<<<<< SEARCH\nx = 1\n=======\nx = 99\n
