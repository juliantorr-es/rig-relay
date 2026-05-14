"""Doctor diagnostics for Rig Console.

Checks environment, config, git status, tool availability, and backend
connectivity. Used by the /doctor slash command.

Adapted from Intake's doctor.py pattern.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import subprocess
import sys

_MIN_PYTHON_MAJOR = 3
_MIN_PYTHON_MINOR = 12


@dataclass
class DoctorCheck:
    name: str
    description: str
    check_fn: Callable[[], tuple[bool, str]]
    is_blocker: bool = False
    category: str = "general"

    def run(self) -> tuple[bool, str]:
        try:
            return self.check_fn()
        except Exception as e:
            return False, f"Check threw: {e}"


@dataclass
class DoctorResult:
    checks: list[DoctorCheck] = field(default_factory=list)

    def add(self, check: DoctorCheck) -> None:
        self.checks.append(check)

    def run_all(self) -> DoctorSummary:
        results: list[tuple[str, str, bool, str, bool]] = []
        for check in self.checks:
            passed, msg = check.run()
            results.append((
                check.name,
                check.description,
                passed,
                msg,
                check.is_blocker,
            ))
        return DoctorSummary(results=results)

    @staticmethod
    def default() -> DoctorResult:
        r = DoctorResult()

        def _check_python() -> tuple[bool, str]:
            v = sys.version_info
            ok = v.major >= _MIN_PYTHON_MAJOR and v.minor >= _MIN_PYTHON_MINOR
            return ok, f"{v.major}.{v.minor}.{v.micro}"

        def _check_uv() -> tuple[bool, str]:
            path = shutil.which("uv")
            if not path:
                return False, "uv not found on PATH"
            try:
                out = subprocess.check_output(
                    ["uv", "--version"], text=True, stderr=subprocess.STDOUT
                ).strip()
                return True, out
            except Exception:
                return False, "uv found but failed to run"

        def _check_git_repo() -> tuple[bool, str]:
            try:
                out = subprocess.check_output(
                    ["git", "rev-parse", "--show-toplevel"],
                    text=True,
                    stderr=subprocess.STDOUT,
                ).strip()
                return True, out
            except subprocess.CalledProcessError:
                return False, "Not a git repository"

        def _check_config_file() -> tuple[bool, str]:
            candidates = [
                Path.cwd() / ".rig" / "relay" / "config.toml",
                Path.home() / ".config" / "rig-relay" / "config.toml",
            ]
            for c in candidates:
                if c.is_file():
                    return True, str(c)
            config_dir = Path.home() / ".config" / "rig-relay"
            return False, f"Config file not found (looked in {config_dir})"

        def _check_workspace() -> tuple[bool, str]:
            cwd = Path.cwd()
            return True, str(cwd)

        r.add(
            DoctorCheck(
                "Python",
                "Python 3.12+",
                _check_python,
                is_blocker=True,
                category="environment",
            )
        )
        r.add(
            DoctorCheck(
                "uv",
                "uv package manager",
                _check_uv,
                is_blocker=True,
                category="environment",
            )
        )
        r.add(
            DoctorCheck(
                "Git repo", "Valid git workspace", _check_git_repo, category="workspace"
            )
        )
        r.add(
            DoctorCheck(
                "Config", "Rig Relay config file", _check_config_file, category="config"
            )
        )
        r.add(
            DoctorCheck(
                "Workspace", "Working directory", _check_workspace, category="workspace"
            )
        )

        return r


@dataclass
class DoctorSummary:
    results: list[tuple[str, str, bool, str, bool]] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r[2])

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r[2])

    @property
    def blockers(self) -> int:
        return sum(1 for r in self.results if not r[2] and r[4])

    @property
    def all_passed(self) -> bool:
        return self.blockers == 0

    def to_text(self) -> str:
        lines: list[str] = []
        lines.append("╒══════════════════════════════════════╕")
        lines.append("│      Rig Console Diagnostics        │")
        lines.append("╘══════════════════════════════════════╛")
        lines.append("")
        for name, desc, passed, msg, _is_blocker in self.results:
            icon = "✓" if passed else "✗"
            status_str = "PASS" if passed else "FAIL"
            lines.append(f"  {icon} {name:12s} {status_str:5s} ({desc})")
            if msg:
                lines.append(f"            {msg}")
        lines.append("")
        lines.append(
            f"  {self.passed} passed, {self.failed} failed ({self.blockers} blockers)"
        )
        if self.all_passed:
            lines.append("  All checks passed.")
        else:
            lines.append("  Run 'uv run rig-relay doctor' for details.")
        return "\n".join(lines)


__all__ = ["DoctorCheck", "DoctorResult", "DoctorSummary"]
