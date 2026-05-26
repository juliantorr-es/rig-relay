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
    session_id: str | None = Field(
        default=None,
        description="Session identifier. Auto-populated by the agent loop. Leave as default.",
    )
    task_id: str | None = Field(
        default=None,
        description="Task identifier. Auto-populated by the agent loop. Leave as default.",
    )
    message: str = Field(
        description="Commit message. Auto-prefixed with 'checkpoint(task_id):' unless starts with 'checkpoint('."
    )
    include_paths: list[str] = Field(
        default_factory=list,
        description="Repository-relative file paths to include in the commit. Files must already be staged. Empty requires allow_partial=True.",
    )
    validation_summary: list[str] = Field(
        default_factory=list,
        description="Command strings that passed before this checkpoint (e.g., 'ruff check', 'pytest'). Included in commit message for audit.",
    )
    allow_partial: bool = Field(
        default=False,
        description="Allow checkpoint with empty include_paths or unrelated staged files from other lanes.",
    )
    preparation_receipt_sha256: str | None = Field(
        default=None,
        description="SHA256 of a durable checkpoint preparation receipt from prepare_checkpoint. "
        "When provided, checkpoint verifies the current index matches the preparation "
        "receipt before committing. Refuses if the receipt is missing, stale, or invalid.",
    )
    validation_receipt_sha256: str | None = Field(
        default=None,
        description="SHA256 of a durable validation receipt from validate. "
        "When provided, checkpoint verifies validation is bound to "
        "the preparation receipt and the current index matches. "
        "Refuses if validation is missing, stale, or unbound.",
    )
    authorization_receipt: str | None = Field(
        default=None,
        description="JSON string of a signed authorization receipt for checkpoint commit.",
    )


