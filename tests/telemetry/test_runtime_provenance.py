from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from rig_relay.core.telemetry.runtime import (
    RuntimeProvenanceResult,
    _check_critical_symbols,
    check_runtime_provenance,
    format_provenance_report,
    get_module_path,
    provenance_to_dict,
)


def _mock_which(path: str | None = None) -> Callable:
    def _which(cmd: str) -> str | None:
        if cmd == "rig-relay":
            return path
        return None

    return _which


class TestCriticalSymbols:
    """Critical symbol presence checks are read-only and make no network calls."""

    def test_all_symbols_present(self) -> None:
        """In a coherent install, all critical symbols should be importable."""
        symbols = _check_critical_symbols()
        for name, found in symbols.items():
            assert found, f"Critical symbol '{name}' should be importable"

    def test_returns_dict_with_all_keys(self) -> None:
        symbols = _check_critical_symbols()
        expected = {
            "write_assembly_report",
            "validate_evidence_session",
            "write_session_manifest",
            "write_session_receipts",
        }
        assert set(symbols.keys()) == expected


class TestModulePath:
    """Module path resolution is read-only and returns expected types."""

    def test_vibe_core_agent_loop(self) -> None:
        path = get_module_path("vibe.core.agent_loop")
        assert path is not None
        assert "agent_loop.py" in path

    def test_vibe_core_context_assembler(self) -> None:
        path = get_module_path("vibe.core.context.assembler")
        assert path is not None
        assert "assembler.py" in path

    def test_bogus_module_returns_none(self) -> None:
        path = get_module_path("vibe.core.does_not_exist_xyz")
        assert path is None


class TestFormatProvenanceReport:
    """Formatting is pure string munging, no side effects."""

    def test_contains_key_fields(self) -> None:
        result = RuntimeProvenanceResult(
            python_executable="/usr/bin/python3",
            rig_relay_command="/usr/local/bin/rig-relay",
            package_path="/some/checkout/vibe",
            agent_loop_path="/some/checkout/vibe/core/agent_loop.py",
            assembler_path="/some/checkout/vibe/core/context/assembler.py",
            git_head_sha="abc1234",
            installed_version="2.9.6",
            critical_symbols={"write_assembly_report": True},
            warnings=[],
            coherent=True,
        )
        report = format_provenance_report(result)
        assert "Python executable" in report
        assert "rig-relay command" in report
        assert "Package path" in report
        assert "agent_loop.py" in report
        assert "assembler.py" in report
        assert "Git HEAD" in report
        assert "abc1234" in report
        assert "PASS" in report

    def test_warning_section_when_present(self) -> None:
        result = RuntimeProvenanceResult(
            python_executable="/usr/bin/python3",
            rig_relay_command=None,
            package_path="/some/vibe",
            agent_loop_path=None,
            assembler_path=None,
            git_head_sha=None,
            installed_version="2.9.6",
            critical_symbols={"write_assembly_report": True},
            warnings=["Something looks off"],
            coherent=False,
        )
        report = format_provenance_report(result)
        assert "Something looks off" in report
        assert "FAIL" in report


class TestProvenanceToDict:
    """Serialization to dict includes all fields."""

    def test_round_trip(self) -> None:
        result = RuntimeProvenanceResult(
            python_executable="/usr/bin/python3",
            rig_relay_command="/usr/bin/rig-relay",
            package_path="/pkg/vibe",
            agent_loop_path="/pkg/vibe/core/agent_loop.py",
            assembler_path="/pkg/vibe/core/context/assembler.py",
            git_head_sha="deadbeef",
            installed_version="2.9.6",
            critical_symbols={"write_assembly_report": True},
            warnings=[],
            coherent=True,
        )
        d = provenance_to_dict(result)
        assert d["python_executable"] == "/usr/bin/python3"
        assert d["coherent"] is True
        assert d["critical_symbols"]["write_assembly_report"] is True
        assert d["git_head_sha"] == "deadbeef"


class TestCheckRuntimeProvenance:
    """Integration-style tests for the full check, mocked where needed."""

    def test_provenance_includes_python_executable(self) -> None:
        with (
            patch(
                "vibe.core.telemetry.runtime.shutil.which",
                _mock_which("/usr/bin/rig-relay"),
            ),
            patch("vibe.core.telemetry.runtime.Path", autospec=True) as mock_path,
        ):
            mock_path.return_value.resolve.return_value = Path("/usr/bin/rig-relay")
            result = check_runtime_provenance()
            assert result.python_executable != ""
            assert isinstance(result.python_executable, str)

    def test_provenance_includes_package_path(self) -> None:
        result = check_runtime_provenance()
        assert "vibe" in result.package_path

    def test_provenance_includes_installed_version(self) -> None:
        result = check_runtime_provenance()
        assert result.installed_version != ""

    def test_no_provider_call_made(self) -> None:
        """The check should not import or call any provider module."""
        import sys as sys_mod

        before = set(sys_mod.modules.keys())
        check_runtime_provenance()
        after = set(sys_mod.modules.keys())
        new_modules = after - before
        provider_modules = {m for m in new_modules if "mistral" in m or "provider" in m}
        assert len(provider_modules) == 0, (
            f"Provider modules were loaded: {provider_modules}"
        )

    def test_read_only_no_side_effects(self, tmp_path: Path) -> None:
        """The check should not create or modify files."""
        files_before = set(tmp_path.rglob("*"))
        check_runtime_provenance()
        files_after = set(tmp_path.rglob("*"))
        assert files_before == files_after
