# ruff: noqa: PLR0911
from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from vibe.core.coordination import CoordinationStore
from vibe.core.guard import DirtyFileGuard, get_guard
from vibe.core.telemetry.local import dump_canonical_json
from vibe.core.telemetry.tool_contract import ToolDeterminismClass, ToolMutationClass
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolCallEvent, ToolResultEvent, ToolStreamEvent


class CheckpointArgs(BaseModel):
    session_id: str | None = None
    task_id: str | None = None
    message: str
    include_paths: list[str] = Field(default_factory=list)
    validation_summary: list[str] = Field(default_factory=list)
    allow_partial: bool = False
    authorization_receipt: str | None = Field(
        default=None,
        description="JSON string of a signed authorization receipt for checkpoint commit.",
    )


class CheckpointResult(BaseModel):
    ok: bool
    commit_sha: str | None = None
    message: str
    files_committed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifact_sha256: str | None = None
    refusal_reason: str | None = None


class CheckpointToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    store_root: Path = Field(
        default_factory=lambda: Path.cwd() / ".build" / "rig-relay" / "coordination"
    )


class Checkpoint(
    BaseTool[CheckpointArgs, CheckpointResult, CheckpointToolConfig, BaseToolState],
    ToolUIData[CheckpointArgs, CheckpointResult],
):
    description: ClassVar[str] = (
        "Create a governed local checkpoint commit for session-owned files."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.NONDETERMINISTIC_EXTERNAL_IO
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.WRITES_WORKSPACE

    _STATUS_LINE_LENGTH: ClassVar[int] = 3

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        args = event.args
        if isinstance(args, CheckpointArgs):
            return ToolCallDisplay(summary=f"Checkpoint: {args.message[:60]}")
        return ToolCallDisplay(summary="Checkpoint commit")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        result = event.result
        if isinstance(result, CheckpointResult):
            if result.ok and result.commit_sha:
                return ToolResultDisplay(
                    success=True, message=f"Committed {result.commit_sha[:8]}"
                )
            return ToolResultDisplay(
                success=False, message=result.refusal_reason or result.message
            )
        return ToolResultDisplay(success=True, message="Checkpoint complete")

    @classmethod
    def get_status_text(cls) -> str:
        return "Creating checkpoint commit"

    async def run(
        self, args: CheckpointArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | CheckpointResult, None]:
        from vibe.core.coordination._models import build_checkpoint_committed_payload
        from vibe.core.telemetry.local import log_local_event

        store = CoordinationStore(self.config.store_root)
        repo_root = Path.cwd().resolve()
        guard = get_guard()

        # 1. Capture git state
        porcelain_out = self._git("status", "--porcelain=v1", "-z", cwd=repo_root)
        if isinstance(porcelain_out, CheckpointResult):
            refusal_result = porcelain_out
            self._emit_checkpoint_refused(args, refusal_result)
            yield refusal_result
            return

        # 2. Parse and validate
        dirty_files = self._parse_porcelain_z(porcelain_out)
        requested = set(self._normalize_paths(args.include_paths))
        refusal = self._validate_preconditions(
            args, requested, dirty_files, store, guard, repo_root
        )
        if refusal:
            self._emit_checkpoint_refused(args, refusal)
            yield refusal
            return

        # 3. Capture pre-commit state
        pre_commit_head = self._git_rev_parse("HEAD", cwd=repo_root)
        branch = self._git_rev_parse("--abbrev-ref", "HEAD", cwd=repo_root)

        # 4. Stage and commit
        if refusal := self._stage_and_commit(requested, args, repo_root):
            self._emit_checkpoint_refused(args, refusal)
            yield refusal
            return

        # 5. Capture post-commit state
        post_commit_head = self._git_rev_parse("HEAD", cwd=repo_root)

        # 6. Build result and artifact
        artifact = self._build_artifact(
            session_id=args.session_id or "",
            task_id=args.task_id or "",
            branch=branch,
            pre_commit_head=pre_commit_head,
            post_commit_head=post_commit_head,
            commit_sha=post_commit_head,
            files_committed=sorted(requested),
            validation_summary=args.validation_summary,
        )
        result = CheckpointResult(
            ok=True,
            commit_sha=post_commit_head,
            message=args.message,
            files_committed=sorted(requested),
            artifact_sha256=artifact["artifact_sha256"],
        )

        # 7. Emit checkpoint committed event
        payload = build_checkpoint_committed_payload(
            session_id=args.session_id or "",
            task_id=args.task_id or "",
            branch=branch,
            pre_commit_head=pre_commit_head,
            post_commit_head=post_commit_head,
            commit_sha=post_commit_head,
            files_committed=sorted(requested),
            validation_summary=args.validation_summary,
            artifact_sha256=artifact["artifact_sha256"],
        )
        log_local_event(
            session_id=args.session_id or "unknown",
            event_name="rig.relay.checkpoint.committed",
            payload=payload,
            parent_session_id=None,
            receipt_candidate=True,
        )

        yield result

    def _emit_checkpoint_refused(
        self, args: CheckpointArgs, result: CheckpointResult
    ) -> None:
        from vibe.core.coordination._models import build_checkpoint_refused_payload
        from vibe.core.telemetry.local import log_local_event

        payload = build_checkpoint_refused_payload(
            session_id=args.session_id or "unknown",
            task_id=args.task_id or "unknown",
            refusal_code=result.refusal_reason or result.message,
            warnings=result.warnings,
        )
        log_local_event(
            session_id=args.session_id or "unknown",
            event_name="rig.relay.checkpoint.refused",
            payload=payload,
            parent_session_id=None,
            receipt_candidate=True,
        )

    def _validate_preconditions(
        self,
        args: CheckpointArgs,
        requested: set[str],
        dirty_files: dict[str, str],
        store: CoordinationStore,
        guard: DirtyFileGuard,
        repo_root: Path,
    ) -> CheckpointResult | None:
        # Authorization gate for checkpoint commits
        action = "checkpoint.commit"
        if args.authorization_receipt:
            valid, reason = self._validate_receipt(args.authorization_receipt, action)
            if not valid:
                return CheckpointResult(
                    ok=False,
                    message=f"Checkpoint refused: {reason}",
                    refusal_reason=reason,
                )
        else:
            # Dev bypass: generate dev receipt internally
            from vibe.core.auth.receipt import generate_dev_receipt

            dev_receipt = generate_dev_receipt(action, ttl_seconds=60)
            valid, reason = self._validate_receipt(json.dumps(dev_receipt), action)
            if not valid:
                return CheckpointResult(
                    ok=False,
                    message=f"Checkpoint refused (dev bypass failed): {reason}",
                    refusal_reason=reason,
                )

        if not requested and not args.allow_partial:
            return CheckpointResult(
                ok=False,
                message="No files specified for checkpoint",
                refusal_reason="include_paths is empty and allow_partial is false",
            )
        for rel_path, status in dirty_files.items():
            if "U" in status:
                return CheckpointResult(
                    ok=False,
                    message="Unresolved conflicts in working tree",
                    refusal_reason=f"Unresolved conflict: {rel_path}",
                )
        staged_files = {
            p for p, s in dirty_files.items() if s[0] not in {" ", "?", "!"}
        }
        unrelated_staged = staged_files - requested
        if unrelated_staged and not args.allow_partial:
            return CheckpointResult(
                ok=False,
                message="Unrelated staged files exist",
                refusal_reason=f"Files staged by another session: {sorted(unrelated_staged)}",
            )
        for rel_path in sorted(requested):
            reason = self._check_path(rel_path, args, store, guard, repo_root)
            if reason:
                return CheckpointResult(
                    ok=False,
                    message=f"Checkpoint refused: {rel_path}",
                    refusal_reason=reason,
                )
        return None

    def _stage_and_commit(
        self, requested: set[str], args: CheckpointArgs, repo_root: Path
    ) -> CheckpointResult | None:
        add_result = self._git("add", "--", *sorted(requested), cwd=repo_root)
        if isinstance(add_result, CheckpointResult):
            return add_result

        subject = (
            args.message
            if args.message.startswith("checkpoint(")
            else f"checkpoint({args.task_id or 'unknown'}): {args.message}"
        )
        body_lines = [""]
        if args.session_id:
            body_lines.append(f"Session: {args.session_id}")
        if args.task_id:
            body_lines.append(f"Task: {args.task_id}")
        body_lines.append("Files:")
        for path in sorted(requested):
            body_lines.append(f"- {path}")
        if args.validation_summary:
            body_lines.append("Validation:")
            for cmd in args.validation_summary:
                body_lines.append(f"- {cmd}")
        full_message = subject + "\n" + "\n".join(body_lines)

        commit_result = self._git("commit", "-m", full_message, cwd=repo_root)
        if isinstance(commit_result, CheckpointResult):
            return commit_result
        return None

    def _git(self, *args: str, cwd: Path) -> str | CheckpointResult:
        try:
            proc = subprocess.run(
                ["git", "--no-optional-locks", *args],
                capture_output=True,
                check=True,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=15,
            )
            return proc.stdout.strip()
        except subprocess.CalledProcessError as exc:
            err = exc.stderr.strip() if exc.stderr else f"exit code {exc.returncode}"
            return CheckpointResult(
                ok=False,
                message="Git command failed",
                refusal_reason=f"git {' '.join(args[:2])} failed: {err}",
            )

    def _git_rev_parse(self, *args: str, cwd: Path | None = None) -> str:
        result = self._git("rev-parse", *args, cwd=cwd or Path.cwd())
        return result if isinstance(result, str) else "unknown"

    def _check_path(
        self,
        rel_path: str,
        args: CheckpointArgs,
        store: CoordinationStore,
        guard: DirtyFileGuard,
        repo_root: Path,
    ) -> str | None:
        abs_path = (repo_root / rel_path).resolve()
        if not abs_path.exists():
            return f"Path does not exist: {rel_path}"
        try:
            abs_path.relative_to(repo_root)
        except ValueError:
            return f"Path outside repo root: {rel_path}"

        projection = store.read_state_projection()
        for _key, reservation in projection.active_path_reservations.items():
            if reservation.status != "active":
                continue
            if reservation.mode != "write":
                continue
            if (
                reservation.session_id == args.session_id
                and reservation.task_id == args.task_id
            ):
                continue
            for reserved_path in reservation.paths:
                if self._paths_overlap(rel_path, reserved_path):
                    return f"Path '{rel_path}' is reserved for write by session {reservation.session_id} (task {reservation.task_id})"

        snapshot = guard.snapshot_for(rel_path)
        if snapshot is not None:
            guard_report = guard.report()
            if rel_path not in guard_report["files_touched_by_mission"]:
                return f"File '{rel_path}' was dirty at mission start and was not safely patched by this session"
        return None

    @staticmethod
    def _paths_overlap(a: str, b: str) -> bool:
        return (
            a == b
            or a.startswith(b.rstrip("/") + "/")
            or b.startswith(a.rstrip("/") + "/")
        )

    @staticmethod
    def _parse_porcelain_z(output: str) -> dict[str, str]:
        result: dict[str, str] = {}
        entries = output.split("\0")
        i = 0
        while i < len(entries):
            entry = entries[i]
            if len(entry) < Checkpoint._STATUS_LINE_LENGTH:
                i += 1
                continue
            status = entry[:2]
            raw_path = entry[3:]
            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ")[-1]
            result[raw_path] = status
            i += 1
        return result

    @staticmethod
    def _normalize_paths(paths: list[str]) -> list[str]:
        return [Path(p).as_posix() for p in paths]

    @staticmethod
    def _build_artifact(
        session_id: str,
        task_id: str,
        branch: str,
        pre_commit_head: str,
        post_commit_head: str,
        commit_sha: str,
        files_committed: list[str],
        validation_summary: list[str],
    ) -> dict[str, Any]:
        payload = {
            "schema_version": "rig.relay.checkpoint.artifact.v1",
            "artifact_kind": "checkpoint_commit",
            "session_id": session_id,
            "task_id": task_id,
            "branch": branch,
            "pre_commit_head": pre_commit_head,
            "post_commit_head": post_commit_head,
            "commit_sha": commit_sha,
            "files_committed": files_committed,
            "validation_summary_hash": (
                "sha256:"
                + hashlib.sha256(
                    dump_canonical_json(validation_summary).encode("utf-8")
                ).hexdigest()
                if validation_summary
                else None
            ),
            "status": "committed",
            "warnings": [],
            "created_at": datetime.now(UTC).isoformat(),
        }
        payload_sha256 = (
            "sha256:"
            + hashlib.sha256(dump_canonical_json(payload).encode("utf-8")).hexdigest()
        )
        payload["artifact_sha256"] = payload_sha256
        return payload

    @staticmethod
    def _validate_receipt(receipt_json: str, action: str) -> tuple[bool, str]:
        from datetime import UTC, datetime

        try:
            receipt = json.loads(receipt_json)
        except json.JSONDecodeError:
            return False, "Invalid receipt JSON"

        if not isinstance(receipt, dict):
            return False, "Receipt must be a JSON object"

        if (
            receipt.get("schema_version")
            != "rig.relay.step_up_authorization_receipt.v1"
        ):
            return False, "Invalid receipt schema version"

        receipt_action = receipt.get("action")
        if receipt_action != action:
            return (
                False,
                f"Action mismatch: receipt for '{receipt_action}', expected '{action}'",
            )

        if receipt.get("user_verified") is not True:
            return False, "User not verified in receipt"

        expires_at_str = receipt.get("expires_at", "")
        if not expires_at_str:
            return False, "Missing expires_at in receipt"

        try:
            expires_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if expires_dt < datetime.now(UTC):
                return False, "Receipt expired"
        except (ValueError, TypeError):
            return False, "Invalid expires_at format"

        return True, "Receipt valid"

    def resolve_permission(self, args: CheckpointArgs) -> None:
        return None
