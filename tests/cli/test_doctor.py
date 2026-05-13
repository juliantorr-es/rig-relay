from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from vibe.cli import cli as cli_mod
from vibe.core.telemetry.local import dump_canonical_json


def _sha256_prefix(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_tree(root: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = (
                path.stat().st_size,
                _sha256_prefix(path),
            )
    return snapshot


def _write_event(log_file: Path, event: dict) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(dump_canonical_json(event))
        handle.write("\n")


def _session_root(root: Path, session_id: str) -> Path:
    return root / "sessions" / session_id


def _make_event(session_id: str, payload: dict, *, sequence: int = 0) -> dict:
    body = {
        "schema_version": "rig.relay.observability.v1",
        "event_id": f"{session_id}-{sequence}",
        "session_id": session_id,
        "sequence": sequence,
        "created_at": "2024-01-01T00:00:00Z",
        "event_name": "rig.relay.session.started"
        if sequence == 0
        else "rig.relay.artifact.tool_output_written",
        "payload": payload,
        "producer": {"name": "rig-relay", "version": "2.9.6"},
        "receipt_candidate": False,
    }
    body["event_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
    )
    return body


def _make_valid_session(evidence_root: Path, session_id: str) -> None:
    session_root = _session_root(evidence_root, session_id)
    session_root.mkdir(parents=True)
    log_file = session_root / "observability.jsonl"
    _write_event(
        log_file,
        _make_event(
            session_id,
            {
                "evidence_root_mode": "repo_local",
                "evidence_root_source": "RIG_RELAY_HOME",
            },
        ),
    )
    _write_event(
        log_file,
        {
            "schema_version": "rig.relay.observability.v1",
            "event_id": f"{session_id}-1",
            "session_id": session_id,
            "sequence": 1,
            "created_at": "2024-01-01T00:00:00Z",
            "event_name": "rig.relay.session.closed",
            "payload": {"session_id": session_id},
            "producer": {"name": "rig-relay", "version": "2.9.6"},
            "receipt_candidate": False,
            "event_hash": "sha256:"
            + hashlib.sha256(
                json.dumps(
                    {
                        "schema_version": "rig.relay.observability.v1",
                        "event_id": f"{session_id}-1",
                        "session_id": session_id,
                        "sequence": 1,
                        "created_at": "2024-01-01T00:00:00Z",
                        "event_name": "rig.relay.session.closed",
                        "payload": {"session_id": session_id},
                        "producer": {"name": "rig-relay", "version": "2.9.6"},
                        "receipt_candidate": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest(),
        },
    )
    manifest = {
        "schema_version": "rig.relay.evidence_manifest.v1",
        "session_id": session_id,
        "created_at": "2024-01-01T00:00:00Z",
        "evidence_root_mode": "repo_local",
        "evidence_root_source": "RIG_RELAY_HOME",
        "entries": [
            {
                "evidence_kind": "observability_log",
                "relative_path": "observability.jsonl",
                "sha256": _sha256_prefix(log_file),
                "size_bytes": log_file.stat().st_size,
            }
        ],
    }
    (session_root / "manifest.json").write_text(
        dump_canonical_json(manifest) + "\n", encoding="utf-8"
    )


def _make_broken_session(evidence_root: Path, session_id: str) -> None:
    session_root = _session_root(evidence_root, session_id)
    session_root.mkdir(parents=True)
    log_file = session_root / "observability.jsonl"
    _write_event(
        log_file,
        _make_event(
            session_id,
            {
                "evidence_root_mode": "repo_local",
                "evidence_root_source": "RIG_RELAY_HOME",
            },
        ),
    )
    (session_root / "manifest.json").write_text(
        dump_canonical_json({
            "schema_version": "rig.relay.evidence_manifest.v1",
            "session_id": session_id,
            "created_at": "2024-01-01T00:00:00Z",
            "evidence_root_mode": "repo_local",
            "evidence_root_source": "RIG_RELAY_HOME",
            "entries": [
                {
                    "evidence_kind": "observability_log",
                    "relative_path": "observability.jsonl",
                    "sha256": "sha256:deadbeef",
                    "size_bytes": log_file.stat().st_size,
                }
            ],
        })
        + "\n",
        encoding="utf-8",
    )


def _make_args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "command": "doctor",
        "doctor_command": "evidence",
        "evidence_root": Path("/tmp/evidence"),
        "session": "session-1",
        "json": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_doctor_evidence_exits_zero_and_reports_root_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence_root = tmp_path / "evidence"
    stale_root = tmp_path / "stale"
    stale_session = _session_root(stale_root, "session-pass")
    stale_session.mkdir(parents=True)
    (stale_session / "observability.jsonl").write_text("{}", encoding="utf-8")
    session_id = "session-pass"
    _make_valid_session(evidence_root, session_id)

    with pytest.raises(SystemExit) as exc_info:
        cli_mod.run_cli(
            _make_args(evidence_root=evidence_root, session=session_id, json=False)
        )

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "status: pass" in output
    assert "root mode: repo_local" in output
    assert "root source: RIG_RELAY_HOME" in output


def test_doctor_evidence_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence_root = tmp_path / "evidence"
    session_id = "session-json"
    _make_valid_session(evidence_root, session_id)

    with pytest.raises(SystemExit) as exc_info:
        cli_mod.run_cli(
            _make_args(evidence_root=evidence_root, session=session_id, json=True)
        )

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert payload["session_id"] == session_id
    assert payload["root_mode"] == "repo_local"
    assert payload["root_source"] == "RIG_RELAY_HOME"


def test_doctor_evidence_exits_nonzero_on_broken_session(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    session_id = "session-fail"
    _make_broken_session(evidence_root, session_id)

    with pytest.raises(SystemExit) as exc_info:
        cli_mod.run_cli(
            _make_args(evidence_root=evidence_root, session=session_id, json=False)
        )

    assert exc_info.value.code == 1


def test_doctor_evidence_is_read_only_on_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence_root = tmp_path / "evidence"
    session_id = "session-pass"
    _make_valid_session(evidence_root, session_id)
    before = _snapshot_tree(evidence_root)

    with pytest.raises(SystemExit) as exc_info:
        cli_mod.run_cli(
            _make_args(evidence_root=evidence_root, session=session_id, json=False)
        )

    assert exc_info.value.code == 0
    capsys.readouterr()
    after = _snapshot_tree(evidence_root)
    assert after == before


def test_doctor_evidence_is_read_only_on_failure(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    session_id = "session-fail"
    _make_broken_session(evidence_root, session_id)
    before = _snapshot_tree(evidence_root)

    with pytest.raises(SystemExit) as exc_info:
        cli_mod.run_cli(
            _make_args(evidence_root=evidence_root, session=session_id, json=True)
        )

    assert exc_info.value.code == 1
    after = _snapshot_tree(evidence_root)
    assert after == before


def test_doctor_evidence_does_not_create_manifest_for_partial_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence_root = tmp_path / "evidence"
    session_id = "session-partial"
    session_root = _session_root(evidence_root, session_id)
    session_root.mkdir(parents=True)
    (session_root / "observability.jsonl").write_text(
        dump_canonical_json(
            {
                "schema_version": "rig.relay.observability.v1",
                "event_id": f"{session_id}-0",
                "session_id": session_id,
                "sequence": 0,
                "created_at": "2024-01-01T00:00:00Z",
                "event_name": "rig.relay.session.started",
                "payload": {
                    "evidence_root_mode": "repo_local",
                    "evidence_root_source": "RIG_RELAY_HOME",
                },
                "producer": {"name": "rig-relay", "version": "2.9.6"},
                "receipt_candidate": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = _snapshot_tree(evidence_root)

    with pytest.raises(SystemExit) as exc_info:
        cli_mod.run_cli(
            _make_args(evidence_root=evidence_root, session=session_id, json=False)
        )

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "manifest missing; using scan fallback" in output
    assert "session.closed" in output
    after = _snapshot_tree(evidence_root)
    assert after == before
    assert not (session_root / "manifest.json").exists()


def test_doctor_evidence_json_output_for_partial_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence_root = tmp_path / "evidence"
    session_id = "session-partial-json"
    session_root = _session_root(evidence_root, session_id)
    session_root.mkdir(parents=True)
    (session_root / "observability.jsonl").write_text(
        dump_canonical_json(
            {
                "schema_version": "rig.relay.observability.v1",
                "event_id": f"{session_id}-0",
                "session_id": session_id,
                "sequence": 0,
                "created_at": "2024-01-01T00:00:00Z",
                "event_name": "rig.relay.session.started",
                "payload": {
                    "evidence_root_mode": "repo_local",
                    "evidence_root_source": "RIG_RELAY_HOME",
                },
                "producer": {"name": "rig-relay", "version": "2.9.6"},
                "receipt_candidate": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        cli_mod.run_cli(
            _make_args(evidence_root=evidence_root, session=session_id, json=True)
        )

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "warn"
    assert "manifest missing; using scan fallback" in payload["warnings"]
    assert "session.closed" in " ".join(payload["warnings"])
