from __future__ import annotations

from pathlib import Path


def test_vibe_cli_purge_inventory_exists():
    # Use the specific artifact path provided in the session context
    inventory_path = Path(
        "/Users/user/.gemini/antigravity/brain/f57b5347-30e1-42cf-8a13-f3a522bf7423/vibe-cli-purge-inventory.md"
    )
    assert inventory_path.exists(), f"Inventory not found at {inventory_path}"


def test_vibe_cli_purge_inventory_content():
    inventory_path = Path(
        "/Users/user/.gemini/antigravity/brain/f57b5347-30e1-42cf-8a13-f3a522bf7423/vibe-cli-purge-inventory.md"
    )
    content = inventory_path.read_text()

    assert "retired" in content.lower()
    assert "Textual" in content
    assert "pywebview" in content.lower()
    assert "cockpit" in content.lower()
    assert "primary" in content.lower()
    assert "vibe" in content.lower()
    assert "rig-relay" in content.lower()


def test_vibe_cli_deprecated_aliases():
    inventory_path = Path(
        "/Users/user/.gemini/antigravity/brain/f57b5347-30e1-42cf-8a13-f3a522bf7423/vibe-cli-purge-inventory.md"
    )
    content = inventory_path.read_text()

    # Ensure vibe and vibe-acp are marked as deprecated
    assert "| `vibe` | **deprecated** |" in content
    assert "| `vibe-acp` | **deprecated** |" in content
