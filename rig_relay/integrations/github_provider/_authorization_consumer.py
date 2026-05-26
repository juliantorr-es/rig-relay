"""GitHub Remote Action Authorization Consumer — consumes Lane A authority.

Bridges Lane B GitHub mutation operations to Lane A's
remote_action_authorization.py contract. Validates authorization receipts
against exact request digests, action classes, providers, targets,
freshness requirements, and single-use semantics before any HTTP request.

A valid Lane A receipt is necessary but not sufficient — GitHub token
and permission checks remain independent.
"""

from __future__ import annotations

from enum import StrEnum, auto
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from rig_relay.governance.remote_action_authorization import (
    RemoteActionClass,
    RemoteActionOutcome,
    RemoteActionResult,
    consume_remote_action_authorization,
    issue_remote_action_authorization,
)

# ═══════════════════════════════════════════════════════════════════════
# ── Lane B → Lane A action mapping ─────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


# Maps Lane B operation_kind strings to Lane A RemoteActionClass enums
_LANE_B_TO_LANE_A_ACTION: dict[str, RemoteActionClass] = {
    "profile_update": RemoteActionClass.GITHUB_USER_PROFILE_UPDATE,
    "repo_create": RemoteActionClass.GITHUB_REPOSITORY_CREATE,
    "issue_create": RemoteActionClass.GITHUB_ISSUE_CREATE,
    "issue_comment": RemoteActionClass.GITHUB_ISSUE_COMMENT,
    "issue_close": RemoteActionClass.GITHUB_ISSUE_CLOSE,
    "workflow_rerun": RemoteActionClass.GITHUB_ACTIONS_RERUN,
    "workflow_dispatch": RemoteActionClass.GITHUB_ACTIONS_DISPATCH,
    "pages_configure": RemoteActionClass.GITHUB_PAGES_CONFIGURE,
    "pages_publish": RemoteActionClass.GITHUB_PAGES_PUBLISH,
    "pages_cancel": RemoteActionClass.GITHUB_PAGES_CANCEL_DEPLOYMENT,
}


def operation_kind_to_action_class(operation_kind: str) -> RemoteActionClass | None:
    """Map Lane B operation kind to Lane A RemoteActionClass."""
    return _LANE_B_TO_LANE_A_ACTION.get(operation_kind)


