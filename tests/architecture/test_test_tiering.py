from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_MARKERS = [
    "smoke",
    "contract",
    "integration",
    "e2e",
    "packaging",
    "slow",
    "legacy",
    "quarantine",
    "flaky",
    "network",
    "provider",
    "destructive",
    "migration",
]


@pytest.mark.smoke
@pytest.mark.contract
def test_required_markers_are_defined():
    pyproject = REPO_ROOT / "pyproject.toml"
    assert pyproject.is_file()
    content = pyproject.read_text()
    for marker in REQUIRED_MARKERS:
        assert f'"{marker}:' in content, (
            f"Marker '{marker}' not defined in pyproject.toml"
        )


def test_smoke_suite_is_not_empty():
    script = REPO_ROOT / "scripts" / "rig_relay_marker_audit.py"
    if not script.is_file():
        pytest.skip("Marker audit script not found")
    result = subprocess.run(
        [sys.executable, str(script), "--json"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(f"Marker audit script failed: {result.stderr}")
    import json

    data = json.loads(result.stdout)
    assert data.get("smoke_count", 0) > 0, (
        "Smoke suite is empty — mark at least smoke tests"
    )


@pytest.mark.slow
def test_collect_only_is_clean():
    result = subprocess.run(
        ["uv", "run", "pytest", "--collect-only", "-q"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
        env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, f"Collect-only failed: {result.stderr[:500]}"
    assert (
        "error" not in result.stderr.lower() or "no tests" in result.stderr.lower()
    ), f"Collection errors found: {result.stderr[:500]}"


@pytest.mark.slow
def test_default_suite_can_collect():
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "-m",
            "not slow and not legacy and not quarantine and not flaky and not network and not provider and not destructive",
            "--collect-only",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
        env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, (
        f"Default suite collection failed: {result.stderr[:500]}"
    )


@pytest.mark.slow
def test_smoke_suite_can_collect():
    result = subprocess.run(
        ["uv", "run", "pytest", "-m", "smoke", "--collect-only", "-q"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
        env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, (
        f"Smoke suite collection failed: {result.stderr[:500]}"
    )
