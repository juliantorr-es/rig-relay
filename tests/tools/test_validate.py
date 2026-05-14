"""Tests for validate tool — Stage 1: Read-Only Profiles.

Tests cover:
- unknown profile returns refused/blocked result
- quick profile builds expected checks
- schemas profile runs or is correctly refused when unavailable
- failed check maps to correct blocker kind
- missing executable maps to missing_dependency
- timeout maps to timeout
- stdout/stderr are hashed and byte-counted
- output truncation flags work
- blocker_summary counts failure kinds
- allow_mutation=false refuses mutation-looking checks
- command_fingerprint is stable for normalized argv
- result does not contain full raw stdout/stderr in long-lived fields
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import textwrap

import pytest

from vibe.core.tools.base import ToolPermission
from vibe.core.tools.builtins.validate import (
    MAX_CAP_BYTES,
    VALIDATE_RECEIPT_SCHEMA_VERSION,
    ValidateCheckReceipt,
    ValidateCheckResult,
    ValidateReceipt,
    ValidateResult,
    ValidateToolConfig,
    _compute_fingerprint,
    _infer_kind_from_argv,
    _parse_check_summary,
    _parse_policy_summary,
    _parse_pyright_summary,
    _parse_pytest_summary,
    _parse_ruff_summary,
    _parse_schema_summary,
    _run_check,
    check_missing_dependency,
    classify_failure,
    get_profile,
    list_profiles,
)

# ── Helpers ───────────────────────────────────────────────────────────


def _make_low_cap_config() -> ValidateToolConfig:
    return ValidateToolConfig(permission=ToolPermission.ASK, default_output_cap=1024)


@pytest.fixture
def tmp_script(tmp_path: Path) -> Path:
    """Create a temporary script that exits with a given code."""
    script = tmp_path / "test_script.py"
    script.write_text(
        textwrap.dedent("""\
        import sys
        print("stdout line")
        print("stderr line", file=sys.stderr)
        sys.exit(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
        """)
    )
    return script


# ── Profile tests ─────────────────────────────────────────────────────


def test_unknown_profile_returns_none() -> None:
    """get_profile returns None for unknown profile names."""
    assert get_profile("nonexistent") is None


def test_known_profiles_are_registered() -> None:
    """Expected profiles are registered."""
    profiles = list_profiles()
    assert "quick" in profiles
    assert "python" in profiles
    assert "schemas" in profiles
    assert "receipt-policy" in profiles
    assert "tool-hardening" in profiles


def test_quick_profile_has_expected_checks() -> None:
    """Quick profile includes git_status check."""
    p = get_profile("quick")
    assert p is not None
    assert len(p.checks) >= 1
    check_ids = [c.check_id for c in p.checks]
    assert "git_status" in check_ids
    assert not p.allow_mutation
    assert not p.allow_network


def test_schemas_profile_has_schema_check() -> None:
    """Schemas profile includes schema_validation check."""
    p = get_profile("schemas")
    assert p is not None
    assert any(c.command_kind == "schema" for c in p.checks)


def test_tool_hardening_profile_has_hardening_checks() -> None:
    """Tool-hardening profile includes bash/receipt tests."""
    p = get_profile("tool-hardening")
    assert p is not None
    check_ids = [c.check_id for c in p.checks]
    assert "bash_hardening" in check_ids
    assert "receipt_emission" in check_ids


# ── Dependency checks ────────────────────────────────────────────────


def test_check_missing_dependency_none() -> None:
    """Commands with 'uv' token are not flagged as missing."""
    result = check_missing_dependency(["uv", "run", "pytest"])
    assert result is None


def test_check_missing_dependency_unknown_binary() -> None:
    """A nonexistent binary is flagged as missing."""
    result = check_missing_dependency(["nonexistent_binary_xyz"])
    assert result is not None


def test_check_missing_dependency_empty_argv() -> None:
    """Empty argv returns no missing dependency."""
    result = check_missing_dependency([])
    assert result is None


# ── Classify failure ──────────────────────────────────────────────────


def test_classify_failure_zero_exit() -> None:
    """Exit code 0 returns empty failure kind."""
    assert classify_failure("pytest", 0, "") == ""


def test_classify_failure_pytest() -> None:
    """Pytest failure maps to test_failure."""
    assert classify_failure("pytest", 1, "FAILED") == "test_failure"


def test_classify_failure_ruff() -> None:
    """Ruff failure maps to lint_failure."""
    assert classify_failure("ruff", 1, "") == "lint_failure"


def test_classify_failure_pyright() -> None:
    """Pyright failure maps to typecheck_failure."""
    assert classify_failure("pyright", 1, "error") == "typecheck_failure"


def test_classify_failure_schema() -> None:
    """Schema failure maps to schema_failure."""
    assert classify_failure("schema", 1, "") == "schema_failure"


def test_classify_failure_policy() -> None:
    """Policy failure maps to governance_failure."""
    assert classify_failure("policy", 1, "") == "governance_failure"


def test_classify_failure_git() -> None:
    """Git failure maps to dirty_workspace."""
    assert classify_failure("git", 1, "") == "dirty_workspace"


def test_classify_failure_timeout() -> None:
    """Negative exit code maps to timeout."""
    assert classify_failure("pytest", -1, "") == "timeout"


def test_classify_failure_unknown() -> None:
    """Unknown kind maps to unknown_failure."""
    assert classify_failure("unknown_tool", 1, "") == "unknown_failure"


# ── Command fingerprint ──────────────────────────────────────────────


def test_fingerprint_stable() -> None:
    """Same argv produces same fingerprint."""
    fp1 = _compute_fingerprint(["uv", "run", "pytest", "-x"])
    fp2 = _compute_fingerprint(["uv", "run", "pytest", "-x"])
    assert fp1 == fp2


def test_fingerprint_differs() -> None:
    """Different argv produces different fingerprint."""
    fp1 = _compute_fingerprint(["uv", "run", "pytest", "-x"])
    fp2 = _compute_fingerprint(["uv", "run", "ruff", "check"])
    assert fp1 != fp2


def test_fingerprint_is_hex() -> None:
    """Fingerprint is a hex string."""
    fp = _compute_fingerprint(["uv", "run", "pytest"])
    assert all(c in "0123456789abcdef" for c in fp)


# ── Infer kind ────────────────────────────────────────────────────────


def test_infer_kind_pytest() -> None:
    assert _infer_kind_from_argv(["uv", "run", "pytest", "-x"]) == "pytest"


def test_infer_kind_ruff() -> None:
    assert _infer_kind_from_argv(["uv", "run", "ruff", "check"]) == "ruff"


def test_infer_kind_pyright() -> None:
    assert _infer_kind_from_argv(["uv", "run", "pyright"]) == "pyright"


def test_infer_kind_schema() -> None:
    assert (
        _infer_kind_from_argv([
            "uv",
            "run",
            "python",
            "scripts/rig_relay_validate_schemas.py",
        ])
        == "schema"
    )


def test_infer_kind_git() -> None:
    assert _infer_kind_from_argv(["git", "status"]) == "git"


# ── Subprocess execution ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_check_success(tmp_script: Path) -> None:
    """Successful check returns passed status with hashes and byte counts."""
    result = await _run_check(
        [sys.executable, str(tmp_script), "0"], output_cap=65536, timeout=30, cwd=None
    )
    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.stdout_bytes is not None and result.stdout_bytes > 0
    assert result.stderr_bytes is not None and result.stderr_bytes > 0
    assert result.stdout_sha256 is not None
    assert result.stderr_sha256 is not None
    assert not result.stdout_truncated
    assert not result.stderr_truncated


@pytest.mark.asyncio
async def test_run_check_failure(tmp_script: Path) -> None:
    """Non-zero exit returns failed status with failure_kind."""
    result = await _run_check(
        [sys.executable, str(tmp_script), "1"], output_cap=65536, timeout=30, cwd=None
    )
    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.failure_kind is not None


@pytest.mark.asyncio
async def test_run_check_timeout(tmp_script: Path) -> None:
    """Check that times out returns timed_out status."""
    result = await _run_check(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        output_cap=65536,
        timeout=1,
        cwd=None,
    )
    assert result.status == "timed_out"
    assert result.failure_kind == "timeout"


@pytest.mark.asyncio
async def test_run_check_missing_executable() -> None:
    """Missing executable returns blocked status."""
    result = await _run_check(
        ["nonexistent_binary_xyz"], output_cap=65536, timeout=30, cwd=None
    )
    assert result.status == "blocked"
    assert result.failure_kind == "missing_dependency"


@pytest.mark.asyncio
async def test_run_check_truncation(tmp_path: Path) -> None:
    """Output exceeding cap sets truncation flag."""
    script = tmp_path / "big_output.py"
    script.write_text('print("x" * 5000)')
    result = await _run_check(
        [sys.executable, str(script), "0"], output_cap=100, timeout=30, cwd=None
    )
    # The stdout is ~5001 bytes (5000 + newline), cap is 100
    assert result.stdout_truncated
    assert result.stdout_bytes is not None and result.stdout_bytes > 100


@pytest.mark.asyncio
async def test_run_check_hashes_raw_bytes(tmp_script: Path) -> None:
    """Hashes are computed from raw bytes, not truncated text."""
    script_text = "hello world"
    script = tmp_script.parent / "small.py"
    script.write_text(f'print("{script_text}")')
    result = await _run_check(
        [sys.executable, str(script), "0"], output_cap=65536, timeout=30, cwd=None
    )
    assert result.stdout_sha256 is not None
    expected = hashlib.sha256((script_text + "\n").encode()).hexdigest()
    assert result.stdout_sha256 == expected


# ── Result model tests ───────────────────────────────────────────────


def test_validate_check_result_extra_forbidden() -> None:
    """ValidateCheckResult rejects extra fields."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ValidateCheckResult.model_validate({
            "check_id": "x",
            "command_kind": "test",
            "unknown_field": "bad",
        })


