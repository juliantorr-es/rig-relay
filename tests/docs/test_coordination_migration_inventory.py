"""Tests for the coordination migration inventory document."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.migration]


from pathlib import Path

INVENTORY_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "audits"
    / "coordination-migration-inventory.md"
)


def test_inventory_doc_exists() -> None:
    assert INVENTORY_PATH.is_file()


def test_inventory_mentions_key_modules() -> None:
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    assert "vibe/core/coordination/_models.py" in text
    assert "vibe/core/coordination/_store.py" in text
    assert "vibe/core/coordination/__init__.py" in text


def test_inventory_names_target_boundary_modules() -> None:
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    assert "rig_relay.coordination.models" in text
    assert "rig_relay.coordination.store" in text
    assert "rig_relay.coordination.events" in text
    assert "rig_relay.coordination.tool" in text


def test_inventory_mentions_compatibility_imports() -> None:
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    assert "compatibility adapters/re-exports" in text
    assert "legacy imports" in text


def test_inventory_states_no_event_or_schema_changes() -> None:
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    assert "No event-name changes in this slice." in text
    assert "No schema changes in this slice." in text


def test_inventory_blocks_circular_imports() -> None:
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    assert "no circular imports from `rig_relay` back into `vibe`" in text.lower()


def test_inventory_references_refinement_packet() -> None:
    text = INVENTORY_PATH.read_text(encoding="utf-8")
    assert "P0-coordination-add_coordination_hook" in text
    assert "mission_packet.json" in text
