from __future__ import annotations

import hashlib
import json

import pytest

from rig_relay.core.tools.base import (
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from rig_relay.core.tools.builtins.bash import Bash, BashArgs, BashToolConfig
from rig_relay.core.tools.builtins.search_replace import (
    SearchReplace,
    SearchReplaceArgs,
    SearchReplaceConfig,
)
from rig_relay.core.tools.builtins.write_file import (
    WriteFile,
    WriteFileArgs,
    WriteFileConfig,
)
from rig_relay.core.tools.permissions import PermissionContext
from tests.mock.utils import collect_result


@pytest.fixture
def bash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = BashToolConfig()
    return Bash(config_getter=lambda: config, state=BaseToolState())


def test_bash_allowlist_no_longer_silently_allows_git_status_diff_log(bash):
    status_perm = bash.resolve_permission(BashArgs(command="git status"))
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
    malformed = [
        "git status; ) ( ; rm -rf",
        'echo "unclosed quote',
        "$(cat /etc/passwd)",
        "`rm -rf /`",
        "| | |",
    ]
    for cmd in malformed:
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

    result = await collect_result(
        tool.run(WriteFileArgs(path="subdir", content="test"))
    )

    assert result.status == "refused"
    assert result.error_kind == "path_is_directory"
    assert result.after_sha256 == ""
    assert "directory" in result.refusal_reason.lower()


@pytest.mark.asyncio
async def test_search_replace_rejects_outside_workdir_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    outside_path = str(tmp_path.parent / "escape.txt")
    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path=outside_path, content="test"))
    )
    assert result.status == "refused"
    assert result.error_kind == "unsafe_path"
    assert result.before_bytes == 0
    assert result.after_bytes == 0


@pytest.mark.asyncio
async def test_search_replace_rejects_file_not_found(tmp_path, monkeypatch):
    """SearchReplace with non-existent file returns structured refused/file_not_found."""
    monkeypatch.chdir(tmp_path)
    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(
            SearchReplaceArgs(
                file_path="nonexistent.py",
                content="<<<<<<< SEARCH\nfoo\n=======\nbar\n>>>>>>> REPLACE",
            )
        )
    )
    assert result.status == "refused"
    assert result.error_kind == "file_not_found"
    assert result.before_bytes == 0
    assert result.after_bytes == 0


@pytest.mark.asyncio
async def test_search_replace_rejects_directory_path(tmp_path, monkeypatch):
    """SearchReplace with directory path returns structured refused/path_is_directory."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mydir").mkdir()
    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(
            SearchReplaceArgs(
                file_path="mydir",
                content="<<<<<<< SEARCH\nfoo\n=======\nbar\n>>>>>>> REPLACE",
            )
        )
    )
    assert result.status == "refused"
    assert result.error_kind == "path_is_directory"
    assert result.before_bytes == 0
    assert result.after_bytes == 0


@pytest.mark.asyncio
async def test_search_replace_rejects_binary_file(tmp_path, monkeypatch):
    """SearchReplace with binary file returns structured refused/binary_file with before_bytes."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "binary.bin"
    target.write_bytes(b"\x00\x01\x02")
    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(
            SearchReplaceArgs(
                file_path="binary.bin",
                content="<<<<<<< SEARCH\nfoo\n=======\nbar\n>>>>>>> REPLACE",
            )
        )
    )
    assert result.status == "refused"
    assert result.error_kind == "binary_file"
    assert result.before_bytes == 3  # len(b"\x00\x01\x02")
    assert result.after_bytes == 0


@pytest.mark.asyncio
async def test_search_replace_rejects_empty_content(tmp_path, monkeypatch):
    """SearchReplace with empty content returns structured refused/empty_content."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")
    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path="file.py", content=""))
    )
    assert result.status == "refused"
    assert result.error_kind == "empty_content"
    assert result.before_bytes == 0
    assert result.after_bytes == 0


@pytest.mark.asyncio
async def test_search_replace_rejects_content_too_large(tmp_path, monkeypatch):
    """SearchReplace with oversized content returns structured refused/content_too_large."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")
    config = SearchReplaceConfig(max_content_size=10)
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path="file.py", content="x" * 20))
    )
    assert result.status == "refused"
    assert result.error_kind == "content_too_large"
    assert result.before_bytes == 0
    assert result.after_bytes == 0