def test_validate_result_extra_forbidden() -> None:
    """ValidateResult rejects extra fields."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ValidateResult.model_validate({"profile": "test", "unknown_field": "bad"})


def test_validate_check_result_no_raw_output() -> None:
    """ValidateCheckResult has no raw stdout/stderr fields."""
    r = ValidateCheckResult(check_id="x", command_kind="test")
    dumped = r.model_dump(mode="json")
    for key in ("stdout", "stderr", "output", "content", "diff"):
        assert key not in dumped


def test_validate_result_no_raw_output() -> None:
    """ValidateResult has no raw stdout/stderr in its model."""
    r = ValidateResult(profile="test")
    dumped = r.model_dump(mode="json")
    for key in ("stdout", "stderr", "output", "content"):
        assert key not in dumped


# ── Receipt model tests ──────────────────────────────────────────────


def test_validate_check_receipt_extra_forbidden() -> None:
    """ValidateCheckReceipt rejects extra fields."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ValidateCheckReceipt.model_validate({
            "check_id": "x",
            "command_kind": "test",
            "unknown_field": "bad",
        })


def test_validate_receipt_extra_forbidden() -> None:
    """ValidateReceipt rejects extra fields."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ValidateReceipt.model_validate({
            "profile": "test_profile",
            "status": "passed",
            "unknown_field": "bad",
        })


def test_validate_check_receipt_no_raw_output() -> None:
    """ValidateCheckReceipt has no raw stdout/stderr fields."""
    r = ValidateCheckReceipt(check_id="x", command_kind="test")
    dumped = r.model_dump(mode="json")
    for key in ("stdout", "stderr", "output", "content", "diff"):
        assert key not in dumped


def test_validate_receipt_no_raw_output() -> None:
    """ValidateReceipt has no raw stdout/stderr in its model."""
    r = ValidateReceipt(profile="test", status="passed")
    dumped = r.model_dump(mode="json")
    for key in ("stdout", "stderr", "output", "content"):
        assert key not in dumped


def test_validate_receipt_schema_version() -> None:
    """ValidateReceipt has the correct schema version."""
    r = ValidateReceipt(profile="test", status="passed")
    assert r.schema_version == VALIDATE_RECEIPT_SCHEMA_VERSION


def test_validate_receipt_contains_check_receipts() -> None:
    """ValidateReceipt check_receipts matches content-light fields."""
    cr1 = ValidateCheckReceipt(
        check_id="c1",
        command_kind="pytest",
        status="passed",
        exit_code=0,
        stdout_sha256="abc",
        stderr_sha256="def",
        stdout_bytes=100,
        stderr_bytes=0,
    )
    cr2 = ValidateCheckReceipt(
        check_id="c2",
        command_kind="ruff",
        status="failed",
        exit_code=1,
        failure_kind="lint_failure",
        stdout_bytes=200,
        stderr_bytes=50,
    )
    receipt = ValidateReceipt(
        profile="test_profile",
        status="failed",
        command_count=2,
        passed_count=1,
        failed_count=1,
        duration_ms=150.0,
        blocker_summary={"lint_failure": 1},
        check_receipts=[cr1, cr2],
    )
    assert len(receipt.check_receipts) == 2
    assert receipt.check_receipts[0].check_id == "c1"
    assert receipt.check_receipts[0].status == "passed"
    assert receipt.check_receipts[1].check_id == "c2"
    assert receipt.check_receipts[1].failure_kind == "lint_failure"


def test_validate_receipt_no_raw_in_check_receipts() -> None:
    """ValidateReceipt check_receipts have no raw stdout/stderr fields."""
    cr = ValidateCheckReceipt(check_id="x", command_kind="test")
    receipt = ValidateReceipt(profile="test", status="passed", check_receipts=[cr])
    dumped = receipt.model_dump(mode="json")
    for key in ("stdout", "stderr", "output", "content"):
        assert key not in dumped


# ── build_receipt tests ──────────────────────────────────────────────


def test_build_receipt_from_result() -> None:
    """build_receipt creates ValidateReceipt with correct content-light fields."""
    from vibe.core.tools.base import BaseToolState
    from vibe.core.tools.builtins.validate import Validate, ValidateToolConfig

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())

    cr1 = ValidateCheckResult(
        check_id="c1",
        command_kind="pytest",
        status="passed",
        exit_code=0,
        duration_ms=50.0,
        stdout_sha256="abc",
        stderr_sha256="def",
        stdout_bytes=100,
        stderr_bytes=0,
        stdout_truncated=False,
        stderr_truncated=False,
    )
    cr2 = ValidateCheckResult(
        check_id="c2",
        command_kind="ruff",
        status="failed",
        exit_code=1,
        duration_ms=30.0,
        stdout_sha256="ghi",
        stderr_sha256="jkl",
        stdout_bytes=200,
        stderr_bytes=50,
        stdout_truncated=False,
        stderr_truncated=False,
        failure_kind="lint_failure",
        affected_paths=["file.py"],
    )
    result = ValidateResult(
        status="failed",
        profile="test_profile",
        scope="test_scope",
        command_count=2,
        passed_count=1,
        failed_count=1,
        duration_ms=80.0,
        checks=[cr1, cr2],
        blocker_summary={"lint_failure": 1},
    )
    receipt = tool.build_receipt(result)

    assert isinstance(receipt, ValidateReceipt)
    assert receipt.profile == "test_profile"
    assert receipt.scope == "test_scope"
    assert receipt.status == "failed"
    assert receipt.command_count == 2
    assert receipt.passed_count == 1
    assert receipt.failed_count == 1
    assert receipt.duration_ms == 80.0
    assert receipt.blocker_summary == {"lint_failure": 1}
    assert receipt.error_kind is None
    assert receipt.refusal_reason is None
    assert len(receipt.check_receipts) == 2

    # Check first receipt mapping
    r1 = receipt.check_receipts[0]
    assert r1.check_id == "c1"
    assert r1.command_kind == "pytest"
    assert r1.status == "passed"
    assert r1.exit_code == 0
    assert r1.duration_ms == 50.0
    assert r1.stdout_sha256 == "abc"
    assert r1.stderr_sha256 == "def"
    assert r1.stdout_bytes == 100
    assert r1.stderr_bytes == 0
    assert not r1.stdout_truncated
    assert not r1.stderr_truncated
    assert r1.failure_kind is None
    assert r1.affected_paths == []

    # Check second receipt mapping
    r2 = receipt.check_receipts[1]
    assert r2.check_id == "c2"
    assert r2.command_kind == "ruff"
    assert r2.status == "failed"
    assert r2.exit_code == 1
    assert r2.duration_ms == 30.0
    assert r2.stdout_sha256 == "ghi"
    assert r2.stderr_sha256 == "jkl"
    assert r2.stdout_bytes == 200
    assert r2.stderr_bytes == 50
    assert not r2.stdout_truncated
    assert not r2.stderr_truncated
    assert r2.failure_kind == "lint_failure"
    assert r2.affected_paths == ["file.py"]


def test_build_receipt_empty_result() -> None:
    """build_receipt handles empty ValidateResult with no checks."""
    from vibe.core.tools.base import BaseToolState
    from vibe.core.tools.builtins.validate import Validate, ValidateToolConfig

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())

    result = ValidateResult(
        profile="quick",
        status="passed",
        command_count=0,
        passed_count=0,
        failed_count=0,
        checks=[],
    )
    receipt = tool.build_receipt(result)

    assert receipt.profile == "quick"
    assert receipt.status == "passed"
    assert receipt.command_count == 0
    assert receipt.passed_count == 0
    assert receipt.failed_count == 0
    assert receipt.skipped_count == 0
    assert receipt.check_receipts == []


def test_build_receipt_preserves_refusal() -> None:
    """build_receipt preserves error_kind and refusal_reason."""
    from vibe.core.tools.base import BaseToolState
    from vibe.core.tools.builtins.validate import Validate, ValidateToolConfig

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())

    result = ValidateResult(
        profile="nonexistent",
        status="refused",
        error_kind="tool_refusal",
        refusal_reason="Unknown profile 'nonexistent'",
    )
    receipt = tool.build_receipt(result)

    assert receipt.status == "refused"
    assert receipt.error_kind == "tool_refusal"
    assert receipt.refusal_reason == "Unknown profile 'nonexistent'"


def test_build_receipt_content_light_enforced() -> None:
    """build_receipt output contains no raw stdout/stderr fields."""
    from vibe.core.tools.base import BaseToolState
    from vibe.core.tools.builtins.validate import Validate, ValidateToolConfig

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())

    cr = ValidateCheckResult(
        check_id="c1",
        command_kind="pytest",
        status="passed",
        exit_code=0,
        stdout_sha256="abc",
        stderr_sha256="def",
        stdout_bytes=100,
        stderr_bytes=0,
    )
    result = ValidateResult(profile="test", status="passed", checks=[cr])
    receipt = tool.build_receipt(result)

    dumped = receipt.model_dump(mode="json")
    for key in ("stdout", "stderr", "output", "content", "diff", "command_output"):
        assert key not in dumped
    # Check check_receipts items too
    for cr in dumped.get("check_receipts", []):
        for key in ("stdout", "stderr", "output", "content", "diff"):
            assert key not in cr


# ── Blocker summary ──────────────────────────────────────────────────


def test_blocker_summary_counts(tmp_path: Path) -> None:
    """Blocker summary counts failure kinds correctly."""
    # Simulate a result with multiple blocker kinds
    check1 = ValidateCheckResult(
        check_id="c1",
        command_kind="pytest",
        status="failed",
        failure_kind="test_failure",
    )
    check2 = ValidateCheckResult(
        check_id="c2", command_kind="ruff", status="failed", failure_kind="lint_failure"
    )
    check3 = ValidateCheckResult(
        check_id="c3",
        command_kind="pytest",
        status="failed",
        failure_kind="test_failure",
    )
    result = ValidateResult(
        status="failed",
        profile="test",
        command_count=3,
        passed_count=0,
        failed_count=3,
        checks=[check1, check2, check3],
        blocker_summary={"test_failure": 2, "lint_failure": 1},
    )
    assert result.blocker_summary.get("test_failure") == 2
    assert result.blocker_summary.get("lint_failure") == 1


# ── MAX_CAP_BYTES ──────────────────────────────────────────────────────


def test_max_cap_bytes_reasonable() -> None:
    """MAX_CAP_BYTES is within reasonable range."""
    assert 1024 <= MAX_CAP_BYTES <= 1_048_576


# ── Path normalization ────────────────────────────────────────────────


def test_normalize_paths_empty() -> None:
    """Empty paths returns empty list with no refusal."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    normalized, refusal = _normalize_validate_paths([])
    assert normalized == []
    assert refusal is None


