from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from rig_relay.coordination.models import reset_path_salt_for_testing
from rig_relay.coordination.store import CoordinationStore, check_ledger_integrity

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent.parent / "scripts"
SCHEMAS_SRC = THIS_DIR.parent.parent / "docs" / "schemas"
GOLDEN_PATH_CHECKER = SCRIPTS_DIR / "rig_rc_golden_path_check.py"
VALIDATOR_PATH = SCRIPTS_DIR / "rig_release_gate_validate.py"


def _repr_root(tmp: Path) -> Path:
    (tmp / "docs" / "schemas").mkdir(parents=True, exist_ok=True)
    (tmp / "docs" / "json" / "release_candidate").mkdir(parents=True, exist_ok=True)
    (tmp / "docs" / "json" / "release_gate").mkdir(parents=True, exist_ok=True)
    (tmp / "frontend" / "desktop").mkdir(parents=True, exist_ok=True)
    (tmp / "rig_relay" / "desktop").mkdir(parents=True, exist_ok=True)
    (tmp / "tests" / "desktop").mkdir(parents=True, exist_ok=True)

    for name in [
        "rig.release_gate.readiness.v1.schema.json",
        "rig.release_gate.blocker.v1.schema.json",
        "rig.release_gate.validation_run.v1.schema.json",
        "rig.release_gate.phase.v1.schema.json",
        "rig.release_candidate.reviewer_golden_path.v1.schema.json",
        "rig.release_candidate.installability_check.v1.schema.json",
        "rig.relay.desktop_projection.v1.schema.json",
    ]:
        src = SCHEMAS_SRC / name
        if src.exists():
            (tmp / "docs" / "schemas" / name).write_text(src.read_text())

    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp, capture_output=True, check=True
    )
    (tmp / "dummy.txt").write_text("test")
    subprocess.run(
        ["git", "add", "dummy.txt"], cwd=tmp, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=True
    )

    return tmp


def _write_minimal_gate(tmp: Path, **overrides) -> Path:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp, text=True
    ).strip()
    base = {
        "schema_version": "rig.release_gate.readiness.v1",
        "gate_id": "test_gate",
        "repository": "",
        "head_sha": head,
        "branch": "test",
        "generated_at": "2026-05-17T00:00:00Z",
        "overall_status": "unknown",
        "phases": [
            {
                "phase_id": "phase_1",
                "title": "Phase 1",
                "status": "unknown",
                "owner_surface": "test",
                "source_commit": head,
            }
        ],
        "policy": {
            "allowed_markdown_exceptions": [
                "AGENTS.md",
                "README.md",
                "LICENSE",
                "CONTRIBUTING.md",
                "SECURITY.md",
                "CODE_OF_CONDUCT.md",
                "CHANGELOG.md",
                "THIRD_PARTY_NOTICES.md",
                "ATTRIBUTION.md",
                "UPSTREAM.md",
            ]
        },
    }
    base.update(overrides)
    p = tmp / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json"
    p.write_text(json.dumps(base, indent=2))
    return p


def _write_blockers(tmp: Path, entries: list[dict]) -> Path:
    p = tmp / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
    with p.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def _write_validation_runs(tmp: Path, entries: list[dict]) -> Path:
    p = tmp / "docs" / "json" / "release_gate" / "rc_validation_runs.v1.jsonl"
    with p.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def _write_golden_path(tmp: Path, steps: list[dict], overall: str = "blocked") -> Path:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp, text=True
    ).strip()
    if not steps:
        dummy_step = {
            "step_id": "gp_placeholder_no_blocking",
            "user_goal": "Placeholder",
            "command_or_ui_action": "N/A",
            "expected_result": "N/A",
            "evidence_path": str(tmp / "evidence/dummy.json"),
            "blocking_failure_conditions": [],
            "status": "passing",
            "validation_method": "manual_review",
            "phase_id": "phase_6_dogfood_operational_readiness",
        }
        steps = [dummy_step]
        (tmp / "evidence").mkdir(exist_ok=True)
        (tmp / "evidence" / "dummy.json").write_text("{}")
    gp = {
        "schema_version": "rig.release_candidate.reviewer_golden_path.v1",
        "golden_path_id": "rc_dogfood_v1",
        "generated_at": "2026-05-17T00:00:00Z",
        "head_sha": head,
        "branch": "test",
        "title": "Test Golden Path",
        "description": "Test",
        "overall_status": overall,
        "steps": steps,
        "evidence_paths": [],
    }
    p = tmp / "docs" / "json" / "release_candidate" / "rc_reviewer_golden_path.v1.json"
    p.write_text(json.dumps(gp, indent=2))
    return p


