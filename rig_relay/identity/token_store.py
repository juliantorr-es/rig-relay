"""Token store abstraction for OAuth token bundles.

Separates token persistence from flow logic. DevFileTokenStore is a
plaintext dev-only scaffold. MacKeychainTokenStore is a future placeholder.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from rig_relay.identity.models import (
    IdentityProviderKind,
    IdentitySessionStatus,
    TokenBundleMetadata,
)
from rig_relay.identity.state_paths import identity_state_root


class TokenStore(ABC):
    """Abstract token store for OAuth token bundles.

    All implementors must store content-light metadata and keep raw tokens
    out of audit, telemetry, and front-end storage paths.
    """

    @abstractmethod
    def get(self, provider: IdentityProviderKind) -> TokenBundleMetadata | None: ...

    @abstractmethod
    def put(
        self,
        provider: IdentityProviderKind,
        token_bundle: dict[str, Any],
        scopes: list[str] | None = None,
    ) -> TokenBundleMetadata: ...

    @abstractmethod
    def delete(self, provider: IdentityProviderKind) -> bool: ...

    @abstractmethod
    def status(self, provider: IdentityProviderKind) -> IdentitySessionStatus: ...


class DevFileTokenStore(TokenStore):
    """Dev-only, plaintext token storage.

    WARNING: Tokens stored in plaintext. NOT for production use.
    Files live under ~/.rig/relay/identity/.
    """

    DEV_STORE_WARNING = "DevFileTokenStore: plaintext storage, do not use in production"

    def __init__(self, store_root: Path | None = None) -> None:
        if store_root is None:
            store_root = identity_state_root()
        self._store_root = store_root
        self._store_root.mkdir(parents=True, exist_ok=True)

    def _path(self, provider: IdentityProviderKind) -> Path:
        return self._store_root / f"{provider.value}.json"

    def get(self, provider: IdentityProviderKind) -> TokenBundleMetadata | None:
        path = self._path(provider)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TokenBundleMetadata(**data.get("metadata", {}))
        except (json.JSONDecodeError, KeyError):
            return None

    def put(
        self,
        provider: IdentityProviderKind,
        token_bundle: dict[str, Any],
        scopes: list[str] | None = None,
    ) -> TokenBundleMetadata:
        raw_token = token_bundle.get("access_token", "")
        account_id_hash = _sha256(token_bundle.get("account_id", raw_token[:16]))
        email_raw = token_bundle.get("email", "")
        email_hash = _sha256(email_raw) if email_raw else ""

        expires_at: datetime | None = None
        expires_in = token_bundle.get("expires_in")
        if isinstance(expires_in, (int, float)):
            raw_ts = datetime.now(UTC).timestamp() + expires_in
            expires_at = datetime.fromtimestamp(raw_ts, tz=UTC)
        else:
            expires_raw = token_bundle.get("expires_at")
            if isinstance(expires_raw, str):
                try:
                    expires_at = datetime.fromisoformat(expires_raw)
                except (ValueError, TypeError):
                    expires_at = None

        metadata = TokenBundleMetadata(
            provider=provider,
            account_id_hash=account_id_hash,
            email_hash=email_hash,
            display_name=token_bundle.get("display_name", ""),
            scopes=sorted(scopes or token_bundle.get("scopes", [])),
            expires_at=expires_at,
            status=IdentitySessionStatus.SIGNED_IN,
            warnings=[self.DEV_STORE_WARNING],
        )

        data = {
            "store_type": "dev_file",
            "warning": self.DEV_STORE_WARNING,
            "metadata": metadata.model_dump(mode="json"),
            # Raw tokens stored in dev-only plaintext — will be removed in production
            # Both GitHub CI/CD tool and Google Drive uploader read from this field.
            "token_bundle": {
                "access_token": token_bundle.get("access_token", ""),
                "refresh_token": token_bundle.get("refresh_token", ""),
                "account_id": token_bundle.get("account_id", ""),
                "display_name": token_bundle.get("display_name", ""),
                "email": token_bundle.get("email", ""),
            },
        }

        path = self._path(provider)
        path.write_text(
            json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8"
        )
        return metadata

    def delete(self, provider: IdentityProviderKind) -> bool:
        path = self._path(provider)
        if path.is_file():
            path.unlink()
            return True
        return False

    def status(self, provider: IdentityProviderKind) -> IdentitySessionStatus:
        meta = self.get(provider)
        if meta is None:
            return IdentitySessionStatus.SIGNED_OUT
        return meta.status

    def all_statuses(self) -> dict[str, dict[str, Any]]:
        """Return status for all known providers."""
        result: dict[str, dict[str, Any]] = {}
        for provider in IdentityProviderKind:
            meta = self.get(provider)
            if meta is not None:
                result[provider.value] = meta.model_dump(mode="json", exclude_none=True)
            else:
                result[provider.value] = {
                    "status": IdentitySessionStatus.SIGNED_OUT.value
                }
        return result


class MacKeychainTokenStore(TokenStore):
    """Future: macOS Keychain-backed token storage.

    Not implemented yet. Placeholder for production token storage.
    """

    def __init__(self) -> None:
        msg = "MacKeychainTokenStore not yet implemented"
        raise NotImplementedError(msg)

    def get(self, provider: IdentityProviderKind) -> TokenBundleMetadata | None:
        raise NotImplementedError

    def put(
        self,
        provider: IdentityProviderKind,
        token_bundle: dict[str, Any],
        scopes: list[str] | None = None,
    ) -> TokenBundleMetadata:
        raise NotImplementedError

    def delete(self, provider: IdentityProviderKind) -> bool:
        raise NotImplementedError

    def status(self, provider: IdentityProviderKind) -> IdentitySessionStatus:
        raise NotImplementedError


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