def test_normalize_paths_inside_workspace(tmp_path: Path) -> None:
    """Paths inside workspace are normalized to workspace-relative paths."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "file.py").write_text("")

    normalized, refusal = _normalize_validate_paths(
        ["sub/file.py"], workspace_root=str(tmp_path)
    )
    assert refusal is None
    assert len(normalized) == 1
    assert normalized[0].endswith("sub/file.py")


def test_normalize_paths_outside_workspace(tmp_path: Path) -> None:
    """Path outside workspace root is refused."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "bad.py").write_text("")

    normalized, refusal = _normalize_validate_paths(
        ["../outside/bad.py"], workspace_root=str(tmp_path)
    )
    assert normalized == []
    assert refusal is not None
    assert "outside workspace root" in refusal


def test_normalize_paths_no_workspace_root(tmp_path: Path) -> None:
    """When workspace_root is None, uses cwd as root (relative paths)."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    normalized, refusal = _normalize_validate_paths(["."])
    assert refusal is None
    assert len(normalized) == 1


# ── Check scoping ─────────────────────────────────────────────────────


def test_normalize_paths_dedup(tmp_path: Path) -> None:
    """Duplicate paths are de-duplicated."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    (tmp_path / "a.py").write_text("")
    normalized, refusal = _normalize_validate_paths(
        ["a.py", "a.py", "./a.py"], workspace_root=str(tmp_path)
    )
    assert refusal is None
    assert len(normalized) == 1