def _write_installability(tmp: Path, overall: str = "passed") -> Path:
    p = (
        tmp
        / "docs"
        / "json"
        / "release_candidate"
        / "rc_installability_verdict.v1.json"
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp, text=True
    ).strip()
    p.write_text(
        json.dumps({
            "schema_version": "rig.release_candidate.installability_check.v1",
            "generated_at": "2026-05-17T00:00:00Z",
            "branch": "test",
            "head_sha": head,
            "package_name": "test",
            "package_version": "1.0",
            "python_requires": ">=3.12",
            "overall_status": overall,
            "cli_entry_points_checked": ["rig-relay", "rig-relay-acp"],
            "public_docs_checked": ["README.md"],
            "license_status": "pass",
            "checks": [],
            "errors": [],
            "warnings": [],
            "evidence_paths": [],
            "commands_run": [],
            "duration_ms": 100,
            "required_next_actions": [],
        })
    )
    return p


def _write_deferred_risks(tmp: Path) -> Path:
    p = tmp / "docs" / "json" / "release_gate" / "rc_deferred_risks.v1.jsonl"
    p.write_text("")
    return p


def _run_validator_in_tmp(tmp: Path) -> dict:
    gate_p = str(tmp / "docs" / "json" / "release_gate" / "rc_readiness_gate.v1.json")
    blockers_p = str(tmp / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl")
    vruns_p = str(
        tmp / "docs" / "json" / "release_gate" / "rc_validation_runs.v1.jsonl"
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR_PATH),
            "--repo-root",
            str(tmp),
            "--readiness-gate",
            gate_p,
            "--blockers",
            blockers_p,
            "--validation-runs",
            vruns_p,
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp),
        timeout=30,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Validator produced invalid JSON. stderr={proc.stderr[:500]}, "
            f"stdout={proc.stdout[:500]}, returncode={proc.returncode}"
        )


def _run_golden_path_checker(tmp: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(GOLDEN_PATH_CHECKER), "--repo-root", str(tmp)],
        capture_output=True,
        text=True,
        cwd=str(tmp),
        timeout=30,
    )
    return json.loads(proc.stdout)


def _make_blocker(blocker_id: str, status: str = "open", **overrides) -> dict:
    base = {
        "blocker_id": blocker_id,
        "phase_id": "phase_1",
        "severity": "high",
        "title": f"Blocker {blocker_id}",
        "description": f"Description for {blocker_id}",
        "status": status,
        "discovered_by": "test",
        "source_commit": "abc1230000000000000000000000000000000000",
        "created_at": "2026-05-17T00:00:00Z",
        "updated_at": "2026-05-17T00:00:00Z",
    }
    base.update(overrides)
    return base


def _make_step(
    step_id: str,
    status: str = "not_verified",
    validation_method: str = "manual_review",
    **overrides,
) -> dict:
    base = {
        "step_id": step_id,
        "user_goal": f"Goal for {step_id}",
        "command_or_ui_action": f"Action for {step_id}",
        "expected_result": f"Result for {step_id}",
        "evidence_path": f"evidence/{step_id}.json",
        "blocking_failure_conditions": ["failure condition"],
        "status": status,
        "validation_method": validation_method,
        "phase_id": "phase_6_dogfood_operational_readiness",
    }
    base.update(overrides)
    if isinstance(base["evidence_path"], Path):
        base["evidence_path"] = str(base["evidence_path"])
    return base


