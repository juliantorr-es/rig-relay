"""Tests for context observation model — Pydantic validation, JSON round-trips, schema conformance."""

from __future__ import annotations

import json

from pydantic import ValidationError
import pytest

from rig_relay.context.observation import ContextObservation


class TestContextObservationModel:
    """ContextObservation Pydantic model behavior."""

    def test_minimal_observation(self) -> None:
        obs = ContextObservation(tool_name="read_file", tool_status="succeeded")
        assert obs.kind == "rig.context.observation.v1"
        assert obs.context_available is False
        assert obs.observation_only is True
        assert obs.matched_recommended_context is False
        assert obs.overlapped_active_work is False
        assert obs.touched_dirty_path is False
        assert obs.blocked_by_policy is False

    def test_full_observation(self) -> None:
        obs = ContextObservation(
            session_id="sess-1",
            agent_id="agent-1",
            context_id="ctx-1",
            tool_call_id="tc-1",
            tool_name="search_replace",
            target_paths=["src/main.py"],
            mutation_class="writes_workspace",
            context_available=True,
            matched_recommended_context=True,
            overlapped_active_work=True,
            touched_dirty_path=True,
            touched_soft_warning=False,
            touched_hard_denied_path=False,
            tool_status="succeeded",
            blocked_by_policy=False,
        )
        assert obs.kind == "rig.context.observation.v1"
        assert obs.observation_only is True
        assert obs.target_paths == ["src/main.py"]

    def test_observation_only_is_always_true(self) -> None:
        """The const field must always be True regardless of input."""
        obs = ContextObservation(tool_name="test", tool_status="pending")
        assert obs.observation_only is True

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ContextObservation.model_validate({
                "tool_name": "t",
                "tool_status": "succeeded",
                "unknown": "x",
            })

    def test_constructs_with_defaults(self) -> None:
        """All fields have sensible defaults, empty construct works."""
        obs = ContextObservation()
        assert obs.kind == "rig.context.observation.v1"
        assert obs.tool_name == ""
        assert obs.tool_status == "pending"
        assert obs.observation_only is True
        assert obs.context_available is False

    def test_json_round_trip(self) -> None:
        obs = ContextObservation(
            tool_name="grep", target_paths=["src/"], tool_status="succeeded"
        )
        data = json.loads(obs.model_dump_json())
        restored = ContextObservation.model_validate(data)
        assert restored.tool_name == "grep"
        assert restored.target_paths == ["src/"]
        assert restored.created_at == obs.created_at

    def test_serializes_without_raw_fields(self) -> None:
        """No file contents, diffs, or secrets should appear in the dump."""
        obs = ContextObservation(tool_name="bash", tool_status="succeeded")
        raw = obs.model_dump_json()
        assert "content" not in raw
        assert "secret" not in raw
        assert "diff" not in raw
        assert "stdout" not in raw
        assert "stderr" not in raw

    def test_multiple_target_paths(self) -> None:
        obs = ContextObservation(
            tool_name="search_replace",
            target_paths=["a.py", "b.py", "c.py"],
            tool_status="succeeded",
        )
        assert len(obs.target_paths) == 3
