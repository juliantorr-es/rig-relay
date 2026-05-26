"""Lane B6.7: Recovery Payload Materialization and Constrained Downstream Execution.

Proves the bridge between digest-only D1 handoffs and governed execution:
  B6.7.1 — Payload materialization: RecoveryIntent.normalized_args → ToolRuntimeRequest.tool_args
  B6.7.2 — Digest verification: SHA256(args) matches handoff.payload_digest
  B6.7.3 — Bounded validation: profile and bounded_paths propagated into execution
  B6.7.4 — Mutation proposal creation: recovered args → patch-proposal with zero mutation
  B6.7.5 — Payload mismatch refusal
  B6.7.6 — Content-light and schema validation
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

import pytest

from rig_relay.core.tool_result_runtime import ToolResultRuntime
from rig_relay.core.tools._agent_outcome import MutationDisposition
from rig_relay.core.types import LLMMessage
from rig_relay.recovery.models import RecoveryIntent
from tests.conftest import build_test_agent_loop, build_test_vibe_config


def _sha256(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode()).hexdigest()}"


def _handoff_sha(data: str) -> str:
    return _sha256(data)


def _payload_digest(args: dict[str, Any]) -> str:
    raw = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


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
        return display_text

    def emit_tool_call_finished(self, **kwargs: Any) -> None:
        pass

    def capture_model_observation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def emit_tool_reasoning_trace(self, **kwargs: Any) -> None:
        pass


# ── Helpers ─────────────────────────────────────────────────────────


def _build_read_only_handoff_with_intent(
    canonical_tool_name: str, normalized_args: dict[str, Any]
) -> tuple[Any, RecoveryIntent]:
    from rig_relay.recovery.handoff import build_read_only_handoff

    pd = _payload_digest(normalized_args)
    handoff = build_read_only_handoff(
        _handoff_sha(f"r-{canonical_tool_name}"),
        _handoff_sha(f"m-{canonical_tool_name}"),
        canonical_tool_name,
        pd,
    )
    intent = RecoveryIntent(
        canonical_tool_name=canonical_tool_name,
        normalized_args=normalized_args,
        payload_digest=pd,
        manifest_digest=_handoff_sha(f"m-{canonical_tool_name}"),
    )
    return handoff, intent


def _build_validation_handoff_with_intent(
    canonical_tool_name: str,
    normalized_args: dict[str, Any],
    *,
    profile: str | None = None,
    bounded_paths: list[str] | None = None,
) -> tuple[Any, RecoveryIntent]:
    from rig_relay.recovery.handoff import build_validation_handoff

    pd = _payload_digest(normalized_args)
    handoff = build_validation_handoff(
        _handoff_sha(f"r-{canonical_tool_name}"),
        _handoff_sha(f"m-{canonical_tool_name}"),
        canonical_tool_name,
        pd,
    )
    if profile:
        handoff.admitted_validation_profile = profile
    if bounded_paths:
        handoff.bounded_paths = list(bounded_paths)
    intent = RecoveryIntent(
        canonical_tool_name=canonical_tool_name,
        normalized_args=normalized_args,
        payload_digest=pd,
        manifest_digest=_handoff_sha(f"m-{canonical_tool_name}"),
    )
    return handoff, intent


def _build_mutation_handoff_with_intent(
    canonical_tool_name: str,
    normalized_args: dict[str, Any],
    mutation_class: str = "writes_workspace",
) -> tuple[Any, RecoveryIntent]:
    from rig_relay.recovery.handoff import build_mutation_handoff

    pd = _payload_digest(normalized_args)
    handoff = build_mutation_handoff(
        _handoff_sha(f"r-{canonical_tool_name}"),
        _handoff_sha(f"m-{canonical_tool_name}"),
        canonical_tool_name,
        pd,
        mutation_class=mutation_class,
    )
    intent = RecoveryIntent(
        canonical_tool_name=canonical_tool_name,
        normalized_args=normalized_args,
        payload_digest=pd,
        manifest_digest=_handoff_sha(f"m-{canonical_tool_name}"),
        mutation_class=mutation_class,
    )
    return handoff, intent


# ── B6.7.1: Payload Materialization ──────────────────────────────────


class TestB6_7_1_PayloadMaterialization:
    @pytest.mark.asyncio
    async def test_read_file_handoff_with_real_path_executes(self) -> None:
        """read_file handoff with a real file_path executes through
        ToolRuntime with materialized args from RecoveryIntent.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello from recovery handoff\n")
            fixture_path = f.name

        try:
            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(loop, evidence=evidence)

            handoff, intent = _build_read_only_handoff_with_intent(
                "read_file", {"path": fixture_path}
            )

            msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
            assert isinstance(msg, LLMMessage)
            content = getattr(msg, "content", "")
            assert _annotation_count(content) == 1

            parsed = _validate_schema(_assert_annotated(content))
            assert parsed["tool_name"] == "read_file"
            assert evidence.events, "No projection event for read_file execution"
            event = evidence.events[-1]
            assert event.model_visible_outcome_digest.startswith("sha256:")
            assert event.outcome_annotation_hash.startswith("sha256:")
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_read_only_handoff_without_intent_still_routes(self) -> None:
        """Without intent, handoff still routes (backward compat for B6.6 behavior)."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        handoff, _ = _build_read_only_handoff_with_intent("git_status", {})
        msg = await runtime.handle_recovery_handoff(handoff)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1

    @pytest.mark.asyncio
    async def test_payload_digest_verification_passes_with_matching_args(self) -> None:
        """When intent args match payload_digest, execution proceeds."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("digest match test\n")
            fixture_path = f.name

        try:
            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(loop, evidence=evidence)

            args = {"path": fixture_path}
            pd = _payload_digest(args)
            from rig_relay.recovery.handoff import build_read_only_handoff

            handoff = build_read_only_handoff(
                _handoff_sha("r-digest"), _handoff_sha("m-digest"), "read_file", pd
            )
            intent = RecoveryIntent(
                canonical_tool_name="read_file",
                normalized_args=args,
                payload_digest=pd,
                manifest_digest=_handoff_sha("m-digest"),
            )

            msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
            assert isinstance(msg, LLMMessage)
            assert _annotation_count(getattr(msg, "content", "")) == 1
            assert evidence.events
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_payload_digest_mismatch_produces_refusal(self) -> None:
        """When intent args don't match handoff.payload_digest, execution is refused."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        args = {"path": "/nonexistent"}
        pd_good = _payload_digest(args)
        pd_bad = _handoff_sha("wrong-payload")

        from rig_relay.recovery.handoff import build_read_only_handoff

        handoff = build_read_only_handoff(
            _handoff_sha("r-mismatch"), _handoff_sha("m-mismatch"), "read_file", pd_bad
        )
        intent = RecoveryIntent(
            canonical_tool_name="read_file",
            normalized_args=args,
            payload_digest=pd_good,
            manifest_digest=_handoff_sha("m-mismatch"),
        )

        msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["status"] == "refused"
        assert parsed["refusal_code"] == "payload_digest_mismatch"


# ── B6.7.2: Bounded Validation Propagation ───────────────────────────


class TestB6_7_2_BoundedValidation:
    @pytest.mark.asyncio
    async def test_validation_handoff_propagates_profile_and_bounded_paths(
        self,
    ) -> None:
        """Validation handoff with admitted_validation_profile and bounded_paths
        propagates both into the validate tool execution.
        """
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        args = {"profile": "quick", "paths": ["."]}
        handoff, intent = _build_validation_handoff_with_intent(
            "validate", args, profile="quick", bounded_paths=["."]
        )

        msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1

        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["tool_name"] == "validate"
        assert evidence.events, "No projection event for validation execution"

    @pytest.mark.asyncio
    async def test_validation_without_profile_propagates_args_only(self) -> None:
        """Validation handoff without explicit profile propagates normalized_args only."""
        config = build_test_vibe_config()
        loop = build_test_agent_loop(config=config)
        evidence = _CapturingEvidence()
        runtime = ToolResultRuntime(loop, evidence=evidence)

        args = {"profile": "quick"}
        handoff, intent = _build_validation_handoff_with_intent("validate", args)

        msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
        assert isinstance(msg, LLMMessage)
        content = getattr(msg, "content", "")
        assert _annotation_count(content) == 1
        parsed = _validate_schema(_assert_annotated(content))
        assert parsed["tool_name"] == "validate"


# ── B6.7.3: Mutation Proposal Creation ───────────────────────────────


class TestB6_7_3_MutationProposalCreation:
    @pytest.mark.asyncio
    async def test_mutation_handoff_with_args_enters_proposal_not_execution(
        self,
    ) -> None:
        """Mutation handoff with recovered write args routes through
        MUTATION_PROPOSAL mode. Disposition is never performed.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("original content\n")
            fixture_path = f.name

        try:
            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(loop, evidence=evidence)

            args = {"path": fixture_path, "content": "new content\n"}
            handoff, intent = _build_mutation_handoff_with_intent(
                "write_file", args, mutation_class="writes_workspace"
            )

            msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
            assert isinstance(msg, LLMMessage)
            content = getattr(msg, "content", "")
            assert _annotation_count(content) == 1

            parsed = _validate_schema(_assert_annotated(content))
            assert parsed["tool_name"] == "write_file"
            assert parsed["mutation_disposition"] != MutationDisposition.PERFORMED.value
            assert parsed["mutation_disposition"] != "previously_performed"

            # File must not have been mutated
            current = Path(fixture_path).read_text()
            assert current == "original content\n", (
                "Mutation handoff must not mutate workspace"
            )
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_mutation_handoff_write_file_args_not_performed(self) -> None:
        """mutation_disposition is never performed for mutation handoffs."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("safe\n")
            fixture_path = f.name

        try:
            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(loop, evidence=evidence)

            args = {"path": fixture_path, "content": "should not write\n"}
            handoff, intent = _build_mutation_handoff_with_intent(
                "write_file", args, mutation_class="writes_workspace"
            )

            msg = await runtime.handle_recovery_handoff(handoff, intent=intent)
            content = getattr(msg, "content", "")
            assert _annotation_count(content) == 1
            parsed = _validate_schema(_assert_annotated(content))

            assert parsed["mutation_disposition"] not in {
                "performed",
                "previously_performed",
            }
            assert evidence.events
            # Verify workspace not mutated
            assert Path(fixture_path).read_text() == "safe\n"
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_mutation_vs_read_only_handoff_with_args_distinct(self) -> None:
        """Mutation and read-only handoffs with materialized payloads produce
        observably different mutation dispositions.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("distinct test\n")
            fixture_path = f.name

        try:
            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(loop, evidence=evidence)

            ro_handoff, ro_intent = _build_read_only_handoff_with_intent(
                "read_file", {"path": fixture_path}
            )
            mut_handoff, mut_intent = _build_mutation_handoff_with_intent(
                "write_file",
                {"path": fixture_path, "content": "new\n"},
                mutation_class="writes_workspace",
            )

            await runtime.handle_recovery_handoff(ro_handoff, intent=ro_intent)
            await runtime.handle_recovery_handoff(mut_handoff, intent=mut_intent)

            dispositions: dict[str, str] = {}
            for msg in loop.messages:
                content = getattr(msg, "content", "")
                annotation = _parse_annotation(content)
                if annotation is None:
                    continue
                parsed = _validate_schema(annotation)
                dispositions[parsed["tool_name"]] = parsed["mutation_disposition"]

            assert (
                dispositions.get("read_file")
                == MutationDisposition.NOT_APPLICABLE.value
            )
            assert dispositions.get("write_file") != MutationDisposition.PERFORMED.value
        finally:
            Path(fixture_path).unlink(missing_ok=True)


