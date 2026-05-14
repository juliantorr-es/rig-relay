from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from rig_relay import __version__

_CRITICAL_SYMBOLS = [
    "write_assembly_report",
    "validate_evidence_session",
    "write_session_manifest",
    "write_session_receipts",
]


@dataclass
class RuntimeProvenanceResult:
    """Read-only diagnostic result for runtime provenance checks."""

    python_executable: str
    rig_relay_command: str | None
    package_path: str
    agent_loop_path: str | None
    assembler_path: str | None
    git_head_sha: str | None
    installed_version: str
    critical_symbols: dict[str, bool]
    warnings: list[str] = field(default_factory=list)
    coherent: bool = True


def _get_git_head() -> str | None:
    """Return short SHA of HEAD if running inside a git checkout."""
    try:
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        git_dir = repo_root / ".git"
        if not git_dir.exists():
            return None
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def resolve_repo_root() -> Path | None:
    """Resolve repository root from vibe package location."""
    pkg = RIG_ROOT.resolve()
    for parent in [pkg] + list(pkg.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _check_critical_symbols() -> dict[str, bool]:
    """Try to import each critical symbol and report presence."""
    results: dict[str, bool] = {}
    for name in _CRITICAL_SYMBOLS:
        try:
            if name == "write_assembly_report":
                from rig_relay.context.assembler import (
                    write_assembly_report,  # noqa: F401
                )
            elif name == "validate_evidence_session":
                from rig_relay.core.telemetry.validation import (
                    validate_evidence_session,  # noqa: F401
                )
            elif name == "write_session_manifest":
                from rig_relay.core.telemetry.manifest import (
                    write_session_manifest,  # noqa: F401
                )
            elif name == "write_session_receipts":
                from rig_relay.core.telemetry.receipts import (
                    write_session_receipts,  # noqa: F401
                )
            results[name] = True
        except ImportError:
            results[name] = False
    return results


def get_module_path(module_name: str) -> str | None:
    """Get the file path of a module, or None if import fails."""
    try:
        mod = importlib.import_module(module_name)
        return str(Path(mod.__file__).resolve()) if mod.__file__ else None
    except Exception:
        return None


def _package_root(path_str: str) -> Path | None:
    """Walk up from a module file to find the 'rig-relay' package root."""
    p = Path(path_str).resolve()
    for parent in [p] + list(p.parents):
        if parent.name == "rig-relay" and (parent.parent / "pyproject.toml").exists():
            return parent
    return None


def _is_dev_checkout(agent_loop_path: str, pkg_path: str) -> bool:
    """Return True if modules resolve inside a development checkout with .git."""
    loop_pkg = _package_root(agent_loop_path) if agent_loop_path else None
    if loop_pkg is None:
        loop_pkg = Path(pkg_path).resolve() if pkg_path else None
    if loop_pkg and (loop_pkg.parent / ".git").exists():
        return True
    return False


def check_runtime_provenance() -> RuntimeProvenanceResult:
    """Check runtime provenance for the current Rig Relay process.

    This is a read-only diagnostic. It does not modify any state, make
    network calls, or change provider configuration.
    """
    warnings: list[str] = []
    coherent = True

    python_exe = sys.executable
    rig_relay_cmd = shutil.which("rig-relay")
    pkg_path = str(RIG_ROOT.resolve())
    agent_loop_path = get_module_path("vibe.core.agent_loop")
    assembler_path = get_module_path("vibe.core.context.assembler")
    git_head = _get_git_head()
    symbols = _check_critical_symbols()

    if any(not found for found in symbols.values()):
        missing = ", ".join(n for n, f in symbols.items() if not f)
        warnings.append(f"Missing critical symbols: {missing}")
        coherent = False

    if rig_relay_cmd and _is_dev_checkout(agent_loop_path or "", pkg_path):
        cr = Path(rig_relay_cmd).resolve()
        pr = Path(pkg_path).resolve()
        if "uv/tools" in str(cr) and str(cr.parent.parent) not in str(pr):
            warnings.append(
                "rig-relay command resolves to uv tool environment "
                f"({cr}), while modules load from checkout "
                f"({pr}). The tool install is stale. "
                "Run 'uv tool install --reinstall .' from the checkout."
            )
            coherent = False

    if agent_loop_path and assembler_path:
        lp = _package_root(agent_loop_path)
        ap = _package_root(assembler_path)
        if lp and ap and lp != ap:
            warnings.append(
                f"Module paths disagree: {agent_loop_path} vs {assembler_path}. "
                "This suggests a mixed install."
            )
            coherent = False

    return RuntimeProvenanceResult(
        python_executable=python_exe,
        rig_relay_command=rig_relay_cmd,
        package_path=pkg_path,
        agent_loop_path=agent_loop_path,
        assembler_path=assembler_path,
        git_head_sha=git_head,
        installed_version=__version__,
        critical_symbols=symbols,
        warnings=warnings,
        coherent=coherent,
    )


def format_provenance_report(result: RuntimeProvenanceResult) -> str:
    """Format a human-readable runtime provenance report."""
    lines: list[str] = []
    lines.append("[bold]Runtime Provenance[/]")
    lines.append("")
    lines.append(f"  [bold]Python executable:[/] {result.python_executable}")
    lines.append(
        f"  [bold]rig-relay command:[/] {result.rig_relay_command or 'not found'}"
    )
    lines.append(f"  [bold]Package path:[/] {result.package_path}")
    lines.append(
        f"  [bold]agent_loop.py:[/] {result.agent_loop_path or 'import failed'}"
    )
    lines.append(f"  [bold]assembler.py:[/] {result.assembler_path or 'import failed'}")
    lines.append(f"  [bold]Git HEAD:[/] {result.git_head_sha or 'not a git checkout'}")
    lines.append(f"  [bold]Installed version:[/] {result.installed_version}")
    lines.append("")
    lines.append("[bold]Critical Symbols:[/]")
    for name, found in sorted(result.critical_symbols.items()):
        status = "[green]OK[/]" if found else "[red]MISSING[/]"
        lines.append(f"    {name}: {status}")
    lines.append("")
    if result.warnings:
        lines.append("[bold yellow]Warnings:[/]")
        for w in result.warnings:
            lines.append(f"  [yellow]- {w}[/]")
        lines.append("")
    status = "[green]PASS[/]" if result.coherent else "[red]FAIL[/]"
    lines.append(f"[bold]Coherent:[/] {status}")
    return "\n".join(lines)


def provenance_to_dict(result: RuntimeProvenanceResult) -> dict[str, Any]:
    """Serialize provenance result to a dict (for JSON output)."""
    return {
        "python_executable": result.python_executable,
        "rig_relay_command": result.rig_relay_command,
        "package_path": result.package_path,
        "agent_loop_path": result.agent_loop_path,
        "assembler_path": result.assembler_path,
        "git_head_sha": result.git_head_sha,
        "installed_version": result.installed_version,
        "critical_symbols": result.critical_symbols,
        "warnings": result.warnings,
        "coherent": result.coherent,
    }


def collect_startup_provenance() -> dict[str, str | None]:
    """Return a minimal provenance snapshot for startup logging.

    No network calls. No modification of state.
    """
    head = _get_git_head()
    pkg = str(RIG_ROOT.resolve())
    return {
        "package_path": pkg,
        "python_executable": sys.executable,
        "git_head": head,
        "installed_version": __version__,
    }