def _make_valid_event_line(
    event_id: str | None = None,
    sequence: int | None = None,
    event_name: str | None = "coord.test.event",
    created_at: str | None = "2025-01-01T00:00:00+00:00",
) -> str:
    eid = event_id or f"evt-{hash(sequence) & 0xFFFFFFFF:08x}"
    seq_val = sequence if sequence is not None else 1
    return json.dumps({
        "schema_version": "rig.relay.coordination.event.v1",
        "event_id": eid,
        "sequence": seq_val,
        "event_name": event_name,
        "created_at": created_at,
        "payload": {},
        "event_hash": f"sha256:deadbeef{eid}",
        "session_id": None,
        "task_id": None,
    })


# ── Evidence snapshot consistency and stale detection ───────────────────


@pytest.mark.contract
class TestStaleValidationRunDetection:
    def test_validator_detects_stale_validation_run_head_mismatch(
        self, tmp_path: Path
    ) -> None:
        tmp = _repr_root(tmp_path)
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=tmp, text=True
        ).strip()
        stale_commit = "0" * 40
        _write_minimal_gate(
            tmp,
            phases=[
                {
                    "phase_id": "phase_1",
                    "title": "Phase 1",
                    "status": "passing",
                    "owner_surface": "test",
                    "source_commit": head,
                    "validation_run_ids": ["stale_run"],
                }
            ],
        )
        _write_blockers(tmp, [])
        _write_validation_runs(
            tmp,
            [
                {
                    "validation_run_id": "stale_run",
                    "phase_ids": ["phase_1"],
                    "command": "pytest",
                    "result": "passed",
                    "source_commit": stale_commit,
                    "created_at": "2026-05-17T00:00:00Z",
                }
            ],
        )
        _write_golden_path(tmp, [])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        errors = vr.get("errors", [])
        assert any(
            "stale" in e.lower() or "source_commit" in e.lower() for e in errors
        ), f"Expected stale/source_commit mismatch message, got: {errors}"


@pytest.mark.contract
class TestMalformedJsonlDetection:
    def test_validator_rejects_truncated_jsonl(self, tmp_path: Path) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        blockers_p = tmp / "docs" / "json" / "release_gate" / "rc_blockers.v1.jsonl"
        blockers_p.write_text('{"blocker_id": "truncated", "status": "open')
        _write_validation_runs(tmp, [])
        _write_golden_path(tmp, [])
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        vr = _run_validator_in_tmp(tmp)
        errors = vr.get("errors", [])
        has_malformed = (
            any("_parse_error" in e for e in errors)
            or any("malformed" in e.lower() for e in errors)
            or any("json" in e.lower() and "error" in e.lower() for e in errors)
            or vr.get("status") == "failed"
        )
        assert has_malformed, (
            f"Expected malformed JSONL detection, got status={vr.get('status')}, errors={errors[:5]}"
        )


@pytest.mark.contract
class TestGoldenPathMixedStaleEvidence:
    def test_golden_path_checker_rejects_mixed_stale_evidence(
        self, tmp_path: Path
    ) -> None:
        tmp = _repr_root(tmp_path)
        _write_minimal_gate(tmp)
        _write_blockers(tmp, [])
        _write_validation_runs(tmp, [])

        missing_path = "evidence/nonexistent_evidence.json"
        _write_golden_path(
            tmp,
            [
                _make_step(
                    "gp_evidence_test",
                    "passing",
                    validation_method="automated_script",
                    evidence_path=missing_path,
                    blocking_failure_conditions=["failure condition"],
                )
            ],
        )
        _write_installability(tmp, "passed")
        _write_deferred_risks(tmp)

        result = _run_golden_path_checker(tmp)
        consistency_errors = result.get("consistency_errors", [])
        missing_evidence = result.get("missing_evidence", [])
        found = (
            any("gp_evidence_test" in e for e in consistency_errors)
            or "gp_evidence_test" in missing_evidence
            or any(
                "does not exist" in e.lower() and "evidence" in e.lower()
                for e in consistency_errors
            )
        )
        assert found, (
            f"Expected missing evidence for step gp_evidence_test, got consistency_errors={consistency_errors[:5]}, missing_evidence={missing_evidence[:5]}"
        )


