"""Canonical distribution artifact manifest service (X4).

Schema-versioned, framed, collision-resistant manifest for macOS .app bundles
and Sparkle update archives. Replaces the informal byte-concatenation hashing
in _evidence_hash.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import stat

from rig_relay.native.models import (
    ArtifactItem,
    ArtifactItemKind,
    ArtifactItemSignificance,
    CanonicalDistributionArtifactManifest,
)

_CHUNK_SIZE = 65536
_ICON_EXTENSIONS: frozenset[str] = frozenset({".icns", ".png", ".pdf"})


class ArtifactManifestService:
    """Builds canonical distribution artifact manifests.

    Walks a .app bundle or archive root deterministically, records every
    file/symlink/directory with a SHA-256 digest, detects embedded extensions
    and frameworks, and produces a manifest whose own digest covers the entire
    artifact tree. Any change to any byte in any file produces a different
    manifest digest.
    """

    def build_manifest(
        self,
        artifact_root: Path,
        artifact_kind: str,
        bundle_identifier: str,
        bundle_name: str = "",
        short_version: str = "",
        build_version: str = "",
        entitlements_path: Path | None = None,
    ) -> CanonicalDistributionArtifactManifest:
        """Walk artifact_root and produce a complete manifest."""
        resolved = artifact_root.resolve(strict=True)
        items: list[ArtifactItem] = []

        for fpath in sorted(resolved.rglob("*")):
            items.append(self._classify_item(fpath, resolved))

        items.sort(key=lambda i: i.relative_path)

        framework_items = [
            i for i in items if i.item_kind == ArtifactItemKind.FRAMEWORK
        ]
        appex_items = [i for i in items if i.item_kind == ArtifactItemKind.APPEX]

        for fw_item in framework_items:
            fw_prefix = fw_item.relative_path + "/"
            child_items = [i for i in items if i.relative_path.startswith(fw_prefix)]
            fw_item.sha256 = self._compute_subtree_identity_digest(child_items)

        for ax_item in appex_items:
            ax_prefix = ax_item.relative_path + "/"
            child_items = [i for i in items if i.relative_path.startswith(ax_prefix)]
            ax_item.sha256 = self._compute_subtree_identity_digest(child_items)

        embedded_extension_digest: str | None = None
        for item in appex_items:
            embedded_extension_digest = item.sha256
            break

        embedded_framework_digests: list[str] = []
        for item in framework_items:
            if item.sha256:
                embedded_framework_digests.append(item.sha256)

        eid = None
        if entitlements_path is not None and entitlements_path.exists():
            eid = self._hash_file(entitlements_path)

        manifest = CanonicalDistributionArtifactManifest(
            artifact_kind=artifact_kind,
            bundle_identifier_digest=f"sha256:{hashlib.sha256(bundle_identifier.encode()).hexdigest()}",
            bundle_name=bundle_name,
            short_version=short_version,
            build_version=build_version,
            created_at=datetime.now(UTC).isoformat(),
            items=items,
            embedded_extension_digest=embedded_extension_digest,
            embedded_framework_digests=embedded_framework_digests,
            entitlement_summary_digest=eid,
        )

        manifest.manifest_digest = self.compute_manifest_digest(manifest)
        return manifest

    @staticmethod
    def _compute_subtree_identity_digest(child_items: list[ArtifactItem]) -> str:
        """SHA-256 of child items' content hashes, providing subtree identity."""
        hasher = hashlib.sha256()
        for item in sorted(child_items, key=lambda i: i.relative_path):
            sha = item.sha256 or ""
            hasher.update(f"{item.relative_path}:{item.size or 0}:{sha}\n".encode())
        return f"sha256:{hasher.hexdigest()}"

    @staticmethod
    def compute_manifest_digest(manifest: CanonicalDistributionArtifactManifest) -> str:
        """Compute SHA-256 of the canonical JSON (manifest_digest and created_at excluded)."""
        data = manifest.model_dump(exclude={"manifest_digest", "created_at"})
        canonical = (
            json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    # -- private helpers --------------------------------------------------------

    @staticmethod
    def _hash_file(fpath: Path) -> str:
        """SHA-256 of a file's complete byte content (chunked 64 KB reads)."""
        hasher = hashlib.sha256()
        with fpath.open("rb") as f:
            while chunk := f.read(_CHUNK_SIZE):
                hasher.update(chunk)
        return f"sha256:{hasher.hexdigest()}"

    @staticmethod
    def _classify_significance(
        relative_path: str, fpath: Path
    ) -> ArtifactItemSignificance:
        """Heuristic significance classification for an artifact item."""
        parts = relative_path.replace("\\", "/").split("/")
        macos_depth = 3
        if len(parts) >= macos_depth and parts[-macos_depth:] == [
            "Contents",
            "MacOS",
            Path(relative_path).name,
        ]:
            return ArtifactItemSignificance.CRITICAL
        if "Contents/MacOS/" in relative_path:
            return ArtifactItemSignificance.CRITICAL
        if relative_path.endswith("Info.plist"):
            return ArtifactItemSignificance.META
        suffix = Path(relative_path).suffix.lower()
        if suffix in _ICON_EXTENSIONS:
            return ArtifactItemSignificance.ICON
        if suffix == ".plist":
            return ArtifactItemSignificance.CONFIG
        return ArtifactItemSignificance.NORMAL

    def _classify_item(self, fpath: Path, root: Path) -> ArtifactItem:
        """Classify a single filesystem entry into an ArtifactItem."""
        rel = str(fpath.relative_to(root)).replace("\\", "/")

        if fpath.is_symlink():
            target = os.readlink(fpath)
            if ".." in target:
                raise ValueError(
                    f"Symlink at {rel} has target containing '..': {target}"
                )
            resolved_target = (fpath.parent / target).resolve()
            if not str(resolved_target).startswith(str(root)):
                raise ValueError(
                    f"Symlink at {rel} resolves outside artifact root: {target} -> {resolved_target}"
                )
            return ArtifactItem(
                relative_path=rel,
                item_kind=ArtifactItemKind.SYMLINK,
                sha256=None,
                size=None,
                symlink_target=target,
                is_executable=False,
                significance=ArtifactItemSignificance.NORMAL,
            )

        if fpath.is_dir():
            item_kind = ArtifactItemKind.DIRECTORY
            if "/PlugIns/" in rel and rel.endswith(".appex"):
                item_kind = ArtifactItemKind.APPEX
            elif "/Frameworks/" in rel and rel.endswith(".framework"):
                item_kind = ArtifactItemKind.FRAMEWORK
            return ArtifactItem(
                relative_path=rel,
                item_kind=item_kind,
                sha256=None,
                size=None,
                symlink_target=None,
                is_executable=False,
                significance=ArtifactItemSignificance.NORMAL,
            )

        if fpath.is_file():
            st = fpath.stat()
            is_exe = bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
            item_kind = (
                ArtifactItemKind.EXECUTABLE if is_exe else ArtifactItemKind.REGULAR_FILE
            )
            significance = self._classify_significance(rel, fpath)
            return ArtifactItem(
                relative_path=rel,
                item_kind=item_kind,
                sha256=self._hash_file(fpath),
                size=st.st_size,
                symlink_target=None,
                is_executable=is_exe,
                significance=significance,
            )

        raise ValueError(
            f"Unknown filesystem entry at {rel}: not file, dir, or symlink"
        )
