from __future__ import annotations

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.rig_relay_sessions_audit as audit_script
import scripts.rig_relay_sessions_compact as compact_script
import scripts.rig_relay_sessions_gc as gc_script


def _make_file(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _build_tree(tmp_path: Path) -> Path:
    root = tmp_path / ".rig" / "sessions"
    _make_file(root / "s1" / "receipt.json", "{}")
    _make_file(root / "s1" / "telemetry_consent.json", "{}")
    _make_file(root / "s1" / "upload_receipt.json", "{}")
    _make_file(root / "s1" / "signed_local_action_envelope.json", "{}")
    _make_file(
        root / "s1" / "intent_events.jsonl",
        json.dumps({"ok": True, "raw_prompt": "keep private"}) + "\n",
    )
    _make_file(
        root / "s1" / "progress_events.jsonl",
        json.dumps({"event": "p", "raw_model_output": "secret"}) + "\n",
    )
    _make_file(root / "s1" / "transcript.jsonl", json.dumps({"turn": 1}) + "\n")
    _make_file(root / "s1" / "stdout.log", "raw stdout")
    _make_file(root / "active" / "active.lock", "active")
    _make_file(root / "pinned" / "pin.lock", "pinned")
    return root


def test_audit_script_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _build_tree(tmp_path)
    monkeypatch.setattr(
        audit_script,
        "parse_args",
        lambda: SimpleNamespace(sessions_root=root, state_root=None, json=True, top=5),
    )
    assert audit_script.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["sessions_root"] == str(root)
    assert out["file_count"] >= 3


def test_compact_script_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _build_tree(tmp_path)
    out_root = tmp_path / "rollups"
    monkeypatch.setattr(
        compact_script,
        "parse_args",
        lambda: SimpleNamespace(
            sessions_root=root,
            state_root=None,
            output_root=out_root,
            dry_run=True,
            confirm=False,
            format="jsonl_gz",
        ),
    )
    assert compact_script.main() == 0
    assert not out_root.exists()
    assert "Dry run only" in capsys.readouterr().out


def test_compact_script_gzip_fallback_without_duckdb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _build_tree(tmp_path)
    out_root = tmp_path / "rollups"
    monkeypatch.setattr(
        compact_script,
        "parse_args",
        lambda: SimpleNamespace(
            sessions_root=root,
            state_root=None,
            output_root=out_root,
            dry_run=False,
            confirm=True,
            format="parquet",
        ),
    )
    monkeypatch.setattr(compact_script, "duckdb", None)
    assert compact_script.main() == 0
    outputs = list(out_root.glob("*.jsonl.gz"))
    assert outputs
    with gzip.open(outputs[0], "rt", encoding="utf-8") as handle:
        payload = json.loads(handle.readline())
    payload_text = json.dumps(payload)
    assert "keep private" not in payload_text
    assert "secret" not in payload_text
    assert "[REDACTED]" in payload_text


def test_compact_script_respects_protected_files_and_confirmed_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _build_tree(tmp_path)
    out_root = tmp_path / "rollups"
    monkeypatch.setattr(
        compact_script,
        "parse_args",
        lambda: SimpleNamespace(
            sessions_root=root,
            state_root=None,
            output_root=out_root,
            dry_run=False,
            confirm=True,
            format="jsonl_gz",
        ),
    )
    assert compact_script.main() == 0
    assert (root / "s1" / "receipt.json").exists()
    assert (root / "s1" / "telemetry_consent.json").exists()
    assert (root / "s1" / "upload_receipt.json").exists()
    assert (root / "s1" / "signed_local_action_envelope.json").exists()
    assert list(out_root.glob("*.jsonl.gz"))


def test_gc_script_dry_run_and_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _build_tree(tmp_path)
    archive_dir = tmp_path / "archive"
    monkeypatch.setattr(
        gc_script,
        "parse_args",
        lambda: SimpleNamespace(
            sessions_root=root,
            state_root=None,
            dry_run=True,
            confirm=False,
            archive_dir=archive_dir,
            older_than_days=0,
            max_delete_mb=10.0,
        ),
    )
    assert gc_script.main() == 0
    assert not archive_dir.exists()
    assert "Dry run only" in capsys.readouterr().out

    old_candidate = root / "s1" / "stdout_old.log"
    old_candidate.write_text("old", encoding="utf-8")
    old_ts = old_candidate.stat().st_mtime - 86400 * 40
    import os

    os.utime(old_candidate, (old_ts, old_ts))

    monkeypatch.setattr(
        gc_script,
        "parse_args",
        lambda: SimpleNamespace(
            sessions_root=root,
            state_root=None,
            dry_run=False,
            confirm=True,
            archive_dir=archive_dir,
            older_than_days=30,
            max_delete_mb=10.0,
        ),
    )
    assert gc_script.main() == 0
    assert (archive_dir / "stdout_old.log").exists()


def test_gc_script_honors_delete_cap_and_protected_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _build_tree(tmp_path)
    old1 = root / "s1" / "stdout_old_1.log"
    old2 = root / "s1" / "stdout_old_2.log"
    _make_file(old1, "old-1")
    _make_file(old2, "old-2")
    for path in (old1, old2):
        old_ts = path.stat().st_mtime - 86400 * 40
        import os

        os.utime(path, (old_ts, old_ts))
    monkeypatch.setattr(
        gc_script,
        "parse_args",
        lambda: SimpleNamespace(
            sessions_root=root,
            state_root=None,
            dry_run=False,
            confirm=True,
            archive_dir=None,
            older_than_days=30,
            max_delete_mb=0.000001,
        ),
    )
    assert gc_script.main() == 0
    assert old1.exists() and old2.exists()
    assert (root / "s1" / "receipt.json").exists()
    assert (root / "s1" / "telemetry_consent.json").exists()
    assert (root / "s1" / "upload_receipt.json").exists()
    assert (root / "s1" / "signed_local_action_envelope.json").exists()
    assert (root / "gc").exists()
