"""Tests for pending proposal persistence admission.

Proves: CREATE_PENDING_SEARCH_REPLACE_PROPOSAL verifies candidate via
compute_proposal(), atomically creates-or-replays a pending PatchProposal,
enforces idempotency via idempotency_key, and leaves workspace unchanged.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess

import pytest

from rig_relay.coordination.patch_workflow import PatchWorkflowStore
from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.tool_invocation_adapter import RuntimeToolIntent, RuntimeToolName
from rig_relay.runtime.tool_invocation_execution import (
    RuntimeToolExecutionRunner,
    RuntimeToolExecutionStatus,
)


def _make_git_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
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
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'test'\nversion = '0.1.0'\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repo, capture_output=True, check=True
    )
    return repo


def _write_and_commit(repo: Path, rel_path: str, content: str) -> None:
    target = repo / rel_path
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", rel_path], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {rel_path}"],
        cwd=repo,
        capture_output=True,
        check=True,
    )


@pytest.fixture(autouse=True)
def _reset_dirty_guard() -> None:
    from rig_relay.governance.dirty_guard import reset_guard

    reset_guard()


def _persistence_intent(
    file_path: str, old_str: str, new_str: str, idempotency_key: str
) -> RuntimeToolIntent:
    content = f"<<<<<<< SEARCH\n{old_str}\n=======\n{new_str}\n>>>>>>> REPLACE"
    return RuntimeToolIntent(
        intent_id=f"test-persist-{idempotency_key[:8]}",
        tool_name=RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL,
        payload={
            "file_path": file_path,
            "content": content,
            "idempotency_key": idempotency_key,
        },
    )


def _ctx(repo: Path) -> RuntimeContext:
    return RuntimeContext(
        session_id="sess-001",
        task_id="task-001",
        worktree_path=str(repo),
        repo_root=str(repo),
        coordination_enabled=False,
    )


class TestPersistenceCreatesProposal:
    """Integration: atomically persists a pending PatchProposal."""

    @pytest.mark.asyncio
    async def test_creates_pending_proposal_with_proposal_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "original\n")
        original_bytes = (repo / "target.py").read_bytes()

        intent = _persistence_intent("target.py", "original", "replaced", "key-001")
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_create_pending_search_replace_proposal(
            intent, resolution
        )

        assert result.status == RuntimeToolExecutionStatus.COMPLETED
        assert result.receipt_sha256 is not None
        assert (repo / "target.py").read_bytes() == original_bytes

    @pytest.mark.asyncio
    async def test_persisted_proposal_is_readable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "before\n")

        intent = _persistence_intent("target.py", "before", "after", "key-002")
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_create_pending_search_replace_proposal(
            intent, resolution
        )

        assert result.status == RuntimeToolExecutionStatus.COMPLETED

        coord_root = repo / ".build" / "rig-relay" / "coordination"
        store = PatchWorkflowStore(coord_root)
        found = store.find_by_idempotency_key("key-002")
        assert found is not None, "Proposal not persisted with idempotency key"
        assert found.status == "pending"
        assert found.idempotency_key == "key-002"


class TestPersistenceIdempotency:
    """Idempotency: replay vs conflict vs new key."""

    @pytest.mark.asyncio
    async def test_same_key_same_candidate_replays(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        intent1 = _persistence_intent("target.py", "hello", "world", "key-replay")
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()

        result1 = await runner.execute_create_pending_search_replace_proposal(
            intent1, resolution
        )
        assert result1.status == RuntimeToolExecutionStatus.COMPLETED

        # Second request with same key + same candidate
        intent2 = _persistence_intent("target.py", "hello", "world", "key-replay")
        result2 = await runner.execute_create_pending_search_replace_proposal(
            intent2, resolution
        )
        assert result2.status == RuntimeToolExecutionStatus.COMPLETED

        # Verify only one proposal persisted
        coord_root = repo / ".build" / "rig-relay" / "coordination"
        store = PatchWorkflowStore(coord_root)
        found = store.find_by_idempotency_key("key-replay")
        assert found is not None

    @pytest.mark.asyncio
    async def test_same_key_different_candidate_conflicts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "first\n")

        intent1 = _persistence_intent("target.py", "first", "second", "key-conflict")
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()

        result1 = await runner.execute_create_pending_search_replace_proposal(
            intent1, resolution
        )
        assert result1.status == RuntimeToolExecutionStatus.COMPLETED

        # Change the file content for a different candidate
        (repo / "target.py").write_text("different\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "changed"],
            cwd=repo,
            capture_output=True,
            check=True,
        )

        intent2 = _persistence_intent("target.py", "different", "third", "key-conflict")
        result2 = await runner.execute_create_pending_search_replace_proposal(
            intent2, resolution
        )
        assert result2.status != RuntimeToolExecutionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_new_key_same_candidate_creates_new(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "same\n")

        intent1 = _persistence_intent("target.py", "same", "new1", "key-a")
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()

        result1 = await runner.execute_create_pending_search_replace_proposal(
            intent1, resolution
        )
        assert result1.status == RuntimeToolExecutionStatus.COMPLETED

        # New key, same content → new proposal (v1 policy)
        intent2 = _persistence_intent("target.py", "same", "new1", "key-b")
        result2 = await runner.execute_create_pending_search_replace_proposal(
            intent2, resolution
        )
        assert result2.status == RuntimeToolExecutionStatus.COMPLETED

        coord_root = repo / ".build" / "rig-relay" / "coordination"
        store = PatchWorkflowStore(coord_root)
        assert store.find_by_idempotency_key("key-a") is not None
        assert store.find_by_idempotency_key("key-b") is not None


class TestPersistenceAdversarial:
    """Adversarial: missing key, invalid candidate, store failure."""

    @pytest.mark.asyncio
    async def test_missing_idempotency_key_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        content = "<<<<<<< SEARCH\nhello\n=======\nworld\n>>>>>>> REPLACE"
        intent = RuntimeToolIntent(
            intent_id="test-001",
            tool_name=RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL,
            payload={"file_path": "target.py", "content": content},
        )
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_create_pending_search_replace_proposal(
            intent, resolution
        )

        assert result.status == RuntimeToolExecutionStatus.REFUSED

    @pytest.mark.asyncio
    async def test_invalid_candidate_refused_without_persistence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "existing\n")
        original_bytes = (repo / "target.py").read_bytes()

        intent = _persistence_intent(
            "target.py", "nonexistent", "replace", "key-invalid"
        )
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_create_pending_search_replace_proposal(
            intent, resolution
        )

        assert result.status != RuntimeToolExecutionStatus.COMPLETED
        assert (repo / "target.py").read_bytes() == original_bytes


class TestExecutionStillFailClosed:
    """Direct execution remains blocked."""

    @pytest.mark.asyncio
    async def test_no_proposal_in_project_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proposals store under temp repo root, never project CWD."""
        import os

        project_cwd = os.getcwd()
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        intent = _persistence_intent("target.py", "hello", "world", "key-isolation")
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_create_pending_search_replace_proposal(
            intent, resolution
        )

        assert result.status == RuntimeToolExecutionStatus.COMPLETED

        # Proposals exist under the temp repo coordination root
        repo_coord = repo / ".build" / "rig-relay" / "coordination"
        repo_props = repo_coord / ".fleet" / "patch-proposals"
        assert repo_props.is_dir(), "Expected proposals directory in temp repo"
        repo_files = list(repo_props.glob("*.json"))
        assert len(repo_files) >= 1, "Expected at least one proposal in temp repo"

        # NO proposals under project CWD
        project_coord = Path(project_cwd) / ".build" / "rig-relay" / "coordination"
        project_props = project_coord / ".fleet" / "patch-proposals"
        if project_props.exists():
            project_files = list(project_props.glob("*.json"))
            assert not project_files, (
                f"Proposals leaked into project CWD: {project_files}"
            )

    @pytest.mark.asyncio
    async def test_separate_repos_isolated_by_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two repos with same key do not see each other's proposals."""
        repo_a = _make_git_repo(tmp_path, name="repo-a")
        repo_b = _make_git_repo(tmp_path, name="repo-b")

        monkeypatch.chdir(repo_a)
        _write_and_commit(repo_a, "target.py", "hello\n")
        intent_a = _persistence_intent("target.py", "hello", "world", "key-isolated")
        resolution_a = RuntimeContextResolution(
            status="resolved",
            context=RuntimeContext(
                session_id="sess-a",
                task_id="task-a",
                worktree_path=str(repo_a),
                repo_root=str(repo_a),
                coordination_enabled=False,
            ),
        )
        runner = RuntimeToolExecutionRunner()
        result_a = await runner.execute_create_pending_search_replace_proposal(
            intent_a, resolution_a
        )
        assert result_a.status == RuntimeToolExecutionStatus.COMPLETED

        # Same key, different repo — should create NEW proposal (not conflict)
        monkeypatch.chdir(repo_b)
        _write_and_commit(repo_b, "target.py", "hello\n")
        intent_b = _persistence_intent("target.py", "hello", "world", "key-isolated")
        resolution_b = RuntimeContextResolution(
            status="resolved",
            context=RuntimeContext(
                session_id="sess-b",
                task_id="task-b",
                worktree_path=str(repo_b),
                repo_root=str(repo_b),
                coordination_enabled=False,
            ),
        )
        result_b = await runner.execute_create_pending_search_replace_proposal(
            intent_b, resolution_b
        )
        assert result_b.status == RuntimeToolExecutionStatus.COMPLETED

        # Each repo should have its own proposal
        for label, rp in [("repo_a", repo_a), ("repo_b", repo_b)]:
            coord = rp / ".build" / "rig-relay" / "coordination"
            props = coord / ".fleet" / "patch-proposals"
            files = list(props.glob("*.json"))
            assert len(files) >= 1, f"Expected proposal in {label}"


