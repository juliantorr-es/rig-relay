"""Tests for rig_relay.coordination.worktree_manager — P1b Worktree Manager."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import jsonschema
from pydantic import ValidationError
import pytest

from rig_relay.coordination.worktree_manager import (
    WorktreeManager,
    WorktreeOperationKind,
    WorktreeOperationResult,
    WorktreeRecord,
    WorktreeStatus,
)

# ── Fixtures ────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKTREE_SCHEMA_PATH = (
    _PROJECT_ROOT / "docs" / "schemas" / "rig.relay.worktree.v1.schema.json"
)


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo for worktree testing."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    # Create an initial commit so worktree add works
    readme = repo / "README.md"
    readme.write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return repo


@pytest.fixture
def mgr(temp_git_repo: Path) -> WorktreeManager:
    """Create a WorktreeManager for the temp repo."""
    worktree_root = temp_git_repo / ".rig" / "relay" / "worktrees"
    return WorktreeManager(repo_root=temp_git_repo, worktree_root=worktree_root)


@pytest.fixture
def schema() -> dict:
    """Load the worktree schema."""
    with open(_WORKTREE_SCHEMA_PATH) as f:
        return json.load(f)


# ── WorktreeStatus ────────────────────────────────────────────────────


class TestWorktreeStatus:
    def test_all_statuses_present(self):
        assert list(WorktreeStatus) == [
            WorktreeStatus.HEALTHY,
            WorktreeStatus.MISSING,
            WorktreeStatus.DIRTY,
            WorktreeStatus.STALE,
            WorktreeStatus.REMOVED,
            WorktreeStatus.ERROR,
        ]

    def test_string_values(self):
        assert WorktreeStatus.HEALTHY.value == "healthy"
        assert WorktreeStatus.MISSING.value == "missing"
        assert WorktreeStatus.DIRTY.value == "dirty"
        assert WorktreeStatus.REMOVED.value == "removed"

    def test_serializes_as_string(self):
        assert str(WorktreeStatus.HEALTHY) == "healthy"


class TestWorktreeOperationKind:
    def test_all_kinds_present(self):
        assert list(WorktreeOperationKind) == [
            WorktreeOperationKind.CREATE,
            WorktreeOperationKind.REMOVE,
            WorktreeOperationKind.LIST,
            WorktreeOperationKind.INSPECT,
            WorktreeOperationKind.GET_HEAD,
        ]

    def test_string_values(self):
        assert WorktreeOperationKind.CREATE.value == "create"
        assert WorktreeOperationKind.REMOVE.value == "remove"
        assert WorktreeOperationKind.LIST.value == "list"

    def test_serializes_as_string(self):
        assert str(WorktreeOperationKind.CREATE) == "create"


# ── WorktreeRecord ────────────────────────────────────────────────────


class TestWorktreeRecord:
    def test_requires_workspace_id_and_path(self):
        WorktreeRecord(workspace_id="test", path="/tmp/test")

    def test_accepts_all_fields(self):
        r = WorktreeRecord(
            workspace_id="lane-42",
            branch_name="feat/lane-42",
            path="/tmp/worktrees/lane-42",
            head_sha="abc123def456abc123def456abc123def456abc1",
            status=WorktreeStatus.HEALTHY,
            created_at="2026-01-01T00:00:00",
            removed_at="2026-01-02T00:00:00",
            refusal_reason="test",
            error_kind="test_error",
        )
        assert r.workspace_id == "lane-42"
        assert r.branch_name == "feat/lane-42"
        assert r.head_sha == "abc123def456abc123def456abc123def456abc1"

    def test_default_schema_version(self):
        r = WorktreeRecord(workspace_id="test", path="/tmp/test")
        assert r.schema_version == "rig.relay.worktree.v1"

    def test_default_status(self):
        r = WorktreeRecord(workspace_id="test", path="/tmp/test")
        assert r.status == WorktreeStatus.HEALTHY

    def test_optional_fields_default_to_none(self):
        r = WorktreeRecord(workspace_id="test", path="/tmp/test")
        assert r.branch_name is None
        assert r.head_sha is None
        assert r.created_at is None
        assert r.removed_at is None
        assert r.refusal_reason is None
        assert r.error_kind is None

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            WorktreeRecord.model_validate({
                "workspace_id": "test",
                "path": "/tmp/test",
                "unknown_field": "x",
            })

    def test_serializes_to_json(self):
        r = WorktreeRecord(workspace_id="test", path="/tmp/test")
        dump = json.loads(r.model_dump_json())
        assert dump["workspace_id"] == "test"
        assert dump["path"] == "/tmp/test"
        assert dump["schema_version"] == "rig.relay.worktree.v1"
        assert dump["status"] == "healthy"


# ── WorktreeOperationResult ──────────────────────────────────────────


class TestWorktreeOperationResult:
    def test_requires_operation_and_status(self):
        WorktreeOperationResult(
            operation=WorktreeOperationKind.CREATE, status="created"
        )

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            WorktreeOperationResult.model_validate({
                "operation": "create",
                "status": "created",
                "unknown": "x",
            })

    def test_default_schema_version(self):
        r = WorktreeOperationResult(
            operation=WorktreeOperationKind.CREATE, status="created"
        )
        assert r.schema_version == "rig.relay.worktree.v1"

    def test_optional_record(self):
        rec = WorktreeRecord(workspace_id="test", path="/tmp/test")
        r = WorktreeOperationResult(
            operation=WorktreeOperationKind.CREATE, status="created", record=rec
        )
        assert r.record is not None
        assert r.record.workspace_id == "test"

    def test_serializes_to_json(self):
        r = WorktreeOperationResult(
            operation=WorktreeOperationKind.CREATE, status="created"
        )
        dump = json.loads(r.model_dump_json())
        assert dump["operation"] == "create"
        assert dump["status"] == "created"
        assert dump["schema_version"] == "rig.relay.worktree.v1"


# ── WorktreeManager: create ──────────────────────────────────────────


class TestWorktreeManagerCreate:
    def test_creates_linked_worktree(self, mgr: WorktreeManager):
        result = mgr.create(workspace_id="lane-1", branch_name="feat/lane-1")
        assert result.status == "created"
        assert result.record is not None
        assert result.record.workspace_id == "lane-1"
        assert result.record.branch_name == "feat/lane-1"
        assert result.record.status == WorktreeStatus.HEALTHY
        assert result.record.head_sha is not None
        assert len(result.record.head_sha) == 40
        path = Path(result.record.path)
        assert path.exists()
        assert (path / "README.md").exists()

    def test_create_worktree_path_is_under_worktree_root(
        self, mgr: WorktreeManager, temp_git_repo: Path
    ):
        result = mgr.create(workspace_id="lane-2", branch_name="feat/lane-2")
        assert result.record is not None
        path = Path(result.record.path)
        expected_root = temp_git_repo / ".rig" / "relay" / "worktrees"
        assert str(path).startswith(str(expected_root))

    def test_create_refuses_empty_workspace_id(self, mgr: WorktreeManager):
        result = mgr.create(workspace_id="", branch_name="test")
        assert result.status == "refused"
        assert result.error_kind == "invalid_workspace_id"

    def test_create_refuses_path_traversal_workspace_id(self, mgr: WorktreeManager):
        result = mgr.create(workspace_id="../escape", branch_name="test")
        assert result.status == "refused"
        assert result.error_kind == "invalid_workspace_id"

    def test_create_refuses_empty_branch_name(self, mgr: WorktreeManager):
        result = mgr.create(workspace_id="lane-3", branch_name="")
        assert result.status == "refused"
        assert result.error_kind == "invalid_branch_name"

    def test_create_refuses_branch_with_space(self, mgr: WorktreeManager):
        result = mgr.create(workspace_id="lane-4", branch_name="bad branch")
        assert result.status == "refused"
        assert result.error_kind == "invalid_branch_name"

    def test_create_refuses_existing_path(self, mgr: WorktreeManager):
        result1 = mgr.create(workspace_id="lane-5", branch_name="feat/lane-5")
        assert result1.status == "created"
        result2 = mgr.create(workspace_id="lane-5", branch_name="feat/lane-5-alt")
        assert result2.status == "refused"
        assert result2.error_kind == "path_exists"

    def test_create_base_ref_defaults_to_head(self, mgr: WorktreeManager):
        result = mgr.create(workspace_id="lane-6", branch_name="feat/lane-6")
        assert result.status == "created"

    def test_create_returns_content_light_record(self, mgr: WorktreeManager):
        result = mgr.create(workspace_id="lane-7", branch_name="feat/lane-7")
        assert result.record is not None
        # No raw git output, no diffs, no file contents
        assert result.record.refusal_reason is None
        assert result.record.error_kind is None


# ── WorktreeManager: list_worktrees ──────────────────────────────────


class TestWorktreeManagerList:
    def test_list_returns_created_worktrees(self, mgr: WorktreeManager):
        mgr.create(workspace_id="list-1", branch_name="feat/list-1")
        mgr.create(workspace_id="list-2", branch_name="feat/list-2")
        records = mgr.list_worktrees()
        ids = {r.workspace_id for r in records}
        assert "list-1" in ids
        assert "list-2" in ids

    def test_list_returns_main_worktree(
        self, mgr: WorktreeManager, temp_git_repo: Path
    ):
        # By default, only the main worktree may appear if it's under worktree_root
        # The main worktree is at repo root, which shouldn't be under worktree_root
        records = mgr.list_worktrees()
        # No worktrees created yet
        assert len(records) == 0

    def test_list_parses_porcelain_output(self, mgr: WorktreeManager):
        mgr.create(workspace_id="list-3", branch_name="feat/list-3")
        records = mgr.list_worktrees()
        assert len(records) >= 1
        r = [rec for rec in records if rec.workspace_id == "list-3"][0]
        assert r.head_sha is not None
        assert len(r.head_sha) == 40
        assert r.branch_name == "feat/list-3"

    def test_list_empty_when_no_worktrees(self, mgr: WorktreeManager):
        records = mgr.list_worktrees()
        assert len(records) == 0

    def test_list_content_light(self, mgr: WorktreeManager):
        mgr.create(workspace_id="list-4", branch_name="feat/list-4")
        records = mgr.list_worktrees()
        for r in records:
            # No refusal reasons on healthy records
            assert r.refusal_reason is None


# ── WorktreeManager: get_head_hash ────────────────────────────────────


class TestWorktreeManagerGetHead:
    def test_returns_sha_for_created_worktree(self, mgr: WorktreeManager):
        mgr.create(workspace_id="head-1", branch_name="feat/head-1")
        sha = mgr.get_head_hash("head-1")
        assert sha is not None
        assert len(sha) == 40
        assert set(sha).issubset(set("0123456789abcdef"))

    def test_returns_none_for_nonexistent(self, mgr: WorktreeManager):
        sha = mgr.get_head_hash("nonexistent")
        assert sha is None

    def test_returns_none_for_invalid_workspace_id(self, mgr: WorktreeManager):
        sha = mgr.get_head_hash("../escape")
        assert sha is None


# ── WorktreeManager: inspect ──────────────────────────────────────────


class TestWorktreeManagerInspect:
    def test_returns_record_for_created_worktree(self, mgr: WorktreeManager):
        mgr.create(workspace_id="inspect-1", branch_name="feat/inspect-1")
        record = mgr.inspect("inspect-1")
        assert record is not None
        assert record.workspace_id == "inspect-1"
        assert record.status == WorktreeStatus.HEALTHY
        assert record.head_sha is not None
        assert len(record.head_sha) == 40

    def test_returns_none_for_nonexistent(self, mgr: WorktreeManager):
        record = mgr.inspect("nonexistent")
        assert record is None

    def test_returns_none_for_invalid_workspace_id(self, mgr: WorktreeManager):
        record = mgr.inspect("../escape")
        assert record is None

    def test_inspect_reports_dirty(self, mgr: WorktreeManager):
        mgr.create(workspace_id="inspect-dirty", branch_name="feat/inspect-dirty")
        # Modify a file in the worktree to make it dirty
        record = mgr.inspect("inspect-dirty")
        assert record is not None
        worktree_path = Path(record.path)
        dirty_file = worktree_path / "dirty.txt"
        dirty_file.write_text("dirty content")
        record = mgr.inspect("inspect-dirty")
        assert record is not None
        assert record.status == WorktreeStatus.DIRTY


# ── WorktreeManager: remove ──────────────────────────────────────────


class TestWorktreeManagerRemove:
    def test_remove_clean_worktree(self, mgr: WorktreeManager):
        mgr.create(workspace_id="rm-clean", branch_name="feat/rm-clean")
        result = mgr.remove("rm-clean")
        assert result.status == "removed"
        assert result.record is not None
        assert result.record.status == WorktreeStatus.REMOVED
        # Worktree path should no longer exist
        assert not Path(result.record.path).exists()

    def test_remove_refuses_dirty_worktree(self, mgr: WorktreeManager):
        mgr.create(workspace_id="rm-dirty", branch_name="feat/rm-dirty")
        # Find the worktree path and dirty it
        record = mgr.inspect("rm-dirty")
        assert record is not None
        dirty_file = Path(record.path) / "dirty.txt"
        dirty_file.write_text("dirty content")
        # Now try to remove — should refuse
        result = mgr.remove("rm-dirty")
        assert result.status == "refused"
        assert result.error_kind == "dirty_worktree"

    def test_remove_force_dirty_worktree(self, mgr: WorktreeManager):
        mgr.create(workspace_id="rm-force", branch_name="feat/rm-force")
        record = mgr.inspect("rm-force")
        assert record is not None
        dirty_file = Path(record.path) / "force.txt"
        dirty_file.write_text("force content")
        # Force remove
        result = mgr.remove("rm-force", force=True)
        assert result.status == "removed"
        assert not Path(record.path).exists()

    def test_remove_refuses_nonexistent(self, mgr: WorktreeManager):
        result = mgr.remove("rm-nonexistent")
        assert result.status == "refused"
        assert result.error_kind == "path_not_found"

    def test_remove_refuses_invalid_workspace_id(self, mgr: WorktreeManager):
        result = mgr.remove("../escape")
        assert result.status == "refused"
        assert result.error_kind == "invalid_workspace_id"

    def test_remove_is_idempotent_structured(self, mgr: WorktreeManager):
        result1 = mgr.remove("rm-nonexistent-2")
        assert result1.status == "refused"
        result2 = mgr.remove("rm-nonexistent-2")
        assert result2.status == "refused"


# ── WorktreeManager: error cases ─────────────────────────────────────


class TestWorktreeManagerErrors:
    def test_create_in_non_git_dir(self, tmp_path: Path):
        non_git = tmp_path / "not-a-repo"
        non_git.mkdir(parents=True)
        wt_root = non_git / ".rig" / "relay" / "worktrees"
        mgr = WorktreeManager(repo_root=non_git, worktree_root=wt_root)
        result = mgr.create(workspace_id="fail", branch_name="fail")
        assert result.status == "error"
        assert result.error_kind == "not_a_git_repo"


# ── Schema validation ──────────────────────────────────────────────────


class TestWorktreeSchema:
    def test_schema_validates_worktree_record(self, schema: dict):
        r = WorktreeRecord(workspace_id="test", path="/tmp/test")
        dump = json.loads(r.model_dump_json())
        jsonschema.validate(dump, schema)

    def test_schema_validates_worktree_operation_result(self, schema: dict):
        r = WorktreeOperationResult(
            operation=WorktreeOperationKind.CREATE, status="created"
        )
        dump = json.loads(r.model_dump_json())
        jsonschema.validate(dump, schema)

    def test_schema_validates_result_with_record(self, schema: dict):
        rec = WorktreeRecord(workspace_id="test", path="/tmp/test")
        r = WorktreeOperationResult(
            operation=WorktreeOperationKind.CREATE, status="created", record=rec
        )
        dump = json.loads(r.model_dump_json())
        jsonschema.validate(dump, schema)

    def test_schema_rejects_unknown_fields_in_record(self, schema: dict):
        bad = {"workspace_id": "test", "path": "/tmp/test", "unknown": "x"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)

    def test_schema_rejects_unknown_fields_in_result(self, schema: dict):
        bad = {"operation": "create", "status": "created", "unknown": "x"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)

    def test_schema_rejects_missing_required(self, schema: dict):
        bad = {"status": "created"}  # missing operation
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)