@pytest.mark.asyncio
async def test_search_replace_rejects_no_valid_blocks(tmp_path, monkeypatch):
    """SearchReplace with no SEARCH/REPLACE blocks returns structured refused/parse_error with before_bytes."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "file.py"
    target.write_text("x = 1\n", encoding="utf-8")
    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path="file.py", content="just some text"))
    )
    assert result.status == "refused"
    assert result.error_kind == "parse_error"
    assert result.before_bytes == 6  # len("x = 1\n")
    assert result.after_bytes == 0


@pytest.mark.asyncio
async def test_search_replace_does_not_write_when_block_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "file.txt"
    target.write_text("Hello World", encoding="utf-8")

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    content = "<<<<<<< SEARCH\nNon-existent\n=======\nNew\n>>>>>>> REPLACE"

    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path="file.txt", content=content))
    )

    assert result.status == "no_match"
    assert result.error_kind == "old_text_not_found"
    assert result.refusal_reason is not None
    assert "SEARCH/REPLACE blocks failed" in result.refusal_reason
    assert result.failed_block_count == 1
    assert result.blocks_applied == 0
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
    assert len(result.after_sha256) == 64 + len("sha256:")
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
        tool.run(WriteFileArgs(path="same.txt", content=content, overwrite=True))
    )

    assert result.before_sha256 == result.after_sha256
    assert result.overwrote_existing_file is True


@pytest.mark.asyncio
async def test_write_file_overwrite_false_on_existing_does_not_emit_hash(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "protected.txt"
    target.write_text("do not touch", encoding="utf-8")

    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(WriteFileArgs(path="protected.txt", content="overwrite attempt"))
    )

    assert result.status == "refused"
    assert result.error_kind == "overwrite_required"
    assert result.file_existed is True
    assert result.after_sha256 == ""
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


@pytest.mark.asyncio
async def test_write_file_emits_coordination_events(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session_dir = tmp_path / "session"
    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    await collect_result(
        tool.run(
            WriteFileArgs(path="coord.txt", content="hello"),
            InvokeContext(tool_call_id="tool-call", session_dir=session_dir),
        )
    )

    events_path = tmp_path / ".build" / "rig-relay" / "coordination" / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [event["event_name"] for event in events] == [
        "coord.task.claimed",
        "coord.path.reserved",
        "coord.artifact.published",
        "coord.path.released",
    ]
    assert events[0]["payload"]["event_kind"] == "task_claimed"
    assert events[2]["payload"]["artifact_kind"] == "write_file"


# ── search_replace mutation evidence ──────────────────────────────────


def _sr_block(search, replace):
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


@pytest.mark.asyncio
async def test_search_replace_successful_records_hashes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "code.py"
    target.write_text("x = 1\ny = 2\n", encoding="utf-8")

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    content = _sr_block("x = 1", "x = 99")
    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path="code.py", content=content))
    )

    assert "code.py" in result.before_file_sha256
    assert "code.py" in result.after_file_sha256
    assert result.before_file_sha256["code.py"].startswith("sha256:")
    assert result.after_file_sha256["code.py"].startswith("sha256:")
    assert result.before_file_sha256["code.py"] != result.after_file_sha256["code.py"]
    assert result.blocks_applied == 1
    assert result.total_block_count == 1
    assert result.failed_block_count == 0
    assert result.changed_files == ["code.py"]


@pytest.mark.asyncio
async def test_search_replace_noop_records_block_counts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "code.py"
    target.write_text("x = 1\ny = 2\n", encoding="utf-8")

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    content = _sr_block("x = 1", "x = 1")
    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path="code.py", content=content))
    )

    assert result.before_file_sha256["code.py"] == result.after_file_sha256["code.py"]
    assert result.blocks_applied == 1
    assert result.total_block_count == 1
    assert result.failed_block_count == 0
    assert result.changed_files == []
    assert result.lines_changed == 0


@pytest.mark.asyncio
async def test_search_replace_failed_does_not_emit_success_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "code.py"
    target.write_text("x = 1\n", encoding="utf-8")

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    content = _sr_block("non-existent", "replacement")
    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path="code.py", content=content))
    )

    assert result.status == "no_match"
    assert result.error_kind == "old_text_not_found"
    assert result.failed_block_count == 1
    assert result.blocks_applied == 0
    assert target.read_text(encoding="utf-8") == "x = 1\n"


@pytest.mark.asyncio
async def test_search_replace_block_counts_on_partial(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "code.py"
    target.write_text("aaa\nbbb\nccc\n", encoding="utf-8")

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    content = _sr_block("aaa", "AAA") + "\n" + _sr_block("zzz", "ZZZ")
    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path="code.py", content=content))
    )

    assert result.status == "no_match"
    assert result.error_kind == "old_text_not_found"
    assert result.blocks_applied == 1
    assert result.failed_block_count == 1
    assert result.total_block_count == 2
    assert target.read_text(encoding="utf-8") == "aaa\nbbb\nccc\n"


@pytest.mark.asyncio
async def test_search_replace_dict_keys_relative(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "src/code.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    content = _sr_block("x = 1", "x = 2")
    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path="src/code.py", content=content))
    )

    assert "src/code.py" in result.before_file_sha256
    assert result.changed_files == ["src/code.py"]


@pytest.mark.asyncio
async def test_search_replace_result_serializes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "code.py"
    target.write_text("x = 1\n", encoding="utf-8")

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    content = _sr_block("x = 1", "x = 2")
    result = await collect_result(
        tool.run(SearchReplaceArgs(file_path="code.py", content=content))
    )

    dump = result.model_dump()
    assert "before_file_sha256" in dump
    assert "after_file_sha256" in dump
    assert "changed_files" in dump
    assert "failed_block_count" in dump
    assert "total_block_count" in dump
    assert isinstance(dump["before_file_sha256"], dict)
    assert dump["total_block_count"] == 1


@pytest.mark.asyncio
async def test_search_replace_emits_coordination_events(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session_dir = tmp_path / "session"
    target = tmp_path / "code.py"
    target.write_text("x = 1\n", encoding="utf-8")

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())

    content = _sr_block("x = 1", "x = 2")
    await collect_result(
        tool.run(
            SearchReplaceArgs(file_path="code.py", content=content),
            InvokeContext(tool_call_id="tool-call", session_dir=session_dir),
        )
    )

    events_path = tmp_path / ".build" / "rig-relay" / "coordination" / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [event["event_name"] for event in events] == [
        "coord.task.claimed",
        "coord.path.reserved",
        "coord.artifact.published",
        "coord.path.released",
    ]
    assert events[2]["payload"]["artifact_kind"] == "search_replace"


# ── Coordination structured blocking (Stage: guard-availability) ───────


@pytest.mark.asyncio
async def test_write_file_blocked_by_active_lease_returns_structured(
    tmp_path, monkeypatch
):
    """WriteFile blocked by active coordination lease returns status='blocked' with error_kind='path_reserved'."""
    monkeypatch.chdir(tmp_path)

    # Create a persistent reservation via CoordinationStore (never released)
    # Use resolved absolute path to match what normalize_tool_path produces
    from rig_relay.coordination.store import CoordinationStore

    abs_path = str((tmp_path / "blocked.txt").resolve())
    store = CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")
    store.claim_task(
        session_id="session_persistent",
        task_id="task_persistent",
        claim_kind="write_file",
        ttl_seconds=600,
        scope={"allowed_paths": [abs_path]},
    )
    store.reserve_paths(
        session_id="session_persistent",
        task_id="task_persistent",
        mode="write",
        paths=[abs_path],
        ttl_seconds=600,
    )

    # Try to write to the reserved path with a different session
    session_dir_beta = tmp_path / "session_beta"
    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())
    result = await collect_result(
        tool.run(
            WriteFileArgs(path="blocked.txt", content="second", overwrite=True),
            InvokeContext(tool_call_id="call-second", session_dir=session_dir_beta),
        )
    )

    assert result.status == "blocked"
    assert result.error_kind == "path_reserved"
    assert (
        result.refusal_reason is not None
        and "reservation refused" in result.refusal_reason
    )
    assert result.bytes_written == 0
    assert result.after_sha256 == ""


@pytest.mark.asyncio
async def test_search_replace_blocked_by_active_lease_returns_structured(
    tmp_path, monkeypatch
):
    """SearchReplace blocked by active coordination lease returns status='blocked' with error_kind='path_reserved'."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "code.py"
    target.write_text("x = 1\ny = 2\n", encoding="utf-8")

    # Create a persistent reservation via CoordinationStore (never released)
    from rig_relay.coordination.store import CoordinationStore

    abs_path = str((tmp_path / "code.py").resolve())
    store = CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")
    store.claim_task(
        session_id="session_persistent",
        task_id="task_persistent_sr",
        claim_kind="search_replace",
        ttl_seconds=600,
        scope={"allowed_paths": [abs_path]},
    )
    store.reserve_paths(
        session_id="session_persistent",
        task_id="task_persistent_sr",
        mode="write",
        paths=[abs_path],
        ttl_seconds=600,
    )
    # Try search_replace on the reserved path with a different session
    session_dir_beta = tmp_path / "session_beta"
    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())
    block_content = _sr_block("x = 1", "x = 99")
    # Second session tries search_replace on same path
    session_dir_beta = tmp_path / "session_beta"
    block_content = _sr_block("x = 1", "x = 99")
    result = await collect_result(
        tool.run(
            SearchReplaceArgs(file_path="code.py", content=block_content),
            InvokeContext(tool_call_id="call-second", session_dir=session_dir_beta),
        )
    )

    assert result.status == "blocked"
    assert result.error_kind == "path_reserved"
    assert (
        result.refusal_reason is not None
        and "reservation refused" in result.refusal_reason
    )
    assert result.blocks_applied == 0


