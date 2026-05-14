"""Tests for the Relay-owned CLI entry point facade.

Verifies that:
- ``pyproject.toml`` maps ``rig-relay`` and ``rig-relay-acp`` to
  ``rig_relay.cli.*`` modules.
- Facade modules import and expose a callable ``main``.
- Compatibility and legacy aliases still exist in ``pyproject.toml``.
- ``rig-relay --help`` / ``rig-relay-acp --help`` exit 0 without
  deprecation warning.
- ``vibe --help`` / ``vibe-acp --help`` exit 0 with deprecation warning.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_pyproject_toml() -> dict[str, Any]:
    """Parse pyproject.toml and return the ``[project.scripts]`` table."""
    import tomllib

    text = (PROJECT_ROOT / "pyproject.toml").read_bytes()
    data = tomllib.loads(text.decode("utf-8"))
    return data.get("project", {}).get("scripts", {})  # pyright: ignore[reportReturnType]


# ── pyproject.toml mapping tests ───────────────────────────────────────────


def test_rig_relay_points_to_relay_facade():
    scripts = _read_pyproject_toml()
    assert scripts.get("rig-relay") == "rig_relay.cli.entrypoint:main"


def test_rig_relay_acp_points_to_relay_facade():
    scripts = _read_pyproject_toml()
    assert scripts.get("rig-relay-acp") == "rig_relay.cli.acp_entrypoint:main"


def test_vibe_alias_still_exists():
    scripts = _read_pyproject_toml()
    assert "vibe" in scripts


def test_vibe_acp_alias_still_exists():
    scripts = _read_pyproject_toml()
    assert "vibe-acp" in scripts


def test_vibe_legacy_alias_still_exists():
    scripts = _read_pyproject_toml()
    assert "vibe-legacy" in scripts


def test_vibe_acp_legacy_alias_still_exists():
    scripts = _read_pyproject_toml()
    assert "vibe-acp-legacy" in scripts


def test_vibe_alias_points_to_vibe_module():
    scripts = _read_pyproject_toml()
    assert scripts.get("vibe") == "vibe.cli.entrypoint:main"


def test_vibe_acp_alias_points_to_vibe_module():
    scripts = _read_pyproject_toml()
    assert scripts.get("vibe-acp") == "vibe.acp.entrypoint:main"


def test_vibe_legacy_alias_points_to_vibe_module():
    scripts = _read_pyproject_toml()
    assert scripts.get("vibe-legacy") == "vibe.cli.entrypoint:main"


def test_vibe_acp_legacy_alias_points_to_vibe_module():
    scripts = _read_pyproject_toml()
    assert scripts.get("vibe-acp-legacy") == "vibe.acp.entrypoint:main"


# ── Facade module existence tests ──────────────────────────────────────────
# These use importlib to verify the module exists and has a callable ``main``
# without triggering import-time side effects in the downstream modules.


def _module_has_callable_main(module_name: str) -> bool:
    """Check if a module defines or imports a callable ``main``.

    Uses AST parsing to avoid triggering import-time side effects.
    Accepts both ``def main`` and ``from ... import main`` patterns.
    """
    import ast

    spec = importlib.util.find_spec(module_name)
    assert spec is not None, f"Module {module_name} not found"
    assert spec.loader is not None, f"Module {module_name} has no loader"
    source = spec.loader.get_source(module_name)  # pyright: ignore[reportAttributeAccessIssue]
    assert source is not None
    tree = ast.parse(source)
    for node in ast.walk(tree):
        # Direct definition: def main(...)
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return True
        # Imported name: from x import main or from x import a, b, main
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "main" or (alias.asname and alias.asname == "main"):
                    return True
        # Direct import: import x (not likely for this case, but handle it)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "main" or (alias.asname and alias.asname == "main"):
                    return True
    return False


def test_relay_cli_entrypoint_module_has_callable_main():
    # Direct import works for CLI entrypoint (no import-time side effects)
    from rig_relay.cli.entrypoint import main

    assert callable(main)


def test_relay_cli_acp_entrypoint_module_has_callable_main():
    # The ACP entrypoint has import-time side effects (sys.stdin.reconfigure)
    # that break under pytest, so we verify via AST instead.
    assert _module_has_callable_main("rig_relay.cli.acp_entrypoint")


# ── Help command behavior tests ────────────────────────────────────────────


def _find_uv_binary() -> str:
    """Find the ``uv`` binary (prefer the one from the same venv)."""
    venv_uv = PROJECT_ROOT / ".venv" / "bin" / "uv"
    if venv_uv.is_file():
        return str(venv_uv)
    import shutil

    return shutil.which("uv") or "uv"


def _run_help(command: str) -> subprocess.CompletedProcess:
    """Run ``uv run <command> --help`` and return the completed process."""
    uv = _find_uv_binary()
    return subprocess.run(
        [uv, "run", command, "--help"], capture_output=True, text=True, cwd=PROJECT_ROOT
    )


def test_rig_relay_help_no_deprecation_warning():
    proc = _run_help("rig-relay")
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "legacy compatibility alias" not in proc.stdout
    assert "legacy compatibility alias" not in proc.stderr


def test_rig_relay_acp_help_no_deprecation_warning():
    proc = _run_help("rig-relay-acp")
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "legacy compatibility alias" not in proc.stdout
    assert "legacy compatibility alias" not in proc.stderr


def test_vibe_help_has_deprecation_warning():
    proc = _run_help("vibe")
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "legacy compatibility alias" in proc.stdout


def test_vibe_acp_help_has_deprecation_warning():
    proc = _run_help("vibe-acp")
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "legacy compatibility alias" in proc.stderr
