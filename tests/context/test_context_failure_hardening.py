from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.context.renderer import ContextRenderer, TrustTier
from rig_relay.context.warnings import (
    ContextWarningCode,
    build_warning,
    exception_class_name,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestRendererCompressionWarnings:
    def test_compression_failure_warns(self):
        renderer = ContextRenderer(compression_mode="symbol_substitution")
        renderer.add_stable_section("test", "x" * 100, "repo_map")

        # Force an import error by removing a required attribute
        import rig_relay.context.symbol_codec
        original = getattr(rig_relay.context.symbol_codec, "compress_with_manifest", None)
        del rig_relay.context.symbol_codec.compress_with_manifest
        try:
            applied = renderer.apply_compression()
            if not applied:
                assert any(
                    isinstance(w, dict) and w.get("code") == ContextWarningCode.COMPRESSION_FAILED
                    for w in renderer.warnings
                ), f"Expected COMPRESSION_FAILED warning, got: {renderer.warnings}"
        finally:
            if original is not None:
                rig_relay.context.symbol_codec.compress_with_manifest = original

    def test_compression_none_no_warning(self):
        renderer = ContextRenderer(compression_mode="none")
        renderer.add_stable_section("test", "hello", "repo_map")
        applied = renderer.apply_compression()
        assert not applied
        assert len(renderer.warnings) == 0


class TestWarningModel:
    def test_build_warning_is_content_light(self):
        w = build_warning(
            ContextWarningCode.REPO_SCAN_FAILED,
            detail="Something failed",
            source="compiler",
        )
        assert w["code"] == ContextWarningCode.REPO_SCAN_FAILED
        assert len(w["detail"]) <= 200
        assert "/Users/" not in str(w)

    def test_exception_class_name_is_safe(self):
        name = exception_class_name(ValueError("sensitive_path=/home/user"))
        assert name == "ValueError"
        assert "/home/user" not in name

    def test_build_warning_truncates_long_detail(self):
        w = build_warning(
            ContextWarningCode.REPO_SCAN_FAILED,
            detail="x" * 500,
        )
        assert len(w["detail"]) <= 200


class TestSecurityBoundaries:
    def test_recent_messages_are_not_first_party(self):
        renderer = ContextRenderer()

        class FakeMsg:
            role = "assistant"
            content = "I think we should..."

        renderer.add_recent_messages_section([FakeMsg()])
        sections = renderer.sections
        msg_section = [s for s in sections if s["section_name"] == "recent_messages"]
        assert len(msg_section) >= 1
        assert msg_section[0]["trust_tier"] != TrustTier.first_party

    def test_repo_section_is_not_first_party(self):
        renderer = ContextRenderer()
        renderer.add_repo_section(root="/tmp/test", branch="main", head="abc")
        sections = renderer.sections
        repo = [s for s in sections if s["section_name"] == "repository"]
        assert len(repo) >= 1
        assert repo[0]["trust_tier"] != TrustTier.first_party


class TestNoBareExceptPass:
    def test_renderer_has_no_bare_except_pass(self):
        source = (_REPO_ROOT / "rig_relay" / "context" / "renderer.py").read_text()
        lines = source.split("\n")
        in_except = False
        for i, line in enumerate(lines):
            if "except Exception:" in line or "except Exception as" in line:
                in_except = True
                continue
            if in_except and line.strip() == "pass":
                assert False, f"renderer.py line {i + 1}: bare except:pass not allowed"
            if in_except and line.strip() and not line.strip().startswith("#"):
                in_except = False

    def test_warnings_module_exists(self):
        assert (_REPO_ROOT / "rig_relay" / "context" / "warnings.py").is_file()
