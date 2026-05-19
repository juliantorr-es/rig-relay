"""Production-grade credential store abstraction.

CredentialStore is an ABC that defines the abstract interface for
credential storage. All implementations must be content-light: metadata
uses SHA-256 hashes only, never raw credentials.

Rules:
- Metadata JSON never contains raw tokens, secrets, or authorization codes.
- credential_hash is SHA-256 of the raw credential (used to detect changes).
- credential_store_ref_hash is a composite SHA-256 over all credential
  metadata entries for a provider — it detects state changes without
  exposing raw credentials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys

from rig_relay.identity.state_paths import identity_state_root


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class CredentialMetadata:
    """Content-light metadata about a stored credential.

    Never contains raw tokens, secrets, or authorization codes.
    credential_hash is SHA-256 of the raw credential value.
    """

    provider: str
    credential_kind: str
    stored_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str | None = None
    credential_hash: str = ""
    status: str = "active"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "provider": self.provider,
            "credential_kind": self.credential_kind,
            "stored_at": self.stored_at,
            "expires_at": self.expires_at,
            "credential_hash": self.credential_hash,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | None]) -> CredentialMetadata:
        def _str(val: str | None, default: str = "") -> str:
            return val if val is not None else default

        return cls(
            provider=_str(data.get("provider")),
            credential_kind=_str(data.get("credential_kind")),
            stored_at=_str(data.get("stored_at")),
            expires_at=data.get("expires_at"),
            credential_hash=_str(data.get("credential_hash")),
            status=_str(data.get("status"), "active"),
        )


class CredentialStore(ABC):
    """Abstract interface for credential storage.

    All implementors must keep raw tokens out of audit, telemetry,
    and front-end storage paths. Metadata uses SHA-256 hashes only.
    """

    @abstractmethod
    def store(
        self,
        provider: str,
        credential_kind: str,
        credential: str,
        metadata: dict | None = None,
    ) -> str: ...

    @abstractmethod
    def retrieve(self, provider: str, credential_kind: str) -> str | None: ...

    @abstractmethod
    def delete(self, provider: str, credential_kind: str) -> bool: ...

    @abstractmethod
    def exists(self, provider: str, credential_kind: str) -> bool: ...

    @abstractmethod
    def list_metadata(self, provider: str) -> list[CredentialMetadata]: ...

    @abstractmethod
    def compute_credential_store_ref_hash(self, provider: str) -> str: ...


class InMemoryCredentialStore(CredentialStore):
    """In-memory credential store for testing.

    Never persists raw tokens to disk. All storage is process-local.
    """

    def __init__(self) -> None:
        self._credentials: dict[tuple[str, str], str] = {}
        self._metadata: dict[tuple[str, str], CredentialMetadata] = {}

    def _key(self, provider: str, credential_kind: str) -> tuple[str, str]:
        return (provider, credential_kind)

    def store(
        self,
        provider: str,
        credential_kind: str,
        credential: str,
        metadata: dict | None = None,
    ) -> str:
        if not credential:
            msg = "Empty credential rejected"
            raise ValueError(msg)
        key = self._key(provider, credential_kind)
        self._credentials[key] = credential
        extra = metadata or {}
        stored_meta = CredentialMetadata(
            provider=provider,
            credential_kind=credential_kind,
            credential_hash=_sha256(credential),
            expires_at=extra.get("expires_at"),
            status=extra.get("status", "active"),
        )
        self._metadata[key] = stored_meta
        return self.compute_credential_store_ref_hash(provider)

    def retrieve(self, provider: str, credential_kind: str) -> str | None:
        return self._credentials.get(self._key(provider, credential_kind))

    def delete(self, provider: str, credential_kind: str) -> bool:
        key = self._key(provider, credential_kind)
        present = key in self._credentials
        self._credentials.pop(key, None)
        self._metadata.pop(key, None)
        return present

    def exists(self, provider: str, credential_kind: str) -> bool:
        return self._key(provider, credential_kind) in self._credentials

    def list_metadata(self, provider: str) -> list[CredentialMetadata]:
        return [meta for (p, _), meta in self._metadata.items() if p == provider]

    def compute_credential_store_ref_hash(self, provider: str) -> str:
        metadatas = sorted(
            self.list_metadata(provider), key=lambda m: (m.credential_kind,)
        )
        composite = "|".join(
            f"{m.provider}:{m.credential_kind}:{m.credential_hash}:{m.status}"
            for m in metadatas
        )
        return _sha256(composite)


class NoOpCredentialStore(CredentialStore):
    """Credential store that always returns None.

    For scenarios where credentials are intentionally unavailable.
    """

    def store(
        self,
        provider: str,
        credential_kind: str,
        credential: str,
        metadata: dict | None = None,
    ) -> str:
        return _sha256("")

    def retrieve(self, provider: str, credential_kind: str) -> str | None:
        return None

    def delete(self, provider: str, credential_kind: str) -> bool:
        return False

    def exists(self, provider: str, credential_kind: str) -> bool:
        return False

    def list_metadata(self, provider: str) -> list[CredentialMetadata]:
        return []

    def compute_credential_store_ref_hash(self, provider: str) -> str:
        return _sha256("")


class KeychainBackedCredentialStore(CredentialStore):
    """macOS Keychain-backed credential store.

    - Credential values are stored in macOS keychain via the 'keyring' library.
    - Content-light metadata is stored in a JSON file at
      ~/.rig/relay/identity/credential_metadata.json.
    - Metadata JSON uses ONLY SHA-256 hashes, never raw credentials.
    - Implements the production credential store missing from
      MacKeychainTokenStore.
    """

    _SERVICE_NAME = "rig-relay.credential"
    _METADATA_FILENAME = "credential_metadata.json"

    def __init__(self, store_root: Path | None = None) -> None:
        self._store_root = store_root or identity_state_root()
        self._store_root.mkdir(parents=True, exist_ok=True)
        self._metadata_path = self._store_root / self._METADATA_FILENAME

        self._available = False
        self._keyring = None
        try:
            import keyring as _kr

            self._keyring = _kr
            self._available = True
            probe_account = "_rig_relay_probe"
            try:
                self._keyring.set_password(self._SERVICE_NAME, probe_account, "probe")
                self._keyring.delete_password(self._SERVICE_NAME, probe_account)
            except Exception:
                self._available = False
        except ImportError:
            self._available = False
        self._keyring = None
        try:
            import keyring as _kr

            self._keyring = _kr
            probe_account = "_rig_relay_probe"
            try:
                self._keyring.set_password(self._SERVICE_NAME, probe_account, "probe")
                self._keyring.delete_password(self._SERVICE_NAME, probe_account)
            except Exception:
                pass
            self._available = True
        except ImportError:
            self._available = False
        self._keyring = None
        try:
            import keyring as _kr

            self._keyring = _kr
            try:
                self._keyring.get_password(self._SERVICE_NAME, "_rig_relay_probe")
            except Exception:
                pass
            self._available = True
        except ImportError:
            self._available = False

    def _account(self, provider: str, credential_kind: str) -> str:
        return f"{provider}:{credential_kind}"

    def _load_metadata_map(self) -> dict[tuple[str, str], CredentialMetadata]:
        result: dict[tuple[str, str], CredentialMetadata] = {}
        if not self._metadata_path.is_file():
            return result
        try:
            raw = json.loads(self._metadata_path.read_text(encoding="utf-8"))
            entries: list[dict[str, str | None]] = raw.get("entries", [])
            for entry in entries:
                meta = CredentialMetadata.from_dict(entry)
                key = (meta.provider, meta.credential_kind)
                result[key] = meta
        except (json.JSONDecodeError, KeyError, TypeError):
            return result
        return result

    def _save_metadata_map(
        self, metadata_map: dict[tuple[str, str], CredentialMetadata]
    ) -> None:
        entries = [m.to_dict() for m in metadata_map.values()]
        payload = {
            "schema_version": "rig.relay.credential_store.metadata.v1",
            "entries": entries,
        }
        self._metadata_path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    def _ensure_metadata_clean(self, metadata_map: dict) -> None:
        for entry in metadata_map.get("entries", []):
            for forbidden in (
                "access_token",
                "refresh_token",
                "credential",
                "token",
                "secret",
                "password",
                "api_key",
            ):
                if forbidden in entry:
                    msg = f"Metadata JSON contains forbidden field: {forbidden}"
                    raise ValueError(msg)

    def store(
        self,
        provider: str,
        credential_kind: str,
        credential: str,
        metadata: dict | None = None,
    ) -> str:
        if not credential:
            msg = "Empty credential rejected"
            raise ValueError(msg)
        if not self._available or self._keyring is None:
            msg = "Keychain backend unavailable (keyring import or backend failed)"
            raise RuntimeError(msg)

        account = self._account(provider, credential_kind)
        try:
            self._keyring.set_password(self._SERVICE_NAME, account, credential.strip())
        except Exception as e:
            msg = f"Keychain set_password failed: {e}"
            raise RuntimeError(msg) from e

        extra = metadata or {}
        stored_meta = CredentialMetadata(
            provider=provider,
            credential_kind=credential_kind,
            credential_hash=_sha256(credential),
            expires_at=extra.get("expires_at"),
            status=extra.get("status", "active"),
        )
        meta_map = self._load_metadata_map()
        key = (provider, credential_kind)
        meta_map[key] = stored_meta
        self._save_metadata_map(meta_map)
        return self.compute_credential_store_ref_hash(provider)

    def retrieve(self, provider: str, credential_kind: str) -> str | None:
        if not self._available or self._keyring is None:
            return None
        try:
            return self._keyring.get_password(
                self._SERVICE_NAME, self._account(provider, credential_kind)
            )
        except Exception:
            return None

    def delete(self, provider: str, credential_kind: str) -> bool:
        if not self._available or self._keyring is None:
            return False
        removed = False
        try:
            self._keyring.delete_password(
                self._SERVICE_NAME, self._account(provider, credential_kind)
            )
            removed = True
        except Exception:
            pass

        meta_map = self._load_metadata_map()
        key = (provider, credential_kind)
        meta_map.pop(key, None)
        self._save_metadata_map(meta_map)
        return removed

    def exists(self, provider: str, credential_kind: str) -> bool:
        return self.retrieve(provider, credential_kind) is not None

    def list_metadata(self, provider: str) -> list[CredentialMetadata]:
        meta_map = self._load_metadata_map()
        return [meta for (p, _), meta in meta_map.items() if p == provider]

    def compute_credential_store_ref_hash(self, provider: str) -> str:
        metadatas = sorted(
            self.list_metadata(provider), key=lambda m: (m.credential_kind,)
        )
        composite = "|".join(
            f"{m.provider}:{m.credential_kind}:{m.credential_hash}:{m.status}"
            for m in metadatas
        )
        return _sha256(composite)


def get_credential_store(
    platform: str | None = None,
    store_root: Path | None = None,
    use_in_memory: bool = False,
) -> CredentialStore:
    """Factory: return the appropriate credential store.

    - macOS with keyring available → KeychainBackedCredentialStore
    - Explicit in-memory mode → InMemoryCredentialStore
    - Other platforms → InMemoryCredentialStore (fallback)
    """
    if use_in_memory:
        return InMemoryCredentialStore()
    resolved_platform = platform or sys.platform
    if resolved_platform == "darwin":
        store = KeychainBackedCredentialStore(store_root=store_root)
        if store._available:
            return store
    return InMemoryCredentialStore()
