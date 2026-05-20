"""Live PR Mutation Transaction Harness + Recovery v1.

Multi-phase transactional executor with crash/ambiguity recovery, reconciliation,
rate-limit handling, and PR status observation. Append-only JSONL ledger.
Fake boundary deterministic scenarios. Alert update deferred. No auto-rollback.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.integrations.github_provider._fake_github_boundary import (
    FakeGitHubBoundary,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GOV = _REPO_ROOT / "docs" / "json" / "governance"
_BUILD = _REPO_ROOT / ".build" / "rig-relay" / "evidence"

_DEFAULT_LEDGER = _BUILD / "github_code_scanning_pr_transaction_ledger_v1.jsonl"
_DEFAULT_TRANSACTION = _GOV / "github_code_scanning_pr_mutation_transaction_v1.v1.json"
_DEFAULT_RECOVERY = _GOV / "github_code_scanning_pr_mutation_recovery_plan_v1.v1.json"
_DEFAULT_RECONCILE = _GOV / "github_code_scanning_pr_mutation_reconciliation_v1.v1.json"
_DEFAULT_OBSERVATION = _GOV / "github_code_scanning_pr_status_observation_v1.v1.json"
_DEFAULT_FINALIZE = _GOV / "github_code_scanning_pr_transaction_finalization_v1.v1.json"
_DEFAULT_PROJECTION = _GOV / "github_code_scanning_pr_transaction_projection_v1.v1.json"

_FORBIDDEN = frozenset({
    "access_token",
    "token_prefix",
    "authorization",
    "client_secret",
    "private_key",
    "raw_response",
    "raw_body",
    "raw_payload",
    "code_snippet",
    "vulnerable_code",
    "file_body",
    "auth_header",
    "bearer",
    "secret_value",
    "source_content",
    "raw_file",
})

TRANSACTION_STATES = [
    "not_started",
    "blocked_preflight",
    "ready",
    "branch_create_attempted",
    "branch_created",
    "branch_create_ambiguous",
    "file_write_attempted",
    "file_written",
    "file_write_ambiguous",
    "pr_create_attempted",
    "pr_created",
    "pr_create_ambiguous",
    "partially_succeeded",
    "paused_rate_limited",
    "paused_permission_lost",
    "reconcile_required",
    "recovery_planned",
    "resumed",
    "finalized_success",
    "finalized_blocked",
    "finalized_manual_review_required",
]

SCENARIOS = [
    "complete_success",
    "branch_created_file_fails",
    "branch_file_ok_pr_fails",
    "branch_exists_from_prior",
    "branch_file_ok_pr_missing",
    "pr_already_exists",
    "rate_limit_before_branch",
    "rate_limit_after_branch",
    "secondary_limit_file_write",
    "unknown_after_branch",
    "unknown_after_file",
    "unknown_after_pr",
    "permission_loss",
    "stale_base_ref",
]


def _sha256_text(val: str) -> str:
    return hashlib.sha256(val.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


class TransactionHarness:
    def __init__(
        self,
        fake_boundary: FakeGitHubBoundary | None = None,
        scenario: str = "complete_success",
    ):
        self.fb = fake_boundary or FakeGitHubBoundary()
        self.scenario = scenario
        self.transaction_id = _sha256_text(f"txn:{_now_iso()}")
        self.idem_key = _sha256_text(f"idem:txn:{self.transaction_id}")
        self.state = "not_started"
        self.branch = "rig/security/fix-5"
        self._ledger_entries: list[str] = []

    def _ledger(
        self,
        phase: str,
        step: str,
        op_class: str,
        status: str,
        remote_mut: bool = False,
        remote_ok: bool = False,
        ambiguous: bool = False,
        retryable: bool = True,
        reconcile: bool = False,
    ) -> None:
        eid = _sha256_text(f"{self.transaction_id}:{len(self._ledger_entries)}")
        entry = {
            "transaction_id": self.transaction_id,
            "transaction_event_id": eid,
            "idempotency_key": self.idem_key,
            "phase": phase,
            "step": step,
            "operation_class": op_class,
            "status": status,
            "remote_mutation_attempted": remote_mut,
            "remote_mutation_succeeded": remote_ok,
            "ambiguity_status": ambiguous,
            "retryable": retryable,
            "resumable": True,
            "reconcile_required": reconcile,
            "rollback_guidance_required": ambiguous,
            "endpoint_route_pattern": f"/repos/OWNER/REPO/{step}",
            "request_method": "POST" if remote_mut else "GET",
            "required_permissions": ["contents:write"]
            if remote_mut
            else ["metadata:read"],
            "used_permissions": ["contents:write"] if remote_mut else [],
            "response_body_persisted": False,
            "rate_limit_snapshot": {"rate_limited": self.fb._rate_limited},
            "redaction_status": {"content_light": True},
        }
        self._ledger_entries.append(json.dumps(entry, sort_keys=True))
        _DEFAULT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        _DEFAULT_LEDGER.write_text(
            "\n".join(self._ledger_entries) + "\n" if self._ledger_entries else "",
            encoding="utf-8",
        )

    def _apply_scenario(self, step: str) -> tuple[int, bool]:
        sc = self.scenario
        if sc == "complete_success":
            return 201, False
        if sc == "rate_limit_before_branch":
            self.fb.set_rate_limited(True)
            return 429, False
        if sc == "rate_limit_after_branch" and step == "create_branch":
            return 201, False
        if sc == "rate_limit_after_branch":
            self.fb.set_rate_limited(True)
            return 429, False
        if sc == "branch_created_file_fails" and step == "create_branch":
            return 201, False
        if sc == "branch_created_file_fails" and step == "write_file":
            self.fb.set_permission("contents:write", False)
            return 403, False
        if sc == "branch_file_ok_pr_fails" and step in ("create_branch", "write_file"):
            return 201, False
        if sc == "branch_file_ok_pr_fails":
            self.fb.set_permission("pull_requests:write", False)
            return 403, False
        if sc == "branch_exists_from_prior" and step == "create_branch":
            self.fb.add_existing_branch(self.branch)
            return 422, False
        if sc == "branch_file_ok_pr_missing" and step in (
            "create_branch",
            "write_file",
        ):
            return 201, False
        if sc == "branch_file_ok_pr_missing":
            self.fb.add_existing_pr(self.idem_key)
            return 200, False  # idempotent
        if sc == "pr_already_exists":
            self.fb.add_existing_pr(self.idem_key)
            return 200, False
        if sc == "secondary_limit_file_write" and step == "write_file":
            self.fb.set_rate_limited(True)
            return 429, True
        if sc == "unknown_after_branch":
            return 201, True
        if sc == "unknown_after_file":
            return 201, step == "write_file"  # ambiguous after file write
        if sc == "unknown_after_pr":
            return 201, step == "create_pr"
        if sc == "permission_loss" and step != "create_branch":
            self.fb.set_permission("contents:write", False)
            return 403, False
        if sc == "stale_base_ref":
            return 409, False
        return 201, False

    def run(self) -> dict[str, Any]:
        self._ledger("preflight", "check_gates", "read_only", "passed")
        remote_mutation_succeeded = False
        branch_created = False
        file_written = False
        pr_created = False
        steps: list[dict[str, Any]] = []

        for step_name, op_class in [
            ("create_branch", "remote_mutation"),
            ("write_file", "remote_mutation"),
            ("create_pr", "remote_mutation"),
        ]:
            sc, ambiguous = self._apply_scenario(step_name)
            step_ok = sc in (201, 200)
            self._ledger(
                "mutation",
                step_name,
                op_class,
                "passed" if step_ok else f"http_{sc}",
                remote_mut=True,
                remote_ok=step_ok,
                ambiguous=ambiguous,
                reconcile=ambiguous,
            )
            steps.append({
                "step": step_name,
                "status": "passed" if step_ok else f"http_{sc}",
                "ambiguous": ambiguous,
            })

            if step_name == "create_branch":
                branch_created = step_ok
            elif step_name == "write_file":
                file_written = step_ok
            elif step_name == "create_pr":
                pr_created = step_ok

        remote_mutation_succeeded = branch_created and file_written and pr_created

        # Post-transaction observation
        pr_state = "unknown"
        if pr_created:
            sc, data = self.fb.get_pr_status(1)
            pr_state = (
                data.get("state", "unknown") if isinstance(data, dict) else "unknown"
            )
            checks = (
                data.get("checks", "unknown") if isinstance(data, dict) else "unknown"
            )
            self._ledger(
                "observation",
                "pr_status",
                "read_only",
                f"pr_{pr_state}_checks_{checks}",
                reconcile=False,
            )

        # Reconciliation
        any_failed = not remote_mutation_succeeded
        reconcile: dict[str, Any] = {
            "branch_exists": branch_created,
            "file_written": file_written,
            "pr_exists": pr_created,
            "alert_state_unchanged": True,
            "divergent": any(s.get("ambiguous") for s in steps) or any_failed,
        }
        self._ledger(
            "reconciliation",
            "verify_state",
            "read_only",
            "divergent" if reconcile["divergent"] else "clean",
            reconcile=True,
        )

        # Recovery
        recovery = {
            "safe_to_resume": not reconcile["divergent"],
            "resume_from_step": None
            if remote_mutation_succeeded
            else "create_branch"
            if not branch_created
            else "write_file"
            if not file_written
            else "create_pr",
            "manual_review_required": reconcile["divergent"],
            "no_auto_rollback": True,
            "alert_update_deferred": True,
        }
        self._ledger(
            "recovery",
            "plan",
            "local_artifact_write",
            "planned",
            reconcile=reconcile["divergent"],
        )

        # Finalization
        status = (
            "finalized_success"
            if remote_mutation_succeeded
            else "finalized_blocked"
            if not branch_created
            else "finalized_manual_review_required"
        )
        final = {
            "status": status,
            "remote_mutation_succeeded": remote_mutation_succeeded,
            "branch_created": branch_created,
            "file_written": file_written,
            "pr_created": pr_created,
            "pr_state": pr_state,
            "alert_updated": False,
            "alert_update_deferred": True,
            "manual_review_required": reconcile["divergent"],
        }
        self._ledger("finalization", "finalize", "local_artifact_write", status)

        # Write artifacts
        tx_report = {
            "schema_version": "rig.github.code_scanning_pr_mutation_transaction.v1",
            "transaction_id": self.transaction_id,
            "idempotency_key": self.idem_key,
            "scenario": self.scenario,
            "status": status,
            "steps": steps,
            "reconciliation": reconcile,
            "recovery": recovery,
            "finalization": final,
            "content_light": True,
        }
        _write_json(_DEFAULT_TRANSACTION, tx_report)
        _write_json(
            _DEFAULT_RECOVERY,
            {
                "schema_version": "rig.github.code_scanning_pr_mutation_recovery_plan.v1",
                "transaction_id": self.transaction_id,
                **recovery,
            },
        )
        _write_json(
            _DEFAULT_RECONCILE,
            {
                "schema_version": "rig.github.code_scanning_pr_mutation_reconciliation.v1",
                "transaction_id": self.transaction_id,
                **reconcile,
            },
        )
        _write_json(
            _DEFAULT_OBSERVATION,
            {
                "schema_version": "rig.github.code_scanning_pr_status_observation.v1",
                "transaction_id": self.transaction_id,
                "pr_state": pr_state,
                "alert_update_deferred": True,
            },
        )
        _write_json(
            _DEFAULT_FINALIZE,
            {
                "schema_version": "rig.github.code_scanning_pr_transaction_finalization.v1",
                "transaction_id": self.transaction_id,
                **final,
            },
        )
        _write_json(
            _DEFAULT_PROJECTION,
            {
                "available": True,
                "transaction_status": status,
                "recovery_status": "planned"
                if not remote_mutation_succeeded
                else "none",
                "pr_status": pr_state,
                "alert_update_status": "deferred",
                "rate_limit_status": "none",
                "next_safe_action": "verify_reconciliation"
                if reconcile["divergent"]
                else "review_transaction",
                "human_review_required": reconcile["divergent"],
                "raw_payloads_exposed": False,
            },
        )

        return tx_report


def _assert_clean(s: str) -> None:
    for k in _FORBIDDEN:
        if f'"{k}"' in s:
            raise ValueError(f"forbidden:{k}")


def run_transaction_harness(scenario: str = "complete_success") -> dict[str, Any]:
    fb = FakeGitHubBoundary()
    harness = TransactionHarness(fb, scenario)
    return harness.run()


def write_transaction_report(
    scenario: str = "complete_success", generated_at_utc: str | None = None
) -> dict[str, Any]:
    return run_transaction_harness(scenario)


__all__ = [
    "SCENARIOS",
    "TransactionHarness",
    "run_transaction_harness",
    "write_transaction_report",
]
