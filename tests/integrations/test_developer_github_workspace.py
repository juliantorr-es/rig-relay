"""Tests for DeveloperGitHubWorkspaceService and workspace models — Lane J0.

Covers: connection, repository discovery, selection, permission inspection,
intake (clone), gridline projection, and token secrecy.
Uses respx for HTTP mocking, unittest.mock for subprocess, and inline fakes.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import respx

from rig_relay.integrations.github_provider._developer_workspace import (
    GITHUB_API_BASE,
    DeveloperGitHubWorkspaceService,
)
from rig_relay.integrations.github_provider._redaction import hash_identifier
from rig_relay.integrations.github_provider._workspace_models import (
    ConnectionState,
    GitHubWorkspaceProjection,
    IntakeState,
    RepositoryIntakeRequest,
    WorkspaceErrorKind,
)

# ── Inline Fake Token Manager ───────────────────────────────────────────


class _FakeTokenManager:
    def __init__(
        self,
        app_id: int = 123,
        inst_id: int = 456,
        token: str | None = "ghs_test_abc123",
        expires_in: float = 3300.0,
        token_cached: bool = True,
    ) -> None:
        self._app_id = app_id
        self._inst_id = inst_id
        self._token = token
        self._expires_in = expires_in
        self._token_cached = token_cached

    def get_token(self) -> str | None:
        if self._token is None:
            return None
        return self._token

    def config_summary(self) -> dict[str, object]:
        return {
            "app_id": self._app_id,
            "installation_id": str(self._inst_id),
            "token_cached": self._token_cached,
            "token_expires_in_seconds": self._expires_in,
            "private_key_present": True,
            "config_source": "test",
        }

    @property
    def is_ready(self) -> bool:
        return self._token is not None and self._expires_in > 0


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_repo_item(
    repo_id: int, full_name: str, visibility: str = "public", has_pages: bool = False
) -> dict:
    owner, name = full_name.split("/", 1)
    return {
        "id": repo_id,
        "name": name,
        "full_name": full_name,
        "owner": {"login": owner},
        "visibility": visibility,
        "default_branch": "main",
        "has_pages": has_pages,
        "clone_url": f"https://github.com/{full_name}.git",
        "html_url": f"https://github.com/{full_name}",
        "private": visibility == "private",
        "description": "",
        "pushed_at": None,
    }


def _make_repos_response(
    repos: list[dict], repository_selection: str = "selected"
) -> dict:
    return {"repositories": repos, "repository_selection": repository_selection}


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def valid_tm() -> _FakeTokenManager:
    return _FakeTokenManager(token="ghs_test_valid", expires_in=3300.0)


@pytest.fixture
def expired_tm() -> _FakeTokenManager:
    return _FakeTokenManager(token="ghs_test_valid", expires_in=0.0, token_cached=True)


@pytest.fixture
def no_token_tm() -> _FakeTokenManager:
    return _FakeTokenManager(token=None, expires_in=0.0, token_cached=False)


@pytest.fixture
def svc_with_tm(valid_tm: _FakeTokenManager) -> DeveloperGitHubWorkspaceService:
    return DeveloperGitHubWorkspaceService(token_manager=valid_tm)


@pytest.fixture
def svc_no_tm() -> DeveloperGitHubWorkspaceService:
    return DeveloperGitHubWorkspaceService(token_manager=None)


# ── Connection Tests ────────────────────────────────────────────────────


class TestConnection:
    @pytest.mark.asyncio
    async def test_connect_without_token_manager_returns_disconnected(
        self, svc_no_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        conn = svc_no_tm.connect()
        assert conn.connection_state == ConnectionState.DISCONNECTED.value
        assert conn.token_available is False
        assert len(conn.errors) == 1
        assert "No GitHub App token manager" in conn.errors[0]

    @pytest.mark.asyncio
    async def test_connect_with_valid_token_returns_connected(
        self, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        conn = svc_with_tm.connect()
        assert conn.connection_state == ConnectionState.CONNECTED.value
        assert conn.token_available is True
        assert conn.app_id == 123
        assert len(conn.errors) == 0

    @pytest.mark.asyncio
    async def test_connect_with_expired_token_returns_token_expired(
        self, expired_tm: _FakeTokenManager
    ) -> None:
        svc = DeveloperGitHubWorkspaceService(token_manager=expired_tm)
        conn = svc.connect()
        assert conn.connection_state == ConnectionState.TOKEN_EXPIRED.value
        assert conn.token_available is True
        assert conn.token_expires_in_seconds == 0.0

    @pytest.mark.asyncio
    async def test_connect_with_config_summary_raises_returns_error(self) -> None:
        bad_tm = MagicMock()
        bad_tm.config_summary.side_effect = RuntimeError("boom")
        svc = DeveloperGitHubWorkspaceService(token_manager=bad_tm)
        conn = svc.connect()
        assert conn.connection_state == ConnectionState.ERROR.value
        assert "Failed to read token manager config" in conn.errors[0]


# ── Repository Discovery Tests ──────────────────────────────────────────


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_discover_repositories_returns_repos_from_api(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        svc_with_tm.connect()

        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(
            json=_make_repos_response([
                _make_repo_item(1, "orgA/repo1"),
                _make_repo_item(2, "orgA/repo2", has_pages=True),
            ])
        )

        result = await svc_with_tm.discover_repositories()
        assert result.total_count == 2
        assert result.error_kind is None
        assert len(result.errors) == 0
        assert result.repositories[0].full_name == "orgA/repo1"
        assert result.repositories[1].has_pages is True

    @pytest.mark.asyncio
    async def test_discover_repositories_handles_api_error(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        svc_with_tm.connect()

        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(status_code=503, text="Service Unavailable")

        result = await svc_with_tm.discover_repositories()
        assert result.error_kind == WorkspaceErrorKind.API_UNAVAILABLE
        assert len(result.errors) == 1
        assert "503" in result.errors[0]

    @pytest.mark.asyncio
    async def test_discover_repositories_no_token_returns_error(
        self, respx_mock: respx.MockRouter, no_token_tm: _FakeTokenManager
    ) -> None:
        svc = DeveloperGitHubWorkspaceService(token_manager=no_token_tm)

        result = await svc.discover_repositories()
        assert result.error_kind == WorkspaceErrorKind.TOKEN_EXPIRED
        assert len(result.errors) == 1
        assert result.total_count == 0

    @pytest.mark.asyncio
    async def test_discover_repositories_paginates(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        svc_with_tm.connect()

        page1_repos = [_make_repo_item(i, f"orgA/repo{i}") for i in range(1, 101)]
        page2_repos = [_make_repo_item(i, f"orgA/repo{i}") for i in range(101, 103)]

        respx_mock.get(
            url=f"{GITHUB_API_BASE}/installation/repositories?per_page=100&page=1"
        ).respond(json=_make_repos_response(page1_repos, repository_selection="all"))

        respx_mock.get(
            url=f"{GITHUB_API_BASE}/installation/repositories?per_page=100&page=2"
        ).respond(json=_make_repos_response(page2_repos, repository_selection="all"))

        result = await svc_with_tm.discover_repositories()
        assert result.total_count == 102
        assert result.repository_selection == "all"
        assert len(result.repositories) == 102

    @pytest.mark.asyncio
    async def test_discover_repositories_without_token_manager(
        self, svc_no_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        result = await svc_no_tm.discover_repositories()
        assert result.error_kind == WorkspaceErrorKind.INSTALLATION_MISSING
        assert len(result.errors) == 1


# ── Repository Selection Tests ──────────────────────────────────────────


class TestSelection:
    @pytest.mark.asyncio
    async def test_select_repository_marks_as_selected(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "orgA/repo1")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("orgA/repo1")

        result = svc_with_tm.select_repository(repo_hash)
        assert result.selected is True
        assert result.intake_state == IntakeState.SELECTED.value
        assert result.error_kind is None

    @pytest.mark.asyncio
    async def test_deselect_repository_unmarks_selection(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "orgA/repo1")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("orgA/repo1")

        svc_with_tm.select_repository(repo_hash)
        result = svc_with_tm.deselect_repository(repo_hash)
        assert result.selected is False
        assert result.intake_state == IntakeState.DISCOVERED.value

    @pytest.mark.asyncio
    async def test_deselect_unknown_repo_still_returns_deselected(
        self, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        fake_hash = hash_identifier("nonexistent/repo")
        result = svc_with_tm.deselect_repository(fake_hash)
        assert result.selected is False
        assert result.intake_state == IntakeState.DISCOVERED.value

    @pytest.mark.asyncio
    async def test_select_nonexistent_repository_returns_error(
        self, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        fake_hash = hash_identifier("nonexistent/repo")
        result = svc_with_tm.select_repository(fake_hash)
        assert result.selected is False
        assert result.error_kind == WorkspaceErrorKind.REPOSITORY_INACCESSIBLE


# ── Permission Inspection Tests ─────────────────────────────────────────


class TestPermissions:
    @pytest.mark.asyncio
    async def test_inspect_permissions_with_contents_read_returns_can_clone(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(url__startswith=f"{GITHUB_API_BASE}/repos/owner/repo").respond(
            json={
                "name": "repo",
                "full_name": "owner/repo",
                "permissions": {
                    "contents": "read",
                    "issues": "read",
                    "metadata": "read",
                    "pages": "read",
                },
            }
        )

        diag = await svc_with_tm.inspect_repository_permissions("owner", "repo")
        assert diag.can_clone is True
        assert diag.contents_readable is True
        assert diag.can_inspect_pages is True
        assert diag.pages_readable is True
        assert diag.can_configure_pages is False
        assert len(diag.missing_for_clone) == 0

    @pytest.mark.asyncio
    async def test_inspect_permissions_without_pages_permission_returns_missing(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(url__startswith=f"{GITHUB_API_BASE}/repos/owner/repo").respond(
            json={
                "name": "repo",
                "full_name": "owner/repo",
                "permissions": {"contents": "read", "metadata": "read"},
            }
        )

        diag = await svc_with_tm.inspect_repository_permissions("owner", "repo")
        assert diag.can_clone is True
        assert diag.can_inspect_pages is False
        assert diag.can_configure_pages is False
        assert len(diag.missing_for_pages) >= 1

    @pytest.mark.asyncio
    async def test_inspect_permissions_with_contents_write_returns_can_clone(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(url__startswith=f"{GITHUB_API_BASE}/repos/owner/repo").respond(
            json={
                "name": "repo",
                "full_name": "owner/repo",
                "permissions": {"contents": "write", "metadata": "read"},
            }
        )

        diag = await svc_with_tm.inspect_repository_permissions("owner", "repo")
        assert diag.can_clone is True
        assert diag.contents_readable is True

    @pytest.mark.asyncio
    async def test_inspect_permissions_unauthorized_returns_token_expired(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(url__startswith=f"{GITHUB_API_BASE}/repos/owner/repo").respond(
            status_code=401
        )

        diag = await svc_with_tm.inspect_repository_permissions("owner", "repo")
        assert diag.error_kind == WorkspaceErrorKind.TOKEN_EXPIRED

    @pytest.mark.asyncio
    async def test_inspect_permissions_forbidden_returns_permission_missing(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(url__startswith=f"{GITHUB_API_BASE}/repos/owner/repo").respond(
            status_code=403
        )

        diag = await svc_with_tm.inspect_repository_permissions("owner", "repo")
        assert diag.error_kind == WorkspaceErrorKind.PERMISSION_MISSING

    @pytest.mark.asyncio
    async def test_inspect_permissions_not_found_returns_inaccessible(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(url__startswith=f"{GITHUB_API_BASE}/repos/owner/repo").respond(
            status_code=404
        )

        diag = await svc_with_tm.inspect_repository_permissions("owner", "repo")
        assert diag.error_kind == WorkspaceErrorKind.REPOSITORY_INACCESSIBLE

    @pytest.mark.asyncio
    async def test_inspect_permissions_no_token_manager_returns_error(
        self, svc_no_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        diag = await svc_no_tm.inspect_repository_permissions("owner", "repo")
        assert diag.error_kind == WorkspaceErrorKind.INSTALLATION_MISSING
        assert diag.can_clone is False


# ── Intake (Clone) Tests ────────────────────────────────────────────────


class TestIntake:
    @pytest.mark.asyncio
    async def test_import_repository_clones_and_sanitizes_remote_url(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/myrepo")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/myrepo")
        svc_with_tm.select_repository(repo_hash)

        clone_target = tmp_path / "owner-myrepo"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = _fake_git_run(clone_target)

                request = RepositoryIntakeRequest(
                    repository_hash=repo_hash,
                    owner="owner",
                    repo="myrepo",
                    local_workspace_root=str(tmp_path),
                )
                result = svc_with_tm.import_repository(request)

        assert result.intake_state == IntakeState.IMPORTED.value
        assert result.clone_successful is True
        assert result.remote_url_sanitized is True
        assert result.local_path == str(clone_target)
        assert (
            result.error_kind == WorkspaceErrorKind.ALREADY_IMPORTED
            or result.error_kind is None
        )
        assert "owner-myrepo" in str(result.local_path)
        mock_popen.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_repository_refuses_undiscovered_unselected_repo(
        self, svc_with_tm: DeveloperGitHubWorkspaceService, tmp_path: Path
    ) -> None:
        fake_hash = hash_identifier("unknown/repo")

        request = RepositoryIntakeRequest(
            repository_hash=fake_hash,
            owner="unknown",
            repo="repo",
            local_workspace_root=str(tmp_path),
        )
        result = svc_with_tm.import_repository(request)

        assert result.intake_state == IntakeState.FAILED.value
        assert result.error_kind == WorkspaceErrorKind.NOT_SELECTED
        assert result.clone_successful is False

    @pytest.mark.asyncio
    async def test_import_repository_refuses_discovered_but_unselected_repo(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        """A discovered-but-never-selected repository must be refused."""
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/myrepo")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/myrepo")
        # Do NOT call select_repository — discovered only

        request = RepositoryIntakeRequest(
            repository_hash=repo_hash,
            owner="owner",
            repo="myrepo",
            local_workspace_root=str(tmp_path),
        )
        result = svc_with_tm.import_repository(request)

        assert result.intake_state == IntakeState.FAILED.value, (
            f"Expected FAILED for discovered-but-unselected, got {result.intake_state}"
        )
        assert result.error_kind == WorkspaceErrorKind.NOT_SELECTED, (
            f"Expected NOT_SELECTED, got {result.error_kind}"
        )
        assert result.clone_successful is False

    @pytest.mark.asyncio
    async def test_import_repository_handles_clone_failure(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/myrepo")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/myrepo")
        svc_with_tm.select_repository(repo_hash)

        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.communicate.return_value = (
            "",
            "fatal: could not read from remote repository",
        )

        with patch("subprocess.Popen", return_value=mock_proc):
            request = RepositoryIntakeRequest(
                repository_hash=repo_hash,
                owner="owner",
                repo="myrepo",
                local_workspace_root=str(tmp_path),
            )
            result = svc_with_tm.import_repository(request)

        assert result.intake_state == IntakeState.FAILED.value
        assert result.error_kind == WorkspaceErrorKind.IMPORT_FAILED
        assert result.clone_successful is False
        assert "could not read" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_import_repository_handles_clone_timeout(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        import subprocess as _sp

        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/myrepo")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/myrepo")
        svc_with_tm.select_repository(repo_hash)

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = _sp.TimeoutExpired(
            cmd="git clone", timeout=120
        )

        with patch("subprocess.Popen", return_value=mock_proc):
            request = RepositoryIntakeRequest(
                repository_hash=repo_hash,
                owner="owner",
                repo="myrepo",
                local_workspace_root=str(tmp_path),
            )
            result = svc_with_tm.import_repository(request)

        assert result.intake_state == IntakeState.FAILED.value
        assert result.error_kind == WorkspaceErrorKind.IMPORT_FAILED
        assert "timed out" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_import_repository_refuses_missing_owner_repo(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(
            json=_make_repos_response([
                {**_make_repo_item(1, "owner/repo"), "owner": {"login": ""}}
            ])
        )

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/repo")
        svc_with_tm.select_repository(repo_hash)

        request = RepositoryIntakeRequest(
            repository_hash=repo_hash,
            owner="",
            repo="",
            local_workspace_root=str(tmp_path),
        )
        result = svc_with_tm.import_repository(request)

        assert result.intake_state == IntakeState.FAILED.value
        assert "Owner and repo name required" in (result.error_message or "")
        assert result.clone_successful is False

    @pytest.mark.asyncio
    async def test_import_repository_clone_generic_exception(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/myrepo")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/myrepo")
        svc_with_tm.select_repository(repo_hash)

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.side_effect = OSError("No space left on device")

            request = RepositoryIntakeRequest(
                repository_hash=repo_hash,
                owner="owner",
                repo="myrepo",
                local_workspace_root=str(tmp_path),
            )
            result = svc_with_tm.import_repository(request)

        assert result.intake_state == IntakeState.FAILED.value
        assert result.error_kind == WorkspaceErrorKind.UNKNOWN
        assert "No space left on device" in (result.error_message or "")


# ── Gridline Projection Tests ───────────────────────────────────────────


class TestGridlineProjection:
    @pytest.mark.asyncio
    async def test_build_gridline_projection_is_content_light(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/repo1")]))

        await svc_with_tm.discover_repositories()
        svc_with_tm.connect()

        projection = svc_with_tm.build_gridline_projection()
        projection_json = projection.model_dump_json()

        parsed: dict = json.loads(projection_json)
        assert parsed["schema_version"] == "rig.relay.developer_github_workspace.v1"

        for pat in ["ghp_", "ghs_", "gho_", "ghu_", "ghr_", "github_pat_"]:
            assert pat not in projection_json, f"Token pattern '{pat}' in projection"

        assert "access_token" not in projection_json
        assert "private_key" not in projection_json
        assert "client_secret" not in projection_json

    @pytest.mark.asyncio
    async def test_build_gridline_projection_reflects_selected_count(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(
            json=_make_repos_response([
                _make_repo_item(1, "orgA/repo1"),
                _make_repo_item(2, "orgA/repo2"),
                _make_repo_item(3, "orgA/repo3"),
            ])
        )

        await svc_with_tm.discover_repositories()
        svc_with_tm.select_repository(hash_identifier("orgA/repo1"))
        svc_with_tm.select_repository(hash_identifier("orgA/repo2"))
        svc_with_tm.connect()

        projection = svc_with_tm.build_gridline_projection()
        assert projection.selected_count == 2
        assert projection.total_discovered == 3
        assert projection.imported_count == 0
        assert len(projection.repositories) == 3

    @pytest.mark.asyncio
    async def test_build_gridline_projection_when_disconnected_has_no_repos(
        self, svc_no_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        connection = svc_no_tm.connect()
        assert connection.connection_state == ConnectionState.DISCONNECTED.value

        projection = svc_no_tm.build_gridline_projection()
        assert projection.total_discovered == 0
        assert projection.selected_count == 0
        assert projection.imported_count == 0


# ── Token Secrecy Tests ─────────────────────────────────────────────────


class TestTokenSecrecy:
    @pytest.mark.asyncio
    async def test_connection_projection_contains_no_raw_token(
        self, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        conn = svc_with_tm.connect()
        conn_json = conn.model_dump_json()

        assert "ghs_test_valid" not in conn_json
        assert "test_token" not in conn_json
        for pat in ["ghp_", "ghs_", "gho_", "ghu_", "ghr_", "github_pat_"]:
            assert pat not in conn_json, f"Token pattern '{pat}' in connection JSON"

        assert "access_token" not in conn_json
        assert "private_key" not in conn_json

    @pytest.mark.asyncio
    async def test_gridline_projection_contains_no_token(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/repo1")]))

        await svc_with_tm.discover_repositories()
        svc_with_tm.connect()

        projection = svc_with_tm.build_gridline_projection()
        projection_json = projection.model_dump_json()

        assert "ghs_test_valid" not in projection_json
        for pat in ["ghp_", "ghs_", "gho_", "ghu_", "ghr_", "github_pat_"]:
            assert pat not in projection_json, f"Token pattern '{pat}' in projection"

    @pytest.mark.asyncio
    async def test_clone_subprocess_argv_contains_no_token(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        """The spawned git clone process argv must contain no raw token.
        Token transport is via os.pipe + pass_fds, not embedded in URL/argv.
        """
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/myrepo")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/myrepo")
        svc_with_tm.select_repository(repo_hash)

        clone_target = tmp_path / "owner-myrepo"
        captured_popen_args: list[list[str]] = []
        captured_popen_kwargs: list[dict] = []

        def _fake_popen(args, **kwargs):
            captured_popen_args.append(list(args))
            captured_popen_kwargs.append(dict(kwargs))
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = ("", "")
            return mock_proc

        with patch("subprocess.Popen", side_effect=_fake_popen):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = _fake_git_run(clone_target)

                request = RepositoryIntakeRequest(
                    repository_hash=repo_hash,
                    owner="owner",
                    repo="myrepo",
                    local_workspace_root=str(tmp_path),
                )
                svc_with_tm.import_repository(request)

        assert len(captured_popen_args) > 0, (
            "Expected subprocess.Popen calls during clone"
        )
        for argv in captured_popen_args:
            argv_str = " ".join(argv)
            assert "x-access-token" not in argv_str, (
                f"Token found in Popen args: {argv_str}"
            )
            assert "ghs_test_valid" not in argv_str, (
                f"Token found in Popen args: {argv_str}"
            )
            # Clone URL must be anonymous
            for arg in argv:
                assert "x-access-token:" not in arg, (
                    f"Token in clone URL argument: {arg}"
                )

        # Verify pipe-based transport: pass_fds is set and env has RIG_GIT_TOKEN_FD
        for kwargs in captured_popen_kwargs:
            assert "pass_fds" in kwargs, "Expected pass_fds for pipe transport"
            env = kwargs.get("env", {})
            assert "RIG_GIT_TOKEN_FD" in env, "Expected RIG_GIT_TOKEN_FD in env"
            assert env["GIT_TERMINAL_PROMPT"] == "0"
            assert env.get("GIT_ASKPASS")
            # Token must not be in any env value
            for key, val in env.items():
                assert "ghs_test_valid" not in str(val), f"Token in env var {key}={val}"

    @pytest.mark.asyncio
    async def test_clone_result_remote_url_is_anonymous(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        """After clone, the persisted remote URL must contain no token."""
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/myrepo")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/myrepo")
        svc_with_tm.select_repository(repo_hash)

        clone_target = tmp_path / "owner-myrepo"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = _fake_git_run(clone_target)

                request = RepositoryIntakeRequest(
                    repository_hash=repo_hash,
                    owner="owner",
                    repo="myrepo",
                    local_workspace_root=str(tmp_path),
                )
                result = svc_with_tm.import_repository(request)

        assert result.remote_url_sanitized is True
        assert result.clone_successful is True
        # The result must not contain token-bearing fields
        result_json = result.model_dump_json()
        assert "x-access-token" not in result_json
        assert "ghs_test_valid" not in result_json

    @pytest.mark.asyncio
    async def test_sync_uses_safe_credential_path(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        """Synchronize must use GIT_ASKPASS + pipe, not token-in-URL."""
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/myrepo")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/myrepo")
        svc_with_tm.select_repository(repo_hash)

        clone_target = tmp_path / "owner-myrepo"
        captured_sync_popen_args: list[list[str]] = []
        captured_sync_popen_kwargs: list[dict] = []

        # Step 1: Import (clone) with Popen mock
        mock_clone_proc = MagicMock()
        mock_clone_proc.returncode = 0
        mock_clone_proc.communicate.return_value = ("", "")

        with patch("subprocess.Popen", return_value=mock_clone_proc):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = _fake_git_run(clone_target)

                intake = RepositoryIntakeRequest(
                    repository_hash=repo_hash,
                    owner="owner",
                    repo="myrepo",
                    local_workspace_root=str(tmp_path),
                )
                svc_with_tm.import_repository(intake)

        # Step 2: Synchronize with Popen mock for fetch
        from rig_relay.integrations.github_provider._workspace_models import (
            RepositorySyncRequest,
        )

        def _fake_popen_for_sync(args, **kwargs):
            captured_sync_popen_args.append(list(args))
            captured_sync_popen_kwargs.append(dict(kwargs))
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = ("", "")
            return mock_proc

        with patch("subprocess.Popen", side_effect=_fake_popen_for_sync):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = _fake_git_run(clone_target)

                sync = RepositorySyncRequest(
                    repository_hash=repo_hash, local_path=str(clone_target)
                )
                svc_with_tm.synchronize_repository(sync)

        fetch_calls = [
            argv for argv in captured_sync_popen_args if "fetch" in argv[0] if argv
        ]
        for argv in fetch_calls:
            argv_str = " ".join(argv)
            assert "x-access-token" not in argv_str, (
                f"Token in fetch subprocess args: {argv_str}"
            )
            assert "ghs_test_valid" not in argv_str, (
                f"Token in fetch subprocess args: {argv_str}"
            )

        # Verify pipe transport is used for fetch
        for kwargs in captured_sync_popen_kwargs:
            env = kwargs.get("env", {})
            assert "RIG_GIT_TOKEN_FD" in env, "Expected pipe transport for fetch"

    @pytest.mark.asyncio
    async def test_error_paths_do_not_surface_token(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        """Clone failure must not include the token in error messages."""
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/myrepo")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/myrepo")
        svc_with_tm.select_repository(repo_hash)

        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.communicate.return_value = (
            "",
            "fatal: could not read from remote repository\n",
        )

        with patch("subprocess.Popen", return_value=mock_proc):
            request = RepositoryIntakeRequest(
                repository_hash=repo_hash,
                owner="owner",
                repo="myrepo",
                local_workspace_root=str(tmp_path),
            )
            result = svc_with_tm.import_repository(request)

        assert result.error_message is not None
        assert "ghs_test_valid" not in (result.error_message or "")
        assert "x-access-token" not in (result.error_message or "")
        assert result.intake_state == IntakeState.FAILED.value

    @pytest.mark.asyncio
    async def test_discovery_output_contains_no_token(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        """Repository discovery output must contain no raw token."""
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/repo1")]))

        result = await svc_with_tm.discover_repositories()
        result_json = result.model_dump_json()

        assert "ghs_test_valid" not in result_json
        for pat in ["ghp_", "ghs_", "gho_", "ghu_", "ghr_", "github_pat_"]:
            assert pat not in result_json, f"Token pattern '{pat}' in discovery result"

    @pytest.mark.asyncio
    async def test_negative_prevent_token_in_url_clone(self, tmp_path: Path) -> None:
        """Structural negative test: the import_repository method must
        never construct an authenticated URL with embedded token.
        """
        import inspect

        from rig_relay.integrations.github_provider._developer_workspace import (
            DeveloperGitHubWorkspaceService,
        )

        source = inspect.getsource(DeveloperGitHubWorkspaceService.import_repository)
        assert "x-access-token:" not in source, (
            "import_repository source contains token-in-URL pattern"
        )
        assert 'f"https://x-access-token:' not in source, (
            "import_repository source contains token-in-URL construction"
        )
        assert "authenticated_url" not in source or (
            "authenticated_url" not in source.split("anonymous_url")[0]
            if "anonymous_url" in source
            else True
        ), "import_repository constructs an authenticated_url with embedded token"

        sync_source = inspect.getsource(
            DeveloperGitHubWorkspaceService.synchronize_repository
        )
        assert "x-access-token:" not in sync_source, (
            "synchronize_repository source contains token-in-URL pattern"
        )

        # Also verify _run_git_with_token source is token-free in URL construction
        git_token_source = inspect.getsource(
            DeveloperGitHubWorkspaceService._run_git_with_token
        )
        assert "x-access-token:" not in git_token_source, (
            "_run_git_with_token source contains token-in-URL pattern"
        )

    @pytest.mark.asyncio
    async def test_repository_descriptor_has_no_token_in_clone_url(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(
            json=_make_repos_response([
                {
                    "id": 1,
                    "name": "repo1",
                    "full_name": "owner/repo1",
                    "owner": {"login": "owner"},
                    "visibility": "public",
                    "default_branch": "main",
                    "has_pages": False,
                    "clone_url": "https://github.com/owner/repo1.git",
                    "html_url": "https://github.com/owner/repo1",
                    "private": False,
                    "description": "",
                    "pushed_at": None,
                }
            ])
        )

        await svc_with_tm.discover_repositories()

        repos = svc_with_tm.discovered_repos
        for repo in repos.values():
            clone = repo.clone_url
            assert "x-access-token" not in clone, f"Token in clone_url: {clone}"
            assert "@" not in clone, f"Credentials in clone_url: {clone}"
            assert "ghs_" not in clone, f"Token prefix in clone_url: {clone}"

    @pytest.mark.asyncio
    async def test_connection_install_id_is_hashed_not_raw(
        self, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        conn = svc_with_tm.connect()
        assert conn.installation_id_hash != ""
        assert "456" not in conn.installation_id_hash
        assert conn.installation_id_hash == hash_identifier("456")

    @pytest.mark.asyncio
    async def test_discover_repositories_token_not_in_result(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/repo1")]))

        result = await svc_with_tm.discover_repositories()
        result_json = result.model_dump_json()

        assert "ghs_test_valid" not in result_json
        for pat in ["ghp_", "ghs_", "gho_", "ghu_", "ghr_", "github_pat_"]:
            assert pat not in result_json, f"Token pattern '{pat}' in discovery result"

    @pytest.mark.asyncio
    async def test_askpass_script_contains_no_token(self) -> None:
        """The token-free askpass source must not contain any hardcoded GitHub token.
        The literal 'x-access-token' is the PAT *username* convention (printed for
        Git when it asks for a username), not a secret. Only actual token patterns
        (ghs_, ghp_, etc.) must be absent.
        """
        source = DeveloperGitHubWorkspaceService._GIT_ASKPASS_SOURCE
        assert "ghs_" not in source, "GIT_ASKPASS_SOURCE contains token prefix ghs_"
        assert "ghp_" not in source, "GIT_ASKPASS_SOURCE contains token prefix ghp_"
        assert "gho_" not in source, "GIT_ASKPASS_SOURCE contains token prefix gho_"
        assert "ghu_" not in source, "GIT_ASKPASS_SOURCE contains token prefix ghu_"
        assert "ghr_" not in source, "GIT_ASKPASS_SOURCE contains token prefix ghr_"
        # x-access-token is the PAT username convention — it appears as a print
        # statement and is intentionally present, not a secret.
        assert "RIG_GIT_TOKEN_FD" in source, (
            "GIT_ASKPASS_SOURCE must reference RIG_GIT_TOKEN_FD"
        )
        assert "os.read(fd" in source, (
            "GIT_ASKPASS_SOURCE must read token from inherited fd"
        )
        # Verify it's a valid Python script
        assert "#!/usr/bin/env python3" in source
        assert "import sys, os" in source or "import sys" in source

    @pytest.mark.asyncio
    async def test_pipe_transport_no_tempfile_token(
        self,
        respx_mock: respx.MockRouter,
        svc_with_tm: DeveloperGitHubWorkspaceService,
        tmp_path: Path,
    ) -> None:
        """Verify that _run_git_with_token uses pipe transport, not
        tempfile-stored token. The token must only appear on the pipe's
        write end, never in a tempfile.
        """
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/myrepo")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/myrepo")
        svc_with_tm.select_repository(repo_hash)

        clone_target = tmp_path / "owner-myrepo"

        # Intercept os.write to track what's written to file descriptors
        import os as _os

        _real_os_write = _os.write
        _fd_askpass_written: list[int] = []  # track askpass fd
        _pipe_writes: list[tuple[int, bytes]] = []

        def _fake_os_write(fd: int, data: bytes) -> int:
            result = _real_os_write(fd, data)
            _pipe_writes.append((fd, data))
            return result

        # Also intercept mkstemp to record askpass fd
        _real_mkstemp = __import__("tempfile").mkstemp
        _askpass_fds: list[int] = []

        def _fake_mkstemp(*args, **kwargs):
            fd, path = _real_mkstemp(*args, **kwargs)
            _askpass_fds.append(fd)
            return fd, path

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")

        with patch("os.write", side_effect=_fake_os_write):
            with patch("tempfile.mkstemp", side_effect=_fake_mkstemp):
                with patch("subprocess.Popen", return_value=mock_proc):
                    with patch("subprocess.run") as mock_run:
                        mock_run.side_effect = _fake_git_run(clone_target)

                        request = RepositoryIntakeRequest(
                            repository_hash=repo_hash,
                            owner="owner",
                            repo="myrepo",
                            local_workspace_root=str(tmp_path),
                        )
                        result = svc_with_tm.import_repository(request)

        assert result.clone_successful is True

        # The token must appear in at least one pipe write (write_fd side of os.pipe)
        token_writes = [
            (fd, data) for fd, data in _pipe_writes if b"ghs_test_valid" in data
        ]
        assert len(token_writes) >= 1, "Token must be written to the pipe"

        # The askpass fd (from mkstemp) must only contain the askpass script,
        # never the raw token
        askpass_writes = [
            data
            for fd, data in _pipe_writes
            if fd in _askpass_fds and b"ghs_test_valid" in data
        ]
        assert len(askpass_writes) == 0, (
            "Token must not be written to the askpass tempfile fd"
        )


# ── Discovery and Connection Interaction Tests ──────────────────────────


class TestDiscoveryConnectionInteraction:
    @pytest.mark.asyncio
    async def test_connection_updates_after_discovery(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(
            json=_make_repos_response([
                _make_repo_item(1, "a/b"),
                _make_repo_item(2, "c/d"),
            ])
        )

        await svc_with_tm.discover_repositories()
        conn = svc_with_tm.connect()

        assert conn.accessible_repository_count == 2

    @pytest.mark.asyncio
    async def test_discovery_preserves_selection_state(
        self, respx_mock: respx.MockRouter, svc_with_tm: DeveloperGitHubWorkspaceService
    ) -> None:
        respx_mock.get(
            url__startswith=f"{GITHUB_API_BASE}/installation/repositories"
        ).respond(json=_make_repos_response([_make_repo_item(1, "owner/repo1")]))

        await svc_with_tm.discover_repositories()
        repo_hash = hash_identifier("owner/repo1")
        svc_with_tm.select_repository(repo_hash)

        await svc_with_tm.discover_repositories()
        repos = svc_with_tm.discovered_repos
        assert repos[repo_hash].selected is True


# ── Model Tests ──────────────────────────────────────────────────────────


class TestModels:
    @pytest.mark.asyncio
    async def test_repository_compute_identity_digest_is_sha256(self) -> None:
        from rig_relay.integrations.github_provider._workspace_models import (
            DeveloperGitHubRepository,
        )

        repo = DeveloperGitHubRepository(owner="owner", name="repo")
        digest = repo.compute_identity_digest()
        assert digest.startswith("sha256:")
        assert len(digest) == 71

    @pytest.mark.asyncio
    async def test_projection_compute_digest_is_sha256(self) -> None:
        projection = GitHubWorkspaceProjection()
        digest = projection.compute_digest()
        assert digest.startswith("sha256:")
        assert len(digest) == 71

    @pytest.mark.asyncio
    async def test_projection_digest_excludes_generated_at(self) -> None:
        proj1 = GitHubWorkspaceProjection(
            total_discovered=5, selected_count=2, generated_at="2026-01-01T00:00:00Z"
        )
        proj2 = GitHubWorkspaceProjection(
            total_discovered=5, selected_count=2, generated_at="2026-12-31T23:59:59Z"
        )
        assert proj1.compute_digest() == proj2.compute_digest()


# ── Helpers ─────────────────────────────────────────────────────────────


def _fake_git_run(target_dir: Path):
    """Return a MagicMock side_effect sequence for post-clone git operations.

    Used with subprocess.run mock only. Clone/fetch now uses Popen
    (via _run_git_with_token) and is mocked separately.
    """

    def _side_effect(*args, **kwargs):
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / ".git").mkdir(parents=True, exist_ok=True)
        (target_dir / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

        cmd = args[0] if args else []
        cmd_str: str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "rev-parse HEAD" in cmd_str:
            return MagicMock(returncode=0, stdout="abc123def456\n", stderr="")
        elif "--abbrev-ref" in cmd_str:
            return MagicMock(returncode=0, stdout="main\n", stderr="")
        elif "rev-parse origin" in cmd_str:
            return MagicMock(returncode=0, stdout="def789abc123\n", stderr="")
        elif "rev-list" in cmd_str and "HEAD.." in cmd_str:
            return MagicMock(returncode=0, stdout="3\n", stderr="")
        elif "rev-list" in cmd_str:
            return MagicMock(returncode=0, stdout="0\n", stderr="")
        elif "set-url" in cmd_str:
            return MagicMock(returncode=0, stderr="")
        # Default: signal success with empty output
        return MagicMock(returncode=0, stdout="", stderr="")

    return _side_effect