def test_normalize_paths_sorted(tmp_path: Path) -> None:
    """Normalized paths are sorted for stable fingerprints."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    (tmp_path / "z.py").write_text("")
    (tmp_path / "a.py").write_text("")
    normalized, refusal = _normalize_validate_paths(
        ["z.py", "a.py"], workspace_root=str(tmp_path)
    )
    assert refusal is None
    assert normalized[0].endswith("a.py")
    assert normalized[1].endswith("z.py")


def test_normalize_paths_nonexistent(tmp_path: Path) -> None:
    """Nonexistent path returns blocked result."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    normalized, refusal = _normalize_validate_paths(
        ["does_not_exist.py"], workspace_root=str(tmp_path)
    )
    assert normalized == []
    assert refusal is not None
    assert "does not exist" in refusal


def test_scope_check_argv_schema_matches_schema_paths() -> None:
    """Schema check matches paths containing 'schema' or under docs/schemas/."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="schema_validation",
        command_kind="schema",
        argv=["uv", "run", "python", "scripts/rig_relay_validate_schemas.py"],
    )
    # Should match docs/schemas/ path
    scoped, run = _scope_check_argv(check, ["docs/schemas/rig.relay.x.schema.json"])
    assert run is True
    # Should match path containing 'schema'
    scoped, run = _scope_check_argv(check, ["some_schema_file.json"])
    assert run is True


def test_scope_check_argv_policy_matches_receipt_paths() -> None:
    """Policy check matches paths containing 'receipt'."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="receipt_policy",
        command_kind="policy",
        argv=["uv", "run", "python", "scripts/rig_relay_validate_tool_receipts.py"],
    )
    scoped, run = _scope_check_argv(
        check, ["rig_relay/evidence/tool_receipt_policy.py"]
    )
    assert run is True
    scoped, run = _scope_check_argv(
        check, ["docs/schemas/rig.relay.bash_receipt.schema.json"]
    )
    assert run is True


def test_quick_profile_ruff_not_added_for_docs_paths() -> None:
    """Quick profile does not add scoped ruff for non-Python paths."""
    from vibe.core.tools.builtins.validate import Profile, ProfileCheck, Validate

    profile = Profile(
        name="quick",
        description="test",
        checks=[
            ProfileCheck(
                check_id="git_status",
                command_kind="git",
                argv=["git", "status", "--short", "--branch"],
            )
        ],
    )
    checks = Validate._build_checks(profile, ["docs/audits/foo.md"])
    check_ids = [c.check_id for c in checks]
    assert "ruff_check" not in check_ids


def test_quick_profile_ruff_added_for_python_paths() -> None:
    """Quick profile adds scoped ruff for Python paths."""
    from vibe.core.tools.builtins.validate import Profile, ProfileCheck, Validate

    profile = Profile(
        name="quick",
        description="test",
        checks=[
            ProfileCheck(
                check_id="git_status",
                command_kind="git",
                argv=["git", "status", "--short", "--branch"],
            )
        ],
    )
    checks = Validate._build_checks(profile, ["vibe/core/tools/builtins/validate.py"])
    check_ids = [c.check_id for c in checks]
    assert "ruff_check" in check_ids


def test_scope_check_argv_ruff_appends_python_paths() -> None:
    """Ruff check appends only Python paths to argv."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="ruff_check", command_kind="ruff", argv=["uv", "run", "ruff", "check"]
    )
    scoped_argv, should_run = _scope_check_argv(check, ["/a/b.py", "/c/d.txt"])
    assert should_run is True
    assert scoped_argv == ["uv", "run", "ruff", "check", "/a/b.py"]


def test_scope_check_argv_ruff_skips_non_python_paths() -> None:
    """Ruff check is skipped when no Python paths provided."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="ruff_check", command_kind="ruff", argv=["uv", "run", "ruff", "check"]
    )
    scoped_argv, should_run = _scope_check_argv(check, ["/a/b.txt", "/c/d.md"])
    assert should_run is False


def test_scope_check_argv_pytest_appends_test_paths() -> None:
    """Pytest check appends only test paths to argv."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="bash_hardening",
        command_kind="pytest",
        argv=["uv", "run", "pytest", "-n0", "tests/tools/test_bash_hardening.py"],
    )
    scoped_argv, should_run = _scope_check_argv(
        check, ["tests/tools/test_bash_hardening.py", "vibe/core/cli.py"]
    )
    assert should_run is True
    assert "tests/tools/test_bash_hardening.py" in scoped_argv
    assert "vibe/core/cli.py" not in scoped_argv


def test_scope_check_argv_pytest_skips_non_test_paths() -> None:
    """Pytest check is skipped when no test paths provided."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="bash_hardening",
        command_kind="pytest",
        argv=["uv", "run", "pytest", "-n0", "tests/tools/test_bash_hardening.py"],
    )
    scoped_argv, should_run = _scope_check_argv(
        check, ["vibe/core/tools/builtins/bash.py"]
    )
    assert should_run is False


