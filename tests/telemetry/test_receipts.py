from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vibe.core.telemetry import validate_evidence_session, write_session_manifest
from vibe.core.telemetry.constants import EventName
from vibe.core.telemetry.local import dump_canonical_json
from vibe.core.telemetry.receipts import (
    build_session_receipts,
    load_receipts,
    verify_receipt,
    write_session_receipts,
)


def _write_event(log_file: Path, event: dict) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(dump_canonical_json(event))
        handle.write("\n")


def _event(
    session_id: str, event_name: str, payload: dict, *, sequence: int = 0
) -> dict:
    event = {
        "schema_version": "rig.relay.observability.v1",
        "event_id": f"{session_id}-{sequence}",
        "session_id": session_id,
        "sequence": sequence,
        "created_at": "2024-01-01T00:00:00Z",
        "event_name": event_name,
        "payload": payload,
        "producer": {"name": "rig-relay", "version": "2.9.6"},
        "receipt_candidate": False,
        "event_hash": "sha256:abc",
    }
    body = dict(event)
    body.pop("event_hash")
    event["event_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
    )
    return event


def _sha256_prefix(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def session_setup(tmp_path):
    repo_root = tmp_path / "repo"
    session_id = "session-1"
    session_root = repo_root / ".rig" / "relay" / "sessions" / session_id
    artifact_dir = session_root / "artifacts" / "tool-results"
    context_dir = session_root / "context"
    artifact_dir.mkdir(parents=True)
    context_dir.mkdir(parents=True)

    log_file = session_root / "observability.jsonl"
    _write_event(
        log_file,
        _event(
            session_id,
            EventName.SESSION_STARTED,
            {
                "evidence_root_mode": "repo_local",
                "evidence_root_source": "RIG_RELAY_HOME",
            },
        ),
    )

    # Create some evidence files
    artifact_path = artifact_dir / "0000_read_file_abcd.json"
    artifact_path.write_text(
        dump_canonical_json({
            "artifact_id": "a1",
            "artifact_record_sha256": "sha256:123",
        }),
        encoding="utf-8",
    )

    assembly_path = context_dir / "assembly_1.json"
    assembly_path.write_text(dump_canonical_json({"report_id": "r1"}), encoding="utf-8")

    _write_event(
        log_file,
        _event(
            session_id,
            EventName.ARTIFACT_WRITTEN,
            {
                "evidence_relative_path": "artifacts/tool-results/0000_read_file_abcd.json",
                "evidence_sha256": "sha256:123",
            },
            sequence=1,
        ),
    )

    _write_event(
        log_file,
        _event(
            session_id,
            EventName.CONTEXT_ASSEMBLY_REPORTED,
            {
                "evidence_relative_path": "context/assembly_1.json",
                "evidence_sha256": _sha256_prefix(assembly_path),
            },
            sequence=2,
        ),
    )

    _write_event(
        log_file,
        _event(
            session_id, EventName.SESSION_CLOSED, {"session_id": session_id}, sequence=3
        ),
    )

    return repo_root, session_id, session_root


def test_receipt_builder_stable_and_contiguous(session_setup):
    repo_root, session_id, session_root = session_setup

    receipts = build_session_receipts(session_root, session_id)
    assert len(receipts) == 2
    assert receipts[0].sequence == 1
    assert receipts[1].sequence == 2
    assert receipts[0].previous_receipt_sha256 is None
    assert receipts[1].previous_receipt_sha256 == receipts[0].receipt_sha256

    for r in receipts:
        assert verify_receipt(r)
        assert r.session_id == session_id
        assert r.evidence_relative_path.startswith(("artifacts/", "context/"))
        assert not Path(r.evidence_relative_path).is_absolute()


def test_receipt_validation_passes(session_setup):
    repo_root, session_id, session_root = session_setup
    write_session_manifest(session_root, session_id)
    write_session_receipts(session_root, session_id)

    result = validate_evidence_session(repo_root / ".rig" / "relay", session_id)
    if result.status != "pass":
        pytest.fail(
            f"Validation failed: {result.failed_checks} (Warnings: {result.warnings})"
        )
    assert result.status == "pass"
    assert result.receipt_count == 2
    assert result.receipt_chain_status == "valid"
    assert result.final_receipt_sha256 is not None


def test_missing_receipts_warns_for_legacy(session_setup):
    repo_root, session_id, session_root = session_setup
    write_session_manifest(session_root, session_id)
    # No write_session_receipts

    result = validate_evidence_session(repo_root / ".rig" / "relay", session_id)
    assert result.status == "warn"
    assert result.receipt_chain_status == "legacy_missing"
    assert any("receipts.jsonl missing" in w for w in result.warnings)


def test_broken_receipt_chain_fails(session_setup):
    repo_root, session_id, session_root = session_setup
    write_session_manifest(session_root, session_id)
    write_session_receipts(session_root, session_id)

    # Tamper with receipts.jsonl
    receipts_path = session_root / "receipts.jsonl"
    lines = receipts_path.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[1])
    data["previous_receipt_sha256"] = "sha256:tampered"
    lines[1] = dump_canonical_json(data)
    receipts_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = validate_evidence_session(repo_root / ".rig" / "relay", session_id)
    assert result.status == "fail"
    assert result.receipt_chain_status == "invalid"
    assert any("broken chain" in f for f in result.failed_checks)