# ═══════════════════════════════════════════════════════════════════════
# ── Request digest computation ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def compute_request_digest(payload: dict[str, Any]) -> str:
    """Compute the canonical SHA256 request digest for a mutation proposal."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


# ═══════════════════════════════════════════════════════════════════════
# ── Consumer result models ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


class ConsumerOutcome(StrEnum):
    AUTHORIZED = auto()
    MISSING_AUTHORIZATION = auto()
    INVALID_RECEIPT = auto()
    EXPIRED_RECEIPT = auto()
    ALREADY_CONSUMED = auto()
    REQUEST_DIGEST_MISMATCH = auto()
    ACTION_MISMATCH = auto()
    TARGET_MISMATCH = auto()
    PROVIDER_MISMATCH = auto()
    STALE_EVIDENCE = auto()
    INTEGRITY_TAMPERED = auto()
    SENTINEL_EXCLUDED = auto()
    NOT_FOUND = auto()
    CORRUPT = auto()
    GITHUB_TOKEN_UNAVAILABLE = auto()
    GITHUB_PERMISSION_MISSING = auto()
    REMOTE_REQUEST_FAILED = auto()
    REMOTE_VERIFICATION_FAILED = auto()
    REMOTE_OUTCOME_INDETERMINATE = auto()
    UNKNOWN_ERROR = auto()


class ConsumerResult(BaseModel):
    """Result from an authorization-bound GitHub mutation attempt."""

    model_config = ConfigDict(extra="forbid")

    outcome: str = ConsumerOutcome.MISSING_AUTHORIZATION.value
    authorization_id: str = ""
    operation_kind: str = ""
    remote_request_sent: bool = False
    remote_status_code: int | None = None
    remote_verified: bool | None = None
    evidence_digest: str | None = None
    error_detail: str = ""
    suggested_next_action: str = ""


def _consumer_result_from_remote(
    rea_result: RemoteActionResult, operation_kind: str
) -> ConsumerResult:
    """Translate Lane A RemoteActionResult to Lane B ConsumerResult."""
    mapping: dict[str, ConsumerOutcome] = {
        RemoteActionOutcome.VALID.value: ConsumerOutcome.AUTHORIZED,
        RemoteActionOutcome.ISSUED.value: ConsumerOutcome.AUTHORIZED,
        RemoteActionOutcome.CONSUMED.value: ConsumerOutcome.AUTHORIZED,
        RemoteActionOutcome.EXPIRED.value: ConsumerOutcome.EXPIRED_RECEIPT,
        RemoteActionOutcome.ALREADY_CONSUMED.value: ConsumerOutcome.ALREADY_CONSUMED,
        RemoteActionOutcome.UNSUPPORTED_ACTION.value: ConsumerOutcome.ACTION_MISMATCH,
        RemoteActionOutcome.ACTION_MISMATCH.value: ConsumerOutcome.ACTION_MISMATCH,
        RemoteActionOutcome.PROVIDER_MISMATCH.value: ConsumerOutcome.PROVIDER_MISMATCH,
        RemoteActionOutcome.TARGET_MISMATCH.value: ConsumerOutcome.TARGET_MISMATCH,
        RemoteActionOutcome.REQUEST_DIGEST_MISMATCH.value: ConsumerOutcome.REQUEST_DIGEST_MISMATCH,
        RemoteActionOutcome.STALE_EVIDENCE.value: ConsumerOutcome.STALE_EVIDENCE,
        RemoteActionOutcome.EVIDENCE_MISMATCH.value: ConsumerOutcome.STALE_EVIDENCE,
        RemoteActionOutcome.MISSING_FRESHNESS.value: ConsumerOutcome.STALE_EVIDENCE,
        RemoteActionOutcome.NOT_FOUND.value: ConsumerOutcome.NOT_FOUND,
        RemoteActionOutcome.CORRUPT.value: ConsumerOutcome.CORRUPT,
        RemoteActionOutcome.INTEGRITY_TAMPERED.value: ConsumerOutcome.INTEGRITY_TAMPERED,
        RemoteActionOutcome.SENTINEL_EXCLUDED.value: ConsumerOutcome.SENTINEL_EXCLUDED,
    }
    outcome = mapping.get(rea_result.outcome.value, ConsumerOutcome.INVALID_RECEIPT)
    return ConsumerResult(
        outcome=outcome.value,
        authorization_id=rea_result.authorization_id,
        operation_kind=operation_kind,
        error_detail=rea_result.error_detail,
        suggested_next_action=_suggested_action_for(outcome),
    )


def _suggested_action_for(outcome: ConsumerOutcome) -> str:
    return {
        ConsumerOutcome.AUTHORIZED: "Proceed with remote mutation",
        ConsumerOutcome.MISSING_AUTHORIZATION: "Request Lane A remote-action authorization for this operation",
        ConsumerOutcome.INVALID_RECEIPT: "Obtain a valid authorization receipt",
        ConsumerOutcome.EXPIRED_RECEIPT: "Re-issue authorization for this operation",
        ConsumerOutcome.ALREADY_CONSUMED: "Request a new authorization receipt",
        ConsumerOutcome.REQUEST_DIGEST_MISMATCH: "Authorization receipt does not match the proposed request",
        ConsumerOutcome.ACTION_MISMATCH: "Authorization receipt is for a different action",
        ConsumerOutcome.TARGET_MISMATCH: "Authorization receipt is for a different target",
        ConsumerOutcome.PROVIDER_MISMATCH: "Authorization receipt is for a different provider",
        ConsumerOutcome.STALE_EVIDENCE: "Remote state has changed since authorization was issued",
        ConsumerOutcome.INTEGRITY_TAMPERED: "Authorization receipt integrity compromised",
        ConsumerOutcome.SENTINEL_EXCLUDED: "Authorization receipt contains confidential sentinel fields",
        ConsumerOutcome.NOT_FOUND: "Authorization receipt not found",
        ConsumerOutcome.CORRUPT: "Authorization receipt is corrupt",
        ConsumerOutcome.GITHUB_TOKEN_UNAVAILABLE: "GitHub authentication required",
        ConsumerOutcome.GITHUB_PERMISSION_MISSING: "Insufficient GitHub permissions",
        ConsumerOutcome.REMOTE_REQUEST_FAILED: "GitHub rejected the request; check permission and payload",
        ConsumerOutcome.REMOTE_VERIFICATION_FAILED: "Post-mutation verification failed; remote state does not match expected",
        ConsumerOutcome.REMOTE_OUTCOME_INDETERMINATE: "Request may have succeeded but verification could not confirm",
        ConsumerOutcome.UNKNOWN_ERROR: "Unexpected error during authorization or execution",
    }.get(outcome, "Check authorization state and retry")


# ═══════════════════════════════════════════════════════════════════════
# ── Authorization Consumer ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


class GitHubAuthorizationConsumer:
    """Consumes Lane A remote-action authorization for GitHub mutations.

    Validates authorization against exact request digests, action classes,
    freshness, and single-use semantics before delegating to GitHub adapters.
    """

    @staticmethod
    def validate_and_consume(
        *,
        authorization_id: str,
        operation_kind: str,
        request_payload: dict[str, Any],
        target_identity: str,
        provider: str = "github",
        prior_evidence_digest: str = "",
    ) -> ConsumerResult:
        """Validate authorization and consume the receipt.

        Computes request digest, maps operation to action class, and calls
        Lane A's consume_remote_action_authorization(). Returns a typed
        consumer result.

        The receipt is consumed BEFORE any HTTP request, following Lane A's
        atomic consume-under-lock contract. After consumption, the caller
        MUST NOT retry with the same receipt on failure.
        """
        action_class = operation_kind_to_action_class(operation_kind)
        if action_class is None:
            return ConsumerResult(
                outcome=ConsumerOutcome.ACTION_MISMATCH.value,
                operation_kind=operation_kind,
                error_detail=f"No Lane A action class mapping for operation: {operation_kind}",
                suggested_next_action="Verify operation kind is supported",
            )

        if not authorization_id:
            return ConsumerResult(
                outcome=ConsumerOutcome.MISSING_AUTHORIZATION.value,
                operation_kind=operation_kind,
                error_detail="No authorization receipt provided",
                suggested_next_action=_suggested_action_for(
                    ConsumerOutcome.MISSING_AUTHORIZATION
                ),
            )

        request_digest = compute_request_digest(request_payload)

        rea_result = consume_remote_action_authorization(
            authorization_id,
            expected_action_class=action_class.value,
            expected_provider=provider,
            expected_target=target_identity,
            expected_request_digest=request_digest,
            current_prior_evidence_digest=prior_evidence_digest or None,
        )

        return _consumer_result_from_remote(rea_result, operation_kind)

    @staticmethod
    def issue_authorization(
        *,
        operation_kind: str,
        request_payload: dict[str, Any],
        target_identity: str,
        provider: str = "github",
        prior_evidence_digest: str = "",
        permission_scope_summary: str = "",
        purpose: str = "",
        ttl_minutes: int = 15,
    ) -> ConsumerResult:
        """Issue a remote-action authorization receipt through Lane A.

        Used when the operator needs to pre-authorize a mutation. The
        receipt can later be consumed by validate_and_consume().
        """
        action_class = operation_kind_to_action_class(operation_kind)
        if action_class is None:
            return ConsumerResult(
                outcome=ConsumerOutcome.ACTION_MISMATCH.value,
                operation_kind=operation_kind,
                error_detail=f"No Lane A action class mapping for: {operation_kind}",
            )

        request_digest = compute_request_digest(request_payload)

        rea_result = issue_remote_action_authorization(
            action_class=action_class.value,
            provider=provider,
            target_identity=target_identity,
            request_digest=request_digest,
            prior_evidence_digest=prior_evidence_digest,
            permission_scope_summary=permission_scope_summary,
            purpose=purpose,
            ttl_minutes=ttl_minutes,
        )

        return _consumer_result_from_remote(rea_result, operation_kind)

    @staticmethod
    def record_indeterminate_outcome(
        authorization_id: str, operation_kind: str, detail: str
    ) -> ConsumerResult:
        """Record that a remote outcome could not be determined.

        The receipt was already consumed. This result signals to the
        operator that manual verification is needed.
        """
        return ConsumerResult(
            outcome=ConsumerOutcome.REMOTE_OUTCOME_INDETERMINATE.value,
            authorization_id=authorization_id,
            operation_kind=operation_kind,
            remote_request_sent=True,
            error_detail=detail,
            suggested_next_action=_suggested_action_for(
                ConsumerOutcome.REMOTE_OUTCOME_INDETERMINATE
            ),
        )


# ═══════════════════════════════════════════════════════════════════════
# ── Built-in tool contract extension ───────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


class GitHubCapabilityContract(BaseModel):
    """Contract definition for a GitHub operation with authorization binding."""

    model_config = ConfigDict(extra="forbid")

    operation_kind: str
    lane_a_action_class: str = ""
    github_permission: str = ""
    token_type: str = ""  # user_access_token, installation_token
    requires_freshness: bool = False
    mutation_class: str = (
        ""  # mutating, destructive, configuration, deployment, repository_creation
    )
    read_only: bool = False
    consumes_lane_a_authority: bool = False
    lane_a_integrated: bool = True


_OPERATION_CONTRACTS: dict[str, GitHubCapabilityContract] = {
    "profile_update": GitHubCapabilityContract(
        operation_kind="profile_update",
        lane_a_action_class=RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
        github_permission="Profile:write",
        token_type="user_access_token",
        requires_freshness=True,
        mutation_class="mutating",
        consumes_lane_a_authority=True,
    ),
    "repo_create": GitHubCapabilityContract(
        operation_kind="repo_create",
        lane_a_action_class=RemoteActionClass.GITHUB_REPOSITORY_CREATE.value,
        github_permission="Administration:write",
        token_type="user_access_token",
        requires_freshness=False,
        mutation_class="repository_creation",
        consumes_lane_a_authority=True,
    ),
    "issue_create": GitHubCapabilityContract(
        operation_kind="issue_create",
        lane_a_action_class=RemoteActionClass.GITHUB_ISSUE_CREATE.value,
        github_permission="Issues:write",
        token_type="installation_token",
        requires_freshness=False,
        mutation_class="mutating",
        consumes_lane_a_authority=True,
    ),
    "issue_comment": GitHubCapabilityContract(
        operation_kind="issue_comment",
        lane_a_action_class=RemoteActionClass.GITHUB_ISSUE_COMMENT.value,
        github_permission="Issues:write",
        token_type="installation_token",
        requires_freshness=True,
        mutation_class="mutating",
        consumes_lane_a_authority=True,
    ),
    "issue_close": GitHubCapabilityContract(
        operation_kind="issue_close",
        lane_a_action_class=RemoteActionClass.GITHUB_ISSUE_CLOSE.value,
        github_permission="Issues:write",
        token_type="installation_token",
        requires_freshness=True,
        mutation_class="mutating",
        consumes_lane_a_authority=True,
    ),
    "workflow_rerun": GitHubCapabilityContract(
        operation_kind="workflow_rerun",
        lane_a_action_class=RemoteActionClass.GITHUB_ACTIONS_RERUN.value,
        github_permission="Actions:write",
        token_type="installation_token",
        requires_freshness=True,
        mutation_class="destructive",
        consumes_lane_a_authority=True,
    ),
    "workflow_dispatch": GitHubCapabilityContract(
        operation_kind="workflow_dispatch",
        lane_a_action_class=RemoteActionClass.GITHUB_ACTIONS_DISPATCH.value,
        github_permission="Actions:write",
        token_type="installation_token",
        requires_freshness=True,
        mutation_class="destructive",
        consumes_lane_a_authority=True,
    ),
    "pages_configure": GitHubCapabilityContract(
        operation_kind="pages_configure",
        lane_a_action_class=RemoteActionClass.GITHUB_PAGES_CONFIGURE.value,
        github_permission="Pages:write, Administration:write",
        token_type="installation_token",
        requires_freshness=True,
        mutation_class="configuration",
        consumes_lane_a_authority=True,
    ),
    "pages_publish": GitHubCapabilityContract(
        operation_kind="pages_publish",
        lane_a_action_class=RemoteActionClass.GITHUB_PAGES_PUBLISH.value,
        github_permission="Pages:write",
        token_type="installation_token",
        requires_freshness=True,
        mutation_class="deployment",
        consumes_lane_a_authority=True,
    ),
    "pages_cancel": GitHubCapabilityContract(
        operation_kind="pages_cancel",
        lane_a_action_class=RemoteActionClass.GITHUB_PAGES_CANCEL_DEPLOYMENT.value,
        github_permission="Pages:write",
        token_type="installation_token",
        requires_freshness=True,
        mutation_class="destructive",
        consumes_lane_a_authority=True,
    ),
}


def get_github_capability_contract(
    operation_kind: str,
) -> GitHubCapabilityContract | None:
    return _OPERATION_CONTRACTS.get(operation_kind)


def all_github_capability_contracts() -> list[GitHubCapabilityContract]:
    return list(_OPERATION_CONTRACTS.values())


__all__ = [
    "ConsumerOutcome",
    "ConsumerResult",
    "GitHubAuthorizationConsumer",
    "GitHubCapabilityContract",
    "all_github_capability_contracts",
    "compute_request_digest",
    "get_github_capability_contract",
    "operation_kind_to_action_class",
]
