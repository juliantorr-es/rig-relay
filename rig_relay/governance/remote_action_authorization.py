"""Remote External Action Authorization Authority v1.

Generic, durable, schema-governed authorization for external remote
actions whose side effects occur outside the local repository. Separate
from disclosure authorization — this authority governs remote writes.

Binds authorization to a specific request digest, action class, provider,
target identity, expected prior remote evidence, and single-use semantics.
Suitable for GitHub user profiles, repository creation, issue mutations,
Actions mutations, Pages configuration, and later comparable provider actions.

Lane A owns this generic authority substrate. Lane B consumes it for
GitHub-specific remote mutation authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum, auto
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets

from pydantic import BaseModel, ConfigDict, Field

# ═══════════════════════════════════════════════════════════════════════
# ── Remote action classes ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


class RemoteActionClass(StrEnum):
    # GitHub user profile
    GITHUB_USER_PROFILE_UPDATE = auto()

    # GitHub repositories
    GITHUB_REPOSITORY_CREATE = auto()

    # GitHub issues
    GITHUB_ISSUE_CREATE = auto()
    GITHUB_ISSUE_COMMENT = auto()
    GITHUB_ISSUE_CLOSE = auto()

    # GitHub Actions
    GITHUB_ACTIONS_RERUN = auto()
    GITHUB_ACTIONS_DISPATCH = auto()

    # GitHub Pages
    GITHUB_PAGES_CONFIGURE = auto()
    GITHUB_PAGES_PUBLISH = auto()
    GITHUB_PAGES_CANCEL_DEPLOYMENT = auto()

    # GitHub Git Content Publication (X3.3)
    GITHUB_GIT_CONTENT_PUBLISH = auto()


# All known valid action classes — used for unsupported-action refusal.
# Consumers add new classes by registering here.
SUPPORTED_ACTION_CLASSES: frozenset[str] = frozenset({
    c.value for c in RemoteActionClass
})

# Actions that always require prior remote evidence freshness.
FRESHNESS_REQUIRED_ACTIONS: frozenset[str] = frozenset({
    RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value,
    RemoteActionClass.GITHUB_ISSUE_COMMENT.value,
    RemoteActionClass.GITHUB_ISSUE_CLOSE.value,
    RemoteActionClass.GITHUB_PAGES_CONFIGURE.value,
    RemoteActionClass.GITHUB_PAGES_PUBLISH.value,
    RemoteActionClass.GITHUB_PAGES_CANCEL_DEPLOYMENT.value,
    RemoteActionClass.GITHUB_GIT_CONTENT_PUBLISH.value,
    RemoteActionClass.GITHUB_ACTIONS_RERUN.value,
    RemoteActionClass.GITHUB_ACTIONS_DISPATCH.value,
})

# Actions allowed without prior evidence (creation actions).
NO_PRIOR_EVIDENCE_ACTIONS: frozenset[str] = frozenset({
    RemoteActionClass.GITHUB_REPOSITORY_CREATE.value,
    RemoteActionClass.GITHUB_ISSUE_CREATE.value,
})


# ═══════════════════════════════════════════════════════════════════════
# ── Remote mutation risk classification ───────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


class RemoteMutationRisk(StrEnum):
    DESTRUCTIVE = auto()
    MUTATING = auto()
    CONFIGURATION = auto()
    DEPLOYMENT = auto()
    REPOSITORY_CREATION = auto()


_ACTION_RISK_MAP: dict[str, RemoteMutationRisk] = {
    RemoteActionClass.GITHUB_USER_PROFILE_UPDATE.value: RemoteMutationRisk.MUTATING,
    RemoteActionClass.GITHUB_REPOSITORY_CREATE.value: RemoteMutationRisk.REPOSITORY_CREATION,
    RemoteActionClass.GITHUB_ISSUE_CREATE.value: RemoteMutationRisk.MUTATING,
    RemoteActionClass.GITHUB_ISSUE_COMMENT.value: RemoteMutationRisk.MUTATING,
    RemoteActionClass.GITHUB_ISSUE_CLOSE.value: RemoteMutationRisk.MUTATING,
    RemoteActionClass.GITHUB_ACTIONS_RERUN.value: RemoteMutationRisk.DESTRUCTIVE,
    RemoteActionClass.GITHUB_ACTIONS_DISPATCH.value: RemoteMutationRisk.DESTRUCTIVE,
    RemoteActionClass.GITHUB_PAGES_CONFIGURE.value: RemoteMutationRisk.CONFIGURATION,
    RemoteActionClass.GITHUB_PAGES_PUBLISH.value: RemoteMutationRisk.DEPLOYMENT,
    RemoteActionClass.GITHUB_PAGES_CANCEL_DEPLOYMENT.value: RemoteMutationRisk.DESTRUCTIVE,
}


# ═══════════════════════════════════════════════════════════════════════
# ── Authorization receipt model ───────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


REA_SCHEMA_VERSION = "rig.relay.remote_action_authorization_receipt.v1"


class RemoteActionAuthorizationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = REA_SCHEMA_VERSION
    authorization_id: str = Field(default_factory=lambda: _rea_generate_id())
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    # Action binding
    action_class: str = ""
    provider: str = ""
    target_identity: str = ""
    requested_actor: str = ""
    producer_identity: str = ""

    # Request binding — hash of the canonical proposed request
    request_digest: str = ""

    # Freshness binding — prior remote evidence digest (empty for creation)
    prior_evidence_digest: str = ""

    # Permission scope
    permission_scope_summary: str = ""

    # Risk classification
    mutation_risk: str = ""

    # Lifecycle
    purpose: str = ""
    issued_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str = ""
    one_time: bool = True
    max_uses: int = 1
    use_count: int = 0
    consumed: bool = False

    # Integrity
    receipt_sha256: str = ""

    def recompute_integrity(self) -> str:
        payload = self.model_dump(exclude={"receipt_sha256"})
        payload["receipt_sha256"] = ""
        payload_data = json.dumps(payload, sort_keys=True).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload_data).hexdigest()

    def seal(self) -> None:
        self.receipt_sha256 = self.recompute_integrity()

    def verify_integrity(self) -> bool:
        return self.receipt_sha256 == self.recompute_integrity()


# ═══════════════════════════════════════════════════════════════════════
# ── Outcomes ──────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


class RemoteActionOutcome(StrEnum):
    ISSUED = auto()
    VALID = auto()
    CONSUMED = auto()
    EXPIRED = auto()
    ALREADY_CONSUMED = auto()
    UNSUPPORTED_ACTION = auto()
    ACTION_MISMATCH = auto()
    PROVIDER_MISMATCH = auto()
    TARGET_MISMATCH = auto()
    REQUEST_DIGEST_MISMATCH = auto()
    STALE_EVIDENCE = auto()
    EVIDENCE_MISMATCH = auto()
    MISSING_FRESHNESS = auto()
    NOT_FOUND = auto()
    CORRUPT = auto()
    INTEGRITY_TAMPERED = auto()
    SENTINEL_EXCLUDED = auto()


@dataclass(slots=True)
class RemoteActionResult:
    outcome: RemoteActionOutcome
    authorization_id: str = ""
    receipt: RemoteActionAuthorizationReceipt | None = None
    error_detail: str = ""

    @property
    def is_authorized(self) -> bool:
        return self.outcome in {
            RemoteActionOutcome.ISSUED,
            RemoteActionOutcome.VALID,
            RemoteActionOutcome.CONSUMED,
        }


# ═══════════════════════════════════════════════════════════════════════
# ── Persistence ───────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def _rea_generate_id() -> str:
    return "rea_" + secrets.token_hex(16)


def _rea_store_root() -> Path:
    return Path(".build/rig-relay/desktop/remote-action-authorizations")


def _rea_receipt_path(authorization_id: str) -> Path:
    return _rea_store_root() / f"{authorization_id}.json"


_lock_fd: dict[str, int] = {}
_lock_import = __import__("threading")  # avoid top-level import complexity


def _rea_acquire_lock(auth_id: str) -> bool:
    path = _rea_receipt_path(auth_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    try:
        fd = os.open(str(path.with_suffix(".json.lock")), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        _lock_fd[auth_id] = fd
        return True
    except OSError:
        return False


def _rea_release_lock(auth_id: str) -> None:
    fd = _lock_fd.pop(auth_id, None)
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        except OSError:
            pass


def _rea_persist_receipt(receipt: RemoteActionAuthorizationReceipt) -> str | None:
    store = _rea_store_root()
    try:
        store.mkdir(parents=True, exist_ok=True)
        path = _rea_receipt_path(receipt.authorization_id)
        path.write_text(
            json.dumps(receipt.model_dump(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return str(path)
    except OSError:
        return None


def _rea_load_receipt(authorization_id: str) -> RemoteActionAuthorizationReceipt | None:
    path = _rea_receipt_path(authorization_id)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Sentinel exclusion before model validation
        sentinel_issue = _check_sentinels(raw)
        if sentinel_issue is not None:
            return None
        return RemoteActionAuthorizationReceipt.model_validate(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


# ═══════════════════════════════════════════════════════════════════════
# ── Sentinel exclusion ────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════

_SENTINEL_FIELDS: frozenset[str] = frozenset({
    "token",
    "authorization_header",
    "request_secret",
    "private_key",
    "raw_github_response",
    "raw_workflow_log",
    "raw_private_content",
    "api_key",
    "bearer_token",
    "oauth_token",
    "client_secret",
    "ssh_private_key",
    "access_token",
    "refresh_token",
})


def _check_sentinels(receipt: dict) -> RemoteActionOutcome | None:
    """Reject receipts containing sentinel/excluded confidential fields."""
    for key in receipt:
        if key.lower() in _SENTINEL_FIELDS:
            return RemoteActionOutcome.SENTINEL_EXCLUDED
        val = receipt[key]
        if isinstance(val, str) and len(val) > 0:
            if any(
                sig in val.lower()
                for sig in [
                    "bearer ",
                    "ghp_",
                    "ghs_",
                    "gho_",
                    "-----begin rsa private key",
                    "-----begin openssh private key",
                ]
            ):
                return RemoteActionOutcome.SENTINEL_EXCLUDED
    return None


# ═══════════════════════════════════════════════════════════════════════
# ── Issue authorization ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def issue_remote_action_authorization(
    *,
    action_class: str,
    provider: str = "github",
    target_identity: str = "",
    requested_actor: str = "",
    producer_identity: str = "",
    request_digest: str = "",
    prior_evidence_digest: str = "",
    permission_scope_summary: str = "",
    purpose: str = "",
    ttl_minutes: int = 15,
    one_time: bool = True,
    max_uses: int = 1,
) -> RemoteActionResult:
    """Issue a remote action authorization receipt.

    Requirements:
    - action_class must be in SUPPORTED_ACTION_CLASSES or refusal
    - request_digest must be provided (binds to exact request)
    - prior_evidence_digest required for freshness-required actions
    - Sentinel fields are excluded
    """
    # Action class validation
    if action_class not in SUPPORTED_ACTION_CLASSES:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.UNSUPPORTED_ACTION,
            error_detail=(
                f"Unsupported remote action class: {action_class}. "
                f"Supported: {sorted(SUPPORTED_ACTION_CLASSES)}"
            ),
        )

    # Request digest binding — mandatory
    if not request_digest:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.REQUEST_DIGEST_MISMATCH,
            error_detail="Request digest is required — authorization must bind to exact request",
        )

    # Freshness requirement
    if action_class in FRESHNESS_REQUIRED_ACTIONS and not prior_evidence_digest:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.MISSING_FRESHNESS,
            error_detail=(
                f"Action {action_class} requires prior_evidence_digest "
                f"for remote state freshness"
            ),
        )

    # Sentinel exclusion
    # (Not applicable at issue time — produce/exclude later)

    # Risk classification
    mutation_risk = _ACTION_RISK_MAP.get(
        action_class, RemoteMutationRisk.MUTATING
    ).value

    now = datetime.now(UTC)
    expires = now + timedelta(minutes=ttl_minutes)

    receipt = RemoteActionAuthorizationReceipt(
        action_class=action_class,
        provider=provider,
        target_identity=target_identity,
        requested_actor=requested_actor,
        producer_identity=producer_identity,
        request_digest=request_digest,
        prior_evidence_digest=prior_evidence_digest,
        permission_scope_summary=permission_scope_summary,
        mutation_risk=mutation_risk,
        purpose=purpose,
        issued_at=now.isoformat(),
        expires_at=expires.isoformat(),
        one_time=one_time,
        max_uses=max_uses,
    )
    receipt.seal()

    # Sentinel check on the serialized receipt
    sentinel_issue = _check_sentinels(receipt.model_dump())
    if sentinel_issue is not None:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.SENTINEL_EXCLUDED,
            error_detail="Receipt contains excluded confidential sentinel fields",
        )

    path = _rea_persist_receipt(receipt)
    if path is None:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.CORRUPT,
            error_detail="Failed to persist remote action authorization receipt",
        )

    return RemoteActionResult(
        outcome=RemoteActionOutcome.ISSUED,
        authorization_id=receipt.authorization_id,
        receipt=receipt,
    )


# ═══════════════════════════════════════════════════════════════════════
# ── Validate authorization ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def validate_remote_action_authorization(
    authorization_id: str,
    *,
    expected_action_class: str | None = None,
    expected_provider: str | None = None,
    expected_target: str | None = None,
    expected_request_digest: str | None = None,
    current_prior_evidence_digest: str | None = None,
) -> RemoteActionResult:
    """Validate a remote action authorization receipt.

    Checks integrity, expiry, consumption, action/provider/target/digest
    matching, evidence freshness, and sentinel exclusion.
    """
    receipt = _rea_load_receipt(authorization_id)
    if receipt is None:
        # Check for sentinel exclusion (receipt exists but was rejected)
        path = _rea_receipt_path(authorization_id)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if _check_sentinels(raw) is not None:
                    return RemoteActionResult(
                        outcome=RemoteActionOutcome.SENTINEL_EXCLUDED,
                        authorization_id=authorization_id,
                        error_detail="Receipt contains excluded confidential sentinel fields",
                    )
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                pass
        return RemoteActionResult(
            outcome=RemoteActionOutcome.NOT_FOUND,
            authorization_id=authorization_id,
            error_detail=f"Receipt not found: {authorization_id}",
        )

    if not receipt.verify_integrity():
        return RemoteActionResult(
            outcome=RemoteActionOutcome.INTEGRITY_TAMPERED,
            authorization_id=receipt.authorization_id,
            error_detail="Receipt integrity check failed",
        )

    # Expiry
    try:
        expires = datetime.fromisoformat(receipt.expires_at)
        if datetime.now(UTC) >= expires:
            return RemoteActionResult(
                outcome=RemoteActionOutcome.EXPIRED,
                authorization_id=receipt.authorization_id,
                receipt=receipt,
                error_detail=f"Receipt expired at {receipt.expires_at}",
            )
    except (ValueError, TypeError):
        return RemoteActionResult(
            outcome=RemoteActionOutcome.CORRUPT,
            authorization_id=receipt.authorization_id,
            error_detail="Invalid expires_at format",
        )

    # Consumption
    if receipt.one_time and receipt.consumed:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.ALREADY_CONSUMED,
            authorization_id=receipt.authorization_id,
            receipt=receipt,
            error_detail="One-time receipt already consumed",
        )
    if not receipt.one_time and receipt.use_count >= receipt.max_uses:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.ALREADY_CONSUMED,
            authorization_id=receipt.authorization_id,
            receipt=receipt,
            error_detail=f"Receipt exhausted ({receipt.use_count}/{receipt.max_uses})",
        )

    # Action match
    if expected_action_class and receipt.action_class != expected_action_class:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.ACTION_MISMATCH,
            authorization_id=receipt.authorization_id,
            receipt=receipt,
            error_detail=(
                f"Action mismatch: receipt for '{receipt.action_class}', "
                f"expected '{expected_action_class}'"
            ),
        )

    # Provider match
    if expected_provider and receipt.provider != expected_provider:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.PROVIDER_MISMATCH,
            authorization_id=receipt.authorization_id,
            receipt=receipt,
            error_detail=(
                f"Provider mismatch: receipt for '{receipt.provider}', "
                f"expected '{expected_provider}'"
            ),
        )

    # Target match
    if expected_target and receipt.target_identity != expected_target:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.TARGET_MISMATCH,
            authorization_id=receipt.authorization_id,
            receipt=receipt,
            error_detail=(
                f"Target mismatch: receipt for '{receipt.target_identity}', "
                f"expected '{expected_target}'"
            ),
        )

    # Request digest match — critical: must bind to exact request
    if expected_request_digest and receipt.request_digest != expected_request_digest:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.REQUEST_DIGEST_MISMATCH,
            authorization_id=receipt.authorization_id,
            receipt=receipt,
            error_detail=(
                f"Request digest mismatch: receipt bound to "
                f"{receipt.request_digest[:16]}..., "
                f"expected {expected_request_digest[:16]}..."
            ),
        )

    # Freshness
    if receipt.action_class in FRESHNESS_REQUIRED_ACTIONS:
        if current_prior_evidence_digest is None:
            return RemoteActionResult(
                outcome=RemoteActionOutcome.MISSING_FRESHNESS,
                authorization_id=receipt.authorization_id,
                receipt=receipt,
                error_detail=(
                    f"Action {receipt.action_class} requires fresh prior evidence"
                ),
            )
        if receipt.prior_evidence_digest != current_prior_evidence_digest:
            return RemoteActionResult(
                outcome=RemoteActionOutcome.STALE_EVIDENCE,
                authorization_id=receipt.authorization_id,
                receipt=receipt,
                error_detail=(
                    f"Stale evidence: receipt expected "
                    f"{receipt.prior_evidence_digest[:16]}..., "
                    f"current is {current_prior_evidence_digest[:16]}..."
                ),
            )

    # Sentinel exclusion
    sentinel_issue = _check_sentinels(json.loads(receipt.model_dump_json()))
    if sentinel_issue is not None:
        return RemoteActionResult(
            outcome=RemoteActionOutcome.SENTINEL_EXCLUDED,
            authorization_id=receipt.authorization_id,
            error_detail="Receipt contains excluded confidential sentinel fields",
        )

    return RemoteActionResult(
        outcome=RemoteActionOutcome.VALID,
        authorization_id=receipt.authorization_id,
        receipt=receipt,
    )


# ═══════════════════════════════════════════════════════════════════════
# ── Consume authorization ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════


def consume_remote_action_authorization(
    authorization_id: str,
    *,
    expected_action_class: str | None = None,
    expected_provider: str | None = None,
    expected_target: str | None = None,
    expected_request_digest: str | None = None,
    current_prior_evidence_digest: str | None = None,
) -> RemoteActionResult:
    """Validate and atomically consume a remote action authorization.

    First validates all bindings, then marks as consumed under lock.
    Re-verifies after persist to prevent races.
    """
    valid = validate_remote_action_authorization(
        authorization_id,
        expected_action_class=expected_action_class,
        expected_provider=expected_provider,
        expected_target=expected_target,
        expected_request_digest=expected_request_digest,
        current_prior_evidence_digest=current_prior_evidence_digest,
    )
    if not valid.is_authorized:
        return valid

    receipt = valid.receipt
    assert receipt is not None

    if not _rea_acquire_lock(receipt.authorization_id):
        return RemoteActionResult(
            outcome=RemoteActionOutcome.ALREADY_CONSUMED,
            authorization_id=receipt.authorization_id,
            error_detail="Could not acquire lock — concurrent consumption likely",
        )

    try:
        # Re-load and re-validate under lock to prevent race
        reloaded = _rea_load_receipt(receipt.authorization_id)
        if reloaded is None:
            return RemoteActionResult(
                outcome=RemoteActionOutcome.CORRUPT,
                authorization_id=receipt.authorization_id,
                error_detail="Receipt disappeared under lock",
            )
        if reloaded.one_time and reloaded.consumed:
            return RemoteActionResult(
                outcome=RemoteActionOutcome.ALREADY_CONSUMED,
                authorization_id=receipt.authorization_id,
                receipt=reloaded,
                error_detail="Receipt consumed by concurrent operation",
            )

        if reloaded.one_time:
            reloaded.consumed = True
        else:
            reloaded.use_count += 1
        reloaded.seal()

        path = _rea_persist_receipt(reloaded)
        if path is None:
            return RemoteActionResult(
                outcome=RemoteActionOutcome.CORRUPT,
                authorization_id=receipt.authorization_id,
                error_detail="Failed to persist consumed receipt",
            )

        # Re-verify consumption
        final = _rea_load_receipt(receipt.authorization_id)
        if final is None or not final.verify_integrity():
            return RemoteActionResult(
                outcome=RemoteActionOutcome.CORRUPT,
                authorization_id=receipt.authorization_id,
                error_detail="Post-consume verification failed",
            )
        if reloaded.one_time and not final.consumed:
            return RemoteActionResult(
                outcome=RemoteActionOutcome.CORRUPT,
                authorization_id=receipt.authorization_id,
                error_detail="Consume flag not persisted",
            )

        return RemoteActionResult(
            outcome=RemoteActionOutcome.CONSUMED,
            authorization_id=receipt.authorization_id,
            receipt=final,
        )
    finally:
        _rea_release_lock(receipt.authorization_id)


__all__ = [
    "FRESHNESS_REQUIRED_ACTIONS",
    "NO_PRIOR_EVIDENCE_ACTIONS",
    "REA_SCHEMA_VERSION",
    "SUPPORTED_ACTION_CLASSES",
    "RemoteActionAuthorizationReceipt",
    "RemoteActionClass",
    "RemoteActionOutcome",
    "RemoteActionResult",
    "RemoteMutationRisk",
    "consume_remote_action_authorization",
    "issue_remote_action_authorization",
    "validate_remote_action_authorization",
]
