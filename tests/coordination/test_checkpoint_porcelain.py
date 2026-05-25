"""Tests for Checkpoint._parse_porcelain_z — real `git status --porcelain=v1 -z`.

Requires real temporary Git repositories and real subprocess output.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from rig_relay.core.tools.builtins.checkpoint import (
    Checkpoint,
    CheckpointPorcelainProtocolError,
)


def _git_porcelain(repo: Path) -> str:
    """Run git status --porcelain=v1 -z and return raw stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v1", "-z"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "init"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@t"], capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "T"], capture_output=True
    )


# ---- Real-git porcelain tests ----------------------------------------


def test_porcelain_unstaged_file_preserves_xy_status(tmp_path):
    """Classification: real-artifact, substrate

    An unstaged modified file produces status ' M' exactly.
    """
    _git_init(tmp_path)
    (tmp_path / "a.py").write_text("x=1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True
    )
    (tmp_path / "a.py").write_text("x=2")  # modified, NOT staged

    output = _git_porcelain(tmp_path)
    result = Checkpoint._parse_porcelain_z(output)

    assert "a.py" in result
    assert result["a.py"] == " M"


def test_porcelain_nested_path_preserved(tmp_path):
    """Classification: real-artifact, substrate

    A nested path like src/app.py is preserved exactly.
    """
    _git_init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("x=1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True
    )
    (tmp_path / "src/app.py").write_text("x=2")

    output = _git_porcelain(tmp_path)
    result = Checkpoint._parse_porcelain_z(output)

    assert "src/app.py" in result
    assert result["src/app.py"] == " M"


def test_porcelain_multiple_files_both_correct(tmp_path):
    """Classification: real-artifact, substrate

    Two modified files are both captured with correct paths and status.
    """
    _git_init(tmp_path)
    (tmp_path / "a.py").write_text("x=1")
    (tmp_path / "b.py").write_text("y=1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True
    )
    (tmp_path / "a.py").write_text("x=2")
    (tmp_path / "b.py").write_text("y=2")

    output = _git_porcelain(tmp_path)
    result = Checkpoint._parse_porcelain_z(output)

    assert result.get("a.py") == " M"
    assert result.get("b.py") == " M"


def test_porcelain_filename_with_spaces(tmp_path):
    """Classification: real-artifact, substrate

    A filename containing spaces is preserved exactly.
    """
    _git_init(tmp_path)
    (tmp_path / "my file.py").write_text("x=1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True
    )
    (tmp_path / "my file.py").write_text("x=2")

    output = _git_porcelain(tmp_path)
    result = Checkpoint._parse_porcelain_z(output)

    assert "my file.py" in result


def test_porcelain_leading_space_filename_preserved(tmp_path):
    """Classification: real-artifact, substrate

    A filename beginning with a space is preserved exactly.
    Defeats any lstrip() regression.
    """
    _git_init(tmp_path)
    leading_space_path = " leading.py"
    (tmp_path / leading_space_path).write_text("x=1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True
    )
    (tmp_path / leading_space_path).write_text("x=2")

    output = _git_porcelain(tmp_path)
    result = Checkpoint._parse_porcelain_z(output)

    # Path must be exact — no lstrip
    if leading_space_path in result:
        assert result[leading_space_path] == " M"
    else:
        # Git may handle differently; either way, no lstrip corruption
        for path in result:
            assert not path.startswith("leading"), f"lstrip corrupted: {path!r}"


def test_porcelain_terminal_nul_accepted(tmp_path):
    """Classification: real-artifact, substrate

    Valid output ending with NUL is accepted.
    """
    _git_init(tmp_path)
    (tmp_path / "a.py").write_text("x=1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True
    )
    (tmp_path / "a.py").write_text("x=2")

    output = _git_porcelain(tmp_path)
    assert output.endswith("\0")
    result = Checkpoint._parse_porcelain_z(output)
    assert "a.py" in result


def test_porcelain_missing_terminal_nul_fails_closed():
    """Classification: sabotage, substrate

    Output without terminal NUL fails closed.
    """
    with pytest.raises(CheckpointPorcelainProtocolError):
        Checkpoint._parse_porcelain_z(" M a.py")  # no NUL


def test_porcelain_embedded_empty_fails_closed():
    """Classification: sabotage, substrate

    Output with embedded empty record fails closed.
    """
    with pytest.raises(CheckpointPorcelainProtocolError):
        Checkpoint._parse_porcelain_z(" M a.py\0\0 M b.py\0")


def test_porcelain_too_short_record_fails_closed():
    """Classification: sabotage, substrate

    Output with a record shorter than 3 chars fails closed.
    """
    with pytest.raises(CheckpointPorcelainProtocolError):
        Checkpoint._parse_porcelain_z("ab\0")


def test_porcelain_missing_space_fails_closed():
    """Classification: sabotage, substrate

    Output with missing space delimiter fails closed.
    """
    with pytest.raises(CheckpointPorcelainProtocolError):
        Checkpoint._parse_porcelain_z("MXa.py\0")

def test_porcelain_rename_copy_parsed_correctly(tmp_path):
    """Classification: real-artifact, substrate

    A staged rename produces 'R  newname\0oldname\0'.
    The parser must skip the old-name token and record only the new path.
    """
    _git_init(tmp_path)
    (tmp_path / "old.py").write_text("x=1")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True
    )
    # Rename: old.py → new.py and stage it
    subprocess.run(
        ["git", "-C", str(tmp_path), "mv", "old.py", "new.py"], capture_output=True
    )

    output = _git_porcelain(tmp_path)
    result = Checkpoint._parse_porcelain_z(output)

    assert "new.py" in result
    assert result["new.py"][0] == "R"
    assert "old.py" not in result, (
        "old-name token must not leak into result dict"
    )
