"""GitHub Repository Truth Adapter v1 — read-only, bounded, GitHub-App-authenticated.

Establishes GitHub as a verifiable remote source of truth for repository state.
Uses GitHub App installation tokens (JWT-signed, short-lived, permission-scoped).
Never persists tokens in evidence, telemetry, or model-visible results.

Wraps GitHubAppTokenManager for auth and httpx for HTTP.
Returns typed _truth_models, not raw API dicts.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from rig_relay.integrations.github_provider._redaction import (
    assert_no_raw_github_token,
    hash_identifier,
)
from rig_relay.integrations.github_provider._truth_models import (
    GitHubCIStatusEvidence,
    GitHubCommitPresence,
    GitHubCommitRelationship,
    GitHubCompareResult,
    GitHubInstallationAccess,
    GitHubPublicationVerification,
    GitHubRemoteRefObservation,
    GitHubRepositoryIdentity,
    GitHubTokenStatus,
    GitHubTruthErrorKind,
    GitHubVerificationStatus,
)

GITHUB_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = 30.0


class GitHubTruthAdapterError(Exception):
    """Typed error from the truth adapter."""

    def __init__(self, error_kind: str, message: str) -> None:
        super().__init__(message)
        self.error_kind = error_kind


# ── HTTP Client (extracted for testability) ────────────────────────────


class _GitHubHttpClient:
    """Isolated HTTP client for GitHub API calls."""

    def __init__(
        self, base_url: str = GITHUB_API_BASE, timeout: float = _DEFAULT_TIMEOUT
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout

    async def get(
        self, path: str, token: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "rig-relay-truth-adapter/1.0",
                },
                params=params,
            )
            response.raise_for_status()
            return response.json()

    async def get_paginated(
        self,
        path: str,
        token: str,
        params: dict[str, Any] | None = None,
        max_pages: int = 5,
    ) -> list[dict[str, Any]]:
        """Collect paginated results up to max_pages."""
        all_items: list[dict[str, Any]] = []
        page_params = dict(params or {})
        page_params.setdefault("per_page", 50)

        for _ in range(max_pages):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}{path}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "rig-relay-truth-adapter/1.0",
                    },
                    params=page_params,
                )
                response.raise_for_status()
                data = response.json()

                if isinstance(data, list):
                    all_items.extend(data)
                elif isinstance(data, dict):
                    items = data.get(
                        "items", data.get("workflow_runs", data.get("check_runs", []))
                    )
                    all_items.extend(items)
                    if len(all_items) >= data.get("total_count", 0):
                        break
                else:
                    break

                # Check Link header for next page
                link_header = response.headers.get("Link", "")
                if 'rel="next"' not in link_header:
                    break

                # Extract page number
                page_params["page"] = page_params.get("page", 1) + 1

        return all_items


# ── Truth Adapter ──────────────────────────────────────────────────────


class GitHubTruthAdapter:
    """Read-only GitHub truth adapter using App installation authentication."""

    def __init__(
        self,
        token_manager: Any,  # GitHubAppTokenManager
        http_client: _GitHubHttpClient | None = None,
    ) -> None:
        self._token_manager = token_manager
        self._http = http_client or _GitHubHttpClient()

    def _get_token(self) -> str:
        """Acquire an installation token or raise typed error."""
        if self._token_manager is None:
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.INSTALLATION_MISSING,
                "No GitHub App token manager configured",
            )
        token = self._token_manager.get_token()
        if token is None:
            config = self._token_manager.config_summary()
            token_cached = config.get("token_cached", False)
            if token_cached:
                raise GitHubTruthAdapterError(
                    GitHubTruthErrorKind.TOKEN_EXPIRED,
                    "GitHub App installation token has expired",
                )
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.TOKEN_ACQUISITION_FAILED,
                "Failed to acquire GitHub App installation token",
            )
        return token

    def _repository_hash(self, owner: str, repo: str) -> str:
        return hash_identifier(f"{owner}/{repo}")

    # ── Installation Access ────────────────────────────────────────────

    def observe_installation_access(self) -> GitHubInstallationAccess:
        """Return bounded installation identity and permission status."""
        try:
            _ = self._get_token()  # check token availability only
            token_status = GitHubTokenStatus.AVAILABLE
        except GitHubTruthAdapterError as e:
            return GitHubInstallationAccess(
                installation_hash="",
                app_id=0,
                installation_id_hash="",
                token_status=(
                    GitHubTokenStatus.EXPIRED
                    if e.error_kind == GitHubTruthErrorKind.TOKEN_EXPIRED
                    else GitHubTokenStatus.UNAVAILABLE
                ),
                error_kind=e.error_kind,
                errors=[str(e)],
            )

        config = self._token_manager.config_summary()

        result = GitHubInstallationAccess(
            installation_hash=hash_identifier(str(config.get("installation_id", ""))),
            app_id=int(config.get("app_id", 0)),
            installation_id_hash=hash_identifier(
                str(config.get("installation_id", ""))
            ),
            token_status=token_status,
            token_expires_in_seconds=config.get("token_expires_in_seconds"),
            account_hash=None,
            error_kind=None,
        )

        # Token expiry
        if config.get("token_expires_in_seconds", 0) <= 0:
            result.token_status = GitHubTokenStatus.EXPIRED
            result.error_kind = GitHubTruthErrorKind.TOKEN_EXPIRED
            result.errors.append("Token has expired")

        return result

    # ── Repository Metadata ────────────────────────────────────────────

    async def observe_repository(
        self, owner: str, repo: str
    ) -> GitHubRepositoryIdentity:
        repo_hash = self._repository_hash(owner, repo)
        try:
            token = self._get_token()
            data = await self._http.get(f"/repos/{owner}/{repo}", token)
            assert_no_raw_github_token(json.dumps(data, sort_keys=True))

            # Sanitize description: never store raw text that could contain secrets
            desc = data.get("description")
            safe_desc: str | None = None
            if isinstance(desc, str) and desc.strip():
                try:
                    assert_no_raw_github_token(desc)
                    safe_desc = desc
                except ValueError:
                    safe_desc = f"sha256:{hash_identifier(desc)}"

            return GitHubRepositoryIdentity(
                owner=owner,
                repo=repo,
                repository_hash=repo_hash,
                visibility=data.get("visibility"),
                default_branch=data.get("default_branch", "main"),
                description=safe_desc,
            )
        except GitHubTruthAdapterError:
            raise
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            if status_code == 404:
                raise GitHubTruthAdapterError(
                    GitHubTruthErrorKind.REPOSITORY_INACCESSIBLE,
                    f"Repository {owner}/{repo} not found or inaccessible",
                ) from e
            if status_code == 403:
                raise GitHubTruthAdapterError(
                    GitHubTruthErrorKind.PERMISSION_MISSING,
                    f"Insufficient permissions for {owner}/{repo}",
                ) from e
            if status_code == 401:
                raise GitHubTruthAdapterError(
                    GitHubTruthErrorKind.TOKEN_EXPIRED,
                    "Installation token is invalid or expired",
                ) from e
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.API_UNAVAILABLE,
                f"GitHub API error {status_code}: {e}",
            ) from e
        except httpx.TimeoutException as e:
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.TIMEOUT, f"Timed out accessing {owner}/{repo}"
            ) from e
        except Exception as e:
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.UNKNOWN, f"Unexpected error: {e}"
            ) from e

    # ── Remote Ref Observation ─────────────────────────────────────────

    async def observe_ref(
        self, owner: str, repo: str, ref: str = "heads/main"
    ) -> GitHubRemoteRefObservation:
        repo_hash = self._repository_hash(owner, repo)
        try:
            token = self._get_token()
            # GitHub requires refs/ prefix for git refs
            ref_path = (
                ref
                if ref.startswith("heads/") or ref.startswith("tags/")
                else f"heads/{ref}"
            )
            data = await self._http.get(
                f"/repos/{owner}/{repo}/git/ref/{ref_path}", token
            )
            sha = data.get("object", {}).get("sha")
            return GitHubRemoteRefObservation(
                repository_hash=repo_hash,
                ref=f"refs/{ref_path}",
                remote_head_sha=sha,
                resolved=sha is not None,
            )
        except GitHubTruthAdapterError:
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise GitHubTruthAdapterError(
                    GitHubTruthErrorKind.REF_MISSING,
                    f"Ref {ref} not found on {owner}/{repo}",
                ) from e
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.API_UNAVAILABLE, f"GitHub API error: {e}"
            ) from e
        except Exception as e:
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.UNKNOWN, f"Unexpected error: {e}"
            ) from e

    # ── Commit Presence ────────────────────────────────────────────────

    async def check_commit_presence(
        self, owner: str, repo: str, sha: str, ref: str = "main"
    ) -> GitHubCommitPresence:
        repo_hash = self._repository_hash(owner, repo)
        try:
            token = self._get_token()

            # Check if commit exists
            try:
                await self._http.get(f"/repos/{owner}/{repo}/commits/{sha}", token)
                commit_exists = True
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    commit_exists = False
                else:
                    raise

            if not commit_exists:
                # Try to get remote head to see where we are
                try:
                    ref_obs = await self.observe_ref(owner, repo, ref)
                    remote_head = ref_obs.remote_head_sha
                except Exception:
                    remote_head = None

                return GitHubCommitPresence(
                    repository_hash=repo_hash,
                    expected_sha=sha,
                    ref=ref,
                    present=False,
                    remote_head_sha=remote_head,
                    relationship=GitHubCommitRelationship.ABSENT,
                    error_kind=None,
                )

            # Commit exists — compare to see relationship
            return await self._determine_commit_relationship(
                token, owner, repo, repo_hash, sha, ref
            )

        except GitHubTruthAdapterError:
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code in {403, 401}:
                raise GitHubTruthAdapterError(
                    GitHubTruthErrorKind.PERMISSION_MISSING,
                    f"Cannot check commit presence: {e}",
                ) from e
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.API_UNAVAILABLE, f"GitHub API error: {e}"
            ) from e
        except Exception as e:
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.UNKNOWN, f"Unexpected error: {e}"
            ) from e

    async def _determine_commit_relationship(
        self, token: str, owner: str, repo: str, repo_hash: str, sha: str, ref: str
    ) -> GitHubCommitPresence:
        """Use compare endpoint to determine exact relationship."""
        try:
            ref_obs = await self.observe_ref(owner, repo, ref)
            remote_head = ref_obs.remote_head_sha
        except Exception:
            remote_head = None

        if remote_head is None:
            return GitHubCommitPresence(
                repository_hash=repo_hash,
                expected_sha=sha,
                ref=ref,
                present=True,
                remote_head_sha=None,
                relationship=GitHubCommitRelationship.EXACT,
                error_kind=GitHubTruthErrorKind.REF_MISSING,
            )

        if sha == remote_head:
            return GitHubCommitPresence(
                repository_hash=repo_hash,
                expected_sha=sha,
                ref=ref,
                present=True,
                remote_head_sha=remote_head,
                relationship=GitHubCommitRelationship.EXACT,
            )

        # Use compare to determine relationship
        try:
            compare = await self._http.get(
                f"/repos/{owner}/{repo}/compare/{sha}...{remote_head}", token
            )
            status = compare.get("status", "unknown")
            ahead = compare.get("ahead_by", 0)
            behind = compare.get("behind_by", 0)
            total = compare.get("total_commits", 0)

            # GitHub compare: base...head
            # "ahead" = head (remote) is ahead of base (expected) -> expected is ancestor
            # "behind" = head (remote) is behind base (expected) -> expected is descendant
            if status == "identical":
                rel = GitHubCommitRelationship.EXACT
            elif status == "ahead":
                rel = GitHubCommitRelationship.ANCESTOR
            elif status == "behind":
                rel = GitHubCommitRelationship.DESCENDANT
            elif status == "diverged":
                rel = GitHubCommitRelationship.DIVERGENT
            else:
                rel = GitHubCommitRelationship.EXACT

            return GitHubCommitPresence(
                repository_hash=repo_hash,
                expected_sha=sha,
                ref=ref,
                present=True,
                remote_head_sha=remote_head,
                relationship=rel,
                ahead_by=ahead,
                behind_by=behind,
                total_commits_diff=total,
            )
        except Exception:
            # Fallback: commit exists but can't determine relationship
            return GitHubCommitPresence(
                repository_hash=repo_hash,
                expected_sha=sha,
                ref=ref,
                present=True,
                remote_head_sha=remote_head,
                relationship=GitHubCommitRelationship.DIVERGENT,
                error_kind=GitHubTruthErrorKind.REMOTE_DIVERGENCE,
            )

    # ── Compare ─────────────────────────────────────────────────────────

    async def compare_commits(
        self, owner: str, repo: str, base_sha: str, head_sha: str
    ) -> GitHubCompareResult:
        repo_hash = self._repository_hash(owner, repo)
        try:
            token = self._get_token()
            data = await self._http.get(
                f"/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}", token
            )
            assert_no_raw_github_token(json.dumps(data, sort_keys=True))

            status = data.get("status", "unknown")
            files = data.get("files", [])
            files_changed = len(files)

            # Classify change kinds without exposing paths
            change_kinds: dict[str, int] = {}
            for f in files:
                kind = f.get("status", "modified")
                change_kinds[kind] = change_kinds.get(kind, 0) + 1

            additions = sum(f.get("additions", 0) for f in files)
            deletions = sum(f.get("deletions", 0) for f in files)

            return GitHubCompareResult(
                repository_hash=repo_hash,
                base_sha=base_sha,
                head_sha=head_sha,
                status=status,
                ahead_by=data.get("ahead_by", 0),
                behind_by=data.get("behind_by", 0),
                total_commits=data.get("total_commits", 0),
                files_changed_count=files_changed,
                additions=additions,
                deletions=deletions,
                change_kind_counts=change_kinds,
                truncated=files_changed > 300,  # GitHub default max
            )
        except GitHubTruthAdapterError:
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise GitHubTruthAdapterError(
                    GitHubTruthErrorKind.COMMIT_ABSENT,
                    f"One or both commits not found: {base_sha[:7]}...{head_sha[:7]}",
                ) from e
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.API_UNAVAILABLE, f"GitHub API error: {e}"
            ) from e
        except Exception as e:
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.UNKNOWN, f"Unexpected error: {e}"
            ) from e

    # ── CI Status ───────────────────────────────────────────────────────

    async def observe_ci_status(
        self, owner: str, repo: str, sha: str
    ) -> GitHubCIStatusEvidence:
        repo_hash = self._repository_hash(owner, repo)
        try:
            token = self._get_token()

            # Combined status (simple)
            status_data = await self._http.get(
                f"/repos/{owner}/{repo}/commits/{sha}/status", token
            )

            overall_state = status_data.get("state", "no_status")
            statuses = status_data.get("statuses", [])

            passed = sum(1 for s in statuses if s.get("state") == "success")
            failed = sum(1 for s in statuses if s.get("state") == "failure")
            pending = sum(1 for s in statuses if s.get("state") == "pending")
            neutral = sum(1 for s in statuses if s.get("state") == "neutral")

            # Check runs (richer)
            try:
                check_data = await self._http.get(
                    f"/repos/{owner}/{repo}/commits/{sha}/check-runs",
                    token,
                    params={"per_page": 100},
                )
                checks = check_data.get("check_runs", [])
            except Exception:
                checks = []

            skipped = sum(1 for c in checks if c.get("conclusion") == "skipped")
            cancelled = sum(1 for c in checks if c.get("conclusion") == "cancelled")
            check_passed = sum(1 for c in checks if c.get("conclusion") == "success")
            check_failed = sum(
                1 for c in checks if c.get("conclusion") in {"failure", "timed_out"}
            )
            check_pending = sum(
                1 for c in checks if c.get("status") not in {"completed"}
            )

            total_passed = passed + check_passed
            total_failed = failed + check_failed
            total_pending = pending + check_pending

            suggested_action = None
            if total_failed > 0:
                suggested_action = "Inspect failed checks; manual review required"
            elif total_pending > 0:
                suggested_action = "Wait for pending checks to complete"
            elif total_passed > 0 and total_failed == 0:
                suggested_action = "All checks passed"

            # Build workflow run summaries (bounded, no logs)
            workflow_runs: list[dict[str, Any]] = []
            try:
                runs_data = await self._http.get(
                    f"/repos/{owner}/{repo}/actions/runs",
                    token,
                    params={"per_page": 10, "head_sha": sha},
                )
                for run in runs_data.get("workflow_runs", [])[:10]:
                    workflow_runs.append({
                        "run_id": run.get("id"),
                        "name": run.get("name", ""),
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "event": run.get("event"),
                        "branch": run.get("head_branch", ""),
                    })
            except Exception:
                pass

            return GitHubCIStatusEvidence(
                repository_hash=repo_hash,
                commit_sha=sha,
                overall_state=overall_state,
                passed_count=total_passed,
                failed_count=total_failed,
                pending_count=total_pending,
                skipped_count=skipped,
                cancelled_count=cancelled,
                neutral_count=neutral,
                total_count=len(statuses) + len(checks),
                check_names=[c.get("name", "") for c in checks[:50]],
                workflow_runs=workflow_runs,
                truncated=len(checks) >= 100,
                suggested_next_action=suggested_action,
            )
        except GitHubTruthAdapterError:
            raise
        except httpx.HTTPStatusError as e:
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.API_UNAVAILABLE,
                f"GitHub API error fetching CI status: {e}",
            ) from e
        except Exception as e:
            raise GitHubTruthAdapterError(
                GitHubTruthErrorKind.UNKNOWN, f"Unexpected error: {e}"
            ) from e

    # ── Publication Verification ───────────────────────────────────────

    async def verify_publication(
        self, owner: str, repo: str, expected_sha: str, ref: str = "main"
    ) -> GitHubPublicationVerification:
        repo_hash = self._repository_hash(owner, repo)
        try:
            _ = self._get_token()  # check token availability
        except GitHubTruthAdapterError as e:
            return GitHubPublicationVerification(
                repository_hash=repo_hash,
                expected_sha=expected_sha,
                ref=ref,
                verification_status=GitHubVerificationStatus.PERMISSION_UNAVAILABLE,
                error_kind=e.error_kind,
                suggested_next_action="Configure GitHub App installation and permissions",
            )

        # Check remote ref
        try:
            ref_obs = await self.observe_ref(owner, repo, ref)
        except GitHubTruthAdapterError as e:
            return GitHubPublicationVerification(
                repository_hash=repo_hash,
                expected_sha=expected_sha,
                ref=ref,
                verification_status=GitHubVerificationStatus.REMOTE_UNAVAILABLE,
                error_kind=e.error_kind,
                suggested_next_action="Verify repository exists and ref is correct",
            )

        if not ref_obs.resolved or not ref_obs.remote_head_sha:
            return GitHubPublicationVerification(
                repository_hash=repo_hash,
                expected_sha=expected_sha,
                ref=ref,
                verification_status=GitHubVerificationStatus.REMOTE_UNAVAILABLE,
                error_kind=GitHubTruthErrorKind.REF_MISSING,
                suggested_next_action=f"Ref {ref} not found on remote",
            )

        remote_head = ref_obs.remote_head_sha

        # Exact match
        if expected_sha == remote_head:
            # Check CI at exact promoted head
            try:
                ci = await self.observe_ci_status(owner, repo, expected_sha)
                ci_state = ci.overall_state
            except Exception:
                ci = None
                ci_state = "unavailable"

            return GitHubPublicationVerification(
                repository_hash=repo_hash,
                expected_sha=expected_sha,
                ref=ref,
                verification_status=GitHubVerificationStatus.EXACT_PROMOTED,
                remote_head_sha=remote_head,
                accepted_head_present=True,
                follow_on_commits_count=0,
                ci_state=ci_state,
                ci_evidence=ci,
            )

        # Check relationship: is expected_sha an ancestor of remote_head?
        try:
            compare = await self.compare_commits(owner, repo, expected_sha, remote_head)
        except GitHubTruthAdapterError:
            # If compare fails, check if expected commit exists at all
            try:
                token_current = self._get_token()
                await self._http.get(
                    f"/repos/{owner}/{repo}/commits/{expected_sha}", token_current
                )
                # Commit exists but relationship unclear
            except Exception:
                return GitHubPublicationVerification(
                    repository_hash=repo_hash,
                    expected_sha=expected_sha,
                    ref=ref,
                    verification_status=GitHubVerificationStatus.EXPECTED_COMMIT_MISSING,
                    remote_head_sha=remote_head,
                    accepted_head_present=False,
                    suggested_next_action="Expected commit not found on remote; verify the commit was actually pushed",
                )

            return GitHubPublicationVerification(
                repository_hash=repo_hash,
                expected_sha=expected_sha,
                ref=ref,
                verification_status=GitHubVerificationStatus.VERIFICATION_INCOMPLETE,
                remote_head_sha=remote_head,
                accepted_head_present=True,
                error_kind=GitHubTruthErrorKind.REMOTE_DIVERGENCE,
                suggested_next_action="Unable to determine relationship between expected and remote commits",
            )

        if compare.status == "identical":
            # Same commit — identical by compare but sha didn't match (edge case)
            return GitHubPublicationVerification(
                repository_hash=repo_hash,
                expected_sha=expected_sha,
                ref=ref,
                verification_status=GitHubVerificationStatus.EXACT_PROMOTED,
                remote_head_sha=remote_head,
                accepted_head_present=True,
                follow_on_commits_count=0,
            )
        elif compare.status == "ahead":
            # head (remote_head) is ahead of base (expected_sha) — follow-on commits
            try:
                ci = await self.observe_ci_status(owner, repo, remote_head)
                ci_state = ci.overall_state
            except Exception:
                ci = None
                ci_state = "unavailable"

            return GitHubPublicationVerification(
                repository_hash=repo_hash,
                expected_sha=expected_sha,
                ref=ref,
                verification_status=GitHubVerificationStatus.ACCEPTED_WITH_FOLLOW_ON,
                remote_head_sha=remote_head,
                accepted_head_present=True,
                follow_on_commits_count=compare.ahead_by,
                follow_on_head_sha=remote_head,
                ci_state=ci_state,
                ci_evidence=ci,
                suggested_next_action="Accepted head present with follow-on commits; review follow-on changes",
            )
        elif compare.status == "behind":
            # head (remote_head) is behind base (expected_sha) — remote lags
            return GitHubPublicationVerification(
                repository_hash=repo_hash,
                expected_sha=expected_sha,
                ref=ref,
                verification_status=GitHubVerificationStatus.TARGET_BEHIND,
                remote_head_sha=remote_head,
                accepted_head_present=False,
                error_kind=GitHubTruthErrorKind.REMOTE_DIVERGENCE,
                suggested_next_action=f"Remote {ref} is {compare.behind_by} commits behind expected publication",
            )
        else:
            # Diverged or other
            return GitHubPublicationVerification(
                repository_hash=repo_hash,
                expected_sha=expected_sha,
                ref=ref,
                verification_status=GitHubVerificationStatus.TARGET_DIVERGENT,
                remote_head_sha=remote_head,
                accepted_head_present=False,
                error_kind=GitHubTruthErrorKind.REMOTE_DIVERGENCE,
                suggested_next_action="Remote and local have diverged; manual reconciliation required",
            )


# ── Factory ────────────────────────────────────────────────────────────


def create_truth_adapter(token_manager: Any | None = None) -> GitHubTruthAdapter | None:
    """Create a truth adapter from the environment GitHub App token manager."""
    if token_manager is None:
        from rig_relay.integrations.github_provider._github_app_token_manager import (
            GitHubAppTokenManager,
        )

        token_manager = GitHubAppTokenManager.from_environment()
    if token_manager is None:
        return None
    return GitHubTruthAdapter(token_manager)


__all__ = ["GitHubTruthAdapter", "GitHubTruthAdapterError", "create_truth_adapter"]