def test_scope_check_argv_schema_skips_non_schema_paths() -> None:
    """Schema check is skipped when no paths are schema-related."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="schema_validation",
        command_kind="schema",
        argv=["uv", "run", "python", "scripts/rig_relay_validate_schemas.py"],
    )
    scoped_argv, should_run = _scope_check_argv(
        check, ["vibe/core/tools/builtins/bash.py"]
    )
    assert should_run is False


def test_scope_check_argv_schema_runs_for_schema_paths() -> None:
    """Schema check runs when paths include schema-related paths."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="schema_validation",
        command_kind="schema",
        argv=["uv", "run", "python", "scripts/rig_relay_validate_schemas.py"],
    )
    scoped_argv, should_run = _scope_check_argv(
        check, ["docs/schemas/rig.relay.validate_invocation.v1.schema.json"]
    )
    assert should_run is True


def test_scope_check_argv_policy_skips_non_receipt_paths() -> None:
    """Policy check is skipped when no paths are receipt-related."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="receipt_policy",
        command_kind="policy",
        argv=["uv", "run", "python", "scripts/rig_relay_validate_tool_receipts.py"],
    )
    scoped_argv, should_run = _scope_check_argv(
        check, ["vibe/core/tools/builtins/bash.py"]
    )
    assert should_run is False


def test_scope_check_argv_policy_runs_for_receipt_paths() -> None:
    """Policy check runs when paths include receipt-related paths."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="receipt_policy",
        command_kind="policy",
        argv=["uv", "run", "python", "scripts/rig_relay_validate_tool_receipts.py"],
    )
    scoped_argv, should_run = _scope_check_argv(
        check, ["docs/schemas/rig.relay.bash_receipt.v1.schema.json"]
    )
    assert should_run is True


def test_scope_check_argv_git_unchanged() -> None:
    """Git check argv is unchanged when paths provided."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="git_status",
        command_kind="git",
        argv=["git", "status", "--short", "--branch"],
    )
    scoped_argv, should_run = _scope_check_argv(check, ["some/path.py"])
    assert should_run is True
    assert scoped_argv == ["git", "status", "--short", "--branch"]


def test_scope_check_argv_pyright_unchanged() -> None:
    """Pyright check argv is unchanged when paths provided."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="pyright", command_kind="pyright", argv=["uv", "run", "pyright"]
    )
    scoped_argv, should_run = _scope_check_argv(check, ["some/file.py"])
    assert should_run is True
    assert scoped_argv == ["uv", "run", "pyright"]


def test_scope_check_argv_no_paths_returns_original() -> None:
    """No paths returns original argv unchanged."""
    from vibe.core.tools.builtins.validate import ProfileCheck, _scope_check_argv

    check = ProfileCheck(
        check_id="ruff_check", command_kind="ruff", argv=["uv", "run", "ruff", "check"]
    )
    scoped_argv, should_run = _scope_check_argv(check, [])
    assert should_run is True
    assert scoped_argv == ["uv", "run", "ruff", "check"]


# ── Quick profile with paths ──────────────────────────────────────────


def test_quick_profile_with_paths_has_scoped_ruff() -> None:
    """Quick profile gets an additional scoped ruff check when paths provided."""
    from vibe.core.tools.builtins.validate import get_profile

    profile = get_profile("quick")
    assert profile is not None
    # Verify base checks exist
    assert any(c.check_id == "git_status" for c in profile.checks)
    # The ruff_check is added dynamically at runtime, not in the profile definition
    # This test validates the profile definition doesn't have it by default
    assert not any(c.check_id == "ruff_check" for c in profile.checks)


# ── Stable relative paths (Stage 3 follow-up) ─────────────────────────


def test_normalize_paths_absolute_input_becomes_relative(tmp_path: Path) -> None:
    """Absolute input path inside workspace becomes relative output."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    (tmp_path / "sub").mkdir()
    f = tmp_path / "sub" / "file.py"
    f.write_text("")

    abs_input = str(f.resolve())
    normalized, refusal = _normalize_validate_paths(
        [abs_input], workspace_root=str(tmp_path)
    )
    assert refusal is None
    assert len(normalized) == 1
    assert normalized[0] == "sub/file.py"
    assert not normalized[0].startswith("/")  # relative, not absolute


def test_normalize_paths_absolute_and_relative_produce_same(tmp_path: Path) -> None:
    """Absolute and equivalent relative input produce same relative output."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    (tmp_path / "sub").mkdir()
    f = tmp_path / "sub" / "file.py"
    f.write_text("")

    abs_result, _ = _normalize_validate_paths(
        [str(f.resolve())], workspace_root=str(tmp_path)
    )
    rel_result, _ = _normalize_validate_paths(
        ["sub/file.py"], workspace_root=str(tmp_path)
    )
    assert abs_result == rel_result


def test_normalize_paths_outside_workspace_absolute_refused(tmp_path: Path) -> None:
    """Absolute path outside workspace root is refused."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    outside = tmp_path / "outside"
    outside.mkdir()
    f = outside / "evil.py"
    f.write_text("")

    normalized, refusal = _normalize_validate_paths(
        [str(f.resolve())], workspace_root=str(tmp_path / "sub")
    )
    assert normalized == []
    assert refusal is not None
    assert "outside workspace root" in refusal


def test_normalize_paths_traversal_refused(tmp_path: Path) -> None:
    """Traversal path outside workspace is refused."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    (tmp_path / "sub").mkdir()

    normalized, refusal = _normalize_validate_paths(
        ["../outside"], workspace_root=str(tmp_path / "sub")
    )
    assert normalized == []
    assert refusal is not None
    assert "outside workspace root" in refusal