@pytest.mark.asyncio
async def test_write_file_blocked_by_dirty_guard_returns_structured(
    tmp_path, monkeypatch
):
    """WriteFile blocked by dirty-file guard returns status='refused' with error_kind='dirty_file_protected'."""
    monkeypatch.chdir(tmp_path)
    import subprocess

    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "clean.py").write_text("x = 1\n")
    subprocess.run(
        ["git", "add", "clean.py"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )

    (tmp_path / "dirty.py").write_text("original\n")
    subprocess.run(
        ["git", "add", "dirty.py"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "add dirty"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "dirty.py").write_text("modified\n")

    from rig_relay.core.guard import reset_guard

    reset_guard()

    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())
    result = await collect_result(
        tool.run(WriteFileArgs(path="dirty.py", content="overwritten", overwrite=True))
    )

    assert result.status == "refused"
    assert result.error_kind == "dirty_file_protected"
    assert result.refusal_reason is not None
    assert result.bytes_written == 0


@pytest.mark.asyncio
async def test_write_file_hash_mismatch_returns_structured(tmp_path, monkeypatch):
    """WriteFile with stale expected hash returns status='refused' with error_kind='expected_hash_mismatch'."""
    monkeypatch.chdir(tmp_path)
    import subprocess

    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "data.py").write_text("original\n")
    subprocess.run(
        ["git", "add", "data.py"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )

    (tmp_path / "data.py").write_text("version1\n")

    from rig_relay.core.guard import reset_guard

    reset_guard()

    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())
    result = await collect_result(
        tool.run(
            WriteFileArgs(
                path="data.py",
                content="version2",
                overwrite=True,
                allow_overwrite_protected=True,
                expected_before_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            )
        )
    )

    assert result.status == "refused"
    assert result.error_kind == "expected_hash_mismatch"
    assert result.refusal_reason is not None


