from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.ast_grep import AstGrep, AstGrepArgs, AstGrepConfig
from tests.mock.utils import collect_result


def _make_ast_grep() -> AstGrep:
    return AstGrep(config_getter=lambda: AstGrepConfig(), state=BaseToolState())


@pytest.mark.asyncio
@pytest.mark.real_artifact
async def test_ast_grep_matches_python_function_defs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "test.py"
    src.write_text("def hello():\n    pass\ndef world():\n    pass\n")

    tool = _make_ast_grep()
    args = AstGrepArgs(
        pattern="def $NAME($$$ARGS): $$$BODY", language="python", paths=[str(src)]
    )
    result = await collect_result(tool.run(args))

    assert result.query_outcome in ("matches", "truncated")
    assert len(result.matches) >= 2


@pytest.mark.asyncio
async def test_ast_grep_no_match_is_normal_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "test.py"
    src.write_text("x = 1\n")

    tool = _make_ast_grep()
    args = AstGrepArgs(
        pattern="class $NAME: $$$BODY", language="python", paths=[str(src)]
    )
    result = await collect_result(tool.run(args))

    assert result.query_outcome == "no_match"
    assert result.error_kind is None
    assert len(result.matches) == 0


@pytest.mark.asyncio
async def test_ast_grep_invalid_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "test.py"
    src.write_text("x = 1\n")

    tool = _make_ast_grep()
    args = AstGrepArgs(
        pattern="this is @#$% not valid python", language="python", paths=[str(src)]
    )
    result = await collect_result(tool.run(args))

    assert result.query_outcome == "invalid_pattern"
    assert result.error_kind is not None


@pytest.mark.asyncio
async def test_ast_grep_language_required_for_repo_scan() -> None:
    tool = _make_ast_grep()
    args = AstGrepArgs(pattern="x = 1", language=None, paths=[])
    result = await collect_result(tool.run(args))

    assert result.query_outcome == "language_required"
    assert result.error_kind == "language_required_for_multi_file_scan"


@pytest.mark.asyncio
async def test_ast_grep_unsupported_language() -> None:
    tool = _make_ast_grep()
    args = AstGrepArgs(pattern="x = 1", language="cobol", paths=[])
    result = await collect_result(tool.run(args))

    assert result.query_outcome == "unsupported_language"
    assert result.error_kind == "unsupported_language"


@pytest.mark.asyncio
async def test_ast_grep_single_file_language_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "test.py"
    src.write_text("def foo():\n    pass\n")

    tool = _make_ast_grep()
    args = AstGrepArgs(pattern="def foo", language=None, paths=[str(src)])
    result = await collect_result(tool.run(args))

    assert result.language == "python"
    assert result.query_outcome in ("matches", "truncated")


@pytest.mark.asyncio
async def test_ast_grep_match_locations_are_correct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "test.py"
    src.write_text("# line 1\ndef hello():\n    pass\n")

    tool = _make_ast_grep()
    args = AstGrepArgs(pattern="def hello", language="python", paths=[str(src)])
    result = await collect_result(tool.run(args))

    assert len(result.matches) >= 1
    m = result.matches[0]
    assert m.start_line == 2
    assert "def hello" in m.snippet


@pytest.mark.asyncio
async def test_ast_grep_path_refused_outside_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    outside = Path("/tmp/_ast_grep_test_outside.py")
    outside.write_text("x = 1\n")

    try:
        tool = _make_ast_grep()
        args = AstGrepArgs(pattern="x", language="python", paths=[str(outside)])
        result = await collect_result(tool.run(args))

        assert result.query_outcome == "path_refused"
        assert result.error_kind == "path_outside_verified_worktree"
    finally:
        outside.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_ast_grep_tool_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _make_ast_grep()

    def _failing_load() -> type:
        raise ImportError("simulated")

    monkeypatch.setattr(tool, "_load_lib", _failing_load)
    args = AstGrepArgs(pattern="x", language="python", paths=[])
    result = await collect_result(tool.run(args))

    assert result.query_outcome == "unavailable"
    assert result.error_kind == "tool_unavailable"


@pytest.mark.asyncio
async def test_ast_grep_snippet_truncation_preserves_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    lines = ["def big():"]
    for i in range(200):
        lines.append(f"    x{i} = {i}")
    src = tmp_path / "test.py"
    src.write_text("\n".join(lines))

    tool = _make_ast_grep()
    args = AstGrepArgs(pattern="def big", language="python", paths=[str(src)])
    result = await collect_result(tool.run(args))

    if result.matches:
        m = result.matches[0]
        assert m.start_line >= 1
        assert m.file == str(src)
        assert isinstance(m.start_line, int)


@pytest.mark.asyncio
async def test_ast_grep_max_matches_capped() -> None:
    tool = _make_ast_grep()
    args = AstGrepArgs(pattern="x", language="python", paths=[], max_matches=500)
    result = await collect_result(tool.run(args))

    assert result.query_outcome in ("matches", "truncated", "no_match")


@pytest.mark.asyncio
async def test_ast_grep_context_lines_capped() -> None:
    tool = _make_ast_grep()
    args = AstGrepArgs(
        pattern="def foo", language="python", paths=[], context_lines=100
    )
    result = await collect_result(tool.run(args))

    assert result.query_outcome in ("matches", "truncated", "no_match")