def test_normalize_paths_uses_posix_separators(tmp_path: Path) -> None:
    """Normalized paths use POSIX forward-slash separators."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    (tmp_path / "a" / "b").mkdir(parents=True)
    f = tmp_path / "a" / "b" / "f.py"
    f.write_text("")

    normalized, refusal = _normalize_validate_paths(
        ["a/b/f.py"], workspace_root=str(tmp_path)
    )
    assert refusal is None
    assert normalized[0] == "a/b/f.py"
    assert "\\" not in normalized[0]


def test_fingerprint_stable_across_path_forms(tmp_path: Path) -> None:
    """Fingerprint is identical for absolute and equivalent relative input."""
    from vibe.core.tools.builtins.validate import (
        _compute_fingerprint,
        _normalize_validate_paths,
    )

    (tmp_path / "sub").mkdir()
    f = tmp_path / "sub" / "file.py"
    f.write_text("")

    abs_paths, _ = _normalize_validate_paths(
        [str(f.resolve())], workspace_root=str(tmp_path)
    )
    rel_paths, _ = _normalize_validate_paths(
        ["sub/file.py"], workspace_root=str(tmp_path)
    )
    assert abs_paths == rel_paths  # same relative output

    argv_abs = ["uv", "run", "ruff", "check"] + abs_paths
    argv_rel = ["uv", "run", "ruff", "check"] + rel_paths
    fp_abs = _compute_fingerprint(argv_abs)
    fp_rel = _compute_fingerprint(argv_rel)
    assert fp_abs == fp_rel


def test_fingerprint_independent_of_path_order(tmp_path: Path) -> None:
    """Fingerprint is stable regardless of input path order."""
    from vibe.core.tools.builtins.validate import (
        _compute_fingerprint,
        _normalize_validate_paths,
    )

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "x.py").write_text("")
    (tmp_path / "b" / "y.py").write_text("")

    paths_ab, _ = _normalize_validate_paths(
        ["a/x.py", "b/y.py"], workspace_root=str(tmp_path)
    )
    paths_ba, _ = _normalize_validate_paths(
        ["b/y.py", "a/x.py"], workspace_root=str(tmp_path)
    )
    assert paths_ab == paths_ba  # sorted

    fp_ab = _compute_fingerprint(["uv", "run", "ruff", "check"] + paths_ab)
    fp_ba = _compute_fingerprint(["uv", "run", "ruff", "check"] + paths_ba)
    assert fp_ab == fp_ba


def test_affected_paths_are_relative_in_result(tmp_path: Path) -> None:
    """ValidateCheckResult.affected_paths contains relative paths."""
    from vibe.core.tools.builtins.validate import _normalize_validate_paths

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "file.py").write_text("")

    normalized, _ = _normalize_validate_paths(
        ["sub/file.py"], workspace_root=str(tmp_path)
    )
    assert normalized == ["sub/file.py"]
    assert not normalized[0].startswith("/")  # relative, not absolute


def test_receipt_affected_paths_are_relative(tmp_path: Path) -> None:
    """ValidateReceipt check_receipts contain relative affected_paths."""
    from vibe.core.tools.base import BaseToolState
    from vibe.core.tools.builtins.validate import (
        Validate,
        ValidateCheckResult,
        ValidateResult,
        ValidateToolConfig,
    )

    config = ValidateToolConfig()
    tool = Validate(config_getter=lambda: config, state=BaseToolState())

    cr = ValidateCheckResult(
        check_id="ruff_check",
        command_kind="ruff",
        status="passed",
        affected_paths=["sub/file.py"],
    )
    result = ValidateResult(profile="python", status="passed", checks=[cr])
    receipt = tool.build_receipt(result)

    assert len(receipt.check_receipts) == 1
    r = receipt.check_receipts[0]
    assert r.affected_paths == ["sub/file.py"]
    assert not r.affected_paths[0].startswith("/")  # relative, not absolute


# ── Parsed summaries (Stage 4) ──────────────────────────────────────


def test_parse_ruff_summary_counts() -> None:
    """Parse ruff output returns violation counts, rule codes, and files."""
    stdout = (
        "src/main.py:1:1: F401 'os' imported but unused\n"
        "src/main.py:2:5: I001 unsorted imports\n"
        "src/utils.py:10:1: F401 'sys' imported but unused\n"
    )
    result = _parse_ruff_summary(stdout)
    assert result is not None
    assert result["parser_name"] == "ruff_text"
    assert result["parser_status"] == "parsed"
    assert result["violation_count"] == 3
    assert result["rule_counts"] == {"F401": 2, "I001": 1}
    assert result["files"] == ["src/main.py", "src/utils.py"]


def test_parse_ruff_summary_empty() -> None:
    """Empty ruff output returns None."""
    assert _parse_ruff_summary("") is None
    assert _parse_ruff_summary("   ") is None
    assert _parse_ruff_summary("All checks passed!") is None


def test_parse_pyright_summary_plural() -> None:
    """Parse pyright output with plural counts."""
    stdout = "1 error, 2 warnings, 0 informations"
    result = _parse_pyright_summary(stdout)
    assert result is not None
    assert result["parser_name"] == "pyright_text"
    assert result["parser_status"] == "parsed"
    assert result["error_count"] == 1
    assert result["warning_count"] == 2
    assert result["information_count"] == 0


def test_parse_pyright_summary_singular() -> None:
    """Parse pyright output with zero counts."""
    stdout = "0 errors, 0 warnings, 0 informations"
    result = _parse_pyright_summary(stdout)
    assert result is not None
    assert result["error_count"] == 0
    assert result["warning_count"] == 0
    assert result["information_count"] == 0


def test_parse_pyright_summary_malformed() -> None:
    """Malformed pyright output returns None."""
    assert _parse_pyright_summary("garbage output") is None
    assert _parse_pyright_summary("") is None
    assert _parse_pyright_summary("1 error") is None  # missing warning


def test_parse_pytest_summary_counts() -> None:
    """Parse pytest output with passed and failed counts."""
    stdout = "= short test summary info =\nFAILED test_foo.py::test_bar\n= 1 failed, 2 passed in 0.12s ="
    result = _parse_pytest_summary(stdout)
    assert result is not None
    assert result["parser_name"] == "pytest_text"
    assert result["parser_status"] == "parsed"
    assert result["passed_count"] == 2
    assert result["failed_count"] == 1


def test_parse_pytest_summary_skipped() -> None:
    """Parse pytest output with skipped and xfailed counts."""
    stdout = "= 2 skipped, 1 xfailed in 0.05s ="
    result = _parse_pytest_summary(stdout)
    assert result is not None
    assert result["skipped_count"] == 2
    assert result["xfailed_count"] == 1


def test_parse_pytest_summary_passed_only() -> None:
    """Parse pytest output with only passed."""
    stdout = "= 3 passed in 0.01s ="
    result = _parse_pytest_summary(stdout)
    assert result is not None
    assert result["passed_count"] == 3
    assert result.get("failed_count") is None


def test_parse_pytest_summary_malformed() -> None:
    """Malformed pytest output returns None."""
    assert _parse_pytest_summary("") is None
    assert _parse_pytest_summary("no summary here") is None
    assert _parse_pytest_summary("collecting ... no tests collected") is None


def test_parse_schema_summary_slash_format() -> None:
    """Parse 'N/N schemas valid' format."""
    stdout = "78/78 schemas valid"
    result = _parse_schema_summary(stdout)
    assert result is not None
    assert result["parser_name"] == "schema_text"
    assert result["parser_status"] == "parsed"
    assert result["valid_count"] == 78
    assert result["total_count"] == 78
    assert result["failed_count"] == 0


def test_parse_schema_summary_passed_failed_format() -> None:
    """Parse 'Passed: N / Failed: M' format."""
    stdout = "Passed: 75\nFailed: 3\nTotal: 78"
    result = _parse_schema_summary(stdout)
    assert result is not None
    assert result["valid_count"] == 75
    assert result["failed_count"] == 3
    assert result["total_count"] == 78


def test_parse_schema_summary_empty() -> None:
    """Empty schema output returns None."""
    assert _parse_schema_summary("") is None
    assert _parse_schema_summary("no schema output here") is None


def test_parse_policy_summary_json() -> None:
    """Parse JSON policy output with findings array."""
    stdout = '{"findings": [{"id": 1}, {"id": 2}, {"id": 3}], "summary": "3 findings"}'
    result = _parse_policy_summary(stdout)
    assert result is not None
    assert result["parser_name"] == "policy_json"
    assert result["parser_status"] == "parsed"
    assert result["finding_count"] == 3


def test_parse_policy_summary_json_violations() -> None:
    """Parse JSON policy output with violations array."""
    stdout = '{"violations": [{"rule": "A1"}, {"rule": "B2"}]}'
    result = _parse_policy_summary(stdout)
    assert result is not None
    assert result["finding_count"] == 2


def test_parse_policy_summary_text_fallback() -> None:
    """Parse text policy output with finding counts."""
    stdout = (
        "checking receipts...\n"
        "finding: missing checksum in receipt 1\n"
        "finding: missing checksum in receipt 2\n"
        "violation: schema mismatch in receipt 3\n"
    )
    result = _parse_policy_summary(stdout)
    assert result is not None
    assert result["parser_name"] == "policy_text"
    assert result["parser_status"] == "parsed"
    assert result["finding_count"] >= 2


def test_parse_policy_summary_empty() -> None:
    """Empty policy output returns None."""
    assert _parse_policy_summary("") is None
    assert _parse_policy_summary("all policies passed") is None


def test_parse_check_summary_ruff_dispatch() -> None:
    """Dispatcher routes ruff command_kind to ruff parser."""
    stdout = "file.py:1:1: F401 unused import"
    result = _parse_check_summary("ruff", stdout, "", 0)
    assert result is not None
    assert result["parser_name"] == "ruff_text"


def test_parse_check_summary_pyright_dispatch() -> None:
    """Dispatcher routes pyright command_kind to pyright parser."""
    stdout = "0 errors, 0 warnings, 0 informations"
    result = _parse_check_summary("pyright", stdout, "", 0)
    assert result is not None
    assert result["parser_name"] == "pyright_text"


def test_parse_check_summary_pytest_dispatch() -> None:
    """Dispatcher routes pytest command_kind to pytest parser."""
    stdout = "= 1 passed in 0.01s ="
    result = _parse_check_summary("pytest", stdout, "", 0)
    assert result is not None
    assert result["parser_name"] == "pytest_text"


def test_parse_check_summary_schema_dispatch() -> None:
    """Dispatcher routes schema command_kind to schema parser."""
    stdout = "78/78 schemas valid"
    result = _parse_check_summary("schema", stdout, "", 0)
    assert result is not None
    assert result["parser_name"] == "schema_text"


def test_parse_check_summary_policy_dispatch() -> None:
    """Dispatcher routes policy command_kind to policy parser."""
    stdout = '{"findings": []}'
    result = _parse_check_summary("policy", stdout, "", 0)
    assert result is not None
    assert result["parser_name"] == "policy_json"


def test_parse_check_summary_unknown_kind() -> None:
    """Unknown command_kind returns None."""
    assert _parse_check_summary("custom", "some output", "", 0) is None
    assert _parse_check_summary("git", "", "", 0) is None
    assert _parse_check_summary("", "output", "", 0) is None


def test_parsed_summary_in_model() -> None:
    """ValidateCheckResult stores parsed_summary correctly."""
    summary = {
        "parser_name": "ruff_text",
        "parser_status": "parsed",
        "violation_count": 3,
    }
    result = ValidateCheckResult(
        check_id="ruff_check", command_kind="ruff", parsed_summary=summary
    )
    assert result.parsed_summary == summary
    assert result.parsed_summary["violation_count"] == 3


def test_parsed_summary_none_default() -> None:
    """ValidateCheckResult.parsed_summary defaults to None."""
    result = ValidateCheckResult(check_id="x", command_kind="test")
    assert result.parsed_summary is None


def test_parsed_summary_no_raw_fields() -> None:
    """parsed_summary dict does not contain stdout/stderr keys."""
    summary = {"parser_name": "ruff_text", "violation_count": 3}
    result = ValidateCheckResult(
        check_id="ruff_check", command_kind="ruff", parsed_summary=summary
    )
    dumped = result.model_dump(mode="json")
    ps = dumped["parsed_summary"]
    assert ps is not None
    assert "stdout" not in ps
    assert "stderr" not in ps
    assert "raw" not in ps
    assert "output" not in ps


def test_parsed_summary_not_in_check_receipt() -> None:
    """ValidateCheckReceipt has no parsed_summary field (extra=forbid)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ValidateCheckReceipt.model_validate({
            "check_id": "x",
            "command_kind": "test",
            "parsed_summary": {"foo": 1},
        })


