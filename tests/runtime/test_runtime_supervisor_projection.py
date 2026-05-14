"""Tests for RuntimeSupervisorProjection — content-light derived projection.

All tests use synthetic audit events — never read real files or user paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.runtime.runtime_audit_event import (
    RuntimeAuditEvent,
    RuntimeAuditPersistenceStore,
)
from rig_relay.runtime.runtime_supervisor_projection import (
    RuntimeSupervisorProjection,
    build_runtime_supervisor_projection,
)

# ── Constants ──────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECTION_SCHEMA_PATH = (
    REPO_ROOT
    / "docs"
    / "schemas"
    / "rig.relay.runtime_supervisor_projection.v1.schema.json"
)

FORBIDDEN_RAW_FIELD_NAMES: frozenset[str] = frozenset({
    "content",
    "stdout",
    "stderr",
    "output_text",
    "diff",
    "patch",
    "snippet",
    "file_contents",
    "old_text",
    "new_text",
    "chunk_text",
    "prompt",
    "secret",
    "argv",
})


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def projection_schema_dict() -> dict:
    raw = json.loads(PROJECTION_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert raw is not None, f"Schema not found at {PROJECTION_SCHEMA_PATH}"
    return raw


def _make_event(
    status: str = "completed",
    tool_name: str = "validate",
    changed_paths: list[str] | None = None,
    created_at: str | None = None,
) -> RuntimeAuditEvent:
    return RuntimeAuditEvent(
        audit_event_id=f"aev-{status}",
        invocation_id=f"inv-{status}",
        tool_name=tool_name,
        status=status,
        changed_paths=changed_paths or [],
        created_at=created_at or f"2026-01-01T00:00:0{0}",
    )


def _make_store(
    events: list[RuntimeAuditEvent], tmp_path: Path
) -> RuntimeAuditPersistenceStore:
    store = RuntimeAuditPersistenceStore(tmp_path / "audit.jsonl")
    for event in events:
        store.append(event)
    return store


# ── Projection tests ───────────────────────────────────────────────────


class TestRuntimeSupervisorProjection:
    def test_empty_projection(self) -> None:
        projection = build_runtime_supervisor_projection([])
        assert projection.total_invocations == 0
        assert projection.status_counts == {}
        assert projection.recent_invocations == []
        assert projection.changed_path_count == 0

    def test_status_counts(self) -> None:
        events = [
            _make_event("completed"),
            _make_event("completed"),
            _make_event("blocked"),
            _make_event("refused"),
        ]
        projection = build_runtime_supervisor_projection(events)
        assert projection.total_invocations == 4
        assert projection.status_counts == {"completed": 2, "blocked": 1, "refused": 1}

    def test_recent_invocations_ordered_by_created_at(self) -> None:
        events = [
            _make_event("completed", created_at="2026-01-01T00:00:01"),
            _make_event("blocked", created_at="2026-01-01T00:00:02"),
            _make_event("refused", created_at="2026-01-01T00:00:03"),
            _make_event("completed", created_at="2026-01-01T00:00:04"),
        ]
        projection = build_runtime_supervisor_projection(events, max_recent=3)
        assert len(projection.recent_invocations) == 3
        # Most recent first
        assert projection.recent_invocations[0].status == "completed"
        assert projection.recent_invocations[0].created_at == "2026-01-01T00:00:04"

    def test_changed_path_count(self) -> None:
        events = [
            _make_event("completed", changed_paths=["a.py"]),
            _make_event("completed", changed_paths=["b.py", "c.py"]),
        ]
        projection = build_runtime_supervisor_projection(events)
        assert projection.changed_path_count == 3

    def test_changed_path_hashes_from_sha256(self) -> None:
        events = [_make_event("completed"), _make_event("completed")]
        projection = build_runtime_supervisor_projection(events)
        # runtime_result_sha256 is None for basic events, so changed_path_hashes is empty
        assert projection.changed_path_hashes == []

    def test_projection_from_store(self, tmp_path: Path) -> None:
        events = [_make_event("completed"), _make_event("blocked")]
        store = _make_store(events, tmp_path)
        projection = build_runtime_supervisor_projection(store)
        assert projection.total_invocations == 2
        assert projection.status_counts == {"completed": 1, "blocked": 1}

    def test_max_recent_caps_invocations(self) -> None:
        events = [_make_event("completed") for _ in range(25)]
        projection = build_runtime_supervisor_projection(events, max_recent=10)
        assert len(projection.recent_invocations) == 10


# ── Content-light enforcement tests ────────────────────────────────────


class TestRuntimeSupervisorProjectionContentLight:
    def test_projection_model_rejects_raw_fields(self) -> None:
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            with pytest.raises(ValueError, match="Extra inputs are not permitted"):
                RuntimeSupervisorProjection.model_validate({
                    "schema_version": "rig.relay.runtime_supervisor_projection.v1",
                    "projection_id": "proj-001",
                    "created_at": "2026-01-01T00:00:00",
                    "total_invocations": 0,
                    forbidden: "some raw value",
                })

    def test_projection_dump_has_no_forbidden_fields(self) -> None:
        projection = build_runtime_supervisor_projection([])
        dumped = json.dumps(projection.model_dump(mode="json"))
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in projection dump"
            )

    def test_projection_from_store_has_no_forbidden_fields(
        self, tmp_path: Path
    ) -> None:
        events = [_make_event("completed"), _make_event("blocked")]
        store = _make_store(events, tmp_path)
        projection = build_runtime_supervisor_projection(store)
        dumped = json.dumps(projection.model_dump(mode="json"))
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            assert forbidden not in dumped, (
                f"Found forbidden field '{forbidden}' in store-derived projection dump"
            )


# ── Schema validation tests ────────────────────────────────────────────


class TestRuntimeSupervisorProjectionSchema:
    def test_minimal_projection_validates(self, projection_schema_dict: dict) -> None:
        projection = build_runtime_supervisor_projection([])
        validator = jsonschema.Draft7Validator(projection_schema_dict)
        errors = list(validator.iter_errors(projection.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_full_projection_validates(self, projection_schema_dict: dict) -> None:
        events = [
            _make_event("completed"),
            _make_event("blocked"),
            _make_event("refused"),
        ]
        projection = build_runtime_supervisor_projection(events)
        validator = jsonschema.Draft7Validator(projection_schema_dict)
        errors = list(validator.iter_errors(projection.model_dump(mode="json")))
        assert errors == [], f"Schema errors: {[e.message for e in errors]}"

    def test_schema_rejects_forbidden_fields(
        self, projection_schema_dict: dict
    ) -> None:
        base = RuntimeSupervisorProjection(
            projection_id="proj-001",
            created_at="2026-01-01T00:00:00",
            total_invocations=0,
        ).model_dump(mode="json")
        validator = jsonschema.Draft7Validator(projection_schema_dict)
        for forbidden in FORBIDDEN_RAW_FIELD_NAMES:
            bad = dict(base)
            bad[forbidden] = "some raw value"
            errors = list(validator.iter_errors(bad))
            assert errors, f"Schema should reject forbidden field '{forbidden}'"
