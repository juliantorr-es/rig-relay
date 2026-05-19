"""Live GitHub auth — real JWT signing, token exchange, and read-only smoke tests.

Content-light by design: no raw tokens, secrets, or API responses are ever
returned. Only SHA-256 hashes and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import re
from typing import Any

from rig_relay.integrations.github_provider._redaction import hash_identifier

_GITHUB_API_BASE = "https://api.github.com"
_GITHUB_TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
_GITHUB_INSTALLATION_TOKEN_ENDPOINT = (
    "https://api.github.com/app/installations/{installation_id}/access_tokens"
)

_RSA_KEY_HEADER_RE = re.compile(rb"^-{5}BEGIN (RSA )?PRIVATE KEY-{5}")


class GitHubLiveAuthError(Exception):
    """Raised when live GitHub auth operations fail."""


@dataclass
class GitHubLiveAuthConfig:
    """Live auth config loaded from environment + local config.

    Fields correspond to env vars:
      RIG_GITHUB_APP_ID
      RIG_GITHUB_INSTALLATION_ID
      RIG_GITHUB_PRIVATE_KEY_PATH
      RIG_GITHUB_PRIVATE_KEY_ENV
      RIG_GITHUB_CLIENT_ID
      RIG_GITHUB_CLIENT_SECRET
      RIG_GITHUB_REDIRECT_URI
    """

    app_id: int | None = None
    installation_id: int | None = None
    private_key_path: str | None = None
    private_key_env: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None

    @classmethod
    def from_environment(cls) -> GitHubLiveAuthConfig:
        return cls(
            app_id=_env_int("RIG_GITHUB_APP_ID"),
            installation_id=_env_int("RIG_GITHUB_INSTALLATION_ID"),
            private_key_path=os.environ.get("RIG_GITHUB_PRIVATE_KEY_PATH"),
            private_key_env=os.environ.get("RIG_GITHUB_PRIVATE_KEY_ENV"),
            client_id=os.environ.get(
                "RIG_GITHUB_CLIENT_ID", os.environ.get("RIG_RELAY_GITHUB_CLIENT_ID")
            ),
            client_secret=os.environ.get(
                "RIG_GITHUB_CLIENT_SECRET",
                os.environ.get("RIG_RELAY_GITHUB_CLIENT_SECRET"),
            ),
            redirect_uri=os.environ.get("RIG_GITHUB_REDIRECT_URI"),
        )

    def is_configured(self) -> bool:
        """True if enough config exists for ANY auth mode."""
        return self._has_app_auth() or self._has_oauth_auth()

    def _has_app_auth(self) -> bool:
        return (
            self.app_id is not None
            and self.installation_id is not None
            and self._has_private_key()
        )

    def _has_oauth_auth(self) -> bool:
        return self.client_id is not None and self.client_secret is not None

    def _has_private_key(self) -> bool:
        if self.private_key_env:
            return True
        if self.private_key_path:
            key_path = Path(self.private_key_path)
            return key_path.exists() and key_path.is_file()
        return False

    def config_summary(self) -> dict[str, Any]:
        """Content-light config summary. NEVER returns raw secrets."""
        return {
            "app_id_configured": self.app_id is not None,
            "installation_id_configured": self.installation_id is not None,
            "private_key_source": self._private_key_source(),
            "private_key_present": self._has_private_key(),
            "client_id_configured": self.client_id is not None,
            "client_secret_configured": self.client_secret is not None,
            "redirect_uri_configured": self.redirect_uri is not None,
            "app_auth_possible": self._has_app_auth(),
            "oauth_auth_possible": self._has_oauth_auth(),
            "any_auth_configured": self.is_configured(),
        }

    def _private_key_source(self) -> str:
        if self.private_key_env:
            return "env_var"
        if self.private_key_path:
            key_path = Path(self.private_key_path)
            return "file" if (key_path.exists() and key_path.is_file()) else "missing"
        return "none"

    def load_private_key(self) -> bytes:
        """Load private key bytes from env or file. Returns content-light result."""
        if self.private_key_env:
            raw = self.private_key_env.encode("utf-8")
            if not _RSA_KEY_HEADER_RE.match(raw):
                raise GitHubLiveAuthError(
                    "private_key_env does not appear to be a PEM-encoded private key"
                )
            return raw
        if self.private_key_path:
            key_path = Path(self.private_key_path)
            if not key_path.exists() or not key_path.is_file():
                raise GitHubLiveAuthError(
                    f"private_key_path does not exist or is not a file: {self.private_key_path}"
                )
            raw = key_path.read_bytes()
            if not _RSA_KEY_HEADER_RE.match(raw):
                raise GitHubLiveAuthError(
                    f"private_key_path file does not appear to be a PEM-encoded private key: {self.private_key_path}"
                )
            return raw
        raise GitHubLiveAuthError("no private key configured")


class GitHubLiveJwtSigner:
    """Signs GitHub App JWTs using RS256 with a real RSA private key.

    Lazily imports PyJWT via importlib. Raises GitHubLiveAuthError if the
    library is unavailable or the private key is missing.
    """

    def __init__(self, private_key_bytes: bytes) -> None:
        self._private_key_bytes = private_key_bytes

    def sign(self, claims: dict[str, Any]) -> str:
        jwt_module = _import_jwt()
        try:
            return jwt_module.encode(
                claims,
                self._private_key_bytes,
                algorithm="RS256",
                headers={"alg": "RS256", "typ": "JWT"},
            )
        except Exception as e:
            raise GitHubLiveAuthError(f"Failed to sign JWT: {e}") from e

    def __call__(self, claims: dict[str, Any]) -> str:
        return self.sign(claims)


class GitHubLiveTokenExchanger:
    """Makes real HTTP calls to GitHub's token endpoints.

    Content-light output: never returns raw tokens. Returns SHA-256 hashes
    and metadata only.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def exchange_installation_token(
        self, app_id: int, installation_id: int, private_key_bytes: bytes
    ) -> tuple[dict[str, Any], str]:
        """Exchange a GitHub App JWT for an installation access token.

        Returns (content-light dict, raw_token). NEVER returns raw token in dict.
        """
        signer = GitHubLiveJwtSigner(private_key_bytes)
        now = int(datetime.now(UTC).timestamp())
        jwt_claims: dict[str, Any] = {
            "iat": now - 60,
            "exp": now + 600,
            "iss": str(app_id),
        }
        jwt_token = signer(jwt_claims)

        url = _GITHUB_INSTALLATION_TOKEN_ENDPOINT.format(
            installation_id=installation_id
        )

        token_response = _post_json(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=self._timeout,
        )

        token = token_response.get("token", "")
        return _redact_token_response(token_response, token, kind="installation"), token

    def exchange_oauth_code(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        code_verifier: str | None = None,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        """Exchange an OAuth authorization code for an access token.

        Returns content-light dict. NEVER returns raw token.
        """
        data: dict[str, str] = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
        }
        if code_verifier is not None:
            data["code_verifier"] = code_verifier
        if redirect_uri is not None:
            data["redirect_uri"] = redirect_uri

        token_response = _post_json(
            _GITHUB_TOKEN_ENDPOINT,
            data=data,
            headers={"Accept": "application/json"},
            timeout=self._timeout,
        )

        token = token_response.get("access_token", "")
        return _redact_token_response(token_response, token, kind="oauth")