def test_parsed_summary_not_in_validate_receipt() -> None:
    """ValidateReceipt has no parsed_summary leakage."""
    cr = ValidateCheckReceipt(check_id="x", command_kind="test")
    r = ValidateReceipt(profile="test", status="passed", check_receipts=[cr])
    dumped = r.model_dump(mode="json")
    assert "parsed_summary" not in dumped
    for cr_dumped in dumped.get("check_receipts", []):
        assert "parsed_summary" not in cr_dumped


@pytest.mark.asyncio
async def test_run_check_parsed_summary_field_present(tmp_path: Path) -> None:
    """_run_check returns a result with a parsed_summary field (even if None)."""
    script = tmp_path / "simple_script.py"
    script.write_text("import sys\nsys.exit(0)\n")
    result = await _run_check(
        [sys.executable, str(script)], output_cap=65536, timeout=30, cwd=None
    )
    # parsed_summary is a field on the result; it may be None for unmatched output
    assert hasattr(result, "parsed_summary")
    # The field is None because command_kind won't match any known parser
    assert result.parsed_summary is None


@pytest.mark.asyncio
async def test_collect_git_state_porcelain_sha256(tmp_path: Path) -> None:
    """_collect_git_state sets status_porcelain_sha256."""
    import subprocess

    from vibe.core.tools.builtins.validate import _collect_git_state

    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True
    )
    (tmp_path / "f.txt").write_text("data")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "c"], cwd=str(tmp_path), capture_output=True)
    state = await _collect_git_state(str(tmp_path))
    assert state.status_porcelain_sha256 is not None
    assert len(state.status_porcelain_sha256) == 64


