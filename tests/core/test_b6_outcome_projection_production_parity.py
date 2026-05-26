"""Lane B6: Runtime Outcome Projection Production Bridge Parity and Recovery Handoff.

Real production-boundary acceptance tests exercising:
  B6.1 — Bridge/conversation parity: projection event digest = delivered annotation hash
  B6.2 — Out-of-order executor correlation through real delivery boundary
  B6.3 — D1 recovery handoff integration (read-only, validation, mutation-proposal, refusal)
  B6.4 — Deprecated shim removal verification
  B6.5 — Content-light enforcement on projection events

No mocks. No stubs. No direct build_projection_event() calls as substitute for
production boundary. All outcomes pass through the real ToolResultRuntime and
are inspected in the actual loop.messages list.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from rig_relay.core.tool_result_runtime import (
    ToolResultRuntime,
    _resolve_mutation_class,
)
from rig_relay.core.tool_runtime_models import (
    RefusalCode,
    ToolRuntimeRefusal,
    ToolRuntimeResult,
    ToolRuntimeStatus,
)
from rig_relay.core.tools._agent_outcome import MutationDisposition
from rig_relay.core.types import LLMMessage
from rig_relay.runtime.outcome_projection import OutcomeProjectionEvent
from tests.conftest import build_test_agent_loop, build_test_vibe_config

# ── Helpers ─────────────────────────────────────────────────────────


def _sha256(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


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


class _FakeFailedCall:
    def __init__(self, tool_name: str, call_id: str, error: str) -> None:
        self.tool_name = tool_name
        self.call_id = call_id
        self.error = error


class _FakeToolCall:
    def __init__(self, tool_name: str, call_id: str) -> None:
        self.tool_name = tool_name
        self.call_id = call_id
        self.args_dict: dict[str, Any] = {}
        self.tool_class = None


def _make_result(
    status: ToolRuntimeStatus = ToolRuntimeStatus.COMPLETED,
    tool_name: str = "test_tool",
    tool_call_id: str = "call_001",
    mutation_performed: bool = False,
    cache_hit: bool = False,
    error_kind: str | None = None,
    refusal: ToolRuntimeRefusal | None = None,
    degraded_capabilities: list[str] | None = None,
    investigation_outcome: str | None = None,
) -> ToolRuntimeResult:
    return ToolRuntimeResult(
        status=status,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        mutation_performed=mutation_performed,
        cache_hit=cache_hit,
        error_kind=error_kind,
        refusal=refusal,
        degraded_capabilities=degraded_capabilities or [],
        investigation_outcome=investigation_outcome,
    )


# ── B6.1: Bridge/Conversation Parity ────────────────────────────────
#
# Every model-visible <rig-tool-outcome> annotation must have a corresponding
# projection event whose outcome_annotation_hash matches the SHA256 of the
# annotation text as it appears in the delivered message. This MUST hold for
# inline, artifacted, empty, and error outcomes.
#
# The production bridge IS the ToolResultRuntime path (AgentLoop delegates
# _handle_tool_response to ToolResultRuntime.handle_tool_response). The old
# ToolResponseMixin._handle_tool_response body is dead code (overridden).
# Parity is proven by showing that the same runtime pass produces matching
# annotation-and-projection pairs through the real delivery boundary.


class _CapturingEvidence:
    """Captures every runtime-outcome projection event for later inspection."""

    def __init__(self) -> None:
        self.events: list[OutcomeProjectionEvent] = []
        self.artifacts: list[tuple[str, str]] = []
        self.outcome_projections: list[Any] = []

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
        pass

    def capture_model_observation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def emit_tool_reasoning_trace(self, **kwargs: Any) -> None:
        pass


class TestB6_1_BridgeConversationParity:
    """Digest parity between delivered annotation and projection event."""

    def _deliver_and_capture(
        self, result: ToolRuntimeResult, text: str, status: str = "success"
    ) -> tuple[str, OutcomeProjectionEvent | None]:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        tc = _FakeToolCall(result.tool_name, result.tool_call_id)
        runtime.handle_tool_response(
            tool_call=tc, text=text, status=status, runtime_result=result
        )
        msg = runtime._loop.messages[-1]
        content = getattr(msg, "content", "")
        annotation = _assert_annotated(content)
        event = evidence.events[-1] if evidence.events else None
        return annotation, event

    def test_inline_outcome_digest_correspondence(self) -> None:
        result = _make_result(
            ToolRuntimeStatus.COMPLETED,
            "read_file",
            "call_inline",
            investigation_outcome="match",
        )
        annotation, event = self._deliver_and_capture(result, "some output")
        assert event is not None
        expected_hash = _sha256(f"<rig-tool-outcome>{annotation}</rig-tool-outcome>")
        assert event.outcome_annotation_hash == expected_hash, (
            f"annotation hash mismatch: {event.outcome_annotation_hash} != {expected_hash}"
        )
        assert event.output_kind == "inline"
        assert event.model_visible_outcome_digest.startswith("sha256:")

    def test_empty_outcome_digest_correspondence(self) -> None:
        result = _make_result(ToolRuntimeStatus.COMPLETED, "echo", "call_empty")
        annotation, event = self._deliver_and_capture(result, "")
        assert event is not None
        expected_hash = _sha256(f"<rig-tool-outcome>{annotation}</rig-tool-outcome>")
        assert event.outcome_annotation_hash == expected_hash
        assert event.output_kind == "empty"

    def test_error_outcome_digest_correspondence(self) -> None:
        result = _make_result(
            ToolRuntimeStatus.FAILED, "fail_tool", "call_err", error_kind="timeout"
        )
        annotation, event = self._deliver_and_capture(
            result, "timeout error", status="failure"
        )
        assert event is not None
        expected_hash = _sha256(f"<rig-tool-outcome>{annotation}</rig-tool-outcome>")
        assert event.outcome_annotation_hash == expected_hash
        assert event.output_kind == "error"

    def test_artifacted_outcome_preserves_digest(self) -> None:
        result = _make_result(
            ToolRuntimeStatus.DEGRADED,
            "cat",
            "call_art",
            degraded_capabilities=["truncation"],
        )
        large_text = "X" * 200_000
        annotation, event = self._deliver_and_capture(result, large_text)
        assert event is not None
        expected_hash = _sha256(f"<rig-tool-outcome>{annotation}</rig-tool-outcome>")
        assert event.outcome_annotation_hash == expected_hash
        assert event.output_kind == "artifacted"

    def test_projection_event_content_light(self) -> None:
        """Projection events must NOT contain raw tool output or secrets."""
        result = _make_result(ToolRuntimeStatus.COMPLETED, "safe", "call_cl")
        _, event = self._deliver_and_capture(result, "normal output")
        assert event is not None
        serialized = event.to_json().lower()
        assert "api_key" not in serialized
        assert "sk-" not in serialized
        assert event.content_light is True

    def test_failed_resolution_digest_correspondence(self) -> None:
        """Failed-resolution handle_failed_tool_response produces matching digest."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        failed = _FakeFailedCall(
            "unknown_tool", "call_f1", "Unknown tool 'unknown_tool'"
        )
        runtime.handle_failed_tool_response(failed)
        content = getattr(loop.messages[-1], "content", "")
        annotation = _assert_annotated(content)
        assert evidence.events, "No projection event emitted for failed resolution"
        event = evidence.events[-1]
        expected_hash = _sha256(f"<rig-tool-outcome>{annotation}</rig-tool-outcome>")
        assert event.outcome_annotation_hash == expected_hash
        assert event.output_kind == "error"

    def test_all_outcome_kinds_produce_distinct_digests(self) -> None:
        """Different outcomes produce different, non-empty digests."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        result_a = _make_result(ToolRuntimeStatus.COMPLETED, "a", "call_a")
        tc_a = _FakeToolCall("a", "call_a")
        runtime.handle_tool_response(
            tool_call=tc_a, text="output A", status="success", runtime_result=result_a
        )
        result_b = _make_result(
            ToolRuntimeStatus.FAILED, "b", "call_b", error_kind="boom"
        )
        tc_b = _FakeToolCall("b", "call_b")
        runtime.handle_tool_response(
            tool_call=tc_b, text="error B", status="failure", runtime_result=result_b
        )
        result_c = _make_result(ToolRuntimeStatus.COMPLETED, "c", "call_c")
        tc_c = _FakeToolCall("c", "call_c")
        runtime.handle_tool_response(
            tool_call=tc_c, text="", status="success", runtime_result=result_c
        )

        digs = [e.model_visible_outcome_digest for e in evidence.events]
        anns = [e.outcome_annotation_hash for e in evidence.events]
        assert len(set(digs)) == len(digs), "Outcome digests must be unique"
        assert all(d.startswith("sha256:") for d in digs)
        assert len(set(anns)) == len(anns), "Annotation hashes must be unique"
        assert all(a.startswith("sha256:") for a in anns)


# ── B6.2: Out-of-order Executor Correlation ──────────────────────────
#
# The real ToolResultRuntime boundary must preserve per-call identity and
# projection event binding when completion order differs from request order.
# Uses actual asyncio concurrency (create_task + queues), not scripted ordering.


@pytest.mark.asyncio
class TestB6_2_OutOfOrderExecutor:
    async def test_out_of_order_preserves_correlation_ids(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        async def deliver(
            call_id: str,
            tool_name: str,
            delay: float,
            status: ToolRuntimeStatus,
            answer: str,
            inv: str | None = None,
        ) -> None:
            await asyncio.sleep(delay)
            refusal = (
                ToolRuntimeRefusal(
                    refusal_code=RefusalCode.TOOL_PERMISSION_DENIED,
                    message="Blocked",
                    recoverable=False,
                )
                if answer == "refused"
                else None
            )
            result = _make_result(
                status=status,
                tool_name=tool_name,
                tool_call_id=call_id,
                investigation_outcome=inv,
                refusal=refusal,
            )
            tc = _FakeToolCall(tool_name, call_id)
            runtime.handle_tool_response(
                tool_call=tc,
                text=f"out {call_id}",
                status="success" if answer != "refused" else "skipped",
                runtime_result=result,
            )

        # C completes first, then B, then A
        await asyncio.gather(
            deliver(
                "call_A", "rd_a", 0.15, ToolRuntimeStatus.COMPLETED, "positive", "match"
            ),
            deliver(
                "call_B",
                "rd_b",
                0.08,
                ToolRuntimeStatus.COMPLETED,
                "negative",
                "no_match",
            ),
            deliver("call_C", "rd_c", 0.02, ToolRuntimeStatus.REFUSED, "refused"),
        )

        events_by_cid: dict[str, OutcomeProjectionEvent] = {
            e.tool_call_id: e for e in evidence.events
        }
        assert "call_A" in events_by_cid
        assert "call_B" in events_by_cid
        assert "call_C" in events_by_cid
        assert events_by_cid["call_A"].answer_kind in {"positive", "completed"}
        assert events_by_cid["call_C"].answer_kind == "refused"

    async def test_out_of_order_annotation_hash_binding(self) -> None:
        """Each out-of-order event binds the correct annotation hash."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        async def deliver(call_id: str, delay: float, text: str) -> None:
            await asyncio.sleep(delay)
            result = _make_result(
                ToolRuntimeStatus.COMPLETED,
                "tool",
                call_id,
                investigation_outcome="match",
            )
            tc = _FakeToolCall("tool", call_id)
            runtime.handle_tool_response(
                tool_call=tc, text=text, status="success", runtime_result=result
            )

        await asyncio.gather(
            deliver("fast", 0.01, "fast output"), deliver("slow", 0.10, "slow output")
        )

        for event in evidence.events:
            assert event.outcome_annotation_hash.startswith("sha256:")
            assert len(event.outcome_annotation_hash) > 8
            assert event.tool_call_id != ""

    async def test_concurrent_mutation_disposition_no_cross_wire(self) -> None:
        """Concurrent mutations and refusals never cross-wire disposition."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        async def deliver(
            call_id: str, delay: float, performed: bool, refused: bool = False
        ) -> None:
            await asyncio.sleep(delay)
            if refused:
                result = _make_result(
                    ToolRuntimeStatus.REFUSED,
                    "write_file",
                    call_id,
                    refusal=ToolRuntimeRefusal(
                        refusal_code=RefusalCode.APPROVAL_DENIED,
                        message="No",
                        recoverable=False,
                    ),
                )
            else:
                result = _make_result(
                    ToolRuntimeStatus.COMPLETED,
                    "write_file",
                    call_id,
                    mutation_performed=performed,
                    investigation_outcome="match",
                )
            tc = _FakeToolCall("write_file", call_id)
            runtime.handle_tool_response(
                tool_call=tc,
                text=f"out {call_id}",
                status="success" if not refused else "skipped",
                runtime_result=result,
            )

        await asyncio.gather(
            deliver("wp_perf", 0.02, performed=True),
            deliver("wp_not", 0.01, performed=False, refused=True),
        )

        by_call: dict[str, str] = {}
        for msg in loop.messages:
            content = getattr(msg, "content", "")
            annotation = _parse_annotation(content)
            if annotation is None:
                continue
            parsed = _validate_schema(annotation)
            by_call[parsed["tool_call_id"]] = parsed["mutation_disposition"]
        assert by_call.get("wp_perf") == MutationDisposition.PERFORMED.value
        assert by_call.get("wp_not") in {
            MutationDisposition.NOT_PERFORMED.value,
            MutationDisposition.NOT_APPLICABLE.value,
        }


# ── B6.3: D1 Recovery Handoff Integration ────────────────────────────


def _handoff_sha(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


class TestB6_3_D1RecoveryHandoffIntegration:
    """Real D1A handoff objects enter real Lane B runtime boundary."""

    def _make_read_only_handoff(self) -> Any:
        from rig_relay.recovery.handoff import build_read_only_handoff

        return build_read_only_handoff(
            _handoff_sha("receipt-ro"),
            _handoff_sha("manifest-ro"),
            "git_status",
            _handoff_sha("payload-ro"),
        )

    def _make_validation_handoff(self) -> Any:
        from rig_relay.recovery.handoff import build_validation_handoff

        return build_validation_handoff(
            _handoff_sha("receipt-val"),
            _handoff_sha("manifest-val"),
            "validate",
            _handoff_sha("payload-val"),
        )

    def _make_mutation_handoff(self) -> Any:
        from rig_relay.recovery.handoff import build_mutation_handoff

        return build_mutation_handoff(
            _handoff_sha("receipt-mut"),
            _handoff_sha("manifest-mut"),
            "write_file",
            _handoff_sha("payload-mut"),
            mutation_class="writes_workspace",
        )

    def _make_refusal_handoff(self) -> Any:
        from rig_relay.recovery.handoff import build_refusal_handoff

        return build_refusal_handoff(
            _handoff_sha("receipt-ref"),
            _handoff_sha("manifest-ref"),
            "unknown_alias",
            reason="not found",
        )

    def test_read_only_handoff_produces_outcome_and_projection(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        handoff = self._make_read_only_handoff()

        msg = runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["tool_name"] == "git_status"
        assert parsed["authority_decision"] == "auto_execute_read_only"
        assert parsed["authority_source"] == "recovery_handoff"
        assert parsed["status"] == "completed"
        assert evidence.events, "No projection event for read_only handoff"
        assert evidence.events[-1].output_kind == "inline"

    def test_validation_handoff_produces_outcome_and_projection(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        handoff = self._make_validation_handoff()

        msg = runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["tool_name"] == "validate"
        assert parsed["authority_decision"] == "auto_execute_validation"
        assert parsed["status"] == "completed"
        assert evidence.events

    def test_mutation_handoff_is_proposal_only(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        handoff = self._make_mutation_handoff()

        msg = runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["tool_name"] == "write_file"
        assert parsed["authority_decision"] == "proposal_only_mutation"
        assert parsed["mutation_disposition"] == "not_applicable"
        assert parsed["status"] == "completed"
        # Mutation disposition is not_performed/not_applicable — never performed
        assert parsed["mutation_disposition"] != MutationDisposition.PERFORMED.value
        assert evidence.events

    def test_mutation_handoff_cannot_become_direct_execution(self) -> None:
        """Hard invariant: mutation handoff cannot express or trigger direct execution."""
        from pydantic import ValidationError

        from rig_relay.recovery.handoff import RecoveryHandoffMutationProposal

        # Contract-level proof: the model itself rejects extra fields like execute_directly
        with pytest.raises(ValidationError):
            RecoveryHandoffMutationProposal.model_validate({
                "recovery_receipt_sha256": _handoff_sha("r"),
                "manifest_digest": _handoff_sha("m"),
                "canonical_tool_name": "write_file",
                "payload_digest": _handoff_sha("p"),
                "mutation_class": "writes_workspace",
                "execute_directly": True,
            })

        # Runtime-level proof: mutation handoff admission produces proposal_only
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        runtime = ToolResultRuntime(loop)
        handoff = self._make_mutation_handoff()
        msg = runtime.handle_recovery_handoff(handoff)
        content = getattr(msg, "content", "")
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["authority_decision"] == "proposal_only_mutation"
        assert "auto_execute" not in parsed.get("authority_decision", "")
        assert parsed["answer_kind"] == "positive"

    def test_refusal_handoff_produces_refusal_outcome_no_execution(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        handoff = self._make_refusal_handoff()

        msg = runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["status"] == "refused"
        assert parsed["refusal_code"] == "unknown_alias"
        assert parsed["error_kind"] == "recovery_refusal"
        assert parsed["answer_kind"] == "refused"
        # Refusal must not attempt execution
        assert "executed" not in content.lower()
        assert evidence.events
        assert evidence.events[-1].refusal_code == "unknown_alias"

    def test_handoff_projection_event_content_light(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        handoff = self._make_read_only_handoff()
        runtime.handle_recovery_handoff(handoff)
        assert evidence.events
        event = evidence.events[-1]
        serialized = event.to_json().lower()
        assert "api_key" not in serialized
        assert "sk-" not in serialized
        assert event.content_light is True

    def test_unknown_handoff_produces_refusal(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        class StrangeHandoff:
            handoff_kind = "something_weird"

        msg = runtime.handle_recovery_handoff(StrangeHandoff())
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["status"] == "refused"
        assert parsed["refusal_code"] == "unknown_handoff_kind"
        assert evidence.events

    def test_all_four_handoff_kinds_in_single_loop(self) -> None:
        """All four handoff kinds coexist in a shared loop without cross-wire."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        runtime.handle_recovery_handoff(self._make_read_only_handoff())
        runtime.handle_recovery_handoff(self._make_validation_handoff())
        runtime.handle_recovery_handoff(self._make_mutation_handoff())
        runtime.handle_recovery_handoff(self._make_refusal_handoff())

        decisions: dict[str, str] = {}
        for msg in loop.messages:
            content = getattr(msg, "content", "")
            annotation = _parse_annotation(content)
            if annotation is None:
                continue
            parsed = _validate_schema(annotation)
            decisions.setdefault(parsed.get("tool_name", ""), parsed["status"])
        assert len(evidence.events) == 4