def test_receipt_hash_verification_failure(session_setup):
    repo_root, session_id, session_root = session_setup
    write_session_manifest(session_root, session_id)
    write_session_receipts(session_root, session_id)

    # Tamper with a field without updating hash
    receipts_path = session_root / "receipts.jsonl"
    lines = receipts_path.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[0])
    data["evidence_sha256"] = "sha256:tampered"
    lines[0] = dump_canonical_json(data)
    receipts_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = validate_evidence_session(repo_root / ".rig" / "relay", session_id)
    assert result.status == "fail"
    assert result.receipt_chain_status == "invalid"
    assert any("hash verification failed" in f for f in result.failed_checks)


def test_receipt_event_name_mismatch(session_setup):
    repo_root, session_id, session_root = session_setup
    write_session_manifest(session_root, session_id)
    write_session_receipts(session_root, session_id)

    # Tamper with event_name in receipts.jsonl (and update hash to pass hash check but fail logical check)
    receipts = load_receipts(session_root)
    receipt = receipts[0]
    tampered_data = receipt.to_dict()
    tampered_data["event_name"] = "wrong.event.name"

    # Re-hash to pass hash verification
    from vibe.core.telemetry.receipts import (
        build_receipt_payload,
        compute_receipt_hashes,
    )

    payload = build_receipt_payload(
        sequence=tampered_data["sequence"],
        session_id=tampered_data["session_id"],
        event_index=tampered_data["event_index"],
        event_name=tampered_data["event_name"],
        evidence_kind=tampered_data["evidence_kind"],
        evidence_relative_path=tampered_data["evidence_relative_path"],
        evidence_sha256=tampered_data["evidence_sha256"],
        previous_receipt_sha256=tampered_data["previous_receipt_sha256"],
    )
    p_hash, r_hash = compute_receipt_hashes(payload)
    tampered_data["receipt_payload_sha256"] = p_hash
    tampered_data["receipt_sha256"] = r_hash

    receipts_path = session_root / "receipts.jsonl"
    lines = receipts_path.read_text(encoding="utf-8").splitlines()
    lines[0] = dump_canonical_json(tampered_data)
    receipts_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = validate_evidence_session(repo_root / ".rig" / "relay", session_id)
    assert result.status == "fail"
    assert result.receipt_chain_status == "invalid"
    assert any("event_name mismatch" in f for f in result.failed_checks)


def test_missing_receipt_for_file_producing_event(session_setup):
    repo_root, session_id, session_root = session_setup
    write_session_manifest(session_root, session_id)
    write_session_receipts(session_root, session_id)

    # Remove one receipt line
    receipts_path = session_root / "receipts.jsonl"
    lines = receipts_path.read_text(encoding="utf-8").splitlines()
    lines.pop(0)
    receipts_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = validate_evidence_session(repo_root / ".rig" / "relay", session_id)
    assert result.status == "fail"
    assert result.receipt_chain_status == "invalid"
    assert any("missing a receipt" in f for f in result.failed_checks)


def test_validation_is_read_only(session_setup):
    repo_root, session_id, session_root = session_setup
    receipts_path = session_root / "receipts.jsonl"
    assert not receipts_path.exists()

    validate_evidence_session(repo_root / ".rig" / "relay", session_id)
    assert not receipts_path.exists()


def test_doctor_receipt_output(session_setup, monkeypatch, capsys):
    repo_root, session_id, session_root = session_setup
    write_session_manifest(session_root, session_id)
    write_session_receipts(session_root, session_id)

    from vibe.core.telemetry.doctor import run_evidence_validation

    run_evidence_validation(repo_root / ".rig" / "relay", session_id)
    captured = capsys.readouterr()
    out = captured.out
    assert "receipts: 2" in out
    assert "receipt chain status: valid" in out
    assert "final receipt hash:" in out
    assert "sha256:" in out


def test_doctor_json_receipt_fields(session_setup, monkeypatch, capsys):
    repo_root, session_id, session_root = session_setup
    write_session_manifest(session_root, session_id)
    write_session_receipts(session_root, session_id)

    from vibe.core.telemetry.doctor import run_evidence_validation

    run_evidence_validation(repo_root / ".rig" / "relay", session_id, json_output=True)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["receipt_count"] == 2
    assert data["receipt_chain_status"] == "valid"
    assert data["final_receipt_sha256"].startswith("sha256:")
