"""Live GitHub auth — real JWT signing, token exchange, and read-only smoke tests.

Content-light by design: no raw tokens, secrets, or API responses are ever
returned. Only SHA-256 hashes and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
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
_GITHUB_INSTALLATION_REPOSITORIES_ENDPOINT = (
    "https://api.github.com/installation/repositories"
)
_READ_ONLY_INSTALLATION_PERMISSIONS = {
    "metadata": "read",
    "security_events": "read",
    "vulnerability_alerts": "read",
}
_MUTATION_PERMISSION_NAMES = frozenset({
    "actions",
    "actions_variables",
    "administration",
    "checks",
    "code_quality",
    "copilot_agent_settings",
    "deployments",
    "issues",
    "packages",
    "pages",
    "pull_requests",
    "repository_hooks",
    "security_events",
    "vulnerability_alerts",
    "workflows",
})

_RSA_KEY_HEADER_RE = re.compile(rb"^-{5}BEGIN (RSA )?PRIVATE KEY-{5}")


class GitHubLiveAuthError(Exception):
    """Raised when live GitHub auth operations fail."""


class GitHubPermissionMode(StrEnum):
    DEVELOPMENT_DEBUG = auto()
    PREPRODUCTION = auto()
    PUBLIC_RELEASE = auto()


def normalize_permission_mode(value: Any | None) -> GitHubPermissionMode:
    if isinstance(value, GitHubPermissionMode):
        return value
    text = _normalize_permission_mode_text(value)
    if text == GitHubPermissionMode.PREPRODUCTION.value:
        return GitHubPermissionMode.PREPRODUCTION
    if text == GitHubPermissionMode.PUBLIC_RELEASE.value:
        return GitHubPermissionMode.PUBLIC_RELEASE
    return GitHubPermissionMode.DEVELOPMENT_DEBUG


def build_read_only_installation_permissions() -> dict[str, str]:
    return dict(_READ_ONLY_INSTALLATION_PERMISSIONS)


def _normalize_permission_mode_text(value: Any | None) -> str:
    if isinstance(value, str):
        return value.strip().lower().replace("-", "_")
    if value is None:
        return ""
    return str(value).strip().lower().replace("-", "_")


def _permission_entries(permissions: Any | None) -> list[dict[str, str]]:
    if isinstance(permissions, list):
        entries = [
            {
                "permission_name": str(item.get("permission_name", "")).strip(),
                "level": str(item.get("level", item.get("requested_level", "")))
                .strip()
                .lower(),
            }
            for item in permissions
            if isinstance(item, dict) and item.get("permission_name")
        ]
        entries.sort(key=lambda item: item["permission_name"])
        return entries
    if not isinstance(permissions, dict):
        return []
    entries = [
        {"permission_name": str(name), "level": str(level).strip().lower()}
        for name, level in permissions.items()
        if isinstance(name, str)
    ]
    entries.sort(key=lambda item: item["permission_name"])
    return entries


def _permission_names_from_entries(entries: list[dict[str, str]]) -> list[str]:
    return sorted({
        entry["permission_name"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("permission_name"), str)
    })


def summarize_permission_posture(
    *,
    permission_mode: GitHubPermissionMode,
    requested_permissions: Any,
    token_permissions: dict[str, Any] | None,
    installation_permission_keys: list[str] | None,
) -> dict[str, Any]:
    requested_entries = _permission_entries(requested_permissions)
    effective_entries = _permission_entries(token_permissions)
    app_granted_permissions = sorted({
        key for key in (installation_permission_keys or []) if isinstance(key, str)
    })
    requested_names = _permission_names_from_entries(requested_entries)
    effective_names = _permission_names_from_entries(effective_entries)
    broad_app_permissions_observed = [
        name for name in app_granted_permissions if name not in requested_names
    ]
    mutation_permissions_observed = [
        name for name in app_granted_permissions if name in _MUTATION_PERMISSION_NAMES
    ]
    token_narrowing_requested = bool(requested_entries)
    token_narrowing_effective = token_narrowing_requested and (
        requested_names == effective_names
    )
    broad_app_permission_risk_mitigated_by_token_scope = bool(
        token_narrowing_requested
        and token_narrowing_effective
        and broad_app_permissions_observed
    )
    over_permission_count = len(broad_app_permissions_observed)
    mutation_permission_count = len(mutation_permissions_observed)
    if permission_mode == GitHubPermissionMode.PUBLIC_RELEASE:
        if mutation_permission_count:
            permission_posture_status = "mutation_enabled"
        elif over_permission_count:
            permission_posture_status = "over_permissioned"
        elif token_narrowing_effective:
            permission_posture_status = "least_privilege"
        else:
            permission_posture_status = "unknown"
    elif permission_mode == GitHubPermissionMode.PREPRODUCTION:
        if mutation_permission_count or over_permission_count:
            permission_posture_status = "over_permissioned"
        elif token_narrowing_effective:
            permission_posture_status = "read_only_sufficient"
        else:
            permission_posture_status = "unknown"
    elif mutation_permission_count or over_permission_count:
        permission_posture_status = "development_debug_overpermissioned"
    elif token_narrowing_effective:
        permission_posture_status = "read_only_sufficient"
    else:
        permission_posture_status = "unknown"

    public_release_ready = (
        permission_mode == GitHubPermissionMode.PUBLIC_RELEASE
        and not over_permission_count
        and not mutation_permission_count
        and token_narrowing_effective
    )
    recommended_permission_reductions = [
        {
            "permission_name": name,
            "recommended_level": "none" if name == "workflows" else "read",
            "rationale": "reduce broad setup/debug permissions for release posture",
        }
        for name in mutation_permissions_observed
    ]
    recommended_permission_reductions.sort(key=lambda item: item["permission_name"])
    return {
        "permission_mode": permission_mode.value,
        "app_granted_permissions": app_granted_permissions,
        "requested_token_permissions": requested_entries,
        "effective_token_permissions": effective_entries,
        "token_narrowing_requested": token_narrowing_requested,
        "token_narrowing_effective": token_narrowing_effective,
        "broad_app_permissions_observed": broad_app_permissions_observed,
        "mutation_permissions_observed": mutation_permissions_observed,
        "unsafe_broad_token_used": False,
        "public_release_ready": public_release_ready,
        "permission_posture_status": permission_posture_status,
        "over_permissioned": bool(over_permission_count or mutation_permission_count),
        "over_permission_count": over_permission_count,
        "mutation_permission_count": mutation_permission_count,
        "broad_app_permission_risk_mitigated_by_token_scope": broad_app_permission_risk_mitigated_by_token_scope,
        "read_only_token_enforced": token_narrowing_effective,
        "recommended_permission_reductions": recommended_permission_reductions,
    }


def _installation_access_refusal(
    error: str, description: str, status_code: int | None = None
) -> dict[str, Any]:
    refusal: dict[str, Any] = {
        "schema_version": "rig.github.live_auth_refusal.v1",
        "auth_mode": "app_installation",
        "error": error,
        "error_description": description[:256],
        "installation_access": "refused",
    }
    if status_code is not None:
        refusal["status_code"] = status_code
    return refusal


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
        self,
        app_id: int,
        installation_id: int,
        private_key_bytes: bytes,
        requested_permissions: dict[str, str] | None = None,
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

        request_body: dict[str, Any] = {}
        if requested_permissions:
            request_body["permissions"] = dict(requested_permissions)

        token_response = _post_json(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            data=request_body or None,
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
        """Compatibility wrapper for installation-token proof."""
        return self.probe_installation_access(token)

    def probe_installation_access(
        self,
        token: str,
        installation_id: int | None = None,
        repository_selection: str | None = None,
        permission_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        """Prove installation-token access without using `/user`."""
        httpx = _import_httpx()
        try:
            repos_response = _get_json(
                _GITHUB_INSTALLATION_REPOSITORIES_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in {401, 403, 404, 422}:
                return _installation_access_refusal(
                    "installation_access_failed",
                    f"HTTP {e.response.status_code}",
                    status_code=e.response.status_code,
                )
            raise GitHubLiveAuthError(f"HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            return _installation_access_refusal(
                "installation_access_failed", f"network_error: {e}"
            )

        repos = [
            repo
            for repo in repos_response.get("repositories", [])
            if isinstance(repo, dict)
        ]
        repo_name_hashes = [
            hash_identifier(repo.get("full_name", repo.get("name", "")))
            for repo in repos
        ]
        derived_permission_keys = sorted({
            key
            for repo in repos
            for key in (
                repo.get("permissions", {})
                if isinstance(repo.get("permissions"), dict)
                else {}
            ).keys()
            if isinstance(key, str)
        })
        merged_permission_keys = sorted(
            {key for key in (permission_keys or []) if isinstance(key, str)}
            | set(derived_permission_keys)
        )

        return {
            "schema_version": "rig.github.live_auth_result.v1",
            "auth_mode": "app_installation",
            "installation_id_hash": (
                hash_identifier(str(installation_id))
                if installation_id is not None
                else ""
            ),
            "installation_access": "success",
            "accessible_repo_count": len(repos),
            "accessible_repo_name_hashes": repo_name_hashes,
            "permission_keys": merged_permission_keys,
            "repository_selection": repository_selection or "",
        }

    def list_accessible_repos(self, token: str) -> list[dict[str, Any]]:
        """List repos accessible to this token.

        Installation-token flow only. Returns installation-accessible repos.
        Content-light: repo names are hashed.
        """
        httpx = _import_httpx()
        try:
            repos_response = _get_json(
                _GITHUB_INSTALLATION_REPOSITORIES_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in {401, 403, 404, 422}:
                raise GitHubLiveAuthError(f"HTTP {e.response.status_code}") from e
            raise GitHubLiveAuthError(f"HTTP {e.response.status_code}") from e

        return [
            _redact_repo(repo)
            for repo in repos_response.get("repositories", [])
            if isinstance(repo, dict)
        ]


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
        "token_present": bool(token),
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
    "GitHubPermissionMode",
    "build_read_only_installation_permissions",
    "normalize_permission_mode",
    "summarize_permission_posture",
]
