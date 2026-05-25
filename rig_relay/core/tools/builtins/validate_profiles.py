"""Validate tool — profile registry.

Named validation profiles with check lists. Registration happens at
module import time so profiles are available before any tool invocation.
"""

from __future__ import annotations

from rig_relay.core.tools.builtins.validate_models import (
    RECEIPT_SCRIPT,
    SCHEMA_SCRIPT,
    Profile,
    ProfileCheck,
)

# ── Registry ──────────────────────────────────────────────────────────

_PROFILES: dict[str, Profile] = {}


def _register(p: Profile) -> None:
    _PROFILES[p.name] = p


def get_profile(name: str) -> Profile | None:
    return _PROFILES.get(name)


def list_profiles() -> list[str]:
    return sorted(_PROFILES)


# ── Built-in profiles ────────────────────────────────────────────────

_register(
    Profile(
        name="quick",
        description="Fast local feedback: git status, focused pytest, scoped ruff",
        checks=[
            ProfileCheck(
                check_id="git_status",
                command_kind="git",
                argv=["git", "status", "--short", "--branch"],
                display="git status",
            )
        ],
        default_timeout=30,
    )
)

_register(
    Profile(
        name="python",
        description="Python surface: ruff check, pyright, pytest",
        checks=[
            ProfileCheck(
                check_id="ruff_check",
                command_kind="ruff",
                argv=["uv", "run", "ruff", "check"],
                display="ruff check",
            ),
            ProfileCheck(
                check_id="pyright",
                command_kind="pyright",
                argv=["uv", "run", "pyright"],
                display="pyright",
            ),
            ProfileCheck(
                check_id="pytest",
                command_kind="pytest",
                argv=["uv", "run", "pytest"],
                display="pytest",
            ),
        ],
        default_timeout=300,
    )
)

_register(
    Profile(
        name="schemas",
        description="Schema and receipt validation",
        checks=[
            ProfileCheck(
                check_id="schema_validation",
                command_kind="schema",
                argv=["uv", "run", "python", SCHEMA_SCRIPT],
                display="schema validation",
            )
        ],
        default_timeout=120,
    )
)

_register(
    Profile(
        name="receipt-policy",
        description="Content-light receipt validation",
        checks=[
            ProfileCheck(
                check_id="receipt_policy",
                command_kind="policy",
                argv=["uv", "run", "python", RECEIPT_SCRIPT],
                display="receipt policy validation",
            )
        ],
        default_timeout=60,
    )
)

_register(
    Profile(
        name="tool-hardening",
        description="Deterministic tool-envelope checks",
        checks=[
            ProfileCheck(
                check_id="bash_hardening",
                command_kind="pytest",
                argv=[
                    "uv",
                    "run",
                    "pytest",
                    "-n0",
                    "tests/tools/test_bash_hardening.py",
                    "--timeout=30",
                    "-x",
                ],
                display="bash hardening tests",
            ),
            ProfileCheck(
                check_id="receipt_emission",
                command_kind="pytest",
                argv=[
                    "uv",
                    "run",
                    "pytest",
                    "-n0",
                    "tests/tools/test_tool_receipt_emission.py",
                    "--timeout=30",
                ],
                display="receipt emission tests",
            ),
        ],
        default_timeout=180,
    )
)

_register(
    Profile(
        name="worktree-readiness",
        description="Lane/worktree readiness: git state collection and dirty policy enforcement",
        checks=[],  # No lint/test/schema commands — purely git state + dirty policy
        default_timeout=30,
    )
)
