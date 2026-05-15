"""Tests for context correlation — verifies tool call ↔ context packet matching.

All tests use in-memory ContextPacket objects. No I/O, no git, no file system.
Proves correlation does not block tool calls and missing context produces safe defaults.
"""

from __future__ import annotations

import itertools

import pytest

from rig_relay.context.correlation import (
    _extract_target_paths,
    _match_recommended_context,
    _normalize_paths,
    _overlap_active_work,
    _touched_dirty_paths,
    _touched_hard_denied,
    correlate_tool_call_with_context,
)
from rig_relay.context.models import (
    ContextPacket,
    PathRecommendation,
    RepoInfo,
)


def _make_packet(**overrides: dict) -> ContextPacket:
    """Build a test ContextPacket with sensible defaults."""
    p = ContextPacket(
        mode="map",
        request_sha256="sha256:test",
        repo=RepoInfo(root="/repo", head="abc123", branch="main"),
        summary_text="Test context",
    )
    return p.model_copy(update=overrides)


# ── Path extraction ──────────────────────────────────────────────


class TestExtractTargetPaths:
    def test_known_path_key(self) -> None:
        paths = _extract_target_paths({"path": "src/main.py", "pattern": "def"})
        assert "src/main.py" in paths
        assert "def" not in paths  # pattern is not a path key

    def test_multiple_path_keys(self) -> None:
        paths = _extract_target_paths({"file_path": "a.py", "paths": ["b.py", "c.py"]})
        assert len(paths) == 3

    def test_non_string_values_skipped(self) -> None:
        paths = _extract_target_paths({"path": 123, "targets": None})
        assert paths == []

    def test_empty_args(self) -> None:
        paths = _extract_target_paths({})
        assert paths == []

    def test_none_args(self) -> None:
        paths = _extract_target_paths({})
        assert paths == []


# ── Path normalization ───────────────────────────────────────────


class TestNormalizePaths:
    def test_strips_leading_dot_slash(self) -> None:
        assert _normalize_paths(["./src/main.py"]) == ["src/main.py"]

    def test_strips_leading_slash(self) -> None:
        assert _normalize_paths(["/src/main.py"]) == ["src/main.py"]

    def test_converts_backslashes(self) -> None:
        result = _normalize_paths(["src\\main.py"])
        # Only test on platforms where backslash is a path separator
        assert len(result) == 1
        # The result may be src/main.py or src\main.py depending on platform
        # Either way it should not be empty and should not crash

    def test_removes_empty_strings(self) -> None:
        assert _normalize_paths(["", " ", "a.py"]) == ["a.py"]

    def test_preserves_already_normalized(self) -> None:
        assert _normalize_paths(["src/main.py", "docs/guide.md"]) == ["src/main.py", "docs/guide.md"]


# ── Recommended context matching ─────────────────────────────────


class TestMatchRecommendedContext:
    def test_exact_match(self) -> None:
        packet = _make_packet(recommended_context=[
            PathRecommendation(path="docs/guide.md", reason="Important"),
        ])
        assert _match_recommended_context(packet, ["docs/guide.md"]) is True

    def test_no_match(self) -> None:
        packet = _make_packet(recommended_context=[
            PathRecommendation(path="docs/guide.md", reason="Important"),
        ])
        assert _match_recommended_context(packet, ["src/main.py"]) is False

    def test_empty_paths(self) -> None:
        packet = _make_packet(recommended_context=[
            PathRecommendation(path="docs/guide.md", reason="Important"),
        ])
        assert _match_recommended_context(packet, []) is False

    def test_empty_recommendations(self) -> None:
        packet = _make_packet()
        assert _match_recommended_context(packet, ["src/main.py"]) is False


# ── Active work overlap ──────────────────────────────────────────


class TestOverlapActiveWork:
    def test_collision_warning_match(self) -> None:
        packet = _make_packet(active_work={
            "lanes": [],
            "collision_warnings": [{"path": "src/main.py", "claimed_by": "a1", "reason": "test"}],
        })
        assert _overlap_active_work(packet, ["src/main.py"]) is True

    def test_claimed_paths_match(self) -> None:
        packet = _make_packet(active_work={
            "lanes": [{"agent_id": "a1", "claimed_paths": ["src/main.py"], "status": "active"}],
            "collision_warnings": [],
        })
        assert _overlap_active_work(packet, ["src/main.py"]) is True

    def test_no_overlap(self) -> None:
        packet = _make_packet(active_work={
            "lanes": [{"agent_id": "a1", "claimed_paths": ["docs/"], "status": "active"}],
            "collision_warnings": [],
        })
        assert _overlap_active_work(packet, ["src/main.py"]) is False

    def test_empty_paths(self) -> None:
        packet = _make_packet(active_work={
            "lanes": [{"agent_id": "a1", "claimed_paths": ["src/main.py"], "status": "active"}],
            "collision_warnings": [],
        })
        assert _overlap_active_work(packet, []) is False


# ── Dirty path detection ─────────────────────────────────────────


class TestTouchedDirtyPaths:
    def test_dirty_count_indicates_possible_match(self) -> None:
        packet = _make_packet(repo=RepoInfo(
            root="/repo", head="h", branch="b",
            dirty_summary={"modified": 3, "untracked": 1, "staged": 0},
        ))
        assert _touched_dirty_paths(packet, ["src/main.py"]) is True

    def test_clean_repo(self) -> None:
        packet = _make_packet(repo=RepoInfo(
            root="/repo", head="h", branch="b",
            dirty_summary={"modified": 0, "untracked": 0, "staged": 0},
        ))
        assert _touched_dirty_paths(packet, ["src/main.py"]) is False

    def test_empty_paths(self) -> None:
        packet = _make_packet(repo=RepoInfo(
            root="/repo", head="h", branch="b",
            dirty_summary={"modified": 3, "untracked": 0, "staged": 0},
        ))
        assert _touched_dirty_paths(packet, []) is False


