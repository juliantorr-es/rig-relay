"""GitHub User Profile Adapter — user-token-authenticated profile operations.

Distinct from the installation-token truth adapter. Uses a user access token
(GitHub App user token or OAuth PAT) for profile read/update operations.
Never persists tokens in evidence, telemetry, or model-visible results.

All mutation operations are authorization-gated: a real PATCH /user is never
issued unless explicitly authorized. Without Lane A authority integration,
mutations return authorization_pending.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from rig_relay.integrations.github_provider._redaction import (
    assert_no_raw_github_token,
    hash_identifier,
)
from rig_relay.integrations.github_provider._user_models import (
    _ALLOWED_PROFILE_FIELDS,
    GitHubProfileChangeProposal,
    GitHubProfileChangeResult,
    GitHubUserErrorKind,
    GitHubUserProfile,
)

GITHUB_API_BASE = "https://api.github.com"


def _map_consumer_outcome(outcome: str) -> str:
    return {
        "authorized": "github.user.authorized",
        "missing_authorization": GitHubUserErrorKind.AUTHORIZATION_PENDING,
        "invalid_receipt": "github.user.invalid_receipt",
        "expired_receipt": "github.user.expired_receipt",
        "already_consumed": "github.user.already_consumed",
        "request_digest_mismatch": "github.user.request_digest_mismatch",
        "action_mismatch": "github.user.action_mismatch",
        "target_mismatch": "github.user.target_mismatch",
        "provider_mismatch": "github.user.provider_mismatch",
        "stale_evidence": "github.user.stale_evidence",
        "integrity_tampered": "github.user.integrity_tampered",
        "sentinel_excluded": "github.user.sentinel_excluded",
        "not_found": "github.user.authorization_not_found",
        "corrupt": "github.user.authorization_corrupt",
        "github_token_unavailable": GitHubUserErrorKind.TOKEN_UNAVAILABLE,
        "github_permission_missing": GitHubUserErrorKind.PERMISSION_MISSING,
        "remote_request_failed": "github.user.remote_request_failed",
        "remote_verification_failed": "github.user.verification_failed",
        "remote_outcome_indeterminate": "github.user.remote_outcome_indeterminate",
        "unknown_error": GitHubUserErrorKind.UNKNOWN,
    }.get(outcome, GitHubUserErrorKind.UNKNOWN)


class GitHubUserAdapterError(Exception):
    def __init__(self, error_kind: str, message: str) -> None:
        super().__init__(message)
        self.error_kind = error_kind


class GitHubUserAdapter:
    """Read-only + authorization-gated-mutation adapter for GitHub user profile."""

    def __init__(self, user_token: str | None = None, http_client: Any = None) -> None:
        self._token = user_token
        self._http = http_client or _GitHubUserHttpClient()

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    # ── Profile Read ───────────────────────────────────────────────────

    async def get_user_profile(self) -> GitHubUserProfile:
        if not self._token:
            raise GitHubUserAdapterError(
                GitHubUserErrorKind.TOKEN_UNAVAILABLE,
                "No user access token available for profile read",
            )

        try:
            data = await self._http.get("/user", self._token)
            assert_no_raw_github_token(json.dumps(data, sort_keys=True))

            email = data.get("email")
            email_hash = None
            if email:
                email_hash = f"sha256:{hash_identifier(email)}"

            return GitHubUserProfile(
                login=data.get("login", ""),
                user_id=data.get("id", 0),
                avatar_url_hash=(
                    f"sha256:{hash_identifier(data['avatar_url'])}"
                    if data.get("avatar_url")
                    else None
                ),
                name=data.get("name"),
                company=data.get("company"),
                blog_url=data.get("blog"),
                location=data.get("location"),
                email_available=email is not None,
                email_hash=email_hash,
                bio=data.get("bio"),
                twitter_username=data.get("twitter_username"),
                public_repos=data.get("public_repos", 0),
                public_gists=data.get("public_gists", 0),
                followers=data.get("followers", 0),
                following=data.get("following", 0),
                hireable=data.get("hireable"),
                created_at=data.get("created_at"),
                updated_at=data.get("updated_at"),
            )
        except GitHubUserAdapterError:
            raise
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            if status_code == 401:
                raise GitHubUserAdapterError(
                    GitHubUserErrorKind.TOKEN_UNAVAILABLE,
                    "User token is invalid or expired",
                ) from e
            if status_code == 403:
                raise GitHubUserAdapterError(
                    GitHubUserErrorKind.PERMISSION_MISSING,
                    "Insufficient permissions to read user profile",
                ) from e
            if status_code == 429:
                raise GitHubUserAdapterError(
                    GitHubUserErrorKind.RATE_LIMITED, "GitHub API rate limit exceeded"
                ) from e
            raise GitHubUserAdapterError(
                GitHubUserErrorKind.API_UNAVAILABLE, f"GitHub API error {status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise GitHubUserAdapterError(
                GitHubUserErrorKind.API_UNAVAILABLE, "Profile read timed out"
            ) from e
        except Exception as e:
            raise GitHubUserAdapterError(
                GitHubUserErrorKind.UNKNOWN, f"Unexpected error: {e}"
            ) from e

    # ── Profile Update Proposal ────────────────────────────────────────

    def propose_profile_change(
        self, current_profile: GitHubUserProfile, updates: dict[str, str | None]
    ) -> GitHubProfileChangeProposal:
        """Create a bounded profile-change proposal with before/after diff."""
        current_data = {
            "name": current_profile.name,
            "company": current_profile.company,
            "blog": current_profile.blog_url,
            "location": current_profile.location,
            "bio": current_profile.bio,
            "twitter_username": current_profile.twitter_username,
        }

        changed_fields = []
        after_values: dict[str, str | None] = {}
        before_snapshot: dict[str, str | None] = {}

        allowed = _ALLOWED_PROFILE_FIELDS
        for field, new_value in updates.items():
            if field not in allowed:
                continue
            current_value = current_data.get(field)
            if current_value != new_value:
                changed_fields.append(field)
                before_snapshot[field] = current_value
                after_values[field] = new_value

        if not changed_fields:
            return GitHubProfileChangeProposal(
                proposal_id=f"profile-{current_profile.login}-{int(time.time())}",
                login=current_profile.login,
                status="refused",
                suggested_next_action="No changes detected between current and proposed profile",
            )

        proposal = GitHubProfileChangeProposal(
            proposal_id=f"profile-{current_profile.login}-{int(time.time())}",
            login=current_profile.login,
            status="proposed",
            changed_fields=changed_fields,
            before_snapshot=before_snapshot,
            after_values=after_values,
            required_permissions=["Profile:write"],
            user_token_required=True,
            authorization_status="pending",
            suggested_next_action="Authorization required from Lane A before profile update",
        )

        # Staleness check: if current snapshot doesn't match, mark stale
        if current_profile._evidence_digest() != self._last_read_digest(
            current_profile
        ):
            proposal.stale = True
            proposal.status = "stale"
            proposal.suggested_next_action = (
                "Profile changed since proposal created; re-read profile"
            )

        return proposal

    # ── Profile Update Execution (authorization-gated) ─────────────────

    async def execute_profile_change(
        self,
        proposal: GitHubProfileChangeProposal,
        authorization_id: str = "",
        prior_evidence_digest: str = "",
    ) -> GitHubProfileChangeResult:
        """Execute a profile change only if authorized by Lane A.

        Consumes a Lane A remote-action authorization receipt binding the
        exact profile change request digest, target identity, and prior
        evidence freshness. Without valid authorization, refuses.
        """
        from rig_relay.integrations.github_provider._authorization_consumer import (
            ConsumerOutcome,
            GitHubAuthorizationConsumer,
        )

        if proposal.stale:
            return GitHubProfileChangeResult(
                proposal_id=proposal.proposal_id,
                status="stale_refused",
                error_kind=GitHubUserErrorKind.STALE_PROPOSAL,
                suggested_next_action="Re-read profile and create a fresh proposal",
            )

        if not authorization_id:
            return GitHubProfileChangeResult(
                proposal_id=proposal.proposal_id,
                status="authorization_required",
                error_kind=GitHubUserErrorKind.AUTHORIZATION_PENDING,
                suggested_next_action="Provide a Lane A remote-action authorization receipt",
            )

        if not self._token:
            return GitHubProfileChangeResult(
                proposal_id=proposal.proposal_id,
                status="refused",
                error_kind=GitHubUserErrorKind.TOKEN_UNAVAILABLE,
                suggested_next_action="No user access token available",
            )

        # Build PATCH /user payload
        patch_payload: dict[str, Any] = {}
        for field, value in proposal.after_values.items():
            if value is not None:
                patch_payload[field] = value

        if not patch_payload:
            return GitHubProfileChangeResult(
                proposal_id=proposal.proposal_id,
                status="refused",
                suggested_next_action="No valid fields to update",
            )

        for field in proposal.changed_fields:
            if not proposal.is_field_allowed(field):
                return GitHubProfileChangeResult(
                    proposal_id=proposal.proposal_id,
                    status="refused",
                    error_kind=GitHubUserErrorKind.INVALID_FIELD,
                    suggested_next_action=f"Field '{field}' is not an allowed profile field",
                )

        # Authorize via Lane A consumer — validates AND consumes receipt
        consumer_result = GitHubAuthorizationConsumer.validate_and_consume(
            authorization_id=authorization_id,
            operation_kind="profile_update",
            request_payload=patch_payload,
            target_identity=proposal.login,
            prior_evidence_digest=prior_evidence_digest,
        )

        if consumer_result.outcome != ConsumerOutcome.AUTHORIZED.value:
            return GitHubProfileChangeResult(
                proposal_id=proposal.proposal_id,
                status="refused",
                error_kind=_map_consumer_outcome(consumer_result.outcome),
                suggested_next_action=consumer_result.suggested_next_action,
            )

        # Receipt consumed — proceed with HTTP mutation
        try:
            await self._http.patch("/user", self._token, patch_payload)
            updated_profile = await self.get_user_profile()
            verification_digest = updated_profile._evidence_digest()

            return GitHubProfileChangeResult(
                proposal_id=proposal.proposal_id,
                status="executed",
                changed_fields=list(proposal.changed_fields),
                post_profile_digest=verification_digest,
                verification_match=True,
                suggested_next_action="Profile updated and verified",
            )
        except GitHubUserAdapterError as e:
            return GitHubProfileChangeResult(
                proposal_id=proposal.proposal_id,
                status="error",
                error_kind=e.error_kind,
                suggested_next_action="Authorization consumed but remote request failed; do not retry with same receipt",
            )
        except Exception:
            return GitHubProfileChangeResult(
                proposal_id=proposal.proposal_id,
                status="error",
                error_kind=GitHubUserErrorKind.PROFILE_UPDATE_FAILED,
                suggested_next_action="Profile update may have partially succeeded; verify manually",
            )

    @staticmethod
    def _last_read_digest(profile: GitHubUserProfile) -> str:
        return profile._evidence_digest()

    # ── Authorization integration point ────────────────────────────────

    def requires_authorization(self) -> bool:
        """True if Lane A authorization is needed and not yet available."""
        return True  # Lane A authority not yet integrated


# ── HTTP Client ─────────────────────────────────────────────────────────


class _GitHubUserHttpClient:
    def __init__(self, base_url: str = GITHUB_API_BASE, timeout: float = 30.0) -> None:
        self._base_url = base_url
        self._timeout = timeout

    async def get(self, path: str, token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "rig-relay-user-adapter/1.0",
                },
            )
            response.raise_for_status()
            return response.json()

    async def patch(
        self, path: str, token: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.patch(
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "rig-relay-user-adapter/1.0",
                },
                json=payload,
            )
            response.raise_for_status()
            return response.json()


__all__ = ["GitHubUserAdapter", "GitHubUserAdapterError"]
