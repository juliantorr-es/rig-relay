from __future__ import annotations

import json
from pathlib import Path

from rig_relay.coordination import (
    CoordinationStore as LegacyCoordinationStore,
    FileCoordinationStore,
)
from rig_relay.coordination._models import (
    CoordinationSession as LegacyCoordinationSession,
    reset_path_salt_for_testing,
)
from rig_relay.coordination.models import (
    CoordinationSession,
    salted_path_hash,
    stable_path_key,
)
from rig_relay.coordination.store import (
    CoordinationStore,
    CoordinationStore as LegacyStoreModuleStore,
)


def test_relay_native_imports_work() -> None:
    session = CoordinationSession(session_id="s1", status="active")
    assert session.session_id == "s1"
    assert stable_path_key(
        "tests/coordination/test_coordination_ownership_migration.py"
    ).startswith("coord:")
    assert salted_path_hash(
        "tests/coordination/test_coordination_ownership_migration.py"
    ).startswith("sha256:")


def test_legacy_imports_reexport_relay_native_types() -> None:
    assert LegacyCoordinationStore is CoordinationStore
    assert FileCoordinationStore is CoordinationStore
    assert LegacyStoreModuleStore is CoordinationStore
    assert LegacyCoordinationSession is CoordinationSession


def test_store_behavior_is_unchanged(tmp_path: Path) -> None:
    reset_path_salt_for_testing()
    store = CoordinationStore(tmp_path)
    session = store.register_session(
        CoordinationSession(session_id="s1", status="active")
    )
    store.heartbeat(
        session_id=session.session_id,
        task_id="task-1",
        status="running",
        reserved_paths=["vibe/core/tools/builtins/task.py"],
    )

    events_path = tmp_path / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]

    assert events[-1]["event_name"] == "coord.session.heartbeat"
    assert events[-1]["event_hash"].startswith("sha256:")
    assert events[-1]["payload"]["path_count"] == 1
