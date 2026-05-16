from __future__ import annotations

from pathlib import Path

import pytest

from rig_relay.context.renderer import ContextRenderer, TrustTier

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestEvidenceNotInstructions:
    def test_repo_section_is_not_first_party(self):
        renderer = ContextRenderer()
        renderer.add_repo_section(root="/tmp/test", branch="main", head="abc")
        sections = renderer.sections
        repo = [s for s in sections if s["section_name"] == "repository"]
        assert len(repo) >= 1
        assert repo[0]["trust_tier"] != TrustTier.first_party

    def test_recent_messages_are_not_first_party(self):
        renderer = ContextRenderer()

        class FakeMsg:
            role = "assistant"
            content = "I think we should..."

        renderer.add_recent_messages_section([FakeMsg()])
        sections = renderer.sections
        msgs = [s for s in sections if s["section_name"] == "recent_messages"]
        assert len(msgs) >= 1
        assert msgs[0]["trust_tier"] != TrustTier.first_party

    def test_stable_section_can_be_first_party(self):
        renderer = ContextRenderer()
        renderer.add_stable_section("doctrine", "Rule: do not force push", "repo_map")
        sections = renderer.sections
        assert sections[0]["trust_tier"] == TrustTier.first_party

    def test_subsystem_section_is_not_first_party(self):
        renderer = ContextRenderer()
        renderer.add_subsystem_section([{"name": "core"}, {"name": "desktop"}])
        sections = renderer.sections
        sub = [s for s in sections if s["section_name"] == "subsystems"]
        assert len(sub) >= 1
        assert sub[0]["trust_tier"] != TrustTier.first_party


class TestProvenanceRegressions:
    def test_existing_privacy_tests_still_pass(self):
        """Privacy: recent messages hashed, root not raw, collisions hashed."""
        renderer = ContextRenderer(workspace_root=Path("/Users/alice/project"))

        class FakeMsg:
            role = "user"
            content = "secret token abc123"

        renderer.add_repo_section(
            root="/Users/alice/project", branch="main", head="abc123"
        )
        renderer.add_recent_messages_section([FakeMsg()])
        renderer.add_active_work_section(
            lane_count=1, collision_count=1, collision_paths=["/Users/alice/src/main.py"]
        )
        rendered = renderer.rendered_content

        assert "/Users/alice" not in rendered
        assert "secret token" not in rendered
        assert "abc123" not in rendered


class TestNoAbsoluteHomePaths:
    def test_renderer_section_builders_no_home_paths(self):
        import os

        home = os.path.expanduser("~")
        renderer = ContextRenderer(workspace_root=Path("/tmp/test"))

        class FakeMsg:
            role = "user"
            content = "hello"

        renderer.add_repo_section(root="/tmp/test", branch="main", head="abc")
        renderer.add_recent_messages_section([FakeMsg()])
        renderer.add_active_work_section(lane_count=0, collision_count=0)
        renderer.add_do_not_touch_section([])
        renderer.add_receipts_section([])
        renderer.add_subsystem_section([{"name": "core"}])
        renderer.add_snapshot_section("snap content")

        rendered = renderer.rendered_content
        assert home not in rendered or home == "/var/empty", (
            f"Absolute home path leaked: {home}"
        )


class TestTrustTierCoverage:
    def test_all_trust_tiers_are_strings(self):
        for attr in dir(TrustTier):
            if not attr.startswith("_") and attr.isupper():
                val = getattr(TrustTier, attr)
                assert isinstance(val, str)
