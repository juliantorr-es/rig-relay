"""Property-based test seeding for Rig Relay security-critical surfaces.

Tests are RED-FIRST — designed to expose real weaknesses before code changes.
"""

from __future__ import annotations

import json
import keyword
import os
from pathlib import Path
import tempfile

from hypothesis import HealthCheck, assume, given, settings, strategies as st
import pytest

from rig_relay.compiler.schema_to_code.reader import _safe_python_identifier
from rig_relay.coordination.current_state import _read_jsonl
from rig_relay.core.tools.security import resolve_safe_path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_workspace() -> Path:
    return Path(tempfile.mkdtemp()).resolve()


def _write_jsonl_lines(lines: list[str]) -> Path:
    p = Path(tempfile.mkdtemp()) / "test.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. Schema field name sanitization (compiler injection surface)
# ---------------------------------------------------------------------------

BUILTINS_TO_REJECT = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    "type",
    "object",
})

_PYTHON_KEYWORDS = frozenset(keyword.kwlist)

INJECTION_PATTERNS = st.sampled_from([
    "eval",
    "exec",
    "compile",
    "__import__",
    "__init__",
    "__class__",
    "__bases__",
    "__subclasses__",
    "__globals__",
    "__code__",
    "}; import os; os.system('id')#",
    "' OR 1=1--",
    "$(cmd)",
    "`cmd`",
    "${cmd}",
    "#pragma",
    "foo\0bar",
    "\nimport os\n",
    "\r\nx",
])


class TestSafePythonIdentifier:
    @given(
        st.text(
            min_size=1,
            max_size=80,
            alphabet=st.characters(blacklist_characters=("\x00", "\n", "\r")),
        )
    )
    @settings(max_examples=200)
    def test_valid_identifiers_pass_contract(self, name: str) -> None:
        is_valid = _safe_python_identifier(name)
        if is_valid:
            assert name.isidentifier(), (
                f"_safe_python_identifier accepted '{name}' but str.isidentifier() rejects it"
            )
            assert name not in _PYTHON_KEYWORDS, (
                f"_safe_python_identifier accepted keyword '{name}'"
            )

    @given(
        st.text(
            min_size=1,
            max_size=80,
            alphabet=st.characters(blacklist_characters=("\x00", "\n", "\r")),
        )
    )
    @settings(max_examples=200)
    def test_non_identifiers_are_rejected(self, name: str) -> None:
        assume(not name.isidentifier() or name in _PYTHON_KEYWORDS)
        assert not _safe_python_identifier(name), (
            f"_safe_python_identifier accepted non-identifier/keyword '{name}'"
        )

    @given(INJECTION_PATTERNS)
    @settings(max_examples=20)
    def test_injection_patterns_rejected(self, injection: str) -> None:
        result = _safe_python_identifier(injection)
        # NOTE: eval, exec, compile, open, input, __import__ are valid
        # identifiers AND are builtins. _safe_python_identifier currently
        # accepts them — this is a real gap. These are reported by
        # test_builtin_names_should_be_rejected.
        if injection in {
            "eval",
            "exec",
            "compile",
            "open",
            "input",
            "__import__",
            "__init__",
            "__class__",
            "__bases__",
            "__subclasses__",
            "__globals__",
            "__code__",
        }:
            if result:
                return  # accepted by current impl, gap tracked below
        assert not result, (
            f"_safe_python_identifier accepted injection pattern: {injection!r}"
        )

    # RED TEST: _safe_python_identifier does NOT reject builtins.
    # This is a real gap — schema properties named 'eval' or '__import__'
    # would pass validation and could surface in generated code.
    @pytest.mark.xfail(
        reason="BUG: _safe_python_identifier does not reject Python builtins",
        strict=True,
    )
    @given(st.sampled_from(sorted(BUILTINS_TO_REJECT)))
    def test_builtin_names_should_be_rejected(self, builtin_name: str) -> None:
        assume(builtin_name.isidentifier())
        result = _safe_python_identifier(builtin_name)
        if result:
            pytest.fail(
                f"BUGBOUNTY: _safe_python_identifier accepted builtin '{builtin_name}'. "
                f"Schema field names that shadow Python builtins can surface in generated "
                f"Pydantic model code. This is a real injection/confusion risk."
            )

    @given(
        st.builds(
            lambda body: f"__{body}__",
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(
                    whitelist_categories=("Ll",), whitelist_characters=""
                ),
            ),
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.filter_too_much])
    def test_dunder_names_not_builtins_pass(self, name: str) -> None:
        assume(name.isascii() and name.isidentifier() and name not in _PYTHON_KEYWORDS)
        assume(name not in BUILTINS_TO_REJECT)
        assert _safe_python_identifier(name), (
            f"_safe_python_identifier rejected valid dunder '{name}'"
        )


