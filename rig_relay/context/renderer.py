"""Context renderer — cache-aware, privacy-hardened, compression-ready.

Produces structured context sections with trust/cache tiers, provenance
labels, and content-hashed metadata. Replaces raw message snippets and
absolute paths with safe alternatives.

Cache tier ordering (stable first, volatile last):
    stable       AGENTS/doctrine/schema, invariant rules
    semi_stable  repo topology, subsystem map
    dynamic      dirty files, active lanes, collisions
    volatile     user task hash, recent message metadata, receipts
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, ClassVar

_HEAD_TRUNCATE = 12
_SUBSYSTEM_TRUNCATE = 20
_RECEIPT_TRUNCATE = 10


class CacheTier:
    STABLE = "stable"
    SEMI_STABLE = "semi_stable"
    DYNAMIC = "dynamic"
    VOLATILE = "volatile"

    _ORDER: ClassVar[dict[str, int]] = {STABLE: 0, SEMI_STABLE: 1, DYNAMIC: 2, VOLATILE: 3}

    @classmethod
    def sort_key(cls, tier: str) -> int:
        return cls._ORDER.get(tier, 99)


class TrustTier:
    FIRST_PARTY = "first_party"
    REPO_CONTENT = "repo_content"
    TOOL_OUTPUT = "tool_output"
    EXTERNAL = "external"
    UNTRUSTED = "untrusted"


class Provenance:
    REPO_MAP = "repo_map"
    WORK_MAP = "work_map"
    PLANNER = "planner"
    RECEIPT = "receipt"
    MESSAGE = "message"


class _Section:
    __slots__ = (
        "name",
        "cache_tier",
        "trust_tier",
        "source",
        "content",
        "content_sha256",
        "token_estimate",
        "compressed",
    )

    def __init__(
        self,
        name: str,
        cache_tier: str,
        trust_tier: str,
        source: str,
        content: str,
    ) -> None:
        self.name = name
        self.cache_tier = cache_tier
        self.trust_tier = trust_tier
        self.source = source
        self.content = content
        self.content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.token_estimate = max(1, len(content) // 4)
        self.compressed = False


class ContextRenderer:
    """Build cache-tiered, privacy-safe context sections.

    Usage:
        renderer = ContextRenderer(workspace_root=Path("."))
        renderer.add_repo_section(repo_info)
        renderer.add_active_work_section(lanes, collisions)
        renderer.add_recent_messages_section(messages)
        sections = renderer.sections  # ordered by cache tier
        rendered = renderer.render()
    """

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        compression_mode: str = "none",
    ) -> None:
        self._workspace_root = workspace_root
        self._compression_mode = compression_mode
        self._sections: list[_Section] = []
        self._substitution_table: dict[str, Any] | None = None
        self._original_total: int = 0
        self._compressed_total: int = 0

    @property
    def sections(self) -> list[dict[str, Any]]:
        """Return sections ordered by cache tier (stable first)."""
        sorted_sections = sorted(self._sections, key=lambda s: CacheTier.sort_key(s.cache_tier))
        return [
            {
                "section_name": s.name,
                "cache_tier": s.cache_tier,
                "trust_tier": s.trust_tier,
                "source": s.source,
                "content_sha256": s.content_sha256,
                "token_estimate": s.token_estimate,
                "compressed": s.compressed,
            }
            for s in sorted_sections
        ]

    @property
    def rendered_content(self) -> str:
        sorted_sections = sorted(self._sections, key=lambda s: CacheTier.sort_key(s.cache_tier))
        return "\n\n".join(s.content for s in sorted_sections)

    @property
    def substitution_table_sha256(self) -> str | None:
        if self._substitution_table is None:
            return None
        raw = str(sorted(self._substitution_table.items())).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @property
    def compression_applied(self) -> bool:
        return self._compressed_total > 0

    @property
    def compression_savings_bytes(self) -> int:
        return self._original_total - self._compressed_total

    # ── Section builders ────────────────────────────────────────────

    def add_stable_section(self, name: str, content: str, source: str) -> None:
        self._sections.append(
            _Section(name, CacheTier.STABLE, TrustTier.FIRST_PARTY, source, content)
        )

    def add_repo_section(
        self,
        *,
        root: str | None = None,
        branch: str = "",
        head: str = "",
        modified: int = 0,
        untracked: int = 0,
        staged: int = 0,
    ) -> None:
        root_hash = hashlib.sha256((root or "").encode("utf-8")).hexdigest()[:16]
        content = (
            f"## Repository\n"
            f"- root_hash: {root_hash}\n"
            f"- branch: {branch}\n"
            f"- head: {head[:_HEAD_TRUNCATE] if len(head) > _HEAD_TRUNCATE else head}\n"
            f"- dirty: {modified} modified, {untracked} untracked, {staged} staged"
        )
        self._sections.append(
            _Section("repository", CacheTier.SEMI_STABLE, TrustTier.REPO_CONTENT, Provenance.REPO_MAP, content)
        )

    def add_subsystem_section(self, subsystems: list[dict[str, Any]] | None = None) -> None:
        if not subsystems:
            return
        sub_count = len(subsystems)
        names = [s.get("name", "?") for s in subsystems[:20]]
        content = (
            f"## Subsystems\n"
            f"- count: {sub_count}\n"
            f"- names: {', '.join(names)}"
            + (f"\n- ... and {sub_count - _SUBSYSTEM_TRUNCATE} more" if sub_count > _SUBSYSTEM_TRUNCATE else "")
        )
        self._sections.append(
            _Section("subsystems", CacheTier.SEMI_STABLE, TrustTier.REPO_CONTENT, Provenance.REPO_MAP, content)
        )

    def add_active_work_section(
        self,
        *,
        lane_count: int = 0,
        collision_count: int = 0,
        collision_paths: list[str] | None = None,
    ) -> None:
        content = (
            f"## Active Work\n"
            f"- active_lanes: {lane_count}\n"
            f"- collision_count: {collision_count}"
        )
        if collision_paths:
            path_hashes = [
                hashlib.sha256(p.encode("utf-8")).hexdigest()[:12]
                for p in collision_paths[:10]
            ]
            content += "\n- collision_path_hashes: " + ", ".join(path_hashes)
        self._sections.append(
            _Section("active_work", CacheTier.DYNAMIC, TrustTier.REPO_CONTENT, Provenance.WORK_MAP, content)
        )

    def add_recent_messages_section(self, messages: list[Any] | None = None) -> None:
        if not messages:
            return
        tail = [
            m for m in messages
            if hasattr(m, "role") and getattr(m, "role", None) not in {"system"}
        ][-6:]
        if not tail:
            return
        lines = []
        for m in tail:
            role = str(getattr(m, "role", "?"))
            raw_content = str(getattr(m, "content", ""))
            content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()[:16]
            byte_count = len(raw_content.encode("utf-8"))
            lines.append(f"- [{role}]: sha256={content_hash} bytes={byte_count}")
        content = "## Recent Messages\n" + "\n".join(lines)
        self._sections.append(
            _Section("recent_messages", CacheTier.VOLATILE, TrustTier.TOOL_OUTPUT, Provenance.MESSAGE, content)
        )

    def add_snapshot_section(self, snapshot_text: str) -> None:
        snap_hash = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()[:16]
        content = f"## Snapshot\n- hash: {snap_hash}\n- bytes: {len(snapshot_text.encode('utf-8'))}"
        self._sections.append(
            _Section("snapshot", CacheTier.VOLATILE, TrustTier.TOOL_OUTPUT, Provenance.RECEIPT, content)
        )

    def add_do_not_touch_section(self, paths: list[str] | None = None) -> None:
        if not paths:
            return
        path_hashes = [
            hashlib.sha256(p.encode("utf-8")).hexdigest()[:12]
            for p in paths[:10]
        ]
        content = "## Do Not Touch\n- collision_path_hashes: " + ", ".join(path_hashes)
        self._sections.append(
            _Section("do_not_touch", CacheTier.DYNAMIC, TrustTier.REPO_CONTENT, Provenance.WORK_MAP, content)
        )

    def add_receipts_section(self, receipts: list[dict[str, Any]] | None = None) -> None:
        if not receipts:
            return
        kinds = [r.get("kind", "?") for r in receipts[:10]]
        content = (
            f"## Receipts\n"
            f"- count: {len(receipts)}\n"
            f"- kinds: {', '.join(kinds[:10])}"
            + (f"\n- ... and {len(receipts) - 10} more" if len(receipts) > _RECEIPT_TRUNCATE else "")
        )
        self._sections.append(
            _Section("receipts", CacheTier.VOLATILE, TrustTier.TOOL_OUTPUT, Provenance.RECEIPT, content)
        )

    # ── Compression ─────────────────────────────────────────────────

    def apply_compression(self) -> bool:
        """Apply symbol substitution compression if mode requires it and savings positive."""
        if self._compression_mode not in {"symbol_substitution", "aggressive"}:
            return False

        rendered = self.rendered_content
        self._original_total = len(rendered.encode("utf-8"))

        try:
            from rig_relay.context.symbol_codec import compress_with_manifest

            result = compress_with_manifest(rendered)
            compressed = result.compressed_text
            manifest = result.manifest
            self._compressed_total = len(compressed.encode("utf-8"))

            if self._compressed_total < self._original_total:
                self._substitution_table = {
                    "manifest_sha256": getattr(manifest, "manifest_sha256", "")
                    if manifest else "",
                    "entry_count": len(getattr(manifest, "entries", []))
                    if manifest else 0,
                }
                for s in self._sections:
                    s.compressed = True
                return True
        except Exception:
            pass

        return False

    # ── Serialization ───────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sections": self.sections,
            "rendered_content_sha256": hashlib.sha256(
                self.rendered_content.encode("utf-8")
            ).hexdigest(),
            "section_count": len(self._sections),
            "estimated_tokens": sum(s.token_estimate for s in self._sections),
            "compression_applied": self.compression_applied,
        }
        if self._substitution_table is not None:
            result["substitution_table_sha256"] = self.substitution_table_sha256
        if self.compression_applied:
            result["compression_savings_bytes"] = self.compression_savings_bytes
        return result


__all__ = [
    "CacheTier",
    "ContextRenderer",
    "Provenance",
    "TrustTier",
]