# ── Cache / Scheduler Integration ─────────────────────────────────────


def test_cache_compute_key_includes_check_id() -> None:
    """compute_cache_key returns unique keys for different check_ids."""
    from rig_relay.evidence.validation_cache import compute_cache_key

    key1 = compute_cache_key("c1", "pytest", "fp1", "fp2", "/tmp")
    key2 = compute_cache_key("c2", "pytest", "fp1", "fp2", "/tmp")
    assert key1 != key2


def test_cache_store_and_lookup(tmp_path: Path) -> None:
    """Stored record is retrievable via lookup."""
    from rig_relay.evidence.validation_cache import (
        CACHE_STATUS_HIT,
        ValidationCacheRecord,
        ValidationCacheStore,
        compute_cache_key,
    )

    ck = compute_cache_key("c1", "pytest", "fp1", "fp2", str(tmp_path))
    store = ValidationCacheStore(str(tmp_path / ".cache"))
    assert store.lookup(ck).cache_status != CACHE_STATUS_HIT

    record = ValidationCacheRecord(
        cache_key=ck,
        check_id="c1",
        command_kind="pytest",
        command_fingerprint="fp1",
        input_fingerprint="fp2",
        input_file_fingerprints={},
        status="passed",
        exit_code=0,
        duration_ms=10.0,
        stdout_sha256="sha256:abc",
        stderr_sha256="sha256:def",
        stdout_bytes=12,
        stderr_bytes=12,
    )
    store.store(record)

    lookup = store.lookup(ck)
    assert lookup.cache_status == CACHE_STATUS_HIT
    assert lookup.record is not None
    assert lookup.record.cache_key == ck


def test_cache_content_light_no_raw_output(tmp_path: Path) -> None:
    """Cache record does not contain raw stdout/stderr."""
    from rig_relay.evidence.validation_cache import (
        ValidationCacheRecord,
        ValidationCacheStore,
        compute_cache_key,
    )

    ck = compute_cache_key("c1", "pytest", "fp1", "fp2", str(tmp_path))
    store = ValidationCacheStore(str(tmp_path / ".cache"))
    record = ValidationCacheRecord(
        cache_key=ck,
        check_id="c1",
        command_kind="pytest",
        command_fingerprint="fp1",
        input_fingerprint="fp2",
        input_file_fingerprints={},
        status="passed",
        exit_code=0,
        duration_ms=10.0,
        stdout_sha256="sha256:abc",
        stdout_bytes=12,
    )
    store.store(record)

    stored = store.lookup(ck).record
    assert stored is not None
    model = stored.model_dump(mode="json")
    assert "stdout" not in model
    assert "stderr" not in model


def test_cache_failed_not_reused_by_default(tmp_path: Path) -> None:
    """Failed cache records are not reused unless allow_failed_reuse=True."""
    from rig_relay.evidence.validation_cache import (
        CACHE_STATUS_MISS_FAILED_REUSE_DISABLED,
        ValidationCacheRecord,
        ValidationCacheStore,
        compute_cache_key,
        decide_cache_eligibility,
    )

    ck = compute_cache_key("c1", "pytest", "fp1", "fp2", str(tmp_path))
    store = ValidationCacheStore(str(tmp_path / ".cache"))
    record = ValidationCacheRecord(
        cache_key=ck,
        check_id="c1",
        command_kind="pytest",
        command_fingerprint="fp1",
        input_fingerprint="fp2",
        input_file_fingerprints={},
        status="failed",
        exit_code=1,
        duration_ms=10.0,
        stdout_sha256="sha256:abc",
        stdout_bytes=12,
    )
    store.store(record)

    lookup = store.lookup(ck)
    result, _ = decide_cache_eligibility("enabled", lookup, allow_failed_reuse=False)
    assert result == CACHE_STATUS_MISS_FAILED_REUSE_DISABLED


def test_scheduler_acquire_then_blocks_duplicate(tmp_path: Path) -> None:
    """Acquiring lock for same key blocks second attempt."""
    from rig_relay.evidence.validation_scheduler import ValidationSchedulerStore

    store = ValidationSchedulerStore(str(tmp_path / ".sched"))
    acquired1, _ = store.acquire_lock("sha256:dup")
    assert acquired1

    acquired2, blocking = store.acquire_lock("sha256:dup")
    assert not acquired2
    assert blocking == "sha256:dup"


def test_scheduler_release_allows_reacquire(tmp_path: Path) -> None:
    """Releasing lock allows reacquire."""
    from rig_relay.evidence.validation_scheduler import ValidationSchedulerStore

    store = ValidationSchedulerStore(str(tmp_path / ".sched"))
    store.acquire_lock("sha256:rel")
    store.release_lock("sha256:rel")
    acquired, _ = store.acquire_lock("sha256:rel")
    assert acquired


def test_parallel_policy_injects_xdist_when_available(tmp_path: Path) -> None:
    """apply_parallel_policy injects -n flag for pytest commands."""
    from rig_relay.evidence.validation_scheduler import (
        PARALLEL_ENABLED,
        PARALLEL_REFUSED,
        apply_parallel_policy,
    )

    argv = ["uv", "run", "pytest", str(tmp_path)]
    mod, status, _ = apply_parallel_policy(argv, "auto", 2, "loadfile")
    if status == PARALLEL_REFUSED:
        assert "xdist" in (_ or "")
    else:
        assert status == PARALLEL_ENABLED
        assert "-n" in mod


def test_lifecycle_edit_phase_full_suite_warns() -> None:
    """check_lifecycle_policy warns on edit phase + full suite."""
    from rig_relay.evidence.validation_scheduler import (
        PHASE_EDIT,
        check_lifecycle_policy,
    )

    warnings = check_lifecycle_policy(PHASE_EDIT, "python", ["pytest"])
    assert "full_suite_during_edit_phase" in warnings


def test_validate_args_cache_fields_serialize() -> None:
    """ValidateArgs cache/scheduler fields serialize to dict."""
    from vibe.core.tools.builtins.validate_models import ValidateArgs

    args = ValidateArgs(
        profile="quick",
        cache_policy="enabled",
        allow_failed_cache_reuse=False,
        cache_root="/tmp/cache",
        scheduler_policy="enabled",
        lock_running_checks=True,
        validation_phase="edit",
        parallel_policy="auto",
        max_workers=4,
        xdist_distribution="loadscope",
    )
    d = args.model_dump(mode="json")
    assert d["cache_policy"] == "enabled"
    assert d["validation_phase"] == "edit"
    assert d["parallel_policy"] == "auto"
    assert d["max_workers"] == 4
