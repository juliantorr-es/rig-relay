"""GitHub App Installation Token Manager v1 — cached, auto-refreshing.

Wires the existing GitHubLiveTokenExchanger into a TTL-cached token provider.
Handles config loading, JWT signing, token exchange, and refresh on expiry.
Content-light: never persists raw tokens, keys, or auth headers in artifacts.
"""

from __future__ import annotations

from datetime import UTC, datetime
import importlib
import os
from pathlib import Path
import time
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOTENV_PATH = Path.home() / ".rig" / "relay" / ".env"

_TOKENS_URL = "https://api.github.com/app/installations/{installation_id}/access_tokens"
_TOKEN_LIFETIME = 55 * 60  # 55 minutes — rotate well before GitHub's 60-min expiry


class GitHubAppTokenManager:
    def __init__(
        self, app_id: int, installation_id: int, private_key_bytes: bytes
    ) -> None:
        self._app_id = app_id
        self._installation_id = installation_id
        self._private_key = private_key_bytes
        self._cached_token: str | None = None
        self._cached_expiry: float = 0.0

    @classmethod
    def from_environment(cls) -> GitHubAppTokenManager | None:
        from dotenv import load_dotenv

        if _DOTENV_PATH.exists():
            load_dotenv(_DOTENV_PATH)

        app_id_str = os.environ.get("RIG_GITHUB_APP_ID", "")
        inst_id_str = os.environ.get("RIG_GITHUB_INSTALLATION_ID", "")
        key_path = os.environ.get("RIG_GITHUB_PRIVATE_KEY_PATH", "")
        key_env = os.environ.get("RIG_GITHUB_PRIVATE_KEY_ENV", "")

        if not app_id_str or not inst_id_str:
            return None
        if not key_path and not key_env:
            return None

        try:
            app_id = int(app_id_str)
            inst_id = int(inst_id_str)
        except ValueError:
            return None

        if key_path:
            actual_path = Path(key_path).expanduser()
            if not actual_path.exists():
                return None
            key_bytes = actual_path.read_bytes()
        else:
            key_bytes = key_env.encode("utf-8")

        return cls(app_id, inst_id, key_bytes)

    def _sign_jwt(self) -> str | None:
        try:
            jwt_module = importlib.import_module("jwt")
            now = int(datetime.now(UTC).timestamp())
            claims = {"iat": now - 60, "exp": now + 600, "iss": str(self._app_id)}
            return jwt_module.encode(
                claims, self._private_key.decode("utf-8"), algorithm="RS256"
            )
        except Exception:
            return None

    def exchange_installation_token(self) -> tuple[str, float] | None:
        import httpx

        jwt_token = self._sign_jwt()
        if jwt_token is None:
            return None
        url = _TOKENS_URL.format(installation_id=self._installation_id)
        try:
            resp = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=30.0,
            )
            if resp.status_code == 201:
                data = resp.json()
                raw_token = data.get("token", "")
                if raw_token:
                    now = time.time()
                    self._cached_token = raw_token
                    self._cached_expiry = now + _TOKEN_LIFETIME
                    return raw_token, self._cached_expiry
        except Exception:
            pass
        return None

    def get_token(self) -> str | None:
        now = time.time()
        if self._cached_token and now < self._cached_expiry:
            return self._cached_token
        result = self.exchange_installation_token()
        if result:
            return result[0]
        return None

    @property
    def is_ready(self) -> bool:
        return self.get_token() is not None

    def config_summary(self) -> dict[str, Any]:
        return {
            "app_id": self._app_id,
            "installation_id": self._installation_id,
            "token_cached": self._cached_token is not None,
            "token_expires_in_seconds": max(0.0, self._cached_expiry - time.time())
            if self._cached_token
            else 0.0,
            "private_key_present": True,
            "config_source": "environment_variables",
        }


__all__ = ["GitHubAppTokenManager"]
