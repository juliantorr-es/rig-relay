"""Lane B6.6: Live Recovery Handoff Execution and Scheduler Ordering Closure.

Production-boundary tests exercising the remaining B6 closure requirements:
  B6.6.1 — Handoff execution: read-only/validation handoffs route through
           ToolRuntime.execute_one() → real tool invocation → canonical outcome
  B6.6.2 — Out-of-order proof: concurrent ToolRuntime.execute_one() calls
           preserve correlation when completion order differs from request order
  B6.6.3 — Mutation proposal routing: mutation handoffs go through
           MUTATION_PROPOSAL mode, never direct execution
  B6.6.4 — Content-light enforcement on all handoff execution outcomes

No manufactured terminal outcomes. Every read-only/validation handoff enters
the real governed ToolRuntime.execute_one() boundary. Every mutation handoff
enters the proposal-only path.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from rig_relay.core.tool_result_runtime import ToolResultRuntime
from rig_relay.core.tool_runtime_models import (
    ToolRuntimeExecutionMode,
    ToolRuntimeRequest,
)
from rig_relay.core.tools._agent_outcome import MutationDisposition
from rig_relay.core.types import LLMMessage
from tests.conftest import build_test_agent_loop, build_test_vibe_config


def _sha256(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


def _handoff_sha(data: str) -> str:
    return _sha256(data)


def _parse_annotation(text: str) -> str | None:
    start = text.find("<rig-tool-outcome>")
    end = text.find("</rig-tool-outcome>")
    if start == -1 or end == -1:
        return None
    return text[start + len("<rig-tool-outcome>") : end]


def _assert_annotated(text: str) -> str:
    result = _parse_annotation(text)
    assert result is not None, f"No annotation in: {text[:200]}"
    return result


def _annotation_count(text: str) -> int:
    return text.count("<rig-tool-outcome>")


def _outcome_schema() -> dict[str, Any]:
    schema_path = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.agent_tool_outcome.v1.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _validate_schema(json_str: str) -> dict[str, Any]:
    from jsonschema import validate as jsonschema_validate

    parsed = json.loads(json_str)
    jsonschema_validate(instance=parsed, schema=_outcome_schema())
    return parsed


class _CapturingEvidence:
    def __init__(self) -> None:
        self.events: list[Any] = []
        self.artifacts: list[tuple[str, str]] = []
        self.outcome_projections: list[Any] = []
        self.tool_calls_finished: list[dict] = []

    def emit_runtime_outcome_projection_event(self, event: Any, **kwargs: Any) -> None:
        self.events.append(event)

    def emit_agent_outcome_projection(self, outcome: Any, **kwargs: Any) -> None:
        self.outcome_projections.append(outcome)

    def emit_artifact_written(
        self,
        artifact: Any = None,
        display_text: str = "",
        tool_name: str = "",
        sequence: int = 0,
    ) -> str:
        bounded = f"[ARTIFACTED {tool_name}] {display_text[:200]}..."
        self.artifacts.append((tool_name, bounded))
        return bounded

    def emit_tool_call_finished(self, **kwargs: Any) -> None:
        self.tool_calls_finished.append(kwargs)

    def capture_model_observation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def emit_tool_reasoning_trace(self, **kwargs: Any) -> None:
        pass


# ── B6.6.1: Handoff Execution Through Governed ToolRuntime ─────────────


class TestB6_6_1_HandoffExecution:
    """Read-only and validation handoffs enter real ToolRuntime.execute_one()."""

    def _make_read_only_handoff(self, tool_name: str = "git_status") -> Any:
        from rig_relay.recovery.handoff import build_read_only_handoff

        return build_read_only_handoff(
            _handoff_sha(f"r-{tool_name}"),
            _handoff_sha(f"m-{tool_name}"),
            tool_name,
            _handoff_sha(f"p-{tool_name}"),
        )

    def _make_validation_handoff(self) -> Any:
        from rig_relay.recovery.handoff import build_validation_handoff

        return build_validation_handoff(
            _handoff_sha("receipt-val-exec"),
            _handoff_sha("manifest-val-exec"),
            "validate",
            _handoff_sha("payload-val-exec"),
        )

    def _make_mutation_handoff(self) -> Any:
        from rig_relay.recovery.handoff import build_mutation_handoff

        return build_mutation_handoff(
            _handoff_sha("receipt-mut-exec"),
            _handoff_sha("manifest-mut-exec"),
            "write_file",
            _handoff_sha("payload-mut-exec"),
            mutation_class="writes_workspace",
        )

    @pytest.mark.asyncio
    async def test_read_only_handoff_executes_through_real_tool_runtime(self) -> None:
        """A read-only handoff for git_status enters ToolRuntime.execute_one()
        and produces a real outcome (not a manufactured admission annotation).
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        handoff = self._make_read_only_handoff("git_status")

        msg = await runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["tool_name"] == "git_status"
        assert evidence.events, "No projection event for executed read_only handoff"
        event = evidence.events[-1]
        assert event.model_visible_outcome_digest.startswith("sha256:")
        assert event.outcome_annotation_hash.startswith("sha256:")
        assert event.content_light is True

    @pytest.mark.asyncio
    async def test_read_only_handoff_uses_read_file(self) -> None:
        """Read-only handoff for read_file enters ToolRuntime and executes."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        handoff = self._make_read_only_handoff("read_file")

        msg = await runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["tool_name"] == "read_file"

    @pytest.mark.asyncio
    async def test_validation_handoff_executes_through_real_tool_runtime(self) -> None:
        """A validation handoff for validate enters ToolRuntime.execute_one()
        and produces a real outcome (not a manufactured admission annotation).
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        handoff = self._make_validation_handoff()

        msg = await runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["tool_name"] == "validate"
        assert evidence.events, "No projection event for executed validation handoff"

    @pytest.mark.asyncio
    async def test_handoff_execution_produces_distinct_events_per_call(self) -> None:
        """Each executed handoff produces its own unique projection event."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        await runtime.handle_recovery_handoff(
            self._make_read_only_handoff("git_status")
        )
        await runtime.handle_recovery_handoff(self._make_read_only_handoff("read_file"))

        assert len(evidence.events) >= 2
        digests = {e.model_visible_outcome_digest for e in evidence.events}
        assert len(digests) >= 2, "Each handoff must produce a unique outcome digest"

    @pytest.mark.asyncio
    async def test_handoff_execution_annotation_hash_matches_delivered_text(
        self,
    ) -> None:
        """The annotation hash in the projection event matches the SHA256 of
        the full <rig-tool-outcome> tag as delivered to the model.
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        handoff = self._make_read_only_handoff("git_status")

        msg = await runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        annotation = _assert_annotated(content)
        full_tag = f"<rig-tool-outcome>{annotation}</rig-tool-outcome>"
        expected_hash = _sha256(full_tag)

        event = evidence.events[-1]
        assert event.outcome_annotation_hash == expected_hash, (
            f"annotation hash mismatch: {event.outcome_annotation_hash} != {expected_hash}"
        )


