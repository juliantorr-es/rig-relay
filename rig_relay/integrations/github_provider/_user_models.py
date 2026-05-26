"""Bounded GitHub user profile models — content-light, hash-heavy.

Models for GitHub authenticated-user profile inspection and change proposals.
Never contain raw tokens, private keys, or raw API payloads.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _GitHubUserEvidenceModel(BaseModel):
    """Mixin for bounded user evidence with redaction and integrity."""

    def _evidence_digest(self) -> str:
        raw = self.model_dump_json()
        return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def redacted_projection(self) -> dict[str, Any]:
        raise NotImplementedError


# ── User Profile ───────────────────────────────────────────────────────


class GitHubUserProfile(_GitHubUserEvidenceModel):
    """Bounded GitHub authenticated-user profile (read-side).

    Fields map to GitHub's GET /user response. Content-light default:
    raw email is never stored; only email_hash or availability flag.
    """

    model_config = ConfigDict(extra="forbid")

    login: str
    user_id: int
    avatar_url_hash: str | None = None  # hashed, not raw URL
    name: str | None = None
    company: str | None = None
    blog_url: str | None = None
    location: str | None = None
    email_available: bool = False
    email_hash: str | None = None
    bio: str | None = None
    twitter_username: str | None = None
    public_repos: int = 0
    public_gists: int = 0
    followers: int = 0
    following: int = 0
    hireable: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "login": self.login,
            "user_id": self.user_id,
            "name_available": self.name is not None,
            "company_available": self.company is not None,
            "blog_available": self.blog_url is not None,
            "location_available": self.location is not None,
            "email_available": self.email_available,
            "bio_available": self.bio is not None,
            "public_repos": self.public_repos,
            "followers": self.followers,
            "following": self.following,
            "hireable": self.hireable,
            "evidence_digest": self._evidence_digest(),
        }


# ── Profile Change Proposal ────────────────────────────────────────────


_ALLOWED_PROFILE_FIELDS: frozenset[str] = frozenset({
    "name",
    "email",
    "blog",
    "twitter_username",
    "company",
    "location",
    "hireable",
    "bio",
})


class GitHubProfileChangeProposal(_GitHubUserEvidenceModel):
    """A proposed, authorization-gated user profile update.

    Contains a bounded before/after diff of allowed fields.
    Never stores tokens or raw API payloads.
    """

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    login: str
    status: str = "proposed"  # proposed, authorized, refused, stale, executed, verified

    # Before/after diffs — only fields that changed
    changed_fields: list[str] = Field(default_factory=list)
    before_snapshot: dict[str, str | None] = Field(default_factory=dict)
    after_values: dict[str, str | None] = Field(default_factory=dict)

    # Authorization
    required_permissions: list[str] = Field(default_factory=list)
    user_token_required: bool = True
    authorization_status: str = "pending"  # pending, granted, refused, unavailable
    authorization_refusal_reason: str | None = None

    # Post-mutation
    executed: bool = False
    execution_refusal_reason: str | None = None
    post_verification_digest: str | None = None
    stale: bool = False
    suggested_next_action: str | None = None

    def is_field_allowed(self, field_name: str) -> bool:
        return field_name in _ALLOWED_PROFILE_FIELDS

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "login": self.login,
            "status": self.status,
            "changed_fields_count": len(self.changed_fields),
            "required_permissions": self.required_permissions,
            "user_token_required": self.user_token_required,
            "authorization_status": self.authorization_status,
            "executed": self.executed,
            "stale": self.stale,
            "suggested_next_action": self.suggested_next_action,
            "evidence_digest": self._evidence_digest(),
        }


# ── Profile Change Result ──────────────────────────────────────────────


class GitHubProfileChangeResult(_GitHubUserEvidenceModel):
    """Result of a profile change execution attempt."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    status: str  # executed, refused, stale_refused, authorization_pending, error
    changed_fields: list[str] = Field(default_factory=list)
    post_profile_digest: str | None = None
    verification_match: bool | None = None
    error_kind: str | None = None
    suggested_next_action: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "status": self.status,
            "changed_fields_count": len(self.changed_fields),
            "verification_match": self.verification_match,
            "error_kind": self.error_kind,
            "suggested_next_action": self.suggested_next_action,
            "evidence_digest": self._evidence_digest(),
        }


# ── Error Vocabulary ───────────────────────────────────────────────────


class GitHubUserErrorKind:
    TOKEN_UNAVAILABLE = "github.user.token_unavailable"
    PERMISSION_MISSING = "github.user.permission_missing"
    PROFILE_READ_FAILED = "github.user.profile_read_failed"
    PROFILE_UPDATE_FAILED = "github.user.profile_update_failed"
    INVALID_FIELD = "github.user.invalid_field"
    STALE_PROPOSAL = "github.user.stale_proposal"
    AUTHORIZATION_PENDING = "github.user.authorization_pending"
    VERIFICATION_FAILED = "github.user.verification_failed"
    RATE_LIMITED = "github.user.rate_limited"
    API_UNAVAILABLE = "github.user.api_unavailable"
    UNKNOWN = "github.user.unknown_error"


__all__ = [
    "GitHubProfileChangeProposal",
    "GitHubProfileChangeResult",
    "GitHubUserErrorKind",
    "GitHubUserProfile",
]