@pytest.mark.asyncio
async def test_write_file_correct_hash_succeeds(tmp_path, monkeypatch):
    """WriteFile with correct expected hash succeeds."""
    monkeypatch.chdir(tmp_path)
    import subprocess

    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "data.py").write_text("original\n")
    subprocess.run(
        ["git", "add", "data.py"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )

    (tmp_path / "data.py").write_text("version1\n")
    current_hash = "sha256:" + hashlib.sha256(b"version1\n").hexdigest()

    from rig_relay.core.guard import reset_guard

    reset_guard()

    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())
    result = await collect_result(
        tool.run(
            WriteFileArgs(
                path="data.py",
                content="version2",
                overwrite=True,
                allow_overwrite_protected=True,
                expected_before_sha256=current_hash,
            )
        )
    )

    assert result.status == "success"
    assert result.bytes_written > 0
    assert (tmp_path / "data.py").read_text(encoding="utf-8") == "version2"


@pytest.mark.asyncio
async def test_write_file_refusal_is_content_light(tmp_path, monkeypatch):
    """WriteFile refusal metadata does not contain raw file contents."""
    monkeypatch.chdir(tmp_path)
    import subprocess

    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    (tmp_path / "secret.py").write_text("API_KEY=secret\n")
    subprocess.run(
        ["git", "add", "secret.py"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )
    (tmp_path / "secret.py").write_text("API_KEY=modified\n")

    from rig_relay.core.guard import reset_guard

    reset_guard()

    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())
    result = await collect_result(
        tool.run(WriteFileArgs(path="secret.py", content="hacked", overwrite=True))
    )

    dumped = result.model_dump(mode="json")
    dumped_str = json.dumps(dumped)
    assert "API_KEY" not in dumped_str
    assert result.content == ""