class CheckpointResult(BaseModel):
    ok: bool
    commit_sha: str | None = None
    message: str = ""
    files_committed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifact_sha256: str | None = None
    refusal_reason: str | None = None
    authorization_receipt_sha256: str | None = None
    error_kind: str | None = Field(default=None)
    suggested_next_action: str | None = Field(default=None)


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

    def _release_if_locked(self, receipt_sha256: str | None) -> None:
        if self._transition_locked and receipt_sha256:
            from rig_relay.governance.receipt_store import release_transition_lock

            release_transition_lock(receipt_sha256)
            self._transition_locked = False

    async def run(
        self, args: CheckpointArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | CheckpointResult, None]:
        from rig_relay.coordination._models import build_checkpoint_committed_payload
        from rig_relay.core.telemetry.local import log_local_event

        tc = self._get_tc(ctx)
        store = CoordinationStore(self.config.store_root)
        repo_root = (
            ctx.workspace_root.resolve()
            if ctx and ctx.workspace_root
            else Path.cwd().resolve()
        )
        guard = get_guard()
        self._receipt_digest: str | None = None
        self._transition_locked: bool = False

        # ── A4: Acquire single-use transition lock for the preparation receipt ─
        if args.preparation_receipt_sha256:
            from rig_relay.governance.receipt_store import (
                ReconciliationOutcome,
                acquire_transition_lock,
                reconcile_receipt_evidence,
                release_transition_lock,
            )

            if not acquire_transition_lock(args.preparation_receipt_sha256):
                refusal_result = CheckpointResult(
                    ok=False,
                    message="Checkpoint refused: cannot acquire transition lock",
                    refusal_reason="transition_lock_unavailable",
                )
                yield refusal_result
                return
            self._transition_locked = True

            # Re-verify under lock: cross-evidence reconciliation
            branch = self._git_rev_parse("--abbrev-ref", "HEAD", cwd=repo_root) or ""
            reconciled = reconcile_receipt_evidence(
                preparation_receipt_sha256=args.preparation_receipt_sha256,
                branch=branch,
                repo_root=repo_root,
                worktree_root=str(repo_root),
            )
            if not reconciled.is_active:
                match reconciled.outcome:
                    case ReconciliationOutcome.CONSUMED_CONSISTENT:
                        error_kind = "preparation_receipt_consumed"
                        msg = "This preparation receipt has already been consumed."
                    case ReconciliationOutcome.TERMINAL_COMMITTED_REPAIRABLE:
                        error_kind = "preparation_receipt_consumed"
                        msg = (
                            "A terminal checkpoint already consumed this "
                            "preparation receipt (repairable lifecycle gap)."
                        )
                    case ReconciliationOutcome.LIFECYCLE_ONLY_NO_TERMINAL:
                        error_kind = "preparation_receipt_inconsistent"
                        msg = (
                            "Lifecycle claims CONSUMED but no terminal git "
                            "evidence exists — inconsistent authority state."
                        )
                    case ReconciliationOutcome.DUPLICATE_TERMINAL:
                        error_kind = "preparation_receipt_duplicate_terminal"
                        msg = (
                            "Multiple terminal commits claim the same "
                            "preparation receipt — integrity incident."
                        )
                    case ReconciliationOutcome.UNRECOVERABLE_CONTRADICTION:
                        error_kind = "preparation_receipt_contradiction"
                        msg = f"Unrecoverable contradiction: {reconciled.error_detail}"
                    case _:
                        error_kind = "preparation_receipt_unavailable"
                        msg = f"Reconciliation refused: {reconciled.outcome}"
                refusal_result = CheckpointResult(
                    ok=False,
                    message=msg,
                    refusal_reason=error_kind,
                    error_kind=error_kind,
                    suggested_next_action=(
                        "Run prepare_checkpoint again to create a fresh receipt."
                    ),
                )
                release_transition_lock(args.preparation_receipt_sha256)
                self._transition_locked = False
                yield refusal_result
                return

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
            self._release_if_locked(args.preparation_receipt_sha256)
            yield refusal_result
            return
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
                self._release_if_locked(args.preparation_receipt_sha256)
                yield refusal_result
                return
        else:
            dirty_files: dict[str, str] = {}
        requested = set(self._normalize_paths(args.include_paths))

        # ── Pre-extract receipt digest for recovery checks ─────────
        if args.authorization_receipt and self._receipt_digest is None:
            try:
                receipt_dict = json.loads(args.authorization_receipt)
                digest = receipt_dict.get("receipt_sha256")
                if digest:
                    self._receipt_digest = digest
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # ── Recovery: check for prior completion before preconditions ─
        if self._receipt_digest:
            committed_sha = self._check_commit_for_receipt_trailer(
                repo_root, self._receipt_digest
            )
            has_terminal = self._has_terminal_receipt(repo_root, self._receipt_digest)
            if has_terminal:
                recovery_result = CheckpointResult(
                    ok=True,
                    commit_sha=committed_sha or "",
                    message=(
                        f"Checkpoint already completed for authorization "
                        f"{self._receipt_digest[:16]}..."
                    ),
                    artifact_sha256=None,
                    authorization_receipt_sha256=self._receipt_digest,
                )
                self._release_if_locked(args.preparation_receipt_sha256)
                yield recovery_result
                return
            if committed_sha and not has_terminal:
                self._persist_terminal_checkpoint_receipt(
                    repo_root, self._receipt_digest, committed_sha, "recovered"
                )
                recovery_result = CheckpointResult(
                    ok=True,
                    commit_sha=committed_sha,
                    message=(
                        f"Recovered terminal checkpoint receipt for "
                        f"existing commit {committed_sha[:8]}"
                    ),
                    artifact_sha256=None,
                    authorization_receipt_sha256=self._receipt_digest,
                )
                self._release_if_locked(args.preparation_receipt_sha256)
                yield recovery_result
                return

        refusal = self._validate_preconditions(
            args, requested, dirty_files, store, guard, repo_root, ctx=ctx
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
            self._release_if_locked(args.preparation_receipt_sha256)
            yield refusal
            return

        # ── Persist authorization receipt before commit ───────────
        if self._receipt_digest and not self._load_latest_authorization_receipt(
            repo_root, self._receipt_digest
        ):
            self._persist_authorization_receipt(
                repo_root, args.authorization_receipt or "", self._receipt_digest
            )

        # 3. Capture pre-commit state
        pre_commit_head = self._git_rev_parse("HEAD", cwd=repo_root)
        branch = self._git_rev_parse("--abbrev-ref", "HEAD", cwd=repo_root)

        # 4. Build commit message (same format for trailers)
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
        if self._receipt_digest:
            body_lines.append(
                f"Rig-Authorization-Receipt-SHA256: {self._receipt_digest}"
            )
        if args.preparation_receipt_sha256:
            body_lines.append(
                f"Rig-Preparation-Receipt-SHA256: {args.preparation_receipt_sha256}"
            )
        if args.validation_receipt_sha256:
            body_lines.append(
                f"Rig-Validation-Receipt-SHA256: {args.validation_receipt_sha256}"
            )
        if args.validation_summary:
            body_lines.append("Validation:")
            for cmd in args.validation_summary:
                body_lines.append(f"- {cmd}")
        full_message = subject + "\n" + "\n".join(body_lines)

        # A5: Execute isolated checkpoint transaction
        from rig_relay.governance.checkpoint_transaction import (
            RefAdvanceOutcome,
            execute_isolated_checkpoint_transaction,
        )

        txn = execute_isolated_checkpoint_transaction(
            repo_root=repo_root,
            branch=branch,
            parent_sha=pre_commit_head,
            authorized_paths=sorted(requested),
            preparation_receipt_sha256=args.preparation_receipt_sha256 or "",
            commit_message=full_message,
        )

        if not txn.is_accepted:
            match txn.ref_outcome:
                case RefAdvanceOutcome.STALE_PARENT:
                    error_kind = "branch_advance_stale_parent"
                    msg = (
                        "Branch advanced since checkpoint preparation. "
                        "The expected parent commit no longer matches."
                    )
                case RefAdvanceOutcome.REF_NOT_FOUND:
                    error_kind = "branch_ref_not_found"
                    msg = "Branch reference not found."
                case RefAdvanceOutcome.DETACHED_HEAD:
                    error_kind = "detached_head_refused"
                    msg = "Detached HEAD — cannot advance branch."
                case _:
                    error_kind = "commit_transaction_failed"
                    msg = f"Transaction failed: {txn.error_detail}"
            refusal_result = CheckpointResult(
                ok=False,
                message=msg,
                refusal_reason=error_kind,
                error_kind=error_kind,
                suggested_next_action="Run prepare_checkpoint again.",
            )
            if tc is not None:
                tc.emit_governance_gate_decision(
                    gate="checkpoint",
                    decision="blocked",
                    reason=refusal_result.refusal_reason or "commit_failed",
                    tool_name="checkpoint",
                    severity="warning",
                    mutation_intent=True,
                )
            self._emit_checkpoint_refused(args, refusal_result)
            self._release_if_locked(args.preparation_receipt_sha256)
            yield refusal_result
            return

        post_commit_head = txn.new_commit_sha
        assert post_commit_head is not None

        # 5. Build result and artifact
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

        # 8. Append consumed lifecycle event for the preparation receipt
        if args.preparation_receipt_sha256:
            self._consume_preparation_receipt(
                receipt_sha256=args.preparation_receipt_sha256,
                branch=branch,
                repo_root=repo_root,
                committed_head_sha=post_commit_head,
            )

        # A4: Release transition lock after successful commit+consume
        if self._transition_locked and args.preparation_receipt_sha256:
            from rig_relay.governance.receipt_store import release_transition_lock

            release_transition_lock(args.preparation_receipt_sha256)
            self._transition_locked = False

        # ── Persist terminal checkpoint receipt ─────────────────
        if self._receipt_digest:
            self._persist_terminal_checkpoint_receipt(
                repo_root, self._receipt_digest, post_commit_head, "completed"
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

    def _verify_preparation_receipt(
        self, receipt_sha256: str, repo_root: Path, requested_paths: set[str]
    ) -> CheckpointResult | None:
        """Verify a durable preparation receipt matches the current index.

        Returns None if verification passes (proceed to commit).
        Returns CheckpointResult with ok=False if verification fails.
        """
        try:
            from rig_relay.governance.auth_receipts import (
                load_preparation_receipt_typed,
            )
            from rig_relay.governance.receipt_store import PreparationLoadOutcome
        except ImportError:
            return CheckpointResult(
                ok=False,
                refusal_reason="preparation_receipt_verification_unavailable",
                error_kind="preparation_receipt_verification_unavailable",
                suggested_next_action=(
                    "Preparation receipt verification is not available. "
                    "Retry checkpoint without a preparation receipt or ensure the "
                    "receipt infrastructure is accessible."
                ),
            )

        # 1. Load the receipt with typed outcome discrimination
        load_result = load_preparation_receipt_typed(receipt_sha256)
        match load_result.outcome:
            case PreparationLoadOutcome.ABSENT:
                return CheckpointResult(
                    ok=False,
                    refusal_reason=f"Preparation receipt not found: {receipt_sha256}",
                    error_kind="preparation_receipt_missing",
                    suggested_next_action=(
                        "The preparation receipt referenced by this checkpoint does not "
                        "exist in the durable ledger. Run prepare_checkpoint again to "
                        "create a new preparation receipt."
                    ),
                )
            case PreparationLoadOutcome.UNREADABLE:
                return CheckpointResult(
                    ok=False,
                    refusal_reason=f"Preparation receipt is unreadable: {load_result.error_detail}",
                    error_kind="preparation_receipt_unreadable",
                    suggested_next_action=(
                        "Check filesystem permissions and retry prepare_checkpoint."
                    ),
                )
            case PreparationLoadOutcome.MALFORMED_JSON:
                return CheckpointResult(
                    ok=False,
                    refusal_reason=f"Preparation receipt contains malformed JSON: {load_result.error_detail}",
                    error_kind="preparation_receipt_corrupt",
                    suggested_next_action=(
                        "Run prepare_checkpoint again to create a fresh receipt."
                    ),
                )
            case PreparationLoadOutcome.SCHEMA_INVALID:
                return CheckpointResult(
                    ok=False,
                    refusal_reason=f"Preparation receipt schema is invalid: {load_result.error_detail}",
                    error_kind="preparation_receipt_invalid",
                    suggested_next_action=(
                        "Run prepare_checkpoint again to create a fresh receipt."
                    ),
                )
            case PreparationLoadOutcome.INTEGRITY_MISMATCH:
                return CheckpointResult(
                    ok=False,
                    refusal_reason=(
                        "Preparation receipt integrity check failed. "
                        "The receipt content does not match its stored digest. "
                        f"{load_result.error_detail}"
                    ),
                    error_kind="preparation_receipt_tampered",
                    suggested_next_action=(
                        "Run prepare_checkpoint again to create a fresh receipt "
                        "with correct integrity."
                    ),
                )
            case PreparationLoadOutcome.LOADED_VALID:
                receipt = load_result.receipt
            case _:
                return CheckpointResult(
                    ok=False,
                    refusal_reason=f"Unexpected preparation receipt load outcome: {load_result.outcome}",
                    error_kind="preparation_binding_error",
                    suggested_next_action="Run prepare_checkpoint again.",
                )

        # 1.5: Lifecycle check — refuse consumed/superseded/revoked receipts
        try:
            from rig_relay.governance.receipt_store import (
                PreparationLifecycleEventKind,
                get_lifecycle_status,
            )

            life_status = get_lifecycle_status(receipt_sha256)
            match life_status:
                case PreparationLifecycleEventKind.CONSUMED:
                    return CheckpointResult(
                        ok=False,
                        refusal_reason=(
                            "This preparation receipt has already been consumed "
                            "by a completed checkpoint. Each preparation receipt "
                            "may only be checkpointed once."
                        ),
                        error_kind="preparation_receipt_consumed",
                        suggested_next_action=(
                            "Run prepare_checkpoint again to create a fresh "
                            "preparation receipt for the new index state."
                        ),
                    )
                case PreparationLifecycleEventKind.SUPERSEDED:
                    return CheckpointResult(
                        ok=False,
                        refusal_reason=(
                            "This preparation receipt has been superseded by a "
                            "newer conflicting preparation. The newer receipt "
                            "governs this scope."
                        ),
                        error_kind="preparation_receipt_superseded",
                        suggested_next_action=(
                            "Use the newer preparation receipt for checkpoint, "
                            "or run prepare_checkpoint again."
                        ),
                    )
                case PreparationLifecycleEventKind.REVOKED:
                    return CheckpointResult(
                        ok=False,
                        refusal_reason="This preparation receipt has been revoked.",
                        error_kind="preparation_receipt_revoked",
                        suggested_next_action=(
                            "Run prepare_checkpoint again to create a fresh receipt."
                        ),
                    )
                case _:
                    pass  # ACTIVE — proceed
        except ImportError:
            pass  # Lifecycle infrastructure not available — proceed without check

        # 2. Verify index tree digest matches
        from rig_relay.core.git_index_operations import compute_index_tree_digest

        current_digest = compute_index_tree_digest(repo_root)
        expected_digest = receipt.get("post_index_tree_digest")

        if current_digest is None:
            return CheckpointResult(
                ok=False,
                refusal_reason="Cannot compute current index tree digest. Index may be empty or unmerged.",
                error_kind="index_tree_digest_unavailable",
                suggested_next_action="Ensure the index has staged content and is fully merged.",
            )

        if expected_digest is None:
            return CheckpointResult(
                ok=False,
                refusal_reason="Preparation receipt has no post_index_tree_digest.",
                error_kind="preparation_receipt_missing_digest",
                suggested_next_action="The preparation receipt is missing the expected index tree digest. Run prepare_checkpoint again.",
            )

        if current_digest != expected_digest:
            return CheckpointResult(
                ok=False,
                refusal_reason=(
                    f"Current index tree digest ({current_digest[:12]}...) does not "
                    f"match preparation receipt ({expected_digest[:12]}...). "
                    "The index has changed since preparation."
                ),
                error_kind="prepared_index_changed",
                suggested_next_action=(
                    "The index content has changed since prepare_checkpoint was run. "
                    "Re-inspect changes and create a new preparation request with "
                    "updated expected file hashes."
                ),
            )

        # 3. Verify prepared paths match requested include_paths
        prepared_set = set(receipt.get("prepared_paths", []) or [])
        if not requested_paths.issubset(prepared_set):
            extra = requested_paths - prepared_set
            return CheckpointResult(
                ok=False,
                refusal_reason=(
                    f"Requested checkpoint paths not in preparation receipt: {sorted(extra)}"
                ),
                error_kind="checkpoint_paths_not_prepared",
                suggested_next_action=(
                    "Run prepare_checkpoint with the intended checkpoint paths "
                    f"including: {sorted(extra)}"
                ),
            )

        # 4. Verify receipt hasn't expired (if expiration is set)
        expires_at = receipt.get("expires_at")
        if expires_at is not None:
            try:
                from datetime import datetime

                expiry = datetime.fromisoformat(expires_at)
                if datetime.now(UTC) > expiry:
                    return CheckpointResult(
                        ok=False,
                        refusal_reason="Preparation receipt has expired.",
                        error_kind="preparation_receipt_expired",
                        suggested_next_action="Run prepare_checkpoint again to create a fresh receipt.",
                    )
            except (ValueError, TypeError):
                pass

        return None  # Verification passed

    def _verify_validation_receipt(
        self, validation_sha256: str, preparation_sha256: str | None, repo_root: Path
    ) -> CheckpointResult | None:
        """Verify a durable validation receipt is bound to the preparation receipt.

        Returns None if verification passes.
        Returns CheckpointResult with ok=False if verification fails.
        """
        try:
            from rig_relay.governance.receipt_store import load_validation_receipt
        except ImportError:
            return CheckpointResult(
                ok=False,
                refusal_reason="validation_receipt_verification_unavailable",
                error_kind="validation_receipt_verification_unavailable",
            )

        receipt = load_validation_receipt(validation_sha256)
        if receipt is None:
            return CheckpointResult(
                ok=False,
                refusal_reason=f"Validation receipt not found: {validation_sha256}",
                error_kind="validation_receipt_missing",
                suggested_next_action="Run bound validation to create a validation receipt.",
            )

        # Verify binds to same preparation receipt
        receipt_prep = receipt.get("preparation_receipt_sha256")
        if preparation_sha256 and receipt_prep != preparation_sha256:
            return CheckpointResult(
                ok=False,
                refusal_reason="Validation receipt does not reference the same preparation receipt.",
                error_kind="validation_preparation_mismatch",
                suggested_next_action="Run bound validation against the current preparation receipt.",
            )

        # Verify validation outcome
        outcome = receipt.get("validation_outcome")
        if outcome != "passed":
            return CheckpointResult(
                ok=False,
                refusal_reason=f"Validation did not pass (outcome: {outcome}).",
                error_kind="validation_not_passed",
                suggested_next_action="Fix validation failures and rerun bound validation.",
            )

        # Verify index digest matches
        receipt_digest = receipt.get("prepared_index_tree_digest")
        if receipt_digest:
            from rig_relay.core.git_index_operations import compute_index_tree_digest

            current = compute_index_tree_digest(repo_root)
            if current is None or current != receipt_digest:
                return CheckpointResult(
                    ok=False,
                    refusal_reason="Current index does not match the validation receipt's prepared index digest.",
                    error_kind="validation_stale_index",
                    suggested_next_action="Re-run bound validation against the current prepared index.",
                )

        return None

    def _validate_preconditions(
        self,
        args: CheckpointArgs,
        requested: set[str],
        dirty_files: dict[str, str],
        store: CoordinationStore,
        guard: DirtyFileGuard,
        repo_root: Path,
        ctx: InvokeContext | None = None,
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

        # ── Step 2.5: Preparation receipt verification ─────────────
        if args.preparation_receipt_sha256:
            result = self._verify_preparation_receipt(
                args.preparation_receipt_sha256, repo_root, requested
            )
            if result is not None:
                return result

        # ── Step 3.2.6: Validation receipt verification ──────────────
        if args.validation_receipt_sha256:
            result = self._verify_validation_receipt(
                args.validation_receipt_sha256,
                args.preparation_receipt_sha256,
                repo_root,
            )
            if result is not None:
                return result

        # ── Step 2.6: In autonomous/governed mode, preparation receipts are mandatory ─
        mission_auth = (
            getattr(getattr(ctx, "tool_runtime", None), "_mission_authority", None)
            if ctx
            else None
        )
        if mission_auth is not None and not args.preparation_receipt_sha256:
            return CheckpointResult(
                ok=False,
                message="Checkpoint refused: preparation receipt required for governed checkpoint",
                refusal_reason="preparation_receipt_required",
                error_kind="preparation_receipt_required",
            )

        # Step 2.7: In governed mode, bound validation receipts are mandatory
        if mission_auth is not None and not args.validation_receipt_sha256:
            return CheckpointResult(
                ok=False,
                message="Checkpoint refused: validation receipt required for governed checkpoint",
                refusal_reason="validation_receipt_required",
                error_kind="validation_receipt_required",
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
                # Use receipt's own receipt_sha256 if available,
                # otherwise compute canonical digest
                receipt_digest = receipt_dict.get("receipt_sha256")
                if not receipt_digest:
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
        """Commit the current index exactly — no git add re-staging."""
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
        if args.preparation_receipt_sha256:
            body_lines.append(
                f"Rig-Preparation-Receipt-SHA256: {args.preparation_receipt_sha256}"
            )
        if args.validation_receipt_sha256:
            body_lines.append(
                f"Rig-Validation-Receipt-SHA256: {args.validation_receipt_sha256}"
            )
        if args.validation_summary:
            body_lines.append("Validation:")
            for cmd in args.validation_summary:
                body_lines.append(f"- {cmd}")
        full_message = subject + "\n" + "\n".join(body_lines)

        # Commit EXACTLY the current index — no git add.
        commit_result = self._git("commit", "-m", full_message, cwd=repo_root)
        if isinstance(commit_result, CheckpointResult):
            return commit_result

        # Verify committed tree matches preparation
        if args.preparation_receipt_sha256:
            try:
                from rig_relay.core.git_index_operations import compute_head_tree_digest
                from rig_relay.governance.auth_receipts import load_preparation_receipt

                receipt = load_preparation_receipt(args.preparation_receipt_sha256)
                if receipt is not None:
                    expected = receipt.get("post_index_tree_digest")
                    committed_tree = compute_head_tree_digest(repo_root)
                    if expected and committed_tree and committed_tree != expected:
                        return CheckpointResult(
                            ok=False,
                            refusal_reason=(
                                f"Committed tree ({committed_tree[:12]}...) does not "
                                f"match preparation receipt ({expected[:12]}...)."
                            ),
                            error_kind="committed_tree_mismatch",
                            suggested_next_action="Investigate commit mismatch. Contact administrator.",
                        )
            except Exception:
                pass  # Post-commit verification is best-effort

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

    # ── Durable Authorization Ledger ────────────────────────────────────

    @staticmethod
    def _auth_ledger_dir(repo_root: Path) -> Path:
        return repo_root / ".build" / "rig-relay" / "governance"

    @staticmethod
    def _persist_authorization_receipt(
        repo_root: Path, receipt_json: str, receipt_digest: str
    ) -> Path:
        """Persist authorization receipt BEFORE commit to durable ledger."""
        ledger_dir = Checkpoint._auth_ledger_dir(repo_root)
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_dir / "checkpoint_authorization_receipts.v1.jsonl"
        record = {
            "receipt_digest": receipt_digest,
            "receipt_json": receipt_json,
            "outcome": "authorized",
            "commit_sha": "",
            "created_at": datetime.now(UTC).isoformat(),
        }
        with open(ledger_path, "a") as f:
            f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        return ledger_path

    @staticmethod
    def _load_latest_authorization_receipt(
        repo_root: Path, receipt_digest: str
    ) -> dict | None:
        """Load the authorization receipt matching a digest from the ledger."""
        ledger_path = (
            Checkpoint._auth_ledger_dir(repo_root)
            / "checkpoint_authorization_receipts.v1.jsonl"
        )
        if not ledger_path.exists():
            return None
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("receipt_digest") == receipt_digest:
                return record
        return None

    @staticmethod
    def _check_commit_for_receipt_trailer(
        repo_root: Path, receipt_digest: str
    ) -> str | None:
        """Return the commit SHA if HEAD carries the receipt digest trailer."""
        trailer = f"Rig-Authorization-Receipt-SHA256: {receipt_digest}"
        result = subprocess.run(
            ["git", "-C", str(repo_root), "log", "--format=%H:%B", "-1"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        if trailer in (result.stdout or ""):
            return result.stdout.split(":", 1)[0].strip().splitlines()[0]
        # Also check last 10 commits for the trailer (recovery: HEAD may have advanced)
        result2 = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                "-10",
                "--format=%H",
                f"--grep={trailer}",
            ],
            capture_output=True,
            text=True,
        )
        if result2.returncode == 0 and result2.stdout.strip():
            return result2.stdout.strip().splitlines()[0]
        return None

    @staticmethod
    def _persist_terminal_checkpoint_receipt(
        repo_root: Path, receipt_digest: str, commit_sha: str, outcome: str
    ) -> Path:
        """Append a terminal checkpoint receipt after commit or recovery."""
        ledger_dir = Checkpoint._auth_ledger_dir(repo_root)
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_dir / "checkpoint_receipts.v1.jsonl"
        record = {
            "receipt_digest": receipt_digest,
            "commit_sha": commit_sha,
            "outcome": outcome,
            "created_at": datetime.now(UTC).isoformat(),
        }
        with open(ledger_path, "a") as f:
            f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        return ledger_path

    @staticmethod
    def _has_terminal_receipt(repo_root: Path, receipt_digest: str) -> bool:
        """Check whether a terminal receipt already exists for this authorization."""
        ledger_path = (
            Checkpoint._auth_ledger_dir(repo_root) / "checkpoint_receipts.v1.jsonl"
        )
        if not ledger_path.exists():
            return False
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("receipt_digest") == receipt_digest:
                return True
        return False

    def resolve_permission(self, args: CheckpointArgs) -> None:
        return None

    @staticmethod
    def _consume_preparation_receipt(
        *, receipt_sha256: str, branch: str, repo_root: Path, committed_head_sha: str
    ) -> None:
        """Append a consumed lifecycle event for the preparation receipt.

        Best-effort — failure to append the lifecycle event does not
        block the checkpoint result. Crash recovery (below) can repair
        a missing consumed event from terminal checkpoint evidence.
        """
        try:
            from rig_relay.governance.receipt_store import (
                PreparationLifecycleEvent,
                PreparationLifecycleEventKind,
                append_lifecycle_event,
                get_lifecycle_status,
            )

            # Check if already consumed (crash recovery: we already
            # committed but may have failed to record lifecycle event)
            if (
                get_lifecycle_status(receipt_sha256)
                == PreparationLifecycleEventKind.CONSUMED
            ):
                return

            event = PreparationLifecycleEvent(
                event_kind=PreparationLifecycleEventKind.CONSUMED,
                preparation_receipt_sha256=receipt_sha256,
                branch=branch,
                worktree_root=str(repo_root.resolve()),
                producer="checkpoint.run",
                committed_head_sha=committed_head_sha,
            )
            append_lifecycle_event(event)
        except Exception:
            pass  # Best-effort; terminal checkpoint evidence provides recovery

    @staticmethod
    def _recover_missing_lifecycle_event(
        *, receipt_sha256: str, branch: str, repo_root: Path
    ) -> bool:
        """Recover a missing consumed lifecycle event from terminal checkpoint evidence.

        Uses ``git interpret-trailers --parse`` for structured trailer
        extraction — never trusts loose substring matching on commit prose.
        Only matches the exact trailer key ``Rig-Preparation-Receipt-SHA256``
        with the exact receipt value.

        Idempotent: if a CONSUMED event already exists, returns False
        without appending another.

        Returns True if recovery appended a repaired event.
        """
        from rig_relay.governance.receipt_store import (
            PreparationLifecycleEvent,
            PreparationLifecycleEventKind,
            append_lifecycle_event,
            load_lifecycle_events,
        )

        # Idempotency: if already consumed, nothing to do
        load_result = load_lifecycle_events(receipt_sha256)
        if (
            load_result.is_ok
            and load_result.status == PreparationLifecycleEventKind.CONSUMED
        ):
            return False
        # If ledger is corrupt, refuse to write new events over it
        if not load_result.is_ok and not load_result.is_absent:
            return False

        # Structured trailer extraction via git interpret-trailers --parse
        import subprocess

        trailer_key = "Rig-Preparation-Receipt-SHA256"
        proc = subprocess.run(
            [
                "git",
                "log",
                "-10",
                "--format=%(trailers:only,unfold)",
                f"--grep=Rig-Preparation-Receipt-SHA256: {receipt_sha256}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
        if proc.returncode != 0:
            return False

        trailer_lines = proc.stdout.strip()
        if not trailer_lines:
            return False

        # Parse structured trailers: each line is "key: value"
        found_sha: str | None = None
        for line in trailer_lines.splitlines():
            line = line.strip()
            if not line:
                continue
            if ": " not in line:
                continue
            key, _, value = line.partition(": ")
            if key == trailer_key and value == receipt_sha256:
                found_sha = value
                break

        if found_sha is None:
            return False

        # Get the commit SHA that carries this trailer
        commit_proc = subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--format=%H",
                f"--grep=Rig-Preparation-Receipt-SHA256: {receipt_sha256}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=repo_root,
        )
        committed_head = (
            commit_proc.stdout.strip()
            if commit_proc.returncode == 0 and commit_proc.stdout.strip()
            else None
        )
        if not committed_head:
            return False

        current = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=repo_root,
        )
        current_branch = current.stdout.strip() if current.returncode == 0 else branch

        event = PreparationLifecycleEvent(
            event_kind=PreparationLifecycleEventKind.CONSUMED,
            preparation_receipt_sha256=receipt_sha256,
            branch=current_branch or branch,
            worktree_root=str(repo_root.resolve()),
            producer="checkpoint._recover_missing_lifecycle_event",
            committed_head_sha=committed_head,
        )
        return append_lifecycle_event(event) is not None