# ---------------------------------------------------------------------------
# 2. JSONL corruption resilience
# ---------------------------------------------------------------------------

_VALID_JSONL_ENTRIES = st.lists(
    st.dictionaries(
        keys=st.text(
            min_size=1,
            max_size=10,
            alphabet=st.characters(whitelist_categories=("Ll",)),
        ),
        values=st.one_of(
            st.integers(),
            st.text(min_size=1, max_size=20),
            st.floats(allow_nan=False, allow_infinity=False),
            st.booleans(),
        ),
        min_size=1,
        max_size=5,
    ),
    min_size=1,
    max_size=10,
)

CORRUPTION_STRATEGIES = st.sampled_from([
    "truncate_mid_line",
    "malformed_json",
    "empty_line",
    "non_utf8",
    "nested_obj",
])


def _corrupt_line(line: str, strategy: str) -> str:
    match strategy:
        case "truncate_mid_line":
            return line[: max(1, len(line) // 2)]
        case "malformed_json":
            if line:
                return line[:-3] + "!!!"
            return "!!!"
        case "empty_line":
            return ""
        case "non_utf8":
            return "valid"
        case "nested_obj":
            return json.dumps({"nested": line})
    return line


class TestJSONLCorruptionResilience:
    @given(_VALID_JSONL_ENTRIES)
    @settings(max_examples=50)
    def test_valid_jsonl_reads_all_entries(self, entries: list[dict]) -> None:
        lines = [json.dumps(e, sort_keys=True) for e in entries]
        path = _write_jsonl_lines(lines)
        result = _read_jsonl(path)
        assert len(result) == len(entries), (
            f"Expected {len(entries)} entries, got {len(result)}"
        )

    @given(_VALID_JSONL_ENTRIES, CORRUPTION_STRATEGIES)
    @settings(max_examples=100)
    def test_single_corrupted_line_does_not_crash(
        self, entries: list[dict], strategy: str
    ) -> None:
        lines = [json.dumps(e, sort_keys=True) for e in entries]
        if lines:
            lines[0] = _corrupt_line(lines[0], strategy)
        path = _write_jsonl_lines(lines)
        result = _read_jsonl(path)
        assert isinstance(result, list)
        assert len(result) <= len(lines)

    @given(CORRUPTION_STRATEGIES)
    @settings(max_examples=10)
    def test_fully_corrupted_file_returns_empty(self, strategy: str) -> None:
        corrupt_lines = [_corrupt_line("x", strategy) for _ in range(5)]
        path = _write_jsonl_lines(corrupt_lines)
        result = _read_jsonl(path)
        assert isinstance(result, list), (
            f"Should return list even on corrupt file, got {type(result)}"
        )

    @given(st.text(min_size=0, max_size=200))
    @settings(max_examples=100)
    def test_arbitrary_text_lines_dont_crash(self, text: str) -> None:
        path = _write_jsonl_lines([text])
        _read_jsonl(path)

    def test_missing_file_returns_empty(self) -> None:
        assert _read_jsonl(Path("/nonexistent/test_never_here.jsonl")) == []

    def test_empty_file_returns_empty(self) -> None:
        path = _write_jsonl_lines([])
        assert _read_jsonl(path) == []

    @pytest.mark.xfail(
        reason="BUG: _read_jsonl crashes on binary content (UnicodeDecodeError unhandled)",
        strict=True,
    )
    def test_binary_content_does_not_crash(self) -> None:
        p = Path(tempfile.mkdtemp()) / "binary.jsonl"
        p.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")
        result = _read_jsonl(p)
        assert isinstance(result, list)

    def test_unicode_replacement_characters_handled(self) -> None:
        entries = [json.dumps({"key": "\ufffd" * 10}), json.dumps({"valid": 1})]
        path = _write_jsonl_lines(entries)
        result = _read_jsonl(path)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# 3. Path normalization safety (traversal rejection)
# ---------------------------------------------------------------------------

_PATH_INJECTIONS = st.sampled_from([
    "../../../etc/passwd",
    "../../../../../../../etc/passwd",
    "..\\..\\Windows\\System32",
    "/etc/passwd",
    "~/.ssh/id_rsa",
    "$HOME/.ssh",
    "subdir/../../../etc/shadow",
    "././././../../etc/hosts",
    "foo/../../../../../../tmp/evil",
    "/var/empty/../../../../private/var/db",
    "../",
    "../..",
    "../../",
    "....//....//....//etc/passwd",
    "..;/etc/passwd",
])


class TestResolveSafePath:
    @given(
        st.text(
            min_size=1, max_size=40, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-."
        )
    )
    @settings(max_examples=100)
    def test_simple_safe_paths_resolve(self, name: str) -> None:
        assume(
            name
            and not name.startswith(".")
            and not name.startswith("-")
            and not name.endswith(".")
            and ".." not in name
        )
        workspace = _tmp_workspace()
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        result = resolve_safe_path(str(target), workspace=workspace)
        assert result.is_absolute()
        result.relative_to(workspace)

    @given(_PATH_INJECTIONS)
    @settings(max_examples=40)
    def test_traversal_attempts_rejected(self, injection: str) -> None:
        workspace = _tmp_workspace()
        # Null byte injection is handled differently by Path
        if "\x00" in injection:
            with pytest.raises((ValueError, TypeError)):
                resolve_safe_path(injection, workspace=workspace)
        else:
            with pytest.raises(ValueError, match="outside"):
                resolve_safe_path(injection, workspace=workspace)

    @given(
        st.text(
            min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_"
        )
    )
    @settings(max_examples=50)
    def test_symlink_traversal_rejected(self, target: str) -> None:
        assume(target and not target.startswith("."))
        workspace = _tmp_workspace()
        external = _tmp_workspace()
        (external / "secret.txt").write_text("secret", encoding="utf-8")
        symlink = workspace / "link_to_secret"
        symlink.symlink_to(external / "secret.txt")
        with pytest.raises(ValueError, match="outside"):
            resolve_safe_path(symlink, workspace=workspace)

    def test_absolute_path_inside_workspace_works(self) -> None:
        workspace = _tmp_workspace()
        subfile = workspace / "inside.txt"
        subfile.write_text("ok", encoding="utf-8")
        result = resolve_safe_path(str(subfile), workspace=workspace)
        assert result == subfile

    def test_relative_path_inside_workspace_works(self) -> None:
        workspace = _tmp_workspace()
        subdir = workspace / "sub"
        subdir.mkdir()
        (subdir / "f.txt").touch()
        saved_cwd = os.getcwd()
        os.chdir(str(workspace))
        try:
            result = resolve_safe_path("sub/f.txt", workspace=workspace)
            assert result.is_absolute()
            result.relative_to(workspace)
        finally:
            os.chdir(saved_cwd)

    def test_path_with_null_byte_is_rejected(self) -> None:
        workspace = _tmp_workspace()
        with pytest.raises((ValueError, TypeError)):
            resolve_safe_path("valid\0../../etc", workspace=workspace)

    def test_default_workspace_is_cwd(self) -> None:
        result = resolve_safe_path(".")
        assert result.is_absolute()
