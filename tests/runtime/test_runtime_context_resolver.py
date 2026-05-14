from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from pydantic import ValidationError
import pytest

from rig_relay.coordination.worktree_manager import WorktreeRecord
from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.context_resolver import RuntimeContextResolver

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "schemas"
    / "rig.relay.runtime_context.v1.schema.json"
)


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _write_session(tmp_path: Path, session_id: str = "session-001") -> Path:
    root = tmp_path / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    payload = {"session_id": session_id, "status": "active"}
    (root / "current.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_explicit_session_and_task_resolve(tmp_path: Path) -> None:
    resolver = RuntimeContextResolver(repo_root=tmp_path)
    result = resolver.resolve_for_intent(
        "validate",
        session_id="session-1",
        task_id="task-1",
        paths=[str(tmp_path / "file.txt")],
    )
    assert result.status == "resolved"
    assert result.context is not None
    assert result.context.session_id == "session-1"
    assert result.context.task_id == "task-1"
    assert result.context.resolved_from == []


def test_missing_task_derives_when_allowed(tmp_path: Path) -> None:
    resolver = RuntimeContextResolver(repo_root=tmp_path)
    result = resolver.resolve_for_intent("validate", session_id="session-1")
    assert result.status == "resolved"
    assert result.context is not None
    assert result.context.task_id.startswith("task_")
    assert "derived_task_id" in result.context.resolved_from
    assert any(
        "derived deterministically" in warning for warning in result.context.warnings
    )


def test_missing_task_blocks_when_disallowed(tmp_path: Path) -> None:
    resolver = RuntimeContextResolver(repo_root=tmp_path)
    result = resolver.resolve_for_intent(
        "validate", session_id="session-1", allow_create_task=False
    )
    assert result.status == "blocked"
    assert result.error_kind == "task_required"


def test_missing_session_blocks_without_inference(tmp_path: Path) -> None:
    resolver = RuntimeContextResolver(repo_root=tmp_path)
    result = resolver.resolve_for_intent("validate", task_id="task-1")
    assert result.status == "blocked"
    assert result.error_kind == "session_required"


def test_session_inferred_from_session_root(tmp_path: Path) -> None:
    session_root = _write_session(tmp_path)
    resolver = RuntimeContextResolver(session_root=session_root, repo_root=tmp_path)
    result = resolver.resolve_for_intent("validate")
    assert result.status == "resolved"
    assert result.context is not None
    assert result.context.session_id == "session-001"
    assert result.context.resolved_from


def test_workspace_and_lane_pass_through(tmp_path: Path) -> None:
    resolver = RuntimeContextResolver(repo_root=tmp_path)
    result = resolver.resolve_for_intent(
        "validate", session_id="session-1", workspace_id="lane-9", lane_id="lane-9"
    )
    assert result.status == "resolved"
    assert result.context is not None
    assert result.context.workspace_id == "lane-9"
    assert result.context.lane_id == "lane-9"


def test_require_worktree_blocks_when_absent(tmp_path: Path) -> None:
    resolver = RuntimeContextResolver(repo_root=tmp_path)
    result = resolver.resolve_for_intent(
        "validate", session_id="session-1", require_worktree=True
    )
    assert result.status == "blocked"
    assert result.error_kind == "worktree_required"


def test_worktree_path_included_when_available(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    worktree_root = repo_root / ".rig" / "relay" / "worktrees"
    workspace_id = "lane-1"
    path = worktree_root / workspace_id
    path.mkdir(parents=True, exist_ok=True)

    class FakeWorktreeManager:
        def inspect(self, workspace_id: str) -> WorktreeRecord | None:
            if workspace_id != "lane-1":
                return None
            return WorktreeRecord(workspace_id=workspace_id, path=str(path))

        def list_worktrees(self) -> list[WorktreeRecord]:
            return [WorktreeRecord(workspace_id=workspace_id, path=str(path))]

    manager = FakeWorktreeManager()
    resolver = RuntimeContextResolver(
        worktree_manager=manager,
        repo_root=repo_root,
        session_root=_write_session(tmp_path),
    )
    result = resolver.resolve_for_intent(
        "validate",
        workspace_id=workspace_id,
        session_id="session-1",
        require_worktree=True,
    )
    assert result.status == "resolved"
    assert result.context is not None
    assert result.context.worktree_path == str(path)


def test_unsafe_paths_are_refused(tmp_path: Path) -> None:
    resolver = RuntimeContextResolver(repo_root=tmp_path)
    outside = tmp_path.parent / "outside.txt"
    result = resolver.resolve_for_intent(
        "validate", session_id="session-1", paths=[str(outside)]
    )
    assert result.status == "refused"
    assert result.error_kind == "unsafe_path"


def test_warnings_record_inferred_ids(tmp_path: Path) -> None:
    session_root = _write_session(tmp_path)
    resolver = RuntimeContextResolver(session_root=session_root, repo_root=tmp_path)
    result = resolver.resolve_for_intent("validate")
    assert result.context is not None
    assert result.context.warnings


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RuntimeContext.model_validate({
            "session_id": "s",
            "task_id": "t",
            "bad": "nope",
        })
    with pytest.raises(ValidationError):
        RuntimeContextResolution.model_validate({"status": "resolved", "extra": "nope"})


def test_schema_validates_actual_dump(tmp_path: Path) -> None:
    resolver = RuntimeContextResolver(repo_root=tmp_path)
    result = resolver.resolve_for_intent("validate", session_id="session-1")
    assert result.context is not None
    jsonschema.validate(instance=result.model_dump(mode="json"), schema=_schema())


def test_schema_rejects_unknown_fields() -> None:
    schema = _schema()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={
                "schema_version": "rig.relay.runtime_context.v1",
                "session_id": "s",
                "task_id": "t",
                "resolved_from": [],
                "warnings": [],
                "extra": "nope",
            },
            schema=schema,
        )
