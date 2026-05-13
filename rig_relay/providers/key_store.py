"""Provider key store abstraction — Env, DevFile, and MacKeychain backends.

Rules:
- EnvProviderKeyStore reads standard env vars.
- DevFileProviderKeyStore stores local dev keys under ~/.rig/relay/providers/ with chmod 0600.
- MacKeychainProviderKeyStore uses the 'keyring' library on macOS. Falls back to
  unavailable/error results if keyring import or backend fails.
- No keys are stored in repo, .build artifacts, intent audit, or frontend storage.
- Key fingerprints are SHA256 hashes, not raw keys.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol

from rig_relay.providers.models import KeySource, Provider
from rig_relay.providers.registry import get_provider_info


def _fingerprint_key(key: str) -> str:
    """Deterministic SHA256 fingerprint of a key — does not expose the raw key."""
    return "sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class ProviderKeyStore(Protocol):
    """Protocol for provider key storage backends."""

    def get_key(self, provider: Provider) -> str | None:
        """Return the API key for the given provider, or None if not found."""
        ...

    def set_key(self, provider: Provider, key: str) -> None:
        """Store an API key for the given provider."""
        ...

    def remove_key(self, provider: Provider) -> bool:
        """Remove the API key for the given provider. Returns True if removed."""
        ...

    def key_source(self, provider: Provider) -> KeySource:
        """Return the key source for the given provider."""
        ...

    def has_key(self, provider: Provider) -> bool:
        """Check if a key exists for the given provider without returning it."""
        ...

    def fingerprint(self, provider: Provider) -> str:
        """Return the fingerprint of the key for the given provider."""
        ...


class EnvProviderKeyStore:
    """Reads API keys from environment variables.

    Uses the primary env var for each provider. Google also checks the
    alternate GOOGLE_API_KEY.
    """

    def get_key(self, provider: Provider) -> str | None:
        info = get_provider_info(provider)
        if info is None:
            return None
        key = os.environ.get(info.env_var)
        if key:
            return key
        if info.alt_env_var:
            key = os.environ.get(info.alt_env_var)
            if key:
                return key
        return None

    def set_key(self, provider: Provider, key: str) -> None:
        msg = "EnvProviderKeyStore is read-only. Cannot set environment variables."
        raise RuntimeError(msg)

    def remove_key(self, provider: Provider) -> bool:
        return False

    def key_source(self, provider: Provider) -> KeySource:
        if self.get_key(provider) is not None:
            return KeySource.ENV
        return KeySource.MISSING

    def has_key(self, provider: Provider) -> bool:
        return self.get_key(provider) is not None

    def fingerprint(self, provider: Provider) -> str:
        key = self.get_key(provider)
        if key is None:
            return ""
        return _fingerprint_key(key)

    def get_google_warnings(self) -> list[str]:
        """Check GEMINI_API_KEY vs GOOGLE_API_KEY and return warnings if both set."""
        gemini = os.environ.get("GEMINI_API_KEY")
        google = os.environ.get("GOOGLE_API_KEY")
        warnings: list[str] = []
        if gemini and google:
            warnings.append(
                "Both GEMINI_API_KEY and GOOGLE_API_KEY are set. "
                "GEMINI_API_KEY takes precedence."
            )
        return warnings


class DevFileProviderKeyStore:
    """Stores API keys in local dev files under the provider state root.

    Each key is stored in a separate file named <provider>.key.
    Files are created with chmod 0600 where the platform supports it.
    Keys are excluded from telemetry, audit, and bundles.
    """

    def __init__(self, providers_dir: Path | None = None) -> None:
        from rig_relay.identity.state_paths import provider_state_root

        self._providers_dir = providers_dir or provider_state_root()

    def _key_path(self, provider: Provider) -> Path:
        return self._providers_dir / f"{provider.value}.key"

    def get_key(self, provider: Provider) -> str | None:
        path = self._key_path(provider)
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    def set_key(self, provider: Provider, key: str) -> None:
        self._providers_dir.mkdir(parents=True, exist_ok=True)
        path = self._key_path(provider)
        path.write_text(key.strip() + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def remove_key(self, provider: Provider) -> bool:
        path = self._key_path(provider)
        if path.is_file():
            path.unlink()
            return True
        return False

    def key_source(self, provider: Provider) -> KeySource:
        if self.get_key(provider) is not None:
            return KeySource.DEV_FILE
        return KeySource.MISSING

    def has_key(self, provider: Provider) -> bool:
        return self._key_path(provider).is_file()

    def fingerprint(self, provider: Provider) -> str:
        key = self.get_key(provider)
        if key is None:
            return ""
        return _fingerprint_key(key)


class MacKeychainProviderKeyStore:
    """macOS Keychain-backed provider key store via the 'keyring' library.

    Service name: "rig-relay.provider"
    Account name: provider.value (e.g. "openai", "anthropic")

    If keyring is unavailable or the backend fails, all operations return
    structured unavailable/error results — they do not crash and do not
    silently fall back to another store.
    """

    _SERVICE_NAME = "rig-relay.provider"

    def __init__(self) -> None:
        self._available = False
        self._keyring = None
        try:
            import keyring as _kr

            self._keyring = _kr
            self._available = True
        except ImportError:
            self._available = False

    def get_key(self, provider: Provider) -> str | None:
        if not self._available or self._keyring is None:
            return None
        try:
            return self._keyring.get_password(self._SERVICE_NAME, provider.value)
        except Exception:
            return None

    def set_key(self, provider: Provider, key: str) -> None:
        if not self._available or self._keyring is None:
            msg = "Keychain backend unavailable (keyring import or backend failed)"
            raise RuntimeError(msg)
        try:
            self._keyring.set_password(self._SERVICE_NAME, provider.value, key.strip())
        except Exception as e:
            msg = f"Keychain set_password failed: {e}"
            raise RuntimeError(msg) from e

    def remove_key(self, provider: Provider) -> bool:
        if not self._available or self._keyring is None:
            return False
        try:
            self._keyring.delete_password(self._SERVICE_NAME, provider.value)
            return True
        except Exception:
            return False

    def key_source(self, provider: Provider) -> KeySource:
        if self.get_key(provider) is not None:
            return KeySource.KEYCHAIN
        return KeySource.MISSING

    def has_key(self, provider: Provider) -> bool:
        return self.get_key(provider) is not None

    def fingerprint(self, provider: Provider) -> str:
        key = self.get_key(provider)
        if key is None:
            return ""
        return _fingerprint_key(key)


def get_key_store(
    source: KeySource = KeySource.DEV_FILE,
) -> EnvProviderKeyStore | DevFileProviderKeyStore | MacKeychainProviderKeyStore:
    """Factory to get the appropriate key store implementation."""
    match source:
        case KeySource.ENV:
            return EnvProviderKeyStore()
        case KeySource.DEV_FILE:
            return DevFileProviderKeyStore()
        case KeySource.KEYCHAIN:
            return MacKeychainProviderKeyStore()
        case KeySource.MISSING:
            return DevFileProviderKeyStore()
