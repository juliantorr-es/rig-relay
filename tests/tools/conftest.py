"""conftest for tests/tools — shared fixtures for tool contract tests.

Provides schema directory fixture for JSON Schema validation tests,
ensuring explicit isolation under xdist parallel execution.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(name="schemas_dir")
def schemas_dir_fixture() -> Path:
    """Absolute path to the docs/schemas/ directory.

    Computed from this file's location to avoid depending on cwd.
    Under xdist each worker computes this independently from its
    own ``__file__``, so there is no cross-worker interference.
    """
    return Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
