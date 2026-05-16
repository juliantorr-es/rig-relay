"""Test layout audit — reports violations without blocking.

Detects:
- Root-level test files that should mirror source layout
- tests/scripts/ files whose target source is not scripts/
- Duplicate known files

All checks are warnings; no assertion failures block CI today.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TESTS = HERE.parent

# ── Known duplicate pairs (canonical, shadow) ─────────────────
KNOWN_DUPLICATES: list[tuple[str, str]] = [
    ("tests/tools/test_validate.py", "tests/tools/test_validate_git_state.py"),
    (
        "tests/ralph/test_ralph_background_policy.py",
        "tests/ralph/test_background_policy_v2.py",
    ),
]

# ── Root-level test files allowed (explicit singletons) ───────
ALLOWED_ROOT = {
    "test_agents.py",
    "test_agent_tool_call.py",
    "test_agent_backend.py",
    "test_agent_observer_streaming.py",
    "test_agent_override_resolve_permission.py",
    "test_agent_auto_compact.py",
    "test_agent_stats.py",
    "test_deferred_init.py",
    "test_reasoning_content.py",
    "test_approve_always_permanent.py",
    "test_cli_programmatic_preload.py",
    "test_middleware.py",
    "test_system_prompt.py",
    "test_tracing.py",
    "test_history_manager.py",
    "test_turn_summary.py",
}

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
        print("\n⚠️  Test layout warnings:")
        for v in violations:
            print(f"  • {v}")
        print(f"  ({len(violations)} total)\n")
    # No assertion — report-only for now