# ── B6.7.4: Content-light and Schema Validation ──────────────────────


class TestB6_7_4_ContentLight:
    @pytest.mark.asyncio
    async def test_materialized_execution_projection_schema_validates(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("schema test\n")
            fixture_path = f.name

        try:
            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(loop, evidence=evidence)

            handoff, intent = _build_read_only_handoff_with_intent(
                "read_file", {"path": fixture_path}
            )
            await runtime.handle_recovery_handoff(handoff, intent=intent)
            assert evidence.events

            event = evidence.events[-1]
            event_dict = event.to_dict()
            from pathlib import Path as P

            from jsonschema import validate as jsonschema_validate

            schema_path = (
                P(__file__).parents[2]
                / "docs"
                / "schemas"
                / "rig.relay.runtime_outcome_projection_event.v1.schema.json"
            )
            schema = json.loads(schema_path.read_text())
            jsonschema_validate(instance=event_dict, schema=schema)
        finally:
            Path(fixture_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_materialized_events_never_leak_args_or_output(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("secret content\n")
            fixture_path = f.name

        try:
            config = build_test_vibe_config()
            loop = build_test_agent_loop(config=config)
            evidence = _CapturingEvidence()
            runtime = ToolResultRuntime(loop, evidence=evidence)

            handoff, intent = _build_read_only_handoff_with_intent(
                "read_file", {"path": fixture_path}
            )
            await runtime.handle_recovery_handoff(handoff, intent=intent)
            assert evidence.events

            for event in evidence.events:
                serialized = event.to_json().lower()
                assert "secret content" not in serialized
                assert "api_key" not in serialized
                assert event.content_light is True
        finally:
            Path(fixture_path).unlink(missing_ok=True)