@pytest.mark.asyncio
async def test_search_replace_refusal_is_content_light(tmp_path, monkeypatch):
    """SearchReplace refusal metadata does not contain raw search/replace text or file contents."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "code.py"
    target.write_text("sensitive=data\n", encoding="utf-8")

    # Create a persistent coordination reservation (never released)
    from rig_relay.coordination.store import CoordinationStore

    abs_path = str((tmp_path / "code.py").resolve())
    store = CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")
    store.claim_task(
        session_id="session_persistent_sr_cl",
        task_id="task_persistent_sr_cl",
        claim_kind="search_replace",
        ttl_seconds=600,
        scope={"allowed_paths": [abs_path]},
    )
    store.reserve_paths(
        session_id="session_persistent_sr_cl",
        task_id="task_persistent_sr_cl",
        mode="write",
        paths=[abs_path],
        ttl_seconds=600,
    )

    config = SearchReplaceConfig()
    tool = SearchReplace(config_getter=lambda: config, state=BaseToolState())
    session_dir_beta = tmp_path / "session_beta"
    block_content = _sr_block("sensitive=data", "leaked=yes")
    result = await collect_result(
        tool.run(
            SearchReplaceArgs(file_path="code.py", content=block_content),
            InvokeContext(tool_call_id="call-second", session_dir=session_dir_beta),
        )
    )

    dumped = result.model_dump(mode="json")
    dumped_str = json.dumps(dumped)
    assert result.status == "blocked"
    assert result.content == ""
    assert "sensitive" not in dumped_str
    assert "leaked" not in dumped_str


# ── Path normalization consistency ─────────────────────────────────────


def test_path_normalization_equivalent_forms(tmp_path, monkeypatch):
    """normalize_path does NOT resolve relative paths -- only converts to POSIX."""
    from rig_relay.coordination.models import normalize_path

    monkeypatch.chdir(tmp_path)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "file.py").write_text("")

    abs_path = str((tmp_path / "sub" / "file.py").resolve())
    rel_path = "sub/file.py"

    abs_normalized = normalize_path(abs_path)
    rel_normalized = normalize_path(rel_path)

    # normalize_path does NOT resolve -- it only converts to POSIX
    # So relative and absolute produce different results for the same file
    assert abs_normalized != rel_normalized
    # But for already-resolved absolute paths, normalize_path is idempotent
    assert normalize_path(abs_path) == abs_path


@pytest.mark.asyncio
async def test_write_file_atomicity_failure_preserves_original(tmp_path, monkeypatch):
    """Existing file content is preserved and temp file cleaned up when atomic replace fails."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "important.txt"
    original = "preserve this content"
    target.write_text(original, encoding="utf-8")

    def _failing_replace(src, dst):
        raise OSError("Simulated atomic replace failure")

    monkeypatch.setattr("os.replace", _failing_replace)

    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    with pytest.raises(ToolError, match="Error writing"):
        await collect_result(
            tool.run(
                WriteFileArgs(
                    path="important.txt",
                    content="this should not appear",
                    overwrite=True,
                )
            )
        )

    # Original content preserved
    assert target.read_text(encoding="utf-8") == original
    # No temp files left behind
    tmp_files = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert len(tmp_files) == 0


@pytest.mark.asyncio
async def test_write_file_atomicity_new_file_timing_and_bytes(tmp_path, monkeypatch):
    """WriteFile new file populates duration_ms, before_bytes=0, after_bytes correctly."""
    monkeypatch.chdir(tmp_path)
    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(WriteFileArgs(path="timing.txt", content="hello world"))
    )

    assert result.duration_ms is not None
    assert result.duration_ms > 0
    assert result.before_bytes == 0  # new file
    assert result.after_bytes == 11  # len("hello world")


@pytest.mark.asyncio
async def test_write_file_atomicity_overwrite_timing_and_bytes(tmp_path, monkeypatch):
    """WriteFile overwrite populates correct before_bytes, after_bytes, and duration_ms."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "existing.txt"
    target.write_text("old content here", encoding="utf-8")

    config = WriteFileConfig()
    tool = WriteFile(config_getter=lambda: config, state=BaseToolState())

    result = await collect_result(
        tool.run(
            WriteFileArgs(path="existing.txt", content="new content!", overwrite=True)
        )
    )

    assert result.duration_ms is not None
    assert result.duration_ms > 0
    assert result.before_bytes == 16  # len("old content here")
    assert result.after_bytes == 12  # len("new content!")
    assert result.before_sha256 is not None
    assert result.after_sha256 is not None
    assert result.before_sha256 != result.after_sha256
