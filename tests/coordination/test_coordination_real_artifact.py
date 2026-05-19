from __future__ import annotations

import concurrent.futures
import fcntl
import json
import os
from pathlib import Path
import threading

import pytest

pytestmark = [pytest.mark.real_artifact, pytest.mark.adversarial, pytest.mark.substrate]

from jsonschema import validate

from rig_relay.coordination._canonical_json import dump_canonical_json
from rig_relay.coordination.models import (
    CoordinationEvent,
    CoordinationSession,
    build_seam_discovered_payload,
    reset_path_salt_for_testing,
    salted_path_hash,
)
from rig_relay.coordination.store import CoordinationStore, check_ledger_integrity

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"
_SEAM_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.coordination.seam_event.v1.schema.json"


def _seam_schema() -> dict:
    return json.loads(_SEAM_SCHEMA_PATH.read_text(encoding="utf-8"))


def _sample_seam_payload(
    contract_family_id: str = "ci_cd", severity: str = "high"
) -> dict:
    reset_path_salt_for_testing()
    paths = [
        f"docs/schemas/rig.{contract_family_id}.example.schema.json",
        f"rig_relay/{contract_family_id}/producer.py",
        f"tests/{contract_family_id}/test_producer.py",
    ]
    return build_seam_discovered_payload(
        contract_family_id=contract_family_id,
        seam_class="schema_authority_disconnected",
        severity=severity,
        proof_chain_status="partial",
        fake_green_risk="medium",
        affected_file_hashes=[salted_path_hash(p) for p in paths],
        evidence_file_hashes=[salted_path_hash(p) for p in paths],
        schema_file_hashes=[salted_path_hash(paths[0])],
        implementation_file_hashes=[salted_path_hash(paths[1])],
        validator_file_hashes=[],
        test_file_hashes=[salted_path_hash(paths[2])],
        trace_fields_observed=["trace_id"],
        trace_fields_missing=["span_id"],
        telemetry_redaction_implications="",
        concurrency_implications="",
        recommended_next_action=f"Fix {contract_family_id} seam.",
        detected_by="audit",
    )


# ── Real ledger JSONL writes ─────────────────────────────────────────────────