class GitHubLiveReadOnlySmoke:
    """Safe read-only GitHub API calls. Content-light output only."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def inspect_identity(self, token: str) -> dict[str, Any]:
        """Check token type and return content-light identity.

        Calls /user for OAuth/token, /app for installation tokens.
        """
        httpx = _import_httpx()
        try:
            user_response = _get_json(
                f"{_GITHUB_API_BASE}/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                return {
                    "error": "identity_inspect_failed",
                    "error_description": f"HTTP {e.response.status_code}",
                }
            raise GitHubLiveAuthError(f"HTTP {e.response.status_code}") from e

        login = user_response.get("login", "")
        user_type = user_response.get("type", "")

        if user_type == "Bot":
            return {
                "identity_type": "installation",
                "login_hash": hash_identifier(login),
                "type": user_type,
                "node_id_hash": hash_identifier(user_response.get("node_id", "")),
            }

        return {
            "identity_type": "user",
            "login_hash": hash_identifier(login),
            "type": user_type,
            "node_id_hash": hash_identifier(user_response.get("node_id", "")),
        }

    def list_accessible_repos(self, token: str) -> list[dict[str, Any]]:
        """List repos accessible to this token.

        Tries installation repos first, falls back to user repos.
        Content-light: repo names are hashed.
        """
        httpx = _import_httpx()
        try:
            user_response = _get_json(
                f"{_GITHUB_API_BASE}/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                # We can't identify if it's user or bot, but we can assume user since /user failed.
                user_response = {"type": "Unknown"}
            else:
                raise GitHubLiveAuthError(f"HTTP {e.response.status_code}") from e

        user_type = user_response.get("type", "")

        if user_type == "Bot":
            return self._list_installation_repos(token)
        return self._list_user_repos(token)

    def _list_installation_repos(self, token: str) -> list[dict[str, Any]]:
        httpx = _import_httpx()
        try:
            repos_response = _get_json(
                f"{_GITHUB_API_BASE}/installation/repositories",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise GitHubLiveAuthError(f"HTTP {e.response.status_code}") from e
            raise GitHubLiveAuthError(f"HTTP {e.response.status_code}") from e

        return [_redact_repo(repo) for repo in repos_response.get("repositories", [])]

    def _list_user_repos(self, token: str) -> list[dict[str, Any]]:
        httpx = _import_httpx()
        try:
            repos_response = _get_json(
                f"{_GITHUB_API_BASE}/user/repos",
                params={"per_page": "100", "sort": "updated"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise GitHubLiveAuthError(f"HTTP {e.response.status_code}") from e
            raise GitHubLiveAuthError(f"HTTP {e.response.status_code}") from e

        return [_redact_repo(repo) for repo in repos_response if isinstance(repo, dict)]


def _redact_repo(repo: dict[str, Any]) -> dict[str, Any]:
    return {
        "name_hash": hash_identifier(repo.get("full_name", repo.get("name", ""))),
        "private": bool(repo.get("private", False)),
        "permissions_summary": _summarize_permissions(repo.get("permissions", {})),
        "owner_type": (
            repo.get("owner", {}).get("type", "unknown")
            if isinstance(repo.get("owner"), dict)
            else "unknown"
        ),
    }


def _summarize_permissions(permissions: dict[str, bool]) -> dict[str, bool]:
    return {k: bool(v) for k, v in permissions.items() if isinstance(v, bool)}


def _redact_token_response(
    response: dict[str, Any], token: str, kind: str
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "token_hash": hash_identifier(token) if token else "",
        "token_prefix": token[:8] if token else "",
        "expires_at": response.get("expires_at", datetime.now(UTC).isoformat()),
        "kind": kind,
    }

    perms = response.get("permissions")
    if isinstance(perms, dict):
        result["permissions"] = dict(perms)

    repo_sel = response.get("repository_selection")
    if repo_sel:
        result["repository_selection"] = str(repo_sel)

    scopes = response.get("scope")
    if scopes:
        result["scopes"] = str(scopes).split()

    return result


def _import_jwt() -> Any:
    from importlib import import_module

    try:
        return import_module("jwt")
    except ImportError as e:
        raise GitHubLiveAuthError(
            "PyJWT library is required for live GitHub App auth. Install with: uv add pyjwt"
        ) from e


def _import_httpx() -> Any:
    from importlib import import_module

    try:
        return import_module("httpx")
    except ImportError as e:
        raise GitHubLiveAuthError(
            "httpx library is required for live GitHub API calls."
        ) from e


def _post_json(
    url: str,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    httpx = _import_httpx()
    response = httpx.post(
        url, json=data, headers=headers or {}, timeout=httpx.Timeout(timeout)
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def _get_json(
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    httpx = _import_httpx()
    response = httpx.get(
        url, headers=headers or {}, params=params, timeout=httpx.Timeout(timeout)
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


__all__ = [
    "GitHubLiveAuthConfig",
    "GitHubLiveAuthError",
    "GitHubLiveJwtSigner",
    "GitHubLiveReadOnlySmoke",
    "GitHubLiveTokenExchanger",
]
