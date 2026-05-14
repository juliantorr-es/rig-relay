from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
POLICY = REPO_ROOT / "docs" / "governance" / "textual-retirement-policy.md"
MATRIX = REPO_ROOT / "docs" / "governance" / "relay-surface-matrix.md"


def test_textual_retirement_policy_exists() -> None:
    assert POLICY.is_file()


def test_policy_has_lifecycle_states() -> None:
    text = POLICY.read_text(encoding="utf-8")
    assert "active-dev-compatibility" in text
    assert "deprecated-product-ui" in text
    assert "delete-candidate" in text
    assert "removed" in text


def test_policy_blocks_textual_deletion_until_parity() -> None:
    text = POLICY.read_text(encoding="utf-8")
    assert "Relay CLI can run status, validation, refinement report" in text
    assert "pywebview cockpit can run safe intents reliably" in text
    assert (
        "Removing Textual would not break packaging or compatibility entry points"
        in text
    )


def test_surface_matrix_exists() -> None:
    assert MATRIX.is_file()


def test_surface_matrix_lists_required_surfaces() -> None:
    text = MATRIX.read_text(encoding="utf-8")
    for surface in ["Textual TUI", "Relay CLI", "pywebview cockpit", "scripts"]:
        assert surface in text


def test_surface_matrix_mentions_vibe_core_legacy_substrate() -> None:
    text = MATRIX.read_text(encoding="utf-8")
    assert "vibe/core" in text
    assert "compatibility substrate" in text
