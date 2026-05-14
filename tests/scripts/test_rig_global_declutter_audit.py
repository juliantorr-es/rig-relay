from __future__ import annotations

import json
from pathlib import Path

from scripts.rig_global_declutter_audit import inventory_rig, quarantine, write_reports


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_audit_mode_does_not_move_or_delete(tmp_path: Path) -> None:
    rig = tmp_path / "rig"
    _touch(rig / "relay" / "history.jsonl")
    inventory = inventory_rig(rig)
    assert (rig / "relay" / "history.jsonl").exists()
    assert inventory["exists"] is True


def test_protected_and_quarantine_classification(tmp_path: Path) -> None:
    rig = tmp_path / "rig"
    _touch(rig / "relay" / "consent" / "active.json")
    _touch(rig / "relay.zip")
    _touch(rig / "config.toml")
    inventory = inventory_rig(rig)
    classes = {entry["path"]: entry["classification"] for entry in inventory["entries"]}
    assert classes[str(rig / "relay" / "consent" / "active.json")] == "protected"
    assert classes[str(rig / "relay.zip")] == "quarantine-candidate"
    assert classes[str(rig / "config.toml")] == "protected"


def test_temporary_scratch_classified_for_quarantine(tmp_path: Path) -> None:
    rig = tmp_path / "rig"
    _touch(rig / ".DS_Store")
    _touch(rig / "relay-smoke" / "scratch.log")
    inventory = inventory_rig(rig)
    classes = [entry["classification"] for entry in inventory["entries"]]
    assert "quarantine-candidate" in classes


def test_ambiguous_content_becomes_manual_review(tmp_path: Path) -> None:
    rig = tmp_path / "rig"
    _touch(rig / "relay" / "mystery.bin", "content")
    inventory = inventory_rig(rig)
    assert any(
        entry["classification"] == "manual-review" for entry in inventory["entries"]
    )


def test_quarantine_moves_only_candidates(tmp_path: Path) -> None:
    rig = tmp_path / "rig"
    quarantine_root = tmp_path / "q"
    _touch(rig / "relay.zip")
    _touch(rig / "relay" / "config.toml")
    inventory = inventory_rig(rig)
    receipt = quarantine(
        rig,
        [
            entry
            for entry in inventory["entries"]
            if entry["classification"] == "quarantine-candidate"
        ],
        quarantine_root,
    )
    assert receipt["moved_count"] == 1
    assert not (rig / "relay.zip").exists()
    assert (rig / "relay" / "config.toml").exists()


def test_receipt_is_content_light(tmp_path: Path) -> None:
    rig = tmp_path / "rig"
    out = tmp_path / "out"
    _touch(rig / "relay.zip")
    inventory = inventory_rig(rig)
    write_reports(inventory, out)
    receipt = json.loads(
        (out / "declutter-quarantine-receipt.json").read_text(encoding="utf-8")
    )
    assert "candidate_paths" in receipt
    assert "x" not in json.dumps(receipt)


def test_no_permanent_delete_function_exists() -> None:
    from scripts import rig_global_declutter_audit as module

    assert not hasattr(module, "delete")
    assert "delete" not in dir(module)


def test_reports_do_not_include_raw_contents(tmp_path: Path) -> None:
    rig = tmp_path / "rig"
    out = tmp_path / "out"
    _touch(rig / "relay" / "history.jsonl", '{"secret":"raw"}')
    inventory = inventory_rig(rig)
    write_reports(inventory, out)
    report = (out / "inventory.md").read_text(encoding="utf-8")
    assert "raw" not in report
