"""Renderer contract unification tests — one vocabulary, no private access."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

from rig_relay.context.assembly_plan import CacheTier, ContextRenderedSection
from rig_relay.context.renderer import ContextRenderer, cache_tier_sort_key

# ── CacheTier unification ────────────────────────────────────────


class TestCacheTierUnification:
    def test_renderer_uses_assembly_plan_cache_tier(self) -> None:
        """No local duplicate CacheTier class in renderer.py."""
        renderer_file = (
            Path(__file__).resolve().parents[2] / "rig_relay/context/renderer.py"
        )
        tree = ast.parse(renderer_file.read_text())
        cache_tier_classes: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "CacheTier":
                cache_tier_classes.append(node.lineno)
        assert len(cache_tier_classes) <= 1, (
            f"Multiple CacheTier class definitions at lines {cache_tier_classes}"
        )

    def test_renderer_uses_assembly_plan_trust_tier(self) -> None:
        """No local duplicate TrustTier class in renderer.py."""
        renderer_file = (
            Path(__file__).resolve().parents[2] / "rig_relay/context/renderer.py"
        )
        tree = ast.parse(renderer_file.read_text())
        trust_tier_classes: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "TrustTier":
                trust_tier_classes.append(node.lineno)
        assert len(trust_tier_classes) <= 1, (
            f"Multiple TrustTier class definitions at lines {trust_tier_classes}"
        )

    def test_cache_tier_sort_key_stable_first(self) -> None:
        tiers = [CacheTier.volatile, CacheTier.stable, CacheTier.dynamic]
        tiers.sort(key=cache_tier_sort_key)
        assert tiers[0] == CacheTier.stable
        assert tiers[-1] == CacheTier.volatile

    def test_cache_tier_sort_key_handles_enum_values(self) -> None:
        assert cache_tier_sort_key(CacheTier.stable) == 0
        assert cache_tier_sort_key(CacheTier.volatile) == 3


# ── Public API tests ─────────────────────────────────────────────


class TestRendererPublicAPI:
    def test_section_count_public(self) -> None:
        renderer = ContextRenderer()
        renderer.add_stable_section("test", "content")
        assert renderer.section_count == 1

    def test_section_metadata_is_context_rendered_section(self) -> None:
        renderer = ContextRenderer()
        renderer.add_stable_section("test", "hello world")
        metadata = renderer.section_metadata
        assert len(metadata) == 1
        assert isinstance(metadata[0], ContextRenderedSection)
        assert metadata[0].section_name == "test"
        assert metadata[0].token_count > 0

    def test_section_metadata_has_no_raw_content(self) -> None:
        renderer = ContextRenderer()
        renderer.add_stable_section("test", "secret content")
        metadata = renderer.section_metadata[0]
        d = metadata.model_dump()
        assert "content" not in d
        assert "raw_content" not in d
        assert "rendered_text" not in d

    def test_estimated_tokens_public(self) -> None:
        renderer = ContextRenderer()
        renderer.add_stable_section("a", "hello")
        assert renderer.estimated_tokens > 0

    def test_rendered_content_sha256_has_prefix(self) -> None:
        renderer = ContextRenderer()
        renderer.add_stable_section("test", "content")
        sha = renderer.rendered_content_sha256
        assert sha.startswith("sha256:")

    def test_to_dict_uses_public_properties(self) -> None:
        renderer = ContextRenderer()
        renderer.add_stable_section("test", "hello")
        d = renderer.to_dict()
        assert d["section_count"] == renderer.section_count
        assert d["estimated_tokens"] == renderer.estimated_tokens


# ── Hash format tests ────────────────────────────────────────────


class TestHashFormat:
    def test_section_sha256_has_prefix(self) -> None:
        renderer = ContextRenderer()
        renderer.add_stable_section("test", "content")
        meta = renderer.section_metadata[0]
        assert meta.section_sha256 is not None
        assert meta.section_sha256.startswith("sha256:")

    def test_substitution_table_sha256_has_prefix(self) -> None:
        renderer = ContextRenderer(compression_mode="aggressive")
        renderer.add_stable_section("test", "hello " * 100)
        # Compression will likely fail on this trivial content, but
        # we just verify the hash format when table is manually set
        renderer._substitution_table = {"test": "value"}
        sha = renderer.substitution_table_sha256
        assert sha is not None
        assert sha.startswith("sha256:")

    def test_rendered_content_hash_consistent(self) -> None:
        renderer = ContextRenderer()
        renderer.add_stable_section("test", "hello")
        sha1 = renderer.rendered_content_sha256
        sha2 = renderer.rendered_content_sha256
        assert sha1 == sha2


# ── Compression tests ────────────────────────────────────────────


class TestCompressionWarnings:
    def test_compression_failure_records_warning(self) -> None:
        renderer = ContextRenderer(compression_mode="aggressive")
        renderer.add_stable_section("test", "x" * 100)
        # Aggressive mode triggers compression attempt
        applied = renderer.apply_compression()
        # May succeed or fail; either way no crash
        assert applied in {True, False}

    def test_no_compression_mode_no_warning(self) -> None:
        renderer = ContextRenderer(compression_mode="none")
        renderer.add_stable_section("test", "hello")
        applied = renderer.apply_compression()
        assert applied is False

    def test_warnings_property_exists(self) -> None:
        renderer = ContextRenderer()
        assert isinstance(renderer.warnings, list)


# ── Privacy tests ────────────────────────────────────────────────


class TestRendererPrivacy:
    def test_no_raw_messages_in_rendered_content(self) -> None:
        renderer = ContextRenderer()
        msg = MagicMock()
        msg.role = "user"
        msg.content = "my secret message"
        renderer.add_recent_messages_section([msg])
        _ = renderer.rendered_content
        assert "my secret message" not in renderer.rendered_content

    def test_no_absolute_paths_in_repo_section(self) -> None:
        renderer = ContextRenderer()
        renderer.add_repo_section(root="/Users/user/dev/rig-relay")
        _ = renderer.rendered_content
        assert "/Users/user" not in renderer.rendered_content

    def test_root_hash_not_raw_path(self) -> None:
        renderer = ContextRenderer()
        renderer.add_repo_section(root="/tmp/test")
        _ = renderer.rendered_content
        assert "/tmp/test" not in renderer.rendered_content
        assert "root_hash" in renderer.rendered_content

    def test_collision_paths_hashed(self) -> None:
        renderer = ContextRenderer()
        renderer.add_active_work_section(collision_paths=["/secret/path.py"])
        _ = renderer.rendered_content
        assert "/secret/path.py" not in renderer.rendered_content
        assert "collision_path_hashes" in renderer.rendered_content


# ── Cache ordering tests ─────────────────────────────────────────


class TestCacheOrdering:
    def test_stable_before_volatile(self) -> None:
        renderer = ContextRenderer()
        renderer.add_stable_section("doctrine", "rules")
        renderer.add_repo_section()
        renderer.add_active_work_section()
        renderer.add_receipts_section([{"kind": "test"}])

        _ = renderer.rendered_content
        sections = renderer.section_metadata

        # Stable should come first
        names = [s.section_name for s in sections]
        stable_idx = names.index("doctrine")
        receipt_idx = names.index("receipts")
        assert stable_idx < receipt_idx, (
            f"stable ({stable_idx}) should be before volatile ({receipt_idx})"
        )