class _LedgerWriter:
    def __init__(self, ledger_path: Path, lock_path: Path) -> None:
        self.ledger_path = ledger_path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.touch(exist_ok=True)
        self._lock_fd = open(lock_path, "r+b")
        self._thread_lock = threading.Lock()

    def _acquire(self) -> None:
        self._thread_lock.acquire()
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX)

    def _release(self) -> None:
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        self._thread_lock.release()

    def _next_sequence(self) -> int:
        if not self.ledger_path.is_file():
            return 1
        max_seq = 0
        with open(self.ledger_path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    seq = event.get("sequence", 0) or 0
                    max_seq = max(max_seq, seq)
                except json.JSONDecodeError:
                    pass
        return max_seq + 1

    def append_event(self, event_name: str, normalized_payload: dict) -> None:
        self._acquire()
        try:
            seq = self._next_sequence()
            payload_json = dump_canonical_json(normalized_payload)
            event = CoordinationEvent(
                event_id=(
                    "sha256:"
                    + __import__("hashlib")
                    .sha256(dump_canonical_json(payload_json).encode("utf-8"))
                    .hexdigest()
                ),
                session_id=normalized_payload.get("session_id"),
                task_id=normalized_payload.get("task_id"),
                sequence=seq,
                event_name=event_name,
                payload=normalized_payload,
                event_hash=(
                    "sha256:"
                    + __import__("hashlib")
                    .sha256(dump_canonical_json(payload_json).encode("utf-8"))
                    .hexdigest()
                ),
            )
            line = dump_canonical_json(event.model_dump(exclude_none=True)) + "\n"
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        finally:
            self._release()


def _make_writer(tmp_path: Path) -> _LedgerWriter:
    root = tmp_path / ".build" / "rig-relay"
    root.mkdir(parents=True, exist_ok=True)
    return _LedgerWriter(root / "events.jsonl", root / ".digester.lock")


def test_ledger_records_seam_event_into_jsonl(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    payload = _sample_seam_payload()
    writer.append_event("rig.relay.coordination.contract_seam_discovered", payload)

    lines = writer.ledger_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event_name"] == "rig.relay.coordination.contract_seam_discovered"
    assert event["payload"]["contract_family_id"] == "ci_cd"
    assert "sequence" in event
    assert "event_id" in event
    assert "event_hash" in event


def test_ledger_lines_validate_against_schema(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    for _i, cid in enumerate(["ci_cd", "mcp", "acp", "sdk"]):
        payload = _sample_seam_payload(contract_family_id=cid)
        writer.append_event("rig.relay.coordination.contract_seam_discovered", payload)

    lines = writer.ledger_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 4

    schema = _seam_schema()
    for line in lines:
        event = json.loads(line)
        validate(instance=event["payload"], schema=schema)


def test_ledger_integrity_passes_after_valid_writes(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    for i in range(5):
        payload = _sample_seam_payload(contract_family_id=f"surface_{i}")
        writer.append_event("rig.relay.coordination.contract_seam_discovered", payload)

    findings = check_ledger_integrity(writer.ledger_path)
    assert len(findings) == 0, f"Integrity findings: {findings}"


def test_malformed_jsonl_detected(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    payload = _sample_seam_payload()
    writer.append_event("rig.relay.coordination.contract_seam_discovered", payload)

    with open(writer.ledger_path, "a", encoding="utf-8") as f:
        f.write("this is not json\n")
        f.flush()
        os.fsync(f.fileno())

    findings = check_ledger_integrity(writer.ledger_path)
    malformed = [f for f in findings if f["type"] == "malformed_json"]
    assert len(malformed) == 1
    assert malformed[0]["line_number"] == 2


def test_duplicate_event_id_detected(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    payload = _sample_seam_payload()
    writer.append_event("rig.relay.coordination.contract_seam_discovered", payload)

    lines = writer.ledger_path.read_text(encoding="utf-8").strip().split("\n")
    first_event = json.loads(lines[0])

    duplicate = dict(first_event)
    duplicate["sequence"] = 999
    with open(writer.ledger_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(duplicate) + "\n")
        f.flush()
        os.fsync(f.fileno())

    findings = check_ledger_integrity(writer.ledger_path)
    dup_events = [f for f in findings if f["type"] == "duplicate_event_id"]
    assert len(dup_events) == 1, f"No duplicate_event_id finding in: {findings}"


def test_duplicate_event_id_rejected_by_ledger_integrity(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    same_payload = _sample_seam_payload(contract_family_id="dupe_test")
    writer.append_event("rig.relay.coordination.contract_seam_discovered", same_payload)
    writer.append_event("rig.relay.coordination.contract_seam_discovered", same_payload)

    lines = writer.ledger_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2

    findings = check_ledger_integrity(writer.ledger_path)
    dup_events = [f for f in findings if f["type"] == "duplicate_event_id"]
    assert len(dup_events) >= 1


def test_concurrent_seam_writes_do_not_corrupt_ledger(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    n_workers = 4
    n_ops = 10
    barrier = threading.Barrier(n_workers)

    def worker(worker_id: int) -> None:
        barrier.wait()
        for i in range(n_ops):
            payload = _sample_seam_payload(
                contract_family_id=f"w{worker_id}_op{i}", severity="high"
            )
            writer.append_event(
                "rig.relay.coordination.contract_seam_discovered", payload
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(worker, i) for i in range(n_workers)]
        for f in futures:
            f.result()

    findings = check_ledger_integrity(writer.ledger_path)
    malformed = [f for f in findings if f["type"] == "malformed_json"]
    assert len(malformed) == 0, f"Malformed JSON found: {malformed}"

    lines = [
        l.strip()
        for l in writer.ledger_path.read_text(encoding="utf-8").split("\n")
        if l.strip()
    ]
    assert len(lines) == n_workers * n_ops

    sequences = []
    for line in lines:
        event = json.loads(line)
        sequences.append(event["sequence"])
    assert len(sequences) == len(set(sequences)), (
        f"Duplicate sequences from concurrent writes. Sequences: {sorted(sequences)}"
    )


def test_concurrent_writes_preserve_line_boundaries(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    n_workers = 4
    n_ops = 5
    barrier = threading.Barrier(n_workers)

    def worker(worker_id: int) -> None:
        barrier.wait()
        for i in range(n_ops):
            payload = _sample_seam_payload(
                contract_family_id=f"boundary_{worker_id}_{i}"
            )
            writer.append_event(
                "rig.relay.coordination.contract_seam_discovered", payload
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(worker, i) for i in range(n_workers)]
        for f in futures:
            f.result()

    lines = [
        l.strip()
        for l in writer.ledger_path.read_text(encoding="utf-8").split("\n")
        if l.strip()
    ]
    assert len(lines) == n_workers * n_ops
    for line in lines:
        json.loads(line)


# ── Seam-event content-light enforcement on real ledger ──────────────────────


def test_ledger_payloads_contain_no_raw_paths(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    payload = _sample_seam_payload()
    writer.append_event("rig.relay.coordination.contract_seam_discovered", payload)

    raw = writer.ledger_path.read_text(encoding="utf-8")
    assert "rig_relay/ci_cd/producer.py" not in raw
    assert "docs/schemas/" not in raw or "docs/schemas/rig." not in raw


def test_ledger_with_seam_and_session_events_stays_valid(tmp_path: Path) -> None:
    store = CoordinationStore(tmp_path / ".build" / "rig-relay" / "coordination")
    session = CoordinationSession(
        session_id="sess-ledger-1",
        task_id="task-1",
        agent_profile="auditor",
        status="running",
    )
    store.register_session(session)

    writer = _LedgerWriter(store.root / "events.jsonl", store.root / ".digester.lock")
    payload = _sample_seam_payload()
    writer.append_event("rig.relay.coordination.contract_seam_discovered", payload)

    findings = check_ledger_integrity(store.root / "events.jsonl")
    assert len(findings) == 0, f"Integrity findings with mixed events: {findings}"

    lines = [
        l.strip()
        for l in (store.root / "events.jsonl").read_text(encoding="utf-8").split("\n")
        if l.strip()
    ]
    event_names = {json.loads(l)["event_name"] for l in lines}
    assert "coord.session.registered" in event_names
    assert "rig.relay.coordination.contract_seam_discovered" in event_names