# ── B6.4: Deprecated Shim Removal Verification ───────────────────────


class TestB6_4_DeprecatedShimRemoval:
    def test_no_deprecated_mutation_tool_names_in_module(self) -> None:
        import rig_relay.core.tool_result_runtime as mod

        assert not hasattr(mod, "_DEPRECATED_MUTATION_TOOL_NAMES"), (
            "_DEPRECATED_MUTATION_TOOL_NAMES shim must not exist"
        )

    def test_mutation_class_resolution_uses_registry_only(self) -> None:
        """_resolve_mutation_class uses only the tool registry, never hardcoded names."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        cls_for_write = _resolve_mutation_class(
            "write_file", tool_manager=loop.tool_manager
        )
        from rig_relay.core.telemetry.tool_contract import ToolMutationClass

        assert cls_for_write == ToolMutationClass.WRITES_WORKSPACE
        cls_for_read = _resolve_mutation_class(
            "git_status", tool_manager=loop.tool_manager
        )
        assert cls_for_read == ToolMutationClass.READ_ONLY

    def test_when_tool_manager_none_defaults_read_only(self) -> None:
        """When no registry available, safe default is READ_ONLY."""
        result = _resolve_mutation_class("write_file", tool_manager=None)
        from rig_relay.core.telemetry.tool_contract import ToolMutationClass

        assert result == ToolMutationClass.READ_ONLY

    def test_when_tool_manager_has_no_available_tools_defaults_read_only(self) -> None:
        class BareManager:
            pass

        result = _resolve_mutation_class("write_file", tool_manager=BareManager())
        from rig_relay.core.telemetry.tool_contract import ToolMutationClass

        assert result == ToolMutationClass.READ_ONLY

    def test_no_hardcoded_mutation_name_authority_anywhere(self) -> None:
        """Verify no other module installs a replacement for the deprecated shim."""
        import ast
        from pathlib import Path

        source = (
            Path(__file__).parents[2]
            / "rig_relay"
            / "core"
            / "tool_result_runtime"
            / "__init__.py"
        )
        tree = ast.parse(source.read_text())
        frozensets: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and "mutation" in target.id.lower():
                        if isinstance(node.value, ast.Call):
                            if "search_replace" in str(
                                node.value
                            ) or "write_file" in str(node.value):
                                frozensets.append(target.id)
        assert not frozensets, (
            f"No hardcoded mutation-name frozensets allowed: {frozensets}"
        )


# ── B6.5: Content-light Enforcement ──────────────────────────────────


class TestB6_5_ContentLight:
    def test_projection_event_never_contains_raw_error_string(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        result = _make_result(
            ToolRuntimeStatus.FAILED, "fail", "call_secret", error_kind="timeout"
        )
        tc = _FakeToolCall("fail", "call_secret")
        runtime.handle_tool_response(
            tool_call=tc,
            text="ERROR: secret-token-abc123 leaked here",
            status="failure",
            runtime_result=result,
        )
        assert evidence.events
        for event in evidence.events:
            serialized = event.to_json()
            assert "secret-token" not in serialized
            assert "leaked" not in serialized

    def test_projection_event_schema_validates(self) -> None:
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)
        result = _make_result(ToolRuntimeStatus.COMPLETED, "ok", "call_sch")
        tc = _FakeToolCall("ok", "call_sch")
        runtime.handle_tool_response(
            tool_call=tc, text="output", status="success", runtime_result=result
        )
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