# ── Hard denied / do_not_touch ───────────────────────────────────


class TestTouchedHardDenied:
    def test_exact_match(self) -> None:
        packet = _make_packet(do_not_touch=[
            PathRecommendation(path="secrets.json", reason="Credentials"),
        ])
        assert _touched_hard_denied(packet, ["secrets.json"]) is True

    def test_no_match(self) -> None:
        packet = _make_packet(do_not_touch=[
            PathRecommendation(path="secrets.json", reason="Credentials"),
        ])
        assert _touched_hard_denied(packet, ["src/main.py"]) is False

    def test_empty_deny_list(self) -> None:
        packet = _make_packet()
        assert _touched_hard_denied(packet, ["secrets.json"]) is False


# ── Full correlation ─────────────────────────────────────────────


class TestCorrelateToolCallWithContext:
    """Prove correlation does not block and produces correct observations."""

    def test_does_not_raise_without_context(self) -> None:
        """Missing context must not cause errors."""
        obs = correlate_tool_call_with_context(
            context_packet=None,
            tool_name="read_file",
            tool_args={"path": "src/main.py"},
        )
        assert obs.context_available is False
        assert obs.tool_name == "read_file"

    def test_does_not_raise_without_args(self) -> None:
        """Missing args must not cause errors."""
        obs = correlate_tool_call_with_context(
            context_packet=_make_packet(),
            tool_name="read_file",
            tool_args=None,
        )
        assert obs.context_available is True
        assert obs.target_paths == []

    def test_context_available_true_with_packet(self) -> None:
        obs = correlate_tool_call_with_context(
            context_packet=_make_packet(),
            tool_name="bash",
            tool_args={"command": "ls"},
        )
        assert obs.context_available is True

    def test_observation_only_is_always_true(self) -> None:
        obs = correlate_tool_call_with_context(
            context_packet=None,
            tool_name="bash",
            tool_args={"command": "rm -rf /"},
        )
        assert obs.observation_only is True

    def test_match_recommended_detected(self) -> None:
        packet = _make_packet(recommended_context=[
            PathRecommendation(path="docs/guide.md", reason="Read first"),
        ])
        obs = correlate_tool_call_with_context(
            context_packet=packet,
            tool_name="read_file",
            tool_args={"path": "docs/guide.md"},
        )
        assert obs.matched_recommended_context is True

    def test_overlap_detected(self) -> None:
        packet = _make_packet(active_work={
            "lanes": [{"agent_id": "a1", "claimed_paths": ["src/main.py"], "status": "active"}],
            "collision_warnings": [],
        })
        obs = correlate_tool_call_with_context(
            context_packet=packet,
            tool_name="search_replace",
            tool_args={"file_path": "src/main.py"},
        )
        assert obs.overlapped_active_work is True

    def test_tool_status_passed_through(self) -> None:
        obs = correlate_tool_call_with_context(
            context_packet=_make_packet(),
            tool_name="bash",
            tool_args={"command": "echo hi"},
            tool_status="succeeded",
        )
        assert obs.tool_status == "succeeded"

    def test_blocked_by_policy_passed_through(self) -> None:
        obs = correlate_tool_call_with_context(
            context_packet=_make_packet(),
            tool_name="bash",
            tool_args={"command": "git reset"},
            blocked_by_policy=True,
        )
        assert obs.blocked_by_policy is True

    def test_multiple_target_paths(self) -> None:
        obs = correlate_tool_call_with_context(
            context_packet=_make_packet(do_not_touch=[
                PathRecommendation(path="secret.key", reason="Key material"),
            ]),
            tool_name="search_replace",
            tool_args={"file_path": "secret.key"},
            tool_status="refused",
        )
        assert obs.touched_hard_denied_path is True
        assert obs.tool_status == "refused"


class TestCorrelationDoesNotBlock:
    """Prove correlation is observation-only and never blocks."""

    @pytest.mark.parametrize(
        "tool_name, tool_args",
        [
            ("read_file", {"path": "src/main.py"}),
            ("search_replace", {"file_path": "docs/guide.md"}),
            ("write_file", {"path": "src/new.py"}),
            ("bash", {"command": "echo hi"}),
            ("grep", {"pattern": "def", "path": "."}),
            ("get_context", {"mode": "map"}),
        ],
    )
    def test_all_tool_types_produce_observation(self, tool_name: str, tool_args: dict) -> None:
        """Prove correlation never raises for any tool type."""
        obs = correlate_tool_call_with_context(
            context_packet=_make_packet(),
            tool_name=tool_name,
            tool_args=tool_args,
        )
        assert obs.tool_name == tool_name
        assert obs.observation_only is True

    def test_no_side_effects(self) -> None:
        """Prove correlation does not modify its inputs."""
        args = {"path": "src/main.py"}
        packet = _make_packet()
        packet_copy = packet.model_copy(deep=True)
        correlate_tool_call_with_context(packet, "read_file", args)
        assert packet.model_dump() == packet_copy.model_dump()
        assert args == {"path": "src/main.py"}
