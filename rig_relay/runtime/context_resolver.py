from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from rig_relay.coordination.store import CoordinationStore
from rig_relay.coordination.worktree_manager import WorktreeRecord
from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution

_WORKTREE_ROOT_ANCESTOR_DEPTH = 4


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _safe_resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class _SessionCandidate:
    session_id: str
    source: str


class _WorktreeManagerLike(Protocol):
    def inspect(self, workspace_id: str) -> WorktreeRecord | None: ...

    def list_worktrees(self) -> list[WorktreeRecord]: ...


@dataclass(frozen=True)
class _ResolvedContextInputs:
    session_id: str
    task_id: str
    lane_id: str | None
    workspace_id: str | None
    worktree_path: str | None
    repo_root: Path | None
    resolved_from: list[str]
    warnings: list[str]


class RuntimeContextResolver:
    def __init__(
        self,
        coordination_store: CoordinationStore | None = None,
        worktree_manager: _WorktreeManagerLike | None = None,
        session_root: Path | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self._coordination_store = coordination_store
        self._worktree_manager = worktree_manager
        self._session_root = (
            session_root.resolve() if session_root is not None else None
        )
        self._repo_root = repo_root.resolve() if repo_root is not None else None

    def resolve_for_intent(
        self,
        intent_kind: str,
        session_id: str | None = None,
        task_id: str | None = None,
        lane_id: str | None = None,
        workspace_id: str | None = None,
        paths: list[str] | None = None,
        require_worktree: bool = False,
        allow_create_task: bool = True,
    ) -> RuntimeContextResolution:
        resolved = self._resolve_intent_inputs(
            intent_kind=intent_kind,
            session_id=session_id,
            task_id=task_id,
            lane_id=lane_id,
            workspace_id=workspace_id,
            paths=paths,
            require_worktree=require_worktree,
            allow_create_task=allow_create_task,
        )
        if isinstance(resolved, RuntimeContextResolution):
            return resolved

        if paths is not None:
            path_result = self._validate_paths(
                paths, resolved.repo_root, resolved.worktree_path
            )
            if path_result is not None:
                return path_result

        context = RuntimeContext(
            session_id=resolved.session_id,
            task_id=resolved.task_id,
            lane_id=resolved.lane_id,
            workspace_id=resolved.workspace_id,
            worktree_path=resolved.worktree_path,
            repo_root=resolved.repo_root.as_posix() if resolved.repo_root else None,
            coordination_scope=(
                resolved.repo_root.as_posix() if resolved.repo_root else None
            ),
            receipt_index_path=self._receipt_index_path_path(),
            dirty_policy="inherit",
            resolved_from=resolved.resolved_from,
            warnings=resolved.warnings,
        )
        return RuntimeContextResolution(status="resolved", context=context)

    def _infer_session_id(self) -> _SessionCandidate | None:
        if self._session_root is None:
            return None
        root = self._session_root
        candidates: list[_SessionCandidate] = []
        if root.is_file():
            data = self._read_session_metadata(root)
            if data is not None:
                return data
            return None
        for path in sorted(root.rglob("*.json")):
            data = self._read_session_metadata(path)
            if data is not None:
                candidates.append(data)
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            active = [
                candidate for candidate in candidates if "active" in candidate.source
            ]
            if len(active) == 1:
                return active[0]
        return None

    def _read_session_metadata(self, path: Path) -> _SessionCandidate | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        session_id = data.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            return _SessionCandidate(session_id=session_id, source=str(path))
        return None

    def _resolve_session(
        self, session_id: str | None
    ) -> tuple[str, list[str], list[str]] | RuntimeContextResolution:
        if session_id is not None:
            return session_id, [], []
        inferred = self._infer_session_id()
        if inferred is None:
            return RuntimeContextResolution(
                status="blocked",
                error_kind="session_required",
                refusal_reason="session_id is required when no current session can be inferred",
            )
        return (
            inferred.session_id,
            [inferred.source],
            ["session_id inferred from session metadata"],
        )

    def _resolve_task(
        self,
        session_id: str,
        intent_kind: str,
        task_id: str | None,
        *,
        allow_create_task: bool,
        lane_id: str | None,
        workspace_id: str | None,
        paths: list[str] | None,
    ) -> tuple[str, list[str], list[str]] | RuntimeContextResolution:
        if task_id is not None:
            return task_id, [], []
        if not allow_create_task:
            return RuntimeContextResolution(
                status="blocked",
                error_kind="task_required",
                refusal_reason="task_id is required when allow_create_task is false",
            )
        derived = self._derive_task_id(
            session_id, intent_kind, lane_id, workspace_id, paths
        )
        return (
            derived,
            ["derived_task_id"],
            ["task_id derived deterministically from intent context"],
        )

    def _resolve_intent_inputs(
        self,
        *,
        intent_kind: str,
        session_id: str | None,
        task_id: str | None,
        lane_id: str | None,
        workspace_id: str | None,
        paths: list[str] | None,
        require_worktree: bool,
        allow_create_task: bool,
    ) -> _ResolvedContextInputs | RuntimeContextResolution:
        resolved_from: list[str] = []
        warnings: list[str] = []

        session_result = self._resolve_session(session_id)
        if isinstance(session_result, RuntimeContextResolution):
            return session_result
        effective_session_id = session_result[0]
        resolved_from.extend(session_result[1])
        warnings.extend(session_result[2])

        task_result = self._resolve_task(
            effective_session_id,
            intent_kind,
            task_id,
            allow_create_task=allow_create_task,
            lane_id=lane_id,
            workspace_id=workspace_id,
            paths=paths,
        )
        if isinstance(task_result, RuntimeContextResolution):
            return task_result
        effective_task_id = task_result[0]
        resolved_from.extend(task_result[1])
        warnings.extend(task_result[2])

        worktree_result = self._resolve_worktree_context(
            lane_id=lane_id,
            workspace_id=workspace_id,
            require_worktree=require_worktree,
        )
        if isinstance(worktree_result, RuntimeContextResolution):
            return worktree_result
        effective_workspace_id = worktree_result[0]
        effective_lane_id = worktree_result[1]
        effective_worktree_path = worktree_result[2]
        resolved_from.extend(worktree_result[3])
        warnings.extend(worktree_result[4])

        return _ResolvedContextInputs(
            session_id=effective_session_id,
            task_id=effective_task_id,
            lane_id=effective_lane_id,
            workspace_id=effective_workspace_id,
            worktree_path=effective_worktree_path,
            repo_root=self._resolve_repo_root(effective_worktree_path),
            resolved_from=resolved_from,
            warnings=warnings,
        )

    def _resolve_worktree_context(
        self, *, lane_id: str | None, workspace_id: str | None, require_worktree: bool
    ) -> (
        tuple[str | None, str | None, str | None, list[str], list[str]]
        | RuntimeContextResolution
    ):
        effective_workspace_id = workspace_id
        effective_lane_id = lane_id
        effective_worktree_path: str | None = None
        resolved_from: list[str] = []
        warnings: list[str] = []

        if self._worktree_manager is not None:
            if effective_workspace_id is not None:
                inspected = self._worktree_manager.inspect(effective_workspace_id)
                if inspected is not None:
                    effective_worktree_path = inspected.path
                    if effective_lane_id is None:
                        effective_lane_id = effective_workspace_id
                        resolved_from.append("workspace_id")
                        warnings.append("lane_id inferred from workspace_id")
            elif effective_lane_id is not None:
                inspected = self._worktree_manager.inspect(effective_lane_id)
                if inspected is not None:
                    effective_workspace_id = effective_lane_id
                    effective_worktree_path = inspected.path
            else:
                inspected = self._infer_from_worktree_paths()
                if inspected is not None:
                    effective_workspace_id = inspected.workspace_id
                    effective_lane_id = inspected.workspace_id
                    effective_worktree_path = inspected.path
                    resolved_from.append("worktree_manager")
                    warnings.append(
                        "workspace_id and lane_id inferred from worktree manager"
                    )

        if require_worktree and effective_worktree_path is None:
            return RuntimeContextResolution(
                status="blocked",
                error_kind="worktree_required",
                refusal_reason="require_worktree is true but no worktree_path could be resolved",
            )

        return (
            effective_workspace_id,
            effective_lane_id,
            effective_worktree_path,
            resolved_from,
            warnings,
        )

    def _resolve_repo_root(self, worktree_path: str | None) -> Path | None:
        if self._repo_root is not None:
            return self._repo_root
        if worktree_path is None:
            return None
        parents = Path(worktree_path).resolve().parents
        if len(parents) < _WORKTREE_ROOT_ANCESTOR_DEPTH:
            return None
        return parents[_WORKTREE_ROOT_ANCESTOR_DEPTH - 1]

    def _receipt_index_path(self) -> Path | None:
        if self._repo_root is None:
            return None
        return self._repo_root / ".build" / "rig-relay" / "receipt-index.jsonl"

    def _receipt_index_path_path(self) -> str | None:
        receipt_index_path = self._receipt_index_path()
        if receipt_index_path is None:
            return None
        return receipt_index_path.as_posix()

    def _validate_paths(
        self, paths: list[str], repo_root: Path | None, worktree_path: str | None
    ) -> RuntimeContextResolution | None:
        if repo_root is None:
            return None
        worktree_root = (
            Path(worktree_path).resolve() if worktree_path is not None else None
        )
        for raw_path in paths:
            candidate = _safe_resolve(raw_path)
            if not _within(candidate, repo_root):
                return RuntimeContextResolution(
                    status="refused",
                    error_kind="unsafe_path",
                    refusal_reason=f"path '{raw_path}' is outside the resolved repo scope",
                )
            if worktree_root is not None and not _within(candidate, worktree_root):
                return RuntimeContextResolution(
                    status="refused",
                    error_kind="unsafe_path",
                    refusal_reason=f"path '{raw_path}' is outside the resolved worktree scope",
                )
        return None

    def _derive_task_id(
        self,
        session_id: str,
        intent_kind: str,
        lane_id: str | None,
        workspace_id: str | None,
        paths: list[str] | None,
    ) -> str:
        payload = {
            "session_id": session_id,
            "intent_kind": intent_kind,
            "lane_id": lane_id,
            "workspace_id": workspace_id,
            "paths": sorted(paths or []),
        }
        digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:24]
        return f"task_{digest}"

    def _infer_from_worktree_paths(self) -> WorktreeRecord | None:
        if self._worktree_manager is None:
            return None
        records = self._worktree_manager.list_worktrees()
        if len(records) != 1:
            return None
        return records[0]