@pytest.mark.contract
class TestCoordinationStoreAtomicWrite:
    def test_coordination_store_atomic_write_no_partial_read(
        self, tmp_path: Path
    ) -> None:
        reset_path_salt_for_testing()
        root = tmp_path / ".build" / "rig-relay" / "coordination"
        store = CoordinationStore(root)

        store.reserve_paths(
            session_id="sess-atomic",
            task_id="task-atomic",
            mode="write",
            paths=["src/atomic_test.py"],
            ttl_seconds=120,
        )

        lease_files = list((root / "leases" / "paths").glob("*.json"))
        assert len(lease_files) >= 1, "Expected at least one lease file"
        for lf in lease_files:
            content = lf.read_text(encoding="utf-8")
            parsed = json.loads(content)
            assert parsed.get("session_id") == "sess-atomic"
            assert parsed.get("task_id") == "task-atomic"

        tmp_files = list((root / "leases" / "paths").glob("*.tmp"))
        assert len(tmp_files) == 0, f"Expected no .tmp files, found {tmp_files}"

    def test_coordination_store_append_detects_truncation(self, tmp_path: Path) -> None:
        reset_path_salt_for_testing()
        root = tmp_path / ".build" / "rig-relay" / "coordination"
        store = CoordinationStore(root)

        for i in range(5):
            store.reserve_paths(
                session_id=f"sess-append-{i}",
                task_id=f"task-append-{i}",
                mode="write",
                paths=[f"src/append_test_{i}.py"],
                ttl_seconds=120,
            )

        events_path = root / "events.jsonl"
        assert events_path.is_file(), "events.jsonl should exist"
        lines = events_path.read_text(encoding="utf-8").splitlines(keepends=False)
        non_empty = [l for l in lines if l.strip()]
        assert len(non_empty) >= 5, f"Expected at least 5 events, got {len(non_empty)}"

        for line_no, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                json.loads(stripped)
            except json.JSONDecodeError as e:
                pytest.fail(
                    f"Line {line_no + 1} is not valid JSON: {e} truncated={stripped[:80]}"
                )


@pytest.mark.contract
class TestLedgerIntegrityDuplicateSequence:
    def test_ledger_integrity_detects_duplicate_sequence(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        lines = [
            _make_valid_event_line(sequence=1, event_id="evt-a"),
            _make_valid_event_line(sequence=1, event_id="evt-b"),
        ]
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

        findings = check_ledger_integrity(ledger)
        dup_seqs = [f for f in findings if f["type"] == "duplicate_sequence"]
        assert len(dup_seqs) >= 1, (
            f"Expected duplicate_sequence finding, got: {findings}"
        )


@pytest.mark.contract
class TestLedgerIntegrityMalformedJson:
    def test_ledger_integrity_detects_malformed_json(self, tmp_path: Path) -> None:
        ledger = tmp_path / "events.jsonl"
        lines = [
            _make_valid_event_line(sequence=1, event_id="evt-a"),
            '{"broken": "json',
            _make_valid_event_line(sequence=2, event_id="evt-b"),
        ]
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

        findings = check_ledger_integrity(ledger)
        malformed = [f for f in findings if f["type"] == "malformed_json"]
        assert len(malformed) >= 1, f"Expected malformed_json finding, got: {findings}"
