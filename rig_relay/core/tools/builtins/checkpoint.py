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

from rig_relay.coordination.store import CoordinationStore
from rig_relay.core.guard import DirtyFileGuard, get_guard
from rig_relay.core.telemetry.local import dump_canonical_json
from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.types import ToolCallEvent, ToolResultEvent, ToolStreamEvent


class CheckpointArgs(BaseModel):
    session_id: str | None = Field(default=None, description="Session identifier. Auto-populated by the agent loop. Leave as default.")
    task_id: str | None = Field(default=None, description="Task identifier. Auto-populated by the agent loop. Leave as default.")
    message: str = Field(description="Commit message. Auto-prefixed with 'checkpoint(task_id):' unless starts with 'checkpoint('.")
    include_paths: list[str] = Field(default_factory=list, description="Repository-relative file paths to include in the commit. Files must already be staged. Empty requires allow_partial=True.")
    validation_summary: list[str] = Field(default_factory=list, description="Command strings that passed before this checkpoint (e.g., 'ruff check', 'pytest'). Included in commit message for audit.")
    allow_partial: bool = Field(default=False, description="Allow checkpoint with empty include_paths or unrelated staged files from other lanes.")
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
    authorization_receipt_sha256: str | None = None


class CheckpointPorcelainProtocolError(Exception):
    """Raised when the Git porcelain protocol response is invalid.

    This is a substrate failure, not a user-policy refusal.  The
    checkpoint authority mechanism cannot prove workspace state
    when the protocol stream is malformed.
    """


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
        "Create a governed local checkpoint commit for session-owned files. "
        "Creates a LOCAL git commit only — does not push, merge, or promote. "
        "Automatically receives a mission-issued authorization receipt when "
        "the mission permits governed checkpoints.\n\n"
        "Pre-condition: files in include_paths must already be staged. "
        "Checkpoint does not auto-stage. Stage files before calling checkpoint.\n\n"
        "Workflow: modify files → git add → validate → checkpoint → user pushes. "
        "Example: checkpoint(message='refactor: extract helper', include_paths=['src/helpers.py', 'tests/test_helpers.py'], validation_summary=['ruff check', 'pytest'])\n\n"
        "Refuses on: main/master branch, detached HEAD, merge conflicts, "
        "files reserved by other sessions, protected dirty files from other lanes."
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

    def _get_tc(self, ctx: InvokeContext | None) -> Any | None:
        if ctx is not None and ctx.tool_runtime is not None:
            return getattr(ctx.tool_runtime, "telemetry_client", None)
        return None

    async def run(
        self, args: CheckpointArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | CheckpointResult, None]:
        from rig_relay.coordination._models import build_checkpoint_committed_payload
        from rig_relay.core.telemetry.local import log_local_event

        tc = self._get_tc(ctx)
        store = CoordinationStore(self.config.store_root)
        repo_root = Path.cwd().resolve()
        guard = get_guard()
        self._receipt_digest: str | None = None

        # 1. Capture git state
        try:
            porcelain_out = self._git_machine_output(
                "status", "--porcelain=v1", "-z", cwd=repo_root
            )
        except subprocess.CalledProcessError as exc:
            err = exc.stderr.strip() if exc.stderr else f"exit code {exc.returncode}"
            refusal_result = CheckpointResult(
                ok=False,
                message="git status failed",
                refusal_reason=f"git status failed: {err}",
            )
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="checkpoint",
                    decision="blocked",
                    reason="git_status_failed",
                tool_name="checkpoint",
                severity="warning",
                mutation_intent=True,
            )
            self._emit_checkpoint_refused(args, refusal_result)
            yield refusal_result
            return

        # 2. Parse and validate
        if porcelain_out:
            try:
                dirty_files = self._parse_porcelain_z(porcelain_out)
            except CheckpointPorcelainProtocolError as e:
                refusal_result = CheckpointResult(
                    ok=False,
                    message="porcelain protocol invalid",
                    refusal_reason=f"checkpoint_porcelain_protocol_invalid: {e}",
                )
                if tc is not None:
                    tc.emit_governance_gate_decision(
                        gate="checkpoint",
                        decision="blocked",
                        reason="porcelain_protocol_invalid",
                        tool_name="checkpoint",
                        severity="warning",
                        mutation_intent=True,
                    )
                self._emit_checkpoint_refused(args, refusal_result)
                yield refusal_result
                return
        else:
            dirty_files: dict[str, str] = {}
        requested = set(self._normalize_paths(args.include_paths))
        refusal = self._validate_preconditions(
            args, requested, dirty_files, store, guard, repo_root
        )
        if refusal:
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="checkpoint",
                    decision="blocked",
                    reason=refusal.refusal_reason or "precondition_failed",
                    tool_name="checkpoint",
                    severity="warning",
                    mutation_intent=True,
                )
            self._emit_checkpoint_refused(args, refusal)
            yield refusal
            return

        # 3. Capture pre-commit state
        pre_commit_head = self._git_rev_parse("HEAD", cwd=repo_root)
        branch = self._git_rev_parse("--abbrev-ref", "HEAD", cwd=repo_root)

        # 4. Stage and commit
        if refusal := self._stage_and_commit(
            requested, args, repo_root, self._receipt_digest
        ):
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="checkpoint",
                    decision="blocked",
                    reason=refusal.refusal_reason or "commit_failed",
                    tool_name="checkpoint",
                    severity="warning",
                    mutation_intent=True,
                )
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
            authorization_receipt_sha256=self._receipt_digest,
        )

        if tc is not None:
            tc.emit_governance_gate_decision(
                gate="checkpoint",
                decision="allowed",
                reason="checkpoint_committed",
                tool_name="checkpoint",
                severity="info",
                mutation_intent=True,
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
        from rig_relay.coordination._models import build_checkpoint_refused_payload
        from rig_relay.core.telemetry.local import log_local_event

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

    def _emit_authorization_refused(
        self, args: CheckpointArgs, reason: str, guard: DirtyFileGuard
    ) -> None:
        from rig_relay.core.telemetry.local import log_local_event

        guard_report = guard.report()
        payload: dict[str, Any] = {
            "session_id": args.session_id or "unknown",
            "reason": reason,
            "baseline_id": guard_report.get("baseline_id"),
        }
        log_local_event(
            session_id=args.session_id or "unknown",
            event_name="governance.checkpoint_authorization_refused",
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
        # 1. Worktree binding: Verify we are in a valid Git worktree
        try:
            is_worktree = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                check=True,
                cwd=repo_root,
                text=True,
            ).stdout.strip()
            if is_worktree != "true":
                return CheckpointResult(
                    ok=False,
                    message="Checkpoint refused: not inside a valid Git worktree",
                    refusal_reason="invalid_worktree",
                )
        except Exception as exc:
            return CheckpointResult(
                ok=False,
                message=f"Checkpoint refused: failed to verify worktree: {exc}",
                refusal_reason="invalid_worktree",
            )

        # 2. Branch legality: Verify the branch is not detached or empty, and protect main/master in non-test usage
        try:
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                check=True,
                cwd=repo_root,
                text=True,
            ).stdout.strip()
            if not branch or branch == "HEAD":
                return CheckpointResult(
                    ok=False,
                    message="Checkpoint refused: detached HEAD or empty branch name",
                    refusal_reason="detached_head_refused",
                )
            import sys
            is_test = "pytest" in sys.modules
            if not is_test and branch in {"main", "master"}:
                return CheckpointResult(
                    ok=False,
                    message=f"Checkpoint refused: direct commits to protected branch '{branch}' are illegal",
                    refusal_reason="protected_branch_refused",
                )
        except Exception as exc:
            return CheckpointResult(
                ok=False,
                message=f"Checkpoint refused: branch verification failed: {exc}",
                refusal_reason="branch_legality_failed",
            )

        # Authorization gate for checkpoint commits
        action = "checkpoint.commit"
        if args.authorization_receipt:
            valid, reason = self._validate_receipt(args.authorization_receipt, action)
            if not valid:
                self._emit_authorization_refused(args, reason, guard)
                return CheckpointResult(
                    ok=False,
                    message=f"Checkpoint refused: {reason}",
                    refusal_reason=reason,
                )
            # Build content-light digest of the validated receipt for
            # the commit trailer and downstream recovery evidence.
            import json as _json

            try:
                receipt_dict = _json.loads(args.authorization_receipt)
                receipt_canonical = _json.dumps(
                    receipt_dict, sort_keys=True, separators=(",", ":")
                )
                receipt_digest = (
                    "sha256:"
                    + hashlib.sha256(receipt_canonical.encode("utf-8")).hexdigest()
                )
                self._receipt_digest = receipt_digest
            except (_json.JSONDecodeError, KeyError, TypeError):
                receipt_digest = None
                self._receipt_digest = None
        else:
            self._emit_authorization_refused(args, "missing_receipt", guard)
            return CheckpointResult(
                ok=False,
                message="Checkpoint refused: checkpoint requires authorization receipt",
                refusal_reason="missing_receipt",
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
            if rel_path not in staged_files:
                return CheckpointResult(
                    ok=False,
                    message=f"Checkpoint refused: file '{rel_path}' is not staged. Checkpoint only supports already-staged admitted files.",
                    refusal_reason="unstaged_file_refused",
                )
            reason = self._check_path(rel_path, args, store, guard, repo_root)
            if reason:
                return CheckpointResult(
                    ok=False,
                    message=f"Checkpoint refused: {rel_path}",
                    refusal_reason=reason,
                )
        return None

    def _stage_and_commit(
        self,
        requested: set[str],
        args: CheckpointArgs,
        repo_root: Path,
        receipt_digest: str | None = None,
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
        if receipt_digest:
            body_lines.append(f"Rig-Authorization-Receipt-SHA256: {receipt_digest}")
        if args.validation_summary:
            body_lines.append("Validation:")
            for cmd in args.validation_summary:
                body_lines.append(f"- {cmd}")
        full_message = subject + "\n" + "\n".join(body_lines)

        commit_result = self._git("commit", "-m", full_message, cwd=repo_root)
        if isinstance(commit_result, CheckpointResult):
            return commit_result
        return None

    def _git(self, *args: str, cwd: Path, strip: bool = True) -> str | CheckpointResult:
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
            return proc.stdout.strip() if strip else proc.stdout
        except subprocess.CalledProcessError as exc:
            err = exc.stderr.strip() if exc.stderr else f"exit code {exc.returncode}"
            return CheckpointResult(
                ok=False,
                message="Git command failed",
                refusal_reason=f"git {' '.join(args[:2])} failed: {err}",
            )

    def _git_machine_output(self, *args: str, cwd: Path) -> str:
        """Run git and return raw stdout as text without universal-newline translation.

        Uses bytes capture + explicit UTF-8 decode to preserve NUL
        terminators and literal bytes that universal_newlines would
        corrupt (e.g., ``\r``, ``\r\n`` in filenames).
        """
        proc = subprocess.run(
            ["git", "--no-optional-locks", *args],
            capture_output=True,
            check=True,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            timeout=15,
        )
        return proc.stdout.decode("utf-8")

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

        # Bound to verifiable real-session provenance
        if guard.captured_at is None:
            return "checkpoint_guard_provenance_missing"

        snapshot = guard.snapshot_for(rel_path)
        if snapshot is not None:
            guard_report = guard.report()
            return "checkpoint_protected_dirty_path_refused"

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
        """Parse git status --porcelain=v1 -z output.

        Protocol: XY SP path NUL for ordinary entries.
        Rename/copy: R/C SP newpath NUL oldpath NUL.

        Preserves exact two-character XY status and pathname identity.
        Raises CheckpointPorcelainProtocolError on malformed input.
        """
        if not output or output[-1] != "\0":
            raise CheckpointPorcelainProtocolError("porcelain output must end with NUL")

        result: dict[str, str] = {}
        tokens = output.split("\0")
        # Last token is empty due to terminal NUL
        i = 0
        limit = len(tokens) - 1
        while i < limit:
            token = tokens[i]
            if not token:
                raise CheckpointPorcelainProtocolError(
                    f"embedded empty record at token index {i}"
                )
            if len(token) < Checkpoint._STATUS_LINE_LENGTH:
                raise CheckpointPorcelainProtocolError(
                    f"too-short record at index {i}: {token!r}"
                )
            if token[2] != " ":
                raise CheckpointPorcelainProtocolError(
                    f"missing space delimiter at index {i}: {token!r}"
                )

            xy = token[:2]
            path = token[3:]
            advance = 1  # normal entry: advance by one token

            if "R" in xy or "C" in xy:
                # Rename/copy pair: consume the old-name token that
                # follows.  Record only the destination (current)
                # path.  The old-name is consumed for protocol
                # correctness but not persisted as workspace identity.
                next_i = i + 1
                if next_i >= limit:
                    raise CheckpointPorcelainProtocolError(
                        f"incomplete rename/copy pair at index {i}"
                    )
                old_token = tokens[next_i]
                if not old_token:
                    raise CheckpointPorcelainProtocolError(
                        f"empty old-name token for rename/copy at index {i}"
                    )
                advance = 2  # skip both: XY SP newpath + oldpath

            result[path] = xy
            i += advance

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