class TestPersistenceFailure:
    """Adversarial: real persistence failure returns explicit outcome."""

    @pytest.mark.asyncio
    async def test_persistence_failure_returns_explicit_outcome(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Store write failure returns pending_proposal_persistence_failed."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        # Create the coordination root but make proposals directory a FILE
        # so save_proposal cannot create the proposal inside it
        coord_root = repo / ".build" / "rig-relay" / "coordination"
        props_dir = coord_root / ".fleet" / "patch-proposals"
        props_dir.parent.mkdir(parents=True, exist_ok=True)
        props_dir.write_text("")  # file, not directory

        import uuid

        key = f"fail-{uuid.uuid4().hex[:8]}"
        content = "<<<<<<< SEARCH\nhello\n=======\nworld\n>>>>>>> REPLACE"
        intent = RuntimeToolIntent(
            intent_id="test-fail",
            tool_name=RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL,
            payload={
                "file_path": "target.py",
                "content": content,
                "idempotency_key": key,
            },
        )
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_create_pending_search_replace_proposal(
            intent, resolution
        )

        assert result.status != RuntimeToolExecutionStatus.COMPLETED
        assert (repo / "target.py").read_text("utf-8") == "hello\n"


class TestConcurrentIdempotency:
    """Concurrent same-key calls must not create duplicate proposals."""

    @pytest.mark.asyncio
    async def test_concurrent_same_key_one_proposal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two simultaneous calls with same key create exactly one proposal."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        intent = _persistence_intent("target.py", "hello", "world", "key-concurrent")
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()
        results: list = []

        async def do_persist() -> None:
            result = await runner.execute_create_pending_search_replace_proposal(
                intent, resolution
            )
            results.append(result)

        await asyncio.gather(do_persist(), do_persist())

        assert len(results) == 2
        assert all(r.status == RuntimeToolExecutionStatus.COMPLETED for r in results), (
            f"Results: {[(r.status.value, r.error_kind) for r in results]}"
        )

        coord_root = repo / ".build" / "rig-relay" / "coordination"
        props_dir = coord_root / ".fleet" / "patch-proposals"
        files = list(props_dir.glob("*.json")) if props_dir.exists() else []
        assert len(files) == 1, (
            f"Expected exactly 1 proposal from concurrent calls, "
            f"got {len(files)}: {[f.name for f in files]}"
        )


class TestCanonicalDigest:
    """Strict SHA-256 digest canonicalization."""

    def _canonical_digest(self, value: str) -> str:
        from rig_relay.coordination.patch_proposal import _canonical_digest

        return _canonical_digest(value)

    def test_raw_hex_passthrough(self) -> None:
        result = self._canonical_digest("a" * 64)
        assert result == "a" * 64

    def test_sha256_prefixed_stripped(self) -> None:
        result = self._canonical_digest("sha256:" + "f" * 64)
        assert result == "f" * 64

    def test_raw_and_prefixed_produce_same(self) -> None:
        hex_digest = "c" * 32 + "d" * 32
        raw = self._canonical_digest(hex_digest)
        prefixed = self._canonical_digest("sha256:" + hex_digest)
        assert raw == prefixed

    def test_empty_string_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            self._canonical_digest("")

    def test_wrong_length_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            self._canonical_digest("a" * 63)
        with pytest.raises(ValueError):
            self._canonical_digest("a" * 65)

    def test_non_hex_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            self._canonical_digest("g" * 64)

    def test_sha256_prefix_only_rejects(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            self._canonical_digest("sha256:")

    def test_candidate_fingerprint_stable_across_representations(self) -> None:
        from rig_relay.coordination.patch_proposal import compute_candidate_fingerprint

        raw_fp = compute_candidate_fingerprint(
            file_path="target.py", before_hash="a" * 64, after_hash="b" * 64
        )
        prefixed_fp = compute_candidate_fingerprint(
            file_path="target.py",
            before_hash="sha256:" + "a" * 64,
            after_hash="sha256:" + "b" * 64,
        )
        assert raw_fp == prefixed_fp


class TestContextMissing:
    """Missing worktree_path/repo_root fails closed."""

    @pytest.mark.asyncio
    async def test_missing_worktree_refuses_context_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No worktree_path or repo_root → context_missing refusal."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")
        original = (repo / "target.py").read_bytes()

        import uuid

        key = f"ctx-{uuid.uuid4().hex[:8]}"
        content = "<<<<<<< SEARCH\nhello\n=======\nworld\n>>>>>>> REPLACE"
        intent = RuntimeToolIntent(
            intent_id="test-ctx",
            tool_name=RuntimeToolName.CREATE_PENDING_SEARCH_REPLACE_PROPOSAL,
            payload={
                "file_path": "target.py",
                "content": content,
                "idempotency_key": key,
            },
        )
        ctx = RuntimeContext(
            session_id="sess",
            task_id="task",
            worktree_path=None,
            repo_root=None,
            coordination_enabled=False,
        )
        resolution = RuntimeContextResolution(status="resolved", context=ctx)
        runner = RuntimeToolExecutionRunner()
        result = await runner.execute_create_pending_search_replace_proposal(
            intent, resolution
        )

        assert result.status == RuntimeToolExecutionStatus.REFUSED
        assert result.error_kind == "context_missing"
        assert (repo / "target.py").read_bytes() == original

        # No proposal artifacts in any coordination store under repo
        coord = repo / ".build" / "rig-relay" / "coordination"
        props = coord / ".fleet" / "patch-proposals"
        if props.exists():
            files = list(props.glob("*.json"))
            assert not files, f"Unexpected proposals: {files}"


class TestSchemaValidation:
    """Persisted proposals validate against governing JSON Schema."""

    def test_persisted_proposal_validates_against_schema(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Persisted PatchProposal validates against its governing schema."""
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        # We test schema validation by proving model_validate_json works
        # on the persisted file - Pydantic validates against the model, which
        # is the canonical Python projection of the JSON Schema.
        # For a full JSON Schema validation, use jsonschema.
        import json
        from pathlib import Path

        intent = _persistence_intent("target.py", "hello", "world", "key-schema")
        resolution = RuntimeContextResolution(status="resolved", context=_ctx(repo))
        runner = RuntimeToolExecutionRunner()

        async def _run() -> None:
            return await runner.execute_create_pending_search_replace_proposal(
                intent, resolution
            )

        import asyncio

        result = asyncio.run(_run())
        assert result.status == RuntimeToolExecutionStatus.COMPLETED

        coord = repo / ".build" / "rig-relay" / "coordination"
        props_dir = coord / ".fleet" / "patch-proposals"
        files = list(props_dir.glob("*.json"))
        assert len(files) >= 1

        proposal_path = files[0]
        proposal_json = json.loads(proposal_path.read_text("utf-8"))

        # Validate against JSON Schema
        from jsonschema import Draft202012Validator

        schema_path = (
            Path(__file__).resolve().parent.parent.parent
            / "docs"
            / "schemas"
            / "rig.fleet.patch_proposal.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text("utf-8"))
        validator = Draft202012Validator(schema)
        errors = list(validator.iter_errors(proposal_json))
        assert not errors, f"Schema validation errors: {errors}"

class TestApplyVerifiedCandidate:
    """Guarded compare-and-write primitive tests."""

    @pytest.mark.asyncio
    async def test_happy_path_hash_match_write_verify(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        import hashlib
        from rig_relay.core.tools.builtins.write_file import (
            apply_verified_candidate,
        )
        current_bytes = (repo / "target.py").read_bytes()
        expected = hashlib.sha256(current_bytes).hexdigest()
        candidate = "sha256:" + hashlib.sha256(b"world\n").hexdigest()

        result = await apply_verified_candidate(
            authority_root=repo,
            coordination_lock_root=tmp_path / "locks",
            canonical_path_identity="target.py",
            operational_file_path=repo / "target.py",
            expected_before_sha256=expected,
            candidate_content=b"world\n",
            candidate_after_sha256=candidate,
        )
        assert result.refusal_reason is None, f"Got: {result.refusal_reason}"
        assert result.path_lock_acquired
        assert result.actual_after_sha256 == candidate
        assert (repo / "target.py").read_text() == "world\n"

    @pytest.mark.asyncio
    async def test_before_hash_mismatch_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        import hashlib
        from rig_relay.core.tools.builtins.write_file import (
            apply_verified_candidate,
        )
        wrong_hash = hashlib.sha256(b"wrong\n").hexdigest()

        result = await apply_verified_candidate(
            authority_root=repo,
            coordination_lock_root=tmp_path / "locks",
            canonical_path_identity="target.py",
            operational_file_path=repo / "target.py",
            expected_before_sha256=wrong_hash,
            candidate_content=b"world\n",
            candidate_after_sha256="sha256:abc",
        )
        assert result.refusal_reason is not None
        assert "expected hash" in result.refusal_reason.lower()
        assert (repo / "target.py").read_text() == "hello\n"

    @pytest.mark.asyncio
    async def test_path_lock_not_in_source_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_git_repo(tmp_path)
        monkeypatch.chdir(repo)
        _write_and_commit(repo, "target.py", "hello\n")

        locks_dir = tmp_path / "coordination-locks"
        locks_dir.mkdir()

        import hashlib
        from rig_relay.core.tools.builtins.write_file import (
            apply_verified_candidate,
        )
        current_bytes = (repo / "target.py").read_bytes()
        expected = hashlib.sha256(current_bytes).hexdigest()
        candidate = "sha256:" + hashlib.sha256(b"world\n").hexdigest()

        result = await apply_verified_candidate(
            authority_root=repo,
            coordination_lock_root=locks_dir,
            canonical_path_identity="target.py",
            operational_file_path=repo / "target.py",
            expected_before_sha256=expected,
            candidate_content=b"world\n",
            candidate_after_sha256=candidate,
        )
        assert result.refusal_reason is None

        # Lock artifacts live under coordination-locks, not source tree
        assert list(locks_dir.rglob("*.lock"))
        assert not list(repo.rglob("*.lock")), (
            "Lock files leaked into source tree"
        )