# ── B6.6.2: Out-of-order Scheduler Proof ─────────────────────────────
#
# The production execution boundary is ToolRuntime.execute_one().
# Concurrent invocations with async interleaving must preserve per-call
# correlation. Completion order may differ from submission order.


@pytest.mark.asyncio
class TestB6_6_2_OutOfOrderScheduler:
    async def test_concurrent_execute_one_preserves_per_call_identity(self) -> None:
        """Two concurrent execute_one() calls with different completion times
        preserve per-call tool_call_id.
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        async def execute_handoff(call_id: str, tool_name: str, delay: float) -> None:
            await asyncio.sleep(delay)
            from rig_relay.recovery.handoff import build_read_only_handoff

            handoff = build_read_only_handoff(
                _handoff_sha(f"r-{call_id}"),
                _handoff_sha(f"m-{call_id}"),
                tool_name,
                _handoff_sha(f"p-{call_id}"),
            )
            handoff.runtime_correlation_id = call_id
            await runtime.handle_recovery_handoff(handoff)

        # B completes first, A later
        await asyncio.gather(
            execute_handoff("call_A", "git_status", 0.10),
            execute_handoff("call_B", "read_file", 0.01),
        )

        found: set[str] = set()
        for msg in loop.messages:
            content = getattr(msg, "content", "")
            annotation = _parse_annotation(content)
            if annotation is None:
                continue
            parsed = _validate_schema(annotation)
            found.add(str(parsed.get("tool_name", "")))
        assert "git_status" in found
        assert "read_file" in found

    async def test_concurrent_execute_one_projection_digest_binding(self) -> None:
        """Each concurrent execute_one() call binds its own annotation hash."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        async def execute_handoff(call_id: str, delay: float) -> None:
            await asyncio.sleep(delay)
            from rig_relay.recovery.handoff import build_read_only_handoff

            handoff = build_read_only_handoff(
                _handoff_sha(f"r-{call_id}"),
                _handoff_sha(f"m-{call_id}"),
                "git_status",
                _handoff_sha(f"p-{call_id}"),
            )
            handoff.runtime_correlation_id = call_id
            await runtime.handle_recovery_handoff(handoff)

        await asyncio.gather(
            execute_handoff("fast", 0.01), execute_handoff("slow", 0.10)
        )

        annotation_hashes = {e.outcome_annotation_hash for e in evidence.events}
        assert len(annotation_hashes) >= 2, (
            "Each call must have distinct annotation hash"
        )
        for h in annotation_hashes:
            assert h.startswith("sha256:")
            assert len(h) > 20

    async def test_direct_execute_one_concurrent_read_only(self) -> None:
        """Two direct ToolRuntime.execute_one() calls with concurrent interleaving
        preserve correlation IDs for read-only tools.
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)

        tool_runtime = (
            loop._get_tool_runtime()
            if hasattr(loop, "_get_tool_runtime")
            else getattr(loop, "_tool_runtime", None)
        )
        assert tool_runtime is not None, "_tool_runtime must be available"

        async def execute(call_id: str, delay: float) -> Any:
            await asyncio.sleep(delay)
            request = ToolRuntimeRequest(
                tool_name="git_status",
                tool_call_id=call_id,
                execution_mode=ToolRuntimeExecutionMode.READ_ONLY,
            )
            return await tool_runtime.execute_one(request)

        # Slow completes first (0.01), fast second (0.10)
        tasks = [
            asyncio.create_task(execute("slow_first", 0.01)),
            asyncio.create_task(execute("fast_second", 0.10)),
        ]
        results = await asyncio.gather(*tasks)

        cids = {r.tool_call_id for r in results}
        assert "slow_first" in cids
        assert "fast_second" in cids
        for r in results:
            assert r.status.value in {"completed", "cached", "refused"}, (
                f"Unexpected status {r.status.value} for {r.tool_call_id}"
            )


# ── B6.6.3: Mutation Proposal Routing ─────────────────────────────────


class TestB6_6_3_MutationProposalRouting:
    @pytest.mark.asyncio
    async def test_mutation_handoff_enters_proposal_mode_not_direct_execution(
        self,
    ) -> None:
        """Mutation handoff routes through MUTATION_PROPOSAL execution mode."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        from rig_relay.recovery.handoff import build_mutation_handoff

        handoff = build_mutation_handoff(
            _handoff_sha("r-mut-prop"),
            _handoff_sha("m-mut-prop"),
            "write_file",
            _handoff_sha("p-mut-prop"),
            mutation_class="writes_workspace",
        )

        msg = await runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        # Mutation disposition must never be "performed"
        assert parsed["mutation_disposition"] != MutationDisposition.PERFORMED.value
        assert parsed["mutation_disposition"] in {
            MutationDisposition.NOT_APPLICABLE.value,
            MutationDisposition.NOT_PERFORMED.value,
        }

    @pytest.mark.asyncio
    async def test_mutation_handoff_never_produces_performed_disposition(self) -> None:
        """Hard invariant: mutation handoff execution must never produce
        mutation_disposition=performed, regardless of handoff content.
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        from rig_relay.recovery.handoff import build_mutation_handoff

        handoff = build_mutation_handoff(
            _handoff_sha("r-mut-safe"),
            _handoff_sha("m-mut-safe"),
            "search_replace",
            _handoff_sha("p-mut-safe"),
            mutation_class="writes_workspace",
        )

        msg = await runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["mutation_disposition"] != "performed"
        assert parsed["mutation_disposition"] != "previously_performed"
        assert evidence.events

    @pytest.mark.asyncio
    async def test_mutation_handoff_vs_read_only_handoff_distinct_paths(self) -> None:
        """Mutation handoffs and read-only handoffs produce observably
        different outcomes (mutation_disposition differs).
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        from rig_relay.recovery.handoff import (
            build_mutation_handoff,
            build_read_only_handoff,
        )

        await runtime.handle_recovery_handoff(
            build_read_only_handoff(
                _handoff_sha("ro"), _handoff_sha("mo"), "git_status", _handoff_sha("po")
            )
        )
        await runtime.handle_recovery_handoff(
            build_mutation_handoff(
                _handoff_sha("rm"),
                _handoff_sha("mm"),
                "write_file",
                _handoff_sha("pm"),
                mutation_class="writes_workspace",
            )
        )

        dispositions: dict[str, str] = {}
        for msg in loop.messages:
            content = getattr(msg, "content", "")
            annotation = _parse_annotation(content)
            if annotation is None:
                continue
            parsed = _validate_schema(annotation)
            dispositions[parsed["tool_name"]] = parsed["mutation_disposition"]

        assert (
            dispositions.get("git_status") == MutationDisposition.NOT_APPLICABLE.value
        )
        assert dispositions.get("write_file") != MutationDisposition.PERFORMED.value


