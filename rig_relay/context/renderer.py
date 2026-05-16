"""Context renderer — cache-aware, privacy-hardened, compression-ready.

Uses canonical assembly_plan.py enums (CacheTier, TrustTier, ContextRenderedSection).
No local duplicate type classes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from rig_relay.context.assembly_plan import CacheTier, ContextRenderedSection, TrustTier
from rig_relay.context.warnings import (
    ContextWarningCode,
    build_warning,
    exception_class_name,
)

_SUBSYSTEM_TRUNCATE = 20
_RECEIPT_TRUNCATE = 10

# ── Cache tier ordering ──────────────────────────────────────────

_CACHE_TIER_ORDER: dict[CacheTier, int] = {
    CacheTier.stable: 0,
    CacheTier.semi_stable: 1,
    CacheTier.dynamic: 2,
    CacheTier.volatile: 3,
}


def cache_tier_sort_key(tier: CacheTier) -> int:
    """Stable ordering: stable < semi_stable < dynamic < volatile."""
    return _CACHE_TIER_ORDER.get(tier, 99)


def _sha256_prefixed(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _sha256_short(data: bytes, n: int = 16) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()[:n]}"


# ── Provenance (renderer-local — no assembly_plan equivalent) ─────


class Provenance:
    REPO_MAP = "repo_map"
    WORK_MAP = "work_map"
    PLANNER = "planner"
    RECEIPT = "receipt"
    MESSAGE = "message"


# ── Internal section with raw content ─────────────────────────────


class _RenderedSection:
    """Private: carries raw rendered content + assembly_plan metadata."""

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
        cache_tier: CacheTier,
        trust_tier: TrustTier,
        source: str,
        content: str,
    ) -> None:
        self.name = name
        self.cache_tier = cache_tier
        self.trust_tier = trust_tier
        self.source = source
        self.content = content
        self.content_sha256 = _sha256_prefixed(content.encode("utf-8"))
        self.token_estimate = max(1, len(content) // 4)
        self.compressed = False

    def to_metadata(self) -> ContextRenderedSection:
        return ContextRenderedSection(
            section_name=self.name,
            token_count=self.token_estimate,
            compression_applied=self.compressed,
            section_sha256=self.content_sha256,
        )


# ── Renderer ──────────────────────────────────────────────────────


_CACHE_TIER_ORDER = {
    CacheTier.stable: 0,
    CacheTier.semi_stable: 1,
    CacheTier.dynamic: 2,
    CacheTier.volatile: 3,
}


class ContextRenderer:
    """Build cache-tiered, privacy-safe context sections.

    Usage:
        renderer = ContextRenderer(workspace_root=Path("."))
        renderer.add_repo_section(root="...", branch="main", ...)
        renderer.add_active_work_section(lane_count=3, ...)
        sections = renderer.section_metadata  # list[ContextRenderedSection]
        rendered = renderer.rendered_content
    """

    def __init__(
        self, *, workspace_root: Path | None = None, compression_mode: str = "none"
    ) -> None:
        self._workspace_root = workspace_root
        self._compression_mode = compression_mode
        self._sections: list[_RenderedSection] = []
        self._substitution_table: dict[str, Any] | None = None
        self._original_total: int = 0
        self._compressed_total: int = 0
        self._warnings: list[dict[str, Any]] = []

    # ── Public metadata API ───────────────────────────────────────

    @property
    def section_count(self) -> int:
        return len(self._sections)

    @property
    def estimated_tokens(self) -> int:
        return sum(s.token_estimate for s in self._sections)

    @property
    def section_metadata(self) -> list[ContextRenderedSection]:
        sorted_sections = sorted(
            self._sections, key=lambda s: cache_tier_sort_key(s.cache_tier)
        )
        return [s.to_metadata() for s in sorted_sections]

    @property
    def sections(self) -> list[dict[str, Any]]:
        """Backward-compatible dict-based metadata. Deprecated — use section_metadata."""
        return [
            {
                "section_name": s.name,
                "cache_tier": s.cache_tier.value,
                "trust_tier": s.trust_tier.value,
                "source": s.source,
                "content_sha256": s.content_sha256,
                "token_estimate": s.token_estimate,
                "compressed": s.compressed,
            }
            for s in self._sections
        ]

    @property
    def rendered_content(self) -> str:
        sorted_sections = sorted(
            self._sections, key=lambda s: cache_tier_sort_key(s.cache_tier)
        )
        return "\n\n".join(s.content for s in sorted_sections)

    @property
    def rendered_content_sha256(self) -> str:
        return _sha256_prefixed(self.rendered_content.encode("utf-8"))

    @property
    def substitution_table_sha256(self) -> str | None:
        if self._substitution_table is None:
            return None
        raw = str(sorted(self._substitution_table.items())).encode("utf-8")
        return _sha256_prefixed(raw)

    @property
    def compression_applied(self) -> bool:
        return self._compressed_total > 0

    @property
    def compression_savings_bytes(self) -> int:
        return self._original_total - self._compressed_total

    @property
    def warnings(self) -> list[dict[str, Any]]:
        return list(self._warnings)

    # ── Section builders ────────────────────────────────────────

    def add_stable_section(
        self, name: str, content: str, source: str = Provenance.PLANNER
    ) -> None:
        self._sections.append(
            _RenderedSection(
                name, CacheTier.stable, TrustTier.first_party, source, content
            )
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
        root_hash = _sha256_short((root or "").encode("utf-8"), n=16)
        head_hash = _sha256_short(head.encode("utf-8"), n=12) if head else "none"
        content = (
            f"## Repository\n"
            f"- root_hash: {root_hash}\n"
            f"- branch: {branch}\n"
            f"- head: {head_hash}\n"
            f"- dirty: {modified} modified, {untracked} untracked, {staged} staged"
        )
        self._sections.append(
            _RenderedSection(
                "repository",
                CacheTier.semi_stable,
                TrustTier.repo_content,
                Provenance.REPO_MAP,
                content,
            )
        )

    def add_subsystem_section(
        self, subsystems: list[dict[str, Any]] | None = None
    ) -> None:
        if not subsystems:
            return
        sub_count = len(subsystems)
        names = [s.get("name", "?") for s in subsystems[:20]]
        content = (
            f"## Subsystems\n"
            f"- count: {sub_count}\n"
            f"- names: {', '.join(names)}"
            + (
                f"\n- ... and {sub_count - _SUBSYSTEM_TRUNCATE} more"
                if sub_count > _SUBSYSTEM_TRUNCATE
                else ""
            )
        )
        self._sections.append(
            _RenderedSection(
                "subsystems",
                CacheTier.semi_stable,
                TrustTier.repo_content,
                Provenance.REPO_MAP,
                content,
            )
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
                _sha256_short(p.encode("utf-8"), n=12) for p in collision_paths[:10]
            ]
            content += "\n- collision_path_hashes: " + ", ".join(path_hashes)
        self._sections.append(
            _RenderedSection(
                "active_work",
                CacheTier.dynamic,
                TrustTier.repo_content,
                Provenance.WORK_MAP,
                content,
            )
        )

    def add_recent_messages_section(self, messages: list[Any] | None = None) -> None:
        if not messages:
            return
        tail = [
            m
            for m in messages
            if hasattr(m, "role") and getattr(m, "role", None) not in {"system"}
        ][-6:]
        if not tail:
            return
        lines = []
        for m in tail:
            role = str(getattr(m, "role", "?"))
            raw_content = str(getattr(m, "content", ""))
            content_hash = _sha256_short(raw_content.encode("utf-8"), n=16)
            byte_count = len(raw_content.encode("utf-8"))
            lines.append(f"- [{role}]: sha256={content_hash} bytes={byte_count}")
        content = "## Recent Messages\n" + "\n".join(lines)
        self._sections.append(
            _RenderedSection(
                "recent_messages",
                CacheTier.volatile,
                TrustTier.tool_output,
                Provenance.MESSAGE,
                content,
            )
        )

    def add_snapshot_section(self, snapshot_text: str) -> None:
        snap_hash = _sha256_short(snapshot_text.encode("utf-8"), n=16)
        content = (
            f"## Snapshot\n"
            f"- hash: {snap_hash}\n"
            f"- bytes: {len(snapshot_text.encode('utf-8'))}"
        )
        self._sections.append(
            _RenderedSection(
                "snapshot",
                CacheTier.volatile,
                TrustTier.tool_output,
                Provenance.RECEIPT,
                content,
            )
        )

    def add_do_not_touch_section(self, paths: list[str] | None = None) -> None:
        if not paths:
            return
        path_hashes = [_sha256_short(p.encode("utf-8"), n=12) for p in paths[:10]]
        content = "## Do Not Touch\n- collision_path_hashes: " + ", ".join(path_hashes)
        self._sections.append(
            _RenderedSection(
                "do_not_touch",
                CacheTier.dynamic,
                TrustTier.repo_content,
                Provenance.WORK_MAP,
                content,
            )
        )

    def add_receipts_section(
        self, receipts: list[dict[str, Any]] | None = None
    ) -> None:
        if not receipts:
            return
        kinds = [r.get("kind", "?") for r in receipts[:10]]
        content = (
            f"## Receipts\n"
            f"- count: {len(receipts)}\n"
            f"- kinds: {', '.join(kinds[:10])}"
            + (
                f"\n- ... and {len(receipts) - 10} more"
                if len(receipts) > _RECEIPT_TRUNCATE
                else ""
            )
        )
        self._sections.append(
            _RenderedSection(
                "receipts",
                CacheTier.volatile,
                TrustTier.tool_output,
                Provenance.RECEIPT,
                content,
            )
        )

    # ── Compression ─────────────────────────────────────────────

    def apply_compression(self) -> bool:
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
                    "manifest_sha256": (
                        getattr(manifest, "manifest_sha256", "") if manifest else ""
                    ),
                    "entry_count": (
                        len(getattr(manifest, "entries", [])) if manifest else 0
                    ),
                }
                for s in self._sections:
                    s.compressed = True
                return True
            else:
                self._warnings.append(
                    build_warning(
                        ContextWarningCode.COMPRESSION_FAILED,
                        detail=f"no savings: {self._compressed_total} >= {self._original_total}",
                    )
                )
        except ImportError:
            self._warnings.append(
                build_warning(
                    ContextWarningCode.COMPRESSION_FAILED,
                    detail="symbol_codec module not found",
                )
            )
        except Exception as exc:
            self._warnings.append(
                build_warning(
                    ContextWarningCode.COMPRESSION_FAILED,
                    detail=exception_class_name(exc),
                )
            )

        return False

    # ── Serialization ───────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sections": self.sections,
            "rendered_content_sha256": self.rendered_content_sha256,
            "section_count": self.section_count,
            "estimated_tokens": self.estimated_tokens,
            "compression_applied": self.compression_applied,
        }
        if self._substitution_table is not None:
            result["substitution_table_sha256"] = self.substitution_table_sha256
        if self.compression_applied:
            result["compression_savings_bytes"] = self.compression_savings_bytes
        if self._warnings:
            result["warnings"] = self._warnings
        return result


__all__ = [
    "CacheTier",
    "ContextRenderer",
    "Provenance",
    "TrustTier",
    "cache_tier_sort_key",
]
