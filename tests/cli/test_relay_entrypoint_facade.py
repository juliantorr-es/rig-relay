"""Tests for the Relay-owned CLI entry point dispatcher.

Verifies that:
- ``pyproject.toml`` maps ``rig-relay`` to ``rig_relay.cli.entrypoint:main``.
- Dispatcher module imports and exposes a callable ``main``.
- No-arg dispatch routes to the Desktop Cockpit.
- ``rig-relay --help`` prints the cockpit description.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_pyproject_toml() -> dict[str, Any]:
    import tomllib

    text = (PROJECT_ROOT / "pyproject.toml").read_bytes()
    data = tomllib.loads(text.decode("utf-8"))
    return data.get("project", {}).get("scripts", {})


# ── pyproject.toml mapping tests ───────────────────────────────────────────


def test_rig_relay_points_to_relay_facade():
    scripts = _read_pyproject_toml()
    assert scripts.get("rig-relay") == "rig_relay.cli.entrypoint:main"


def test_rig_relay_acp_points_to_relay_facade():
    scripts = _read_pyproject_toml()
    assert scripts.get("rig-relay-acp") == "rig_relay.cli.acp_entrypoint:main"


def test_rig_relay_cockpit_is_alias():
    scripts = _read_pyproject_toml()
    assert scripts.get("rig-relay-cockpit") == "rig_relay.cli.desktop_cockpit:main"


# ── Facade module existence tests ──────────────────────────────────────────


def test_relay_cli_entrypoint_module_has_callable_main():
    from rig_relay.cli.entrypoint import main

    assert callable(main)


def test_rig_relay_no_args_routes_to_cockpit(monkeypatch):
    import rig_relay.cli.entrypoint as entrypoint

    cockpit = Mock()
    monkeypatch.setattr("rig_relay.cli.desktop_cockpit.main", cockpit)

    entrypoint.main([])

    cockpit.assert_called_once_with([])


def test_relay_cli_acp_entrypoint_has_callable_main():
    import ast
    import importlib.util

    # Use AST parsing to avoid triggering import-time side effects
    # (sys.stdin.reconfigure) in the ACP entrypoint.
    spec = importlib.util.find_spec("rig_relay.cli.acp_entrypoint")
    assert spec is not None
    assert spec.loader is not None
    source = spec.loader.get_source("rig_relay.cli.acp_entrypoint")
    assert source is not None
    tree = ast.parse(source)
    has_def = any(
        isinstance(node, ast.FunctionDef) and node.name == "main"
        for node in ast.walk(tree)
    )
    has_import = any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "main" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert has_def or has_import, "acp_entrypoint must expose a callable main"


# ── Help command behavior tests ────────────────────────────────────────────


def _find_uv_binary() -> str:
    venv_uv = PROJECT_ROOT / ".venv" / "bin" / "uv"
    if venv_uv.is_file():
        return str(venv_uv)
    import shutil

    return shutil.which("uv") or "uv"


def _run_help(command: str) -> subprocess.CompletedProcess:
    uv = _find_uv_binary()
    return subprocess.run(
        [uv, "run", command, "--help"], capture_output=True, text=True, cwd=PROJECT_ROOT
    )


def test_rig_relay_acp_help_succeeds():
    proc = _run_help("rig-relay-acp")
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"


def test_rig_relay_help_mentions_cockpit():
    proc = _run_help("rig-relay")
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "Desktop Cockpit" in proc.stdout
