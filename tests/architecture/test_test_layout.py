"""Test layout audit — reports violations without blocking.

Detects:
- Root-level test files that should mirror source layout
- tests/scripts/ files whose target source is not scripts/
- Duplicate known files

All checks are warnings; no assertion failures block CI today.
"""

from __future__ import annotations

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TESTS = HERE.parent

# ── Known duplicate pairs (canonical, shadow) ─────────────────
KNOWN_DUPLICATES: list[tuple[str, str]] = [
    (
        "tests/telemetry/test_observability.py",
        "tests/telemetry/test_observability_e2e.py",
    ),
    ("tests/tools/test_bash.py", "tests/tools/test_bash_hardening.py"),
]

# ── Root-level test files allowed (explicit singletons) ───────
ALLOWED_ROOT = {"test_install_script.py", "test_conftest_hygiene.py"}

# ── scripts/ test files allowed (target IS scripts/) ──────────
ALLOWED_SCRIPTS: set[str] = set()


def _test_files() -> list[Path]:
    return sorted(TESTS.rglob("test_*.py"))


def _root_test_files() -> list[Path]:
    return [p for p in _test_files() if p.parent == TESTS]


def _scripts_test_files() -> list[Path]:
    scripts_dir = TESTS / "scripts"
    return [
        p for p in _test_files() if p.parent == scripts_dir or scripts_dir in p.parents
    ]


@pytest.mark.smoke
@pytest.mark.contract
def test_layout_audit() -> None:
    """Warn (but don't fail) on layout violations."""
    violations: list[str] = []

    # Root-level test files
    for p in _root_test_files():
        if p.name not in ALLOWED_ROOT:
            violations.append(f"root-level test: {p.relative_to(ROOT)}")

    # scripts/ test files
    for p in _scripts_test_files():
        if p.name not in ALLOWED_SCRIPTS:
            violations.append(f"tests/scripts/ test: {p.relative_to(ROOT)}")

    # Duplicate pairs
    for canonical, shadow in KNOWN_DUPLICATES:
        cpath = ROOT / canonical
        spath = ROOT / shadow
        if cpath.exists() and spath.exists():
            violations.append(f"duplicate pair: {canonical} ↔ {shadow}")

    if violations:
        msg = (
            f"Test layout violations ({len(violations)}): "
            + "; ".join(violations[:5])
            + ("..." if len(violations) > 5 else "")
        )
        print(f"\n⚠️  {msg}\n")
        for v in violations:
            print(f"  • {v}")
        print(f"  ({len(violations)} total)\n")
    # No assertion — report-only. Enforce after relocation is complete.
