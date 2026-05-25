"""Application-owned storage paths for Rig Relay desktop app.

Durable state lives under Application Support. Recomputable cache lives
under Caches. Never writes into the opened user repository.

Slice 1A: Desktop Repository Preview Intake v1.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
from typing import ClassVar


@dataclass(frozen=True)
class RigApplicationPaths:
    """Resolves app-owned storage paths from the desktop app's bundle identifier.

    Durable support state:
        ~/Library/Application Support/<CFBundleIdentifier>/

    Recomputable cache state:
        ~/Library/Caches/<CFBundleIdentifier>/

    Temporary execution state uses system temp directory.

    In development/unbundled mode, uses <CFBundleIdentifier>.development.
    In test mode, injects temporary roots via factory methods.
    """

    support_root: Path
    cache_root: Path
    temp_root: Path
    bundle_identifier: str
    is_development: bool = False

    _DEFAULT_DEVELOPMENT_ID: ClassVar[str] = "com.rig-relay.app.development"

    @classmethod
    def for_production(
        cls, bundle_identifier: str | None = None
    ) -> RigApplicationPaths:
        """Resolve paths for the bundled desktop app.

        Uses the actual CFBundleIdentifier from packaging metadata.
        Falls back to development identifier if not bundled.
        """
        resolved_id = bundle_identifier or cls._resolve_bundle_identifier()
        is_dev = resolved_id == cls._DEFAULT_DEVELOPMENT_ID or not cls._is_bundled()

        return cls(
            support_root=cls._resolve_support_root(resolved_id),
            cache_root=cls._resolve_cache_root(resolved_id),
            temp_root=cls._resolve_temp_root(),
            bundle_identifier=resolved_id,
            is_development=is_dev,
        )

    @classmethod
    def for_test(
        cls, support_root: Path, cache_root: Path, temp_root: Path | None = None
    ) -> RigApplicationPaths:
        """Create paths with injected temporary roots for test suites.

        Never touches real Application Support or Caches directories.
        """
        return cls(
            support_root=support_root.resolve(),
            cache_root=cache_root.resolve(),
            temp_root=(temp_root or Path(os.environ.get("TMPDIR", "/tmp"))).resolve(),
            bundle_identifier="com.rig-relay.app.test",
            is_development=True,
        )

    @classmethod
    def _resolve_bundle_identifier(cls) -> str:
        """Resolve the canonical CFBundleIdentifier.

        In production: from environment or packaging metadata.
        In development: uses development identifier.

        This is a placeholder until proper packaging metadata is available.
        """
        env_id = os.environ.get("RIG_RELAY_BUNDLE_IDENTIFIER", "")
        if env_id:
            return env_id
        if cls._is_bundled():
            return cls._DEFAULT_DEVELOPMENT_ID.replace(".development", "")
        return cls._DEFAULT_DEVELOPMENT_ID

    @classmethod
    def _is_bundled(cls) -> bool:
        """Detect whether running as a bundled/packaged app."""
        if os.environ.get("RIG_RELAY_BUNDLED", "") in {"1", "true", "yes"}:
            return True
        try:
            from rig_relay import resources

            return resources.is_bundled()
        except Exception:
            return False

    @staticmethod
    def _resolve_support_root(bundle_identifier: str) -> Path:
        """Resolve the Application Support directory for durable app state."""
        system = platform.system()
        if system == "Darwin":
            home = Path.home()
            return home / "Library" / "Application Support" / bundle_identifier
        # Linux: XDG_DATA_HOME or ~/.local/share
        xdg_data = os.environ.get("XDG_DATA_HOME", "")
        if xdg_data:
            return Path(xdg_data) / bundle_identifier
        return Path.home() / ".local" / "share" / bundle_identifier

    @staticmethod
    def _resolve_cache_root(bundle_identifier: str) -> Path:
        """Resolve the Caches directory for recomputable app state."""
        system = platform.system()
        if system == "Darwin":
            home = Path.home()
            return home / "Library" / "Caches" / bundle_identifier
        # Linux: XDG_CACHE_HOME or ~/.cache
        xdg_cache = os.environ.get("XDG_CACHE_HOME", "")
        if xdg_cache:
            return Path(xdg_cache) / bundle_identifier
        return Path.home() / ".cache" / bundle_identifier

    @staticmethod
    def _resolve_temp_root() -> Path:
        """Resolve the system temporary directory."""
        return Path(os.environ.get("TMPDIR", "/tmp"))

    # ── Repository-scoped paths ──────────────────────────────────

    def digest_cache_for(self, opaque_id: str) -> Path:
        """Cache path for a repository's digestion data."""
        return self.cache_root / "digestion" / opaque_id

    def structural_index_for(self, opaque_id: str) -> Path:
        """Cache path for a repository's structural index."""
        return self.cache_root / "structural-index" / opaque_id

    # ── Future slices (1B, 1C) ──

    def repository_support_dir(self, opaque_id: str) -> Path:
        """Support directory for a registered repository (Slice 1B+)."""
        return self.support_root / "repositories" / opaque_id

    def provider_support_dir(self, provider: str) -> Path:
        """Support directory for provider auth state (Slice 1B+)."""
        return self.support_root / "providers" / provider