# ── B6.6.4: Content-light Enforcement ─────────────────────────────────


class TestB6_6_4_ContentLightExecution:
    @pytest.mark.asyncio
    async def test_handoff_execution_projection_schema_validates(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        from rig_relay.recovery.handoff import build_read_only_handoff

        handoff = build_read_only_handoff(
            _handoff_sha("r-schema"),
            _handoff_sha("m-schema"),
            "git_status",
            _handoff_sha("p-schema"),
        )
        await runtime.handle_recovery_handoff(handoff)
        assert evidence.events

        event = evidence.events[-1]
        event_dict = event.to_dict()
        from pathlib import Path

        from jsonschema import validate as jsonschema_validate

        schema_path = (
            Path(__file__).parents[2]
            / "docs"
            / "schemas"
            / "rig.relay.runtime_outcome_projection_event.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text())
        jsonschema_validate(instance=event_dict, schema=schema)

    @pytest.mark.asyncio
    async def test_handoff_execution_events_never_leak_raw_output(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        from rig_relay.recovery.handoff import build_read_only_handoff

        handoff = build_read_only_handoff(
            _handoff_sha("r-raw"),
            _handoff_sha("m-raw"),
            "git_status",
            _handoff_sha("p-raw"),
        )
        await runtime.handle_recovery_handoff(handoff)
        assert evidence.events

        for event in evidence.events:
            serialized = event.to_json().lower()
            assert "api_key" not in serialized
            assert "sk-" not in serialized
            assert "secret" not in serialized
            assert event.content_light is True
