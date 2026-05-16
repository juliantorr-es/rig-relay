from __future__ import annotations

from pathlib import Path

import pytest

INCORRECT_PYCACHE_SIGNATURES = ["HarnessFilesManager.reset_instance"]
CORRECT_CONFTEST_SIGNATURES = ["init_harness_files_manager", "reset_harness_files_manager"]


@pytest.mark.smoke
@pytest.mark.contract
def test_conftest_source_has_init_reset_not_stale_reset_instance():
    conftest = Path(__file__).resolve().parent / "conftest.py"
    source = conftest.read_text()

    for sig in INCORRECT_PYCACHE_SIGNATURES:
        assert sig not in source, (
            f"conftest.py contains stale signature '{sig}'. "
            f"If the source was correctly updated to use init_harness_files_manager, "
            f"delete __pycache__ directories and retry. "
            f"Never revert to the stale HarnessFilesManager.reset_instance pattern."
        )

    for sig in CORRECT_CONFTEST_SIGNATURES:
        assert sig in source, (
            f"conftest.py missing expected signature '{sig}'. "
            f"conftest.py must use init_harness_files_manager() and reset_harness_files_manager(), "
            f"not the old HarnessFilesManager.reset_instance() pattern."
        )
