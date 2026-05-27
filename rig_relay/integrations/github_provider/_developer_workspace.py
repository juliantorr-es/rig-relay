"""Developer GitHub Workspace Service — Lane J0.

Unified application service for:
- Connecting Carte Blanche (GitHub App installation identity)
- Discovering repositories available to the installation
- Selecting repositories for local intake
- Importing/synchronizing repositories via pipe-transport (os.pipe + pass_fds), never in argv/URL/tempfile
- Inspecting GitHub Pages / publication readiness
- Preparing publication actions (never executing silently)
- Building Gridline-consumable projections

Content-light: never persists installation tokens, raw contents, or secrets.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
from typing import Any

import httpx

from rig_relay.integrations.github_provider._redaction import (
    assert_no_raw_github_token,
    hash_identifier,
)
from rig_relay.integrations.github_provider._workspace_models import (
    ConnectionState,
    DeveloperGitHubConnection,
    DeveloperGitHubRepository,
    GitHubPermissionDiagnostic,
    GitHubWorkspaceProjection,
    IntakeState,
    LocalWorkspaceRegistration,
    PagesActionPreparation,
    PagesActionState,
    PagesTargetMode,
    PublicationReadiness,
    PublicationReadinessState,
    RepositoryDiscoveryResult,
    RepositoryIntakeRequest,
    RepositoryIntakeResult,
    RepositorySelectionResult,
    RepositorySyncRequest,
    RepositorySyncResult,
    WorkspaceErrorKind,
)

GITHUB_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = 30.0
_MAX_PAGINATION_PAGES = 10
_HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_READ_WRITE_PERMISSIONS: frozenset[str] = frozenset({"read", "write"})

_DOTENV_PATH = Path.home() / ".rig" / "relay" / ".env"
_APP_SUPPORT_ROOT = Path.home() / ".rig" / "relay" / "workspaces"


class DeveloperGitHubWorkspaceError(Exception):
    """Typed error from the developer workspace service."""

    def __init__(self, error_kind: str, message: str) -> None:
        super().__init__(message)
        self.error_kind = error_kind


# ── In-Memory Selection Store ─────────────────────────────────────────


class _SelectionStore:
    """In-memory store for repository selection state.

    Each developer session maintains its own selection. No persistence
    until Lane J0 extends to durable registration.
    """

    def __init__(self) -> None:
        self._selected: dict[str, DeveloperGitHubRepository] = {}
        self._registration: dict[str, LocalWorkspaceRegistration] = {}

    def select(self, repo: DeveloperGitHubRepository) -> None:
        repo.selected = True
        repo.intake_state = IntakeState.SELECTED.value
        self._selected[repo.repository_hash] = repo

    def deselect(self, repo_hash: str) -> None:
        repo = self._selected.pop(repo_hash, None)
        if repo:
            repo.selected = False
            repo.intake_state = IntakeState.DISCOVERED.value

    def is_selected(self, repo_hash: str) -> bool:
        return repo_hash in self._selected

    def get(self, repo_hash: str) -> DeveloperGitHubRepository | None:
        return self._selected.get(repo_hash)

    def list_selected(self) -> list[DeveloperGitHubRepository]:
        return list(self._selected.values())

    def register(self, reg: LocalWorkspaceRegistration) -> None:
        self._registration[reg.repository_hash] = reg

    def get_registration(self, repo_hash: str) -> LocalWorkspaceRegistration | None:
        return self._registration.get(repo_hash)


# ── Service ────────────────────────────────────────────────────────────


class DeveloperGitHubWorkspaceService:
    """Typed application service for the Carte Blanche developer workspace.

    Composes GitHubAppTokenManager for auth, httpx for API calls, and
    Git subprocess for local repository intake. Never persists tokens.
    State is in-memory per session.
    """

    def __init__(
        self, token_manager: Any | None = None, workspace_root: Path | None = None
    ) -> None:
        self._token_manager = token_manager
        self._workspace_root = Path(workspace_root or _APP_SUPPORT_ROOT)
        self._selection_store = _SelectionStore()
        self._connection: DeveloperGitHubConnection | None = None
        self._discovered: dict[str, DeveloperGitHubRepository] = {}
        self._token_permissions: dict[str, str] = {}

    # ── Connection ────────────────────────────────────────────────────

    @classmethod
    def from_environment(cls) -> DeveloperGitHubWorkspaceService:
        """Factory: create a service from environment config.

        Reads RIG_GITHUB_APP_ID, RIG_GITHUB_INSTALLATION_ID,
        RIG_GITHUB_PRIVATE_KEY_PATH from ~/.rig/relay/.env.
        """
        from rig_relay.integrations.github_provider._github_app_token_manager import (
            GitHubAppTokenManager,
        )

        tm = GitHubAppTokenManager.from_environment()
        return cls(token_manager=tm)

    def connect(self) -> DeveloperGitHubConnection:
        """Establish connection from environment config.

        Returns a content-light connection projection. Never exposes the token.
        """
        if self._token_manager is None:
            return DeveloperGitHubConnection(
                connection_state=ConnectionState.DISCONNECTED.value,
                errors=["No GitHub App token manager configured"],
            )

        try:
            config = self._token_manager.config_summary()
        except Exception:
            return DeveloperGitHubConnection(
                connection_state=ConnectionState.ERROR.value,
                errors=["Failed to read token manager config"],
            )

        app_id = int(config.get("app_id", 0))
        installation_id = str(config.get("installation_id", ""))
        token_available = bool(config.get("token_cached", False))
        expires_in = float(config.get("token_expires_in_seconds", 0.0))

        if not token_available:
            token = self._token_manager.get_token()
            if token is None:
                return DeveloperGitHubConnection(
                    connection_state=ConnectionState.ERROR.value,
                    app_id=app_id,
                    installation_id_hash=hash_identifier(installation_id),
                    token_available=False,
                    errors=["Failed to acquire installation token"],
                )
            token_available = True
            config = self._token_manager.config_summary()
            expires_in = float(config.get("token_expires_in_seconds", 0.0))

        state = (
            ConnectionState.CONNECTED.value
            if token_available
            else ConnectionState.DISCONNECTED.value
        )
        if token_available and expires_in <= 0:
            state = ConnectionState.TOKEN_EXPIRED.value

        self._connection = DeveloperGitHubConnection(
            installation_id_hash=hash_identifier(installation_id),
            app_id=app_id,
            connection_state=state,
            token_available=token_available,
            token_expires_in_seconds=max(0.0, expires_in),
            repository_selection="",
            accessible_repository_count=len(self._discovered),
            permissions_summary=dict(self._token_permissions),
        )
        return self._connection

    def _get_token(self) -> str:
        if self._token_manager is None:
            raise DeveloperGitHubWorkspaceError(
                WorkspaceErrorKind.INSTALLATION_MISSING, "No token manager configured"
            )
        token = self._token_manager.get_token()
        if token is None:
            raise DeveloperGitHubWorkspaceError(
                WorkspaceErrorKind.TOKEN_EXPIRED, "Failed to acquire installation token"
            )
        return token

    # ── Repository Discovery ──────────────────────────────────────────

    async def discover_repositories(self) -> RepositoryDiscoveryResult:
        """List repositories accessible to this installation.

        Uses GET /installation/repositories. Caches in memory.
        Never stores raw token in results.
        """
        try:
            token = self._get_token()
        except DeveloperGitHubWorkspaceError as e:
            return RepositoryDiscoveryResult(error_kind=e.error_kind, errors=[str(e)])

        all_repos: list[dict[str, Any]] = []
        per_page = 100
        page = 1
        repository_selection = ""

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            while page <= _MAX_PAGINATION_PAGES:
                resp = await client.get(
                    f"{GITHUB_API_BASE}/installation/repositories",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "rig-relay-workspace/1.0",
                    },
                    params={"per_page": per_page, "page": page},
                )

                if resp.status_code != _HTTP_OK:
                    error_body = resp.text[:200]
                    return RepositoryDiscoveryResult(
                        error_kind=WorkspaceErrorKind.API_UNAVAILABLE,
                        errors=[f"GitHub API error {resp.status_code}: {error_body}"],
                    )

                data: dict[str, Any] = resp.json()
                repos = data.get("repositories", [])
                all_repos.extend(repos)
                if page == 1:
                    repository_selection = data.get("repository_selection", "")

                if len(repos) < per_page:
                    break
                page += 1

        for item in all_repos:
            assert_no_raw_github_token(json.dumps(item, sort_keys=True))

        discovered: dict[str, DeveloperGitHubRepository] = {}
        for item in all_repos:
            full_name = item.get("full_name", "")
            repo_hash = hash_identifier(full_name)

            desc = item.get("description")
            desc_hash: str | None = None
            if isinstance(desc, str) and desc.strip():
                try:
                    assert_no_raw_github_token(desc)
                    desc_hash = hash_identifier(desc)
                except ValueError:
                    desc_hash = f"sha256:{hash_identifier(desc)}"

            existing = self._discovered.get(repo_hash)
            intake_state = (
                existing.intake_state if existing else IntakeState.DISCOVERED.value
            )

            repo = DeveloperGitHubRepository(
                repository_id=item.get("id", 0),
                repository_hash=repo_hash,
                owner=item.get("owner", {}).get("login", ""),
                name=item.get("name", ""),
                full_name=full_name,
                description_hash=desc_hash,
                visibility=item.get("visibility", ""),
                default_branch=item.get("default_branch", "main"),
                has_pages=item.get("has_pages", False),
                clone_url=item.get("clone_url", ""),
                html_url=item.get("html_url", ""),
                intake_state=intake_state,
                selected=self._selection_store.is_selected(repo_hash),
                private=item.get("private", False),
                pushed_at=item.get("pushed_at"),
            )
            discovered[repo_hash] = repo

        self._discovered = discovered

        if self._connection:
            self._connection.accessible_repository_count = len(discovered)

        return RepositoryDiscoveryResult(
            total_count=len(discovered),
            repositories=list(discovered.values()),
            repository_selection=repository_selection,
        )

    # ── Repository Selection ──────────────────────────────────────────

    def select_repository(self, repo_hash: str) -> RepositorySelectionResult:
        repo = self._discovered.get(repo_hash)
        if repo is None:
            return RepositorySelectionResult(
                repository_hash=repo_hash,
                selected=False,
                error_kind=WorkspaceErrorKind.REPOSITORY_INACCESSIBLE,
            )
        self._selection_store.select(repo)
        return RepositorySelectionResult(
            repository_hash=repo_hash,
            selected=True,
            intake_state=IntakeState.SELECTED.value,
        )

    def deselect_repository(self, repo_hash: str) -> RepositorySelectionResult:
        self._selection_store.deselect(repo_hash)
        return RepositorySelectionResult(
            repository_hash=repo_hash,
            selected=False,
            intake_state=IntakeState.DISCOVERED.value,
        )

    # ── Permission Inspection ─────────────────────────────────────────

    async def inspect_repository_permissions(
        self, owner: str, repo: str
    ) -> GitHubPermissionDiagnostic:
        repo_hash = hash_identifier(f"{owner}/{repo}")

        try:
            token = self._get_token()
        except DeveloperGitHubWorkspaceError as e:
            return GitHubPermissionDiagnostic(
                repository_hash=repo_hash, error_kind=e.error_kind
            )

        permissions: dict[str, str] = {}
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "rig-relay-workspace/1.0",
                    },
                )

                if resp.status_code == _HTTP_UNAUTHORIZED:
                    return GitHubPermissionDiagnostic(
                        repository_hash=repo_hash,
                        error_kind=WorkspaceErrorKind.TOKEN_EXPIRED,
                    )
                if resp.status_code == _HTTP_FORBIDDEN:
                    return GitHubPermissionDiagnostic(
                        repository_hash=repo_hash,
                        error_kind=WorkspaceErrorKind.PERMISSION_MISSING,
                    )
                if resp.status_code == _HTTP_NOT_FOUND:
                    return GitHubPermissionDiagnostic(
                        repository_hash=repo_hash,
                        error_kind=WorkspaceErrorKind.REPOSITORY_INACCESSIBLE,
                    )
                resp.raise_for_status()

                data = resp.json()
                permissions = data.get("permissions", {})

        except httpx.HTTPStatusError:
            return GitHubPermissionDiagnostic(
                repository_hash=repo_hash, error_kind=WorkspaceErrorKind.API_UNAVAILABLE
            )
        except Exception:
            return GitHubPermissionDiagnostic(
                repository_hash=repo_hash, error_kind=WorkspaceErrorKind.UNKNOWN
            )

        has_contents_read = permissions.get("contents") in _READ_WRITE_PERMISSIONS
        has_pages_read = permissions.get("pages") in _READ_WRITE_PERMISSIONS
        has_pages_write = permissions.get("pages") == "write"
        has_admin_read = permissions.get("administration") in _READ_WRITE_PERMISSIONS
        has_admin_write = permissions.get("administration") == "write"

        can_clone = has_contents_read
        can_inspect_pages = has_pages_read or has_admin_read
        can_configure_pages = has_pages_write or has_admin_write

        missing_clone: list[str] = []
        if not has_contents_read:
            missing_clone.append("contents:read")
        missing_pages: list[str] = []
        if not can_inspect_pages:
            missing_pages.append("pages:read or administration:read")
        if not can_configure_pages:
            missing_pages.append("pages:write or administration:write")

        return GitHubPermissionDiagnostic(
            repository_hash=repo_hash,
            permissions={k: str(v) for k, v in permissions.items()},
            contents_readable=has_contents_read,
            pages_readable=can_inspect_pages,
            pages_configurable=can_configure_pages,
            administration_readable=has_admin_read,
            can_clone=can_clone,
            can_inspect_pages=can_inspect_pages,
            can_configure_pages=can_configure_pages,
            missing_for_clone=missing_clone,
            missing_for_pages=missing_pages,
        )

    # ── Repository Intake (Clone) ─────────────────────────────────────

    # Token-free askpass script. Reads token from inherited file descriptor
    # at runtime. Contains NO token in source.
    _GIT_ASKPASS_SOURCE = (
        "#!/usr/bin/env python3\n"
        "import sys, os\n"
        "fd = int(os.environ.get('RIG_GIT_TOKEN_FD', '-1'))\n"
        "if fd < 0:\n  sys.exit(1)\n"
        "token = os.read(fd, 4096).decode().strip()\n"
        "q = sys.argv[1].lower() if len(sys.argv) > 1 else ''\n"
        "if 'username' in q:\n  print('x-access-token')\n"
        "else:\n  print(token)\n"
    )

    @staticmethod
    def _run_git_with_token(
        args: list[str], *, cwd: str | None = None, timeout: int = 120, token: str
    ) -> subprocess.CompletedProcess[str]:
        fd_askpass, askpass_path = tempfile.mkstemp(prefix=".rig-git-askpass-")
        os.write(
            fd_askpass, DeveloperGitHubWorkspaceService._GIT_ASKPASS_SOURCE.encode()
        )
        os.close(fd_askpass)
        os.chmod(askpass_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

        read_fd, write_fd = os.pipe()
        os.write(write_fd, token.encode())
        os.close(write_fd)

        try:
            env = _sanitized_env()
            env["GIT_ASKPASS"] = askpass_path
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["RIG_GIT_TOKEN_FD"] = str(read_fd)

            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
                env=env,
                pass_fds=(read_fd,),
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                return subprocess.CompletedProcess(
                    args=args, returncode=proc.returncode, stdout=stdout, stderr=stderr
                )
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
            finally:
                try:
                    os.close(read_fd)
                except OSError:
                    pass
        finally:
            try:
                os.unlink(askpass_path)
            except OSError:
                pass

    def import_repository(
        self, request: RepositoryIntakeRequest
    ) -> RepositoryIntakeResult:
        """Import a repository into local workspace via installation token.

        Token is transported through an anonymous pipe (os.pipe + pass_fds).
        The askpass executable is token-free; it reads the token from the
        inherited file descriptor at runtime. Token never appears in argv,
        URLs, environment values, script contents, tempfile contents,
        process listings, or persisted state.
        """
        repo = self._discovered.get(request.repository_hash)
        if repo is None or not repo.selected:
            return RepositoryIntakeResult(
                repository_hash=request.repository_hash,
                intake_state=IntakeState.FAILED.value,
                error_kind=WorkspaceErrorKind.NOT_SELECTED,
                error_message="Repository must be discovered and selected first",
            )

        try:
            token = self._get_token()
        except DeveloperGitHubWorkspaceError as e:
            return RepositoryIntakeResult(
                repository_hash=request.repository_hash,
                intake_state=IntakeState.FAILED.value,
                error_kind=e.error_kind,
                error_message=str(e),
            )

        owner = request.owner or (repo.owner if repo else "")
        name = request.repo or (repo.name if repo else "")

        if not owner or not name:
            return RepositoryIntakeResult(
                repository_hash=request.repository_hash,
                intake_state=IntakeState.FAILED.value,
                error_kind=WorkspaceErrorKind.UNKNOWN,
                error_message="Owner and repo name required",
            )

        ws_root = Path(request.local_workspace_root or str(self._workspace_root))
        target_dir = ws_root / f"{owner}-{name}"
        anonymous_url = f"https://github.com/{owner}/{name}.git"

        if target_dir.exists():
            return RepositoryIntakeResult(
                repository_hash=request.repository_hash,
                intake_state=IntakeState.IMPORTED.value,
                local_path=str(target_dir),
                workspace_root=str(ws_root),
                error_kind=WorkspaceErrorKind.ALREADY_IMPORTED,
                error_message=f"Directory already exists: {target_dir}",
            )

        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            result = self._run_git_with_token(
                ["git", "clone", "--quiet", anonymous_url, str(target_dir)], token=token
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip()[:500]
                return RepositoryIntakeResult(
                    repository_hash=request.repository_hash,
                    intake_state=IntakeState.FAILED.value,
                    error_kind=WorkspaceErrorKind.IMPORT_FAILED,
                    error_message=error_msg,
                )

        except subprocess.TimeoutExpired:
            return RepositoryIntakeResult(
                repository_hash=request.repository_hash,
                intake_state=IntakeState.FAILED.value,
                error_kind=WorkspaceErrorKind.IMPORT_FAILED,
                error_message="Clone timed out after 120 seconds",
            )
        except Exception as e:
            return RepositoryIntakeResult(
                repository_hash=request.repository_hash,
                intake_state=IntakeState.FAILED.value,
                error_kind=WorkspaceErrorKind.UNKNOWN,
                error_message=str(e),
            )

        sanitized = self._sanitize_remote_url(target_dir, anonymous_url)

        head_sha = ""
        branch = ""
        try:
            head_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(target_dir),
                env=_sanitized_env(),
            ).stdout.strip()
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(target_dir),
                env=_sanitized_env(),
            ).stdout.strip()
        except Exception:
            pass

        if repo:
            repo.intake_state = IntakeState.IMPORTED.value

        reg = LocalWorkspaceRegistration(
            repository_hash=request.repository_hash,
            owner=owner,
            repo=name,
            local_path=str(target_dir),
            head_sha=head_sha,
            branch=branch,
            imported_at=datetime.now(UTC).isoformat(),
            registered=True,
        )
        self._selection_store.register(reg)

        return RepositoryIntakeResult(
            repository_hash=request.repository_hash,
            intake_state=IntakeState.IMPORTED.value,
            local_path=str(target_dir),
            workspace_root=str(ws_root),
            head_sha=head_sha,
            branch=branch,
            clone_successful=True,
            remote_url_sanitized=sanitized,
        )

    def _sanitize_remote_url(self, repo_path: Path, anonymous_url: str) -> bool:
        """Replace token-bearing origin URL with anonymous URL."""
        try:
            subprocess.run(
                ["git", "remote", "set-url", "origin", anonymous_url],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(repo_path),
                env=_sanitized_env(),
                check=True,
            )
            return True
        except Exception:
            return False

    def synchronize_repository(
        self, request: RepositorySyncRequest
    ) -> RepositorySyncResult:
        """Fetch latest from remote for an imported repository.

        Uses the same pipe-transport mechanism as import_repository.
        Token never appears in argv, URLs, tempfiles, or persisted state.
        """
        target = Path(request.local_path)
        if not target.is_dir() or not (target / ".git").is_dir():
            return RepositorySyncResult(
                repository_hash=request.repository_hash,
                error_kind=WorkspaceErrorKind.IMPORT_FAILED,
            )

        reg = self._selection_store.get_registration(request.repository_hash)
        try:
            token = self._get_token()
        except DeveloperGitHubWorkspaceError as e:
            return RepositorySyncResult(
                repository_hash=request.repository_hash, error_kind=e.error_kind
            )

        repo = self._discovered.get(request.repository_hash)
        owner = repo.owner if repo else (reg.owner if reg else "")
        name = repo.name if repo else (reg.repo if reg else "")
        anonymous_url = f"https://github.com/{owner}/{name}.git"

        local_head_before = ""
        try:
            local_head_before = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(target),
                env=_sanitized_env(),
            ).stdout.strip()
        except Exception:
            pass

        try:
            fetch_result = self._run_git_with_token(
                ["git", "fetch", "--quiet", anonymous_url],
                cwd=str(target),
                timeout=60,
                token=token,
            )
            if fetch_result.returncode != 0:
                self._sanitize_remote_url(target, anonymous_url)
                return RepositorySyncResult(
                    repository_hash=request.repository_hash,
                    error_kind=WorkspaceErrorKind.IMPORT_FAILED,
                )
        except Exception:
            self._sanitize_remote_url(target, anonymous_url)
            return RepositorySyncResult(
                repository_hash=request.repository_hash,
                error_kind=WorkspaceErrorKind.UNKNOWN,
            )

        self._sanitize_remote_url(target, anonymous_url)

        remote_head = ""
        branch = ""
        behind = 0
        ahead = 0
        try:
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(target),
                env=_sanitized_env(),
            ).stdout.strip()
            remote_head = subprocess.run(
                ["git", "rev-parse", f"origin/{branch}"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(target),
                env=_sanitized_env(),
            ).stdout.strip()

            behind_out = subprocess.run(
                ["git", "rev-list", "--count", f"HEAD..origin/{branch}"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(target),
                env=_sanitized_env(),
            ).stdout.strip()
            ahead_out = subprocess.run(
                ["git", "rev-list", "--count", f"origin/{branch}..HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(target),
                env=_sanitized_env(),
            ).stdout.strip()

            behind = int(behind_out) if behind_out.isdigit() else 0
            ahead = int(ahead_out) if ahead_out.isdigit() else 0
        except Exception:
            pass

        if reg:
            reg.last_synced_at = datetime.now(UTC).isoformat()

        return RepositorySyncResult(
            repository_hash=request.repository_hash,
            synced=True,
            local_head_before=local_head_before,
            remote_head=remote_head,
            branch=branch,
            commits_behind=behind,
            commits_ahead=ahead,
        )

    # ── Publication Readiness ─────────────────────────────────────────

    async def inspect_publication_readiness(
        self, owner: str, repo: str
    ) -> PublicationReadiness:
        """Check GitHub Pages capability for a repository.

        Inspects Pages status, determines if configuration is possible,
        and identifies missing permissions or blockers.
        """
        repo_hash = hash_identifier(f"{owner}/{repo}")

        try:
            token = self._get_token()
        except DeveloperGitHubWorkspaceError as e:
            return PublicationReadiness(
                repository_hash=repo_hash,
                readiness_state=PublicationReadinessState.MISSING_PERMISSION.value,
                blockers=[e.error_kind],
            )

        pages_status = await self._get_pages_status(token, owner, repo)

        if pages_status is None:
            permission = await self.inspect_repository_permissions(owner, repo)
            blockers: list[str] = ["Pages not configured for this repository"]
            missing: list[str] = []

            if permission.can_configure_pages:
                readiness = PublicationReadinessState.CONFIGURABLE.value
            else:
                readiness = PublicationReadinessState.MISSING_PERMISSION.value
                missing = list(permission.missing_for_pages)
                blockers.append("Missing permissions to configure Pages")

            return PublicationReadiness(
                repository_hash=repo_hash,
                has_pages=False,
                can_configure_pages=permission.can_configure_pages,
                publication_eligible=permission.can_configure_pages,
                requires_additional_permissions=missing,
                readiness_state=readiness,
                blockers=blockers,
            )

        evidence_raw = pages_status.model_dump_json(exclude={"evidence_digest"})
        evidence_digest = f"sha256:{hashlib.sha256(evidence_raw.encode()).hexdigest()}"

        permission = await self.inspect_repository_permissions(owner, repo)

        is_built = pages_status.build_status == "built"
        is_configurable = permission.can_configure_pages

        if is_built:
            readiness = PublicationReadinessState.BUILT.value
        elif is_configurable:
            readiness = PublicationReadinessState.CONFIGURABLE.value
        else:
            readiness = PublicationReadinessState.MISSING_PERMISSION.value

        pub_blockers: list[str] = []
        if not is_configurable:
            pub_blockers.append("Cannot configure Pages: insufficient permissions")

        return PublicationReadiness(
            repository_hash=repo_hash,
            has_pages=pages_status.has_pages,
            pages_build_status=pages_status.build_status,
            pages_html_url=pages_status.html_url,
            cname=pages_status.cname,
            source_branch=pages_status.source_branch,
            source_path=pages_status.source_path,
            https_enforced=pages_status.https_enforced,
            public=pages_status.public,
            can_configure_pages=is_configurable,
            publication_eligible=is_configurable,
            requires_additional_permissions=permission.missing_for_pages,
            readiness_state=readiness,
            blockers=pub_blockers,
            evidence_digest=evidence_digest,
        )

    async def _get_pages_status(self, token: str, owner: str, repo: str) -> Any | None:
        from rig_relay.integrations.github_provider._pages_adapter import (
            GitHubPagesAdapter,
        )

        class _TokenGetter:
            def __init__(self, t: str) -> None:
                self._t = t

            def get_token(self) -> str:
                return self._t

        adapter = GitHubPagesAdapter(token_getter=_TokenGetter(token))
        try:
            return await adapter.get_pages_status(owner, repo)
        except Exception:
            return None

    # ── Pages Action Preparation ──────────────────────────────────────

    async def prepare_pages_action(
        self,
        owner: str,
        repo: str,
        target_type: str = PagesTargetMode.PROJECT_PAGE.value,
        source_branch: str = "main",
        source_path: str = "/",
    ) -> PagesActionPreparation:
        """Prepare a GitHub Pages action without executing it.

        Returns a planned action requiring explicit developer approval.
        """
        repo_hash = hash_identifier(f"{owner}/{repo}")

        permission = await self.inspect_repository_permissions(owner, repo)
        readiness = await self.inspect_publication_readiness(owner, repo)

        action_id = f"pages-prepare-{int(time.time())}"
        blockers: list[str] = []
        required_perms: list[str] = []

        if not permission.can_configure_pages:
            blockers.append("Insufficient permissions to configure Pages")
            required_perms = list(permission.missing_for_pages)

        if readiness.pages_build_status == "built":
            blockers.append("Pages already configured and built")

        action_type = "configure_and_deploy" if not readiness.has_pages else "inspect"

        return PagesActionPreparation(
            action_id=action_id,
            repository_hash=repo_hash,
            owner=owner,
            repo=repo,
            target_type=target_type,
            action_type=action_type,
            source_branch=source_branch,
            source_path=source_path,
            requires_approval=True,
            approval_status=PagesActionState.PLANNED.value,
            required_permissions=required_perms,
            will_mutate_remote=action_type == "configure_and_deploy",
            suggested_next_action=(
                "Review Pages configuration and approve publication action"
                if not blockers
                else "Resolve blockers before proceeding"
            ),
            blockers=blockers,
        )

    # ── Gridline Projection ───────────────────────────────────────────

    def build_gridline_projection(self) -> GitHubWorkspaceProjection:
        """Build a Gridline-consumable projection of the workspace state.

        Content-light: no tokens, raw file contents, or secrets.
        """
        repos = list(self._discovered.values())

        selected = [r for r in repos if r.selected]
        imported = [
            r
            for r in repos
            if r.intake_state
            in {
                IntakeState.IMPORTED.value,
                IntakeState.SYNCED.value,
                IntakeState.STALE.value,
                IntakeState.ANALYZING.value,
                IntakeState.ANALYZED.value,
            }
        ]
        analyzed = [r for r in repos if r.intake_state in {IntakeState.ANALYZED.value}]

        errors: list[str] = []
        if self._connection and self._connection.connection_state in {
            ConnectionState.DISCONNECTED.value,
            ConnectionState.ERROR.value,
            ConnectionState.TOKEN_EXPIRED.value,
        }:
            errors = list(self._connection.errors)

        return GitHubWorkspaceProjection(
            connection=self._connection,
            repositories=repos,
            selected_count=len(selected),
            imported_count=len(imported),
            analyzed_count=len(analyzed),
            publishable_count=sum(1 for r in repos if r.has_pages),
            total_discovered=len(repos),
            errors=errors,
            generated_at=datetime.now(UTC).isoformat(),
        )

    # ── Connection State Query ────────────────────────────────────────

    @property
    def connection(self) -> DeveloperGitHubConnection | None:
        return self._connection

    @property
    def discovered_repos(self) -> dict[str, DeveloperGitHubRepository]:
        return dict(self._discovered)

    @property
    def selected_repos(self) -> list[DeveloperGitHubRepository]:
        return self._selection_store.list_selected()


# ── Helpers ───────────────────────────────────────────────────────────


def _sanitized_env() -> dict[str, str]:
    """Return a sanitized environment dict for subprocess calls.

    Strips sensitive variables to prevent token leakage into child processes.
    """
    env: dict[str, str] = {}
    blocklist = frozenset({
        "RIG_GITHUB_PRIVATE_KEY",
        "RIG_GITHUB_PRIVATE_KEY_ENV",
        "RIG_GITHUB_APP_ID",
        "RIG_GITHUB_INSTALLATION_ID",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "RIG_RELAY_OAUTH_TOKEN",
        "RIG_RELAY_API_KEY",
    })
    for key, value in os.environ.items():
        if key not in blocklist:
            env[key] = value
    return env


__all__ = ["DeveloperGitHubWorkspaceError", "DeveloperGitHubWorkspaceService"]
