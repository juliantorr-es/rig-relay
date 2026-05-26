"""Production boundary tests for the provider evidence ledger and operations report.

Exercises real fsync+fcntl locked append-only file ledger persistence,
deterministic report generation from canonical evidence, and JSON Schema
validation of persisted events. No mocks — every test uses real persistence,
real digest computation, real integrity checks, and real schema validation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from unittest import mock

import pytest

from rig_relay.providers.evidence_ledger import (
    LEDGER_DIR,
    LEDGER_FILE,
    SchemaValidationUnavailableError,
    load_provider_events,
    persist_provider_event,
)
from rig_relay.providers.invocation import (
    InvocationOutcomeClass,
    InvocationOutcomeInput,
    InvocationRefusalClass,
    assert_content_light,
    build_invocation_outcome,
)
from rig_relay.providers.models import ProviderClass
from rig_relay.providers.operations import (
    _report_to_ordered_dict,
    generate_operations_report,
)


def _ledger_path() -> Path:
    return LEDGER_DIR / LEDGER_FILE


class TestEvidenceLedgerPersistence:
    """Exercises the real fsync+fcntl locked append-only file ledger."""

    def setup_method(self) -> None:
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        ledger = _ledger_path()
        if ledger.exists():
            ledger.unlink()

    def test_persist_and_load_event(self) -> None:
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
                input_tokens=100,
                output_tokens=50,
                usage_verified=True,
            )
        )
        event_digest = persist_provider_event(outcome, session_id="s-1", turn_id="t-1")
        events = load_provider_events()
        assert len(events) == 1
        event = events[0]
        assert event["event_digest"] == event_digest
        assert event["content_light"] is True
        assert event["schema_version"] == (
            "rig.relay.provider_invocation_evidence_event.v1"
        )
        assert event["session_id"] == "s-1"
        assert event["turn_id"] == "t-1"
        assert event["outcome"]["requested_provider_id"] == "openai"
        assert event["outcome"]["outcome_class"] == "success"

    def test_persist_multiple_events(self) -> None:
        provider_ids = ("openai", "anthropic", "deepseek")
        streaming_flags = (False, True, False)
        for pid, sf in zip(provider_ids, streaming_flags, strict=True):
            outcome = build_invocation_outcome(
                InvocationOutcomeInput(
                    requested_provider_id=pid,
                    requested_model_id="test-model",
                    provider_class=ProviderClass.DIRECT_INFERENCE,
                    api_style="openai",
                    outcome_class=InvocationOutcomeClass.SUCCESS,
                    streaming=sf,
                )
            )
            persist_provider_event(outcome, session_id="s-2")
        events = load_provider_events()
        assert len(events) == 3
        event_ids = {e["event_id"] for e in events}
        assert len(event_ids) == 3, "all events must have unique event_ids"

    def test_content_light_violation_raises(self) -> None:
        violations = assert_content_light({
            "api_key": "sk-secret-value-should-be-forbidden"
        })
        assert len(violations) > 0
        found_sk = any("sk-" in v for v in violations)
        found_api = any("api_key" in v for v in violations)
        assert found_sk or found_api, "must detect forbidden tokens"

        bare_bearer = assert_content_light({"authorization": "Bearer some-token"})
        assert len(bare_bearer) > 0

    def test_ledger_integrity_digests(self) -> None:
        for i in range(2):
            outcome = build_invocation_outcome(
                InvocationOutcomeInput(
                    requested_provider_id="openai",
                    requested_model_id=f"model-{i}",
                    provider_class=ProviderClass.DIRECT_INFERENCE,
                    api_style="openai",
                    outcome_class=InvocationOutcomeClass.SUCCESS,
                )
            )
            persist_provider_event(outcome, session_id="s-3")
        events = load_provider_events()
        assert len(events) == 2
        for event in events:
            digest = event["event_digest"]
            assert isinstance(digest, str) and len(digest) > 0
            assert digest.startswith("sha256:")

    def test_concurrent_append_isolation(self) -> None:
        for i in range(5):
            outcome = build_invocation_outcome(
                InvocationOutcomeInput(
                    requested_provider_id="openai",
                    requested_model_id=f"gpt-4o-{i}",
                    provider_class=ProviderClass.DIRECT_INFERENCE,
                    api_style="openai",
                    outcome_class=InvocationOutcomeClass.SUCCESS,
                )
            )
            persist_provider_event(outcome, session_id="s-concurrent")
        events = load_provider_events()
        assert len(events) == 5
        event_ids = {e["event_id"] for e in events}
        assert len(event_ids) == 5
        digests = {e["event_digest"] for e in events}
        assert len(digests) == 5, "all events must have distinct digests"

    def teardown_method(self) -> None:
        ledger = _ledger_path()
        if ledger.exists():
            ledger.unlink(missing_ok=True)


class TestProviderOperationsReport:
    """Exercises deterministic report generation from real ledger events."""

    def teardown_method(self) -> None:
        ledger = _ledger_path()
        if ledger.exists():
            ledger.unlink(missing_ok=True)

    def test_empty_ledger_report(self) -> None:
        report = generate_operations_report(events=[])
        assert report.event_count == 0
        assert report.integrity_verified is True
        assert report.streaming_count == 0
        assert report.non_streaming_count == 0
        assert report.cached_tokens_events == 0
        assert report.refusal_events == 0
        assert report.error_events == 0
        assert report.content_light_violations == 0

    def test_report_with_persisted_events(self) -> None:
        _persist_event(
            provider_id="openai",
            streaming=False,
            outcome_class=InvocationOutcomeClass.SUCCESS,
            input_tokens=200,
            output_tokens=100,
            usage_verified=True,
        )
        _persist_event(
            provider_id="anthropic",
            streaming=True,
            outcome_class=InvocationOutcomeClass.SUCCESS,
            input_tokens=150,
            output_tokens=80,
            cache_read_tokens=120,
            cache_read_verified=True,
            usage_verified=True,
        )
        _persist_event(
            provider_id="gemini",
            streaming=False,
            outcome_class=InvocationOutcomeClass.SAFETY_BLOCK,
            refusal_class=InvocationRefusalClass.PROVIDER_SAFETY,
            safety_refusal_verified=True,
        )

        events = load_provider_events()
        report = generate_operations_report(events=events)

        assert report.event_count == 3
        assert set(report.provider_identities) == {"anthropic", "gemini", "openai"}
        assert report.streaming_count == 1
        assert report.non_streaming_count == 2
        assert report.cached_tokens_events >= 1
        assert report.cached_tokens_verified >= 1
        assert report.refusal_events >= 1
        assert "success" in report.outcome_class_counts
        assert "safety_block" in report.outcome_class_counts
        assert report.integrity_verified is True
        assert report.report_digest.startswith("sha256:")

    def test_report_with_cached_and_reasoning_tokens(self) -> None:
        _persist_event(
            provider_id="anthropic",
            streaming=False,
            outcome_class=InvocationOutcomeClass.SUCCESS,
            cache_read_tokens=100,
            cache_read_verified=True,
            reasoning_tokens=50,
            reasoning_tokens_verified=True,
            usage_verified=True,
        )
        events = load_provider_events()
        report = generate_operations_report(events=events)
        assert report.cached_tokens_events == 1
        assert report.cached_tokens_verified == 1
        assert report.reasoning_tokens_events == 1
        assert report.reasoning_tokens_verified == 1

    def test_report_discrepancy_detection(self) -> None:
        _persist_event(
            provider_id="openai",
            streaming=False,
            outcome_class=InvocationOutcomeClass.SUCCESS,
            usage_discrepancy_detected=True,
        )
        _persist_event(
            provider_id="openai",
            streaming=False,
            outcome_class=InvocationOutcomeClass.SUCCESS,
            usage_discrepancy_detected=False,
        )
        events = load_provider_events()
        report = generate_operations_report(events=events)
        assert report.discrepancy_detected_count == 1
        assert report.discrepancy_free_count == 1

    def test_report_content_light_guarantee(self) -> None:
        report = generate_operations_report(events=[])
        data = _report_to_ordered_dict(report)
        serialized = json.dumps(data)
        for forbidden in ("sk-", "Bearer", "api_key", "ghp_"):
            assert forbidden not in serialized, (
                f"forbidden token {forbidden!r} found in report"
            )

    def test_report_deterministic(self) -> None:
        _persist_event(
            provider_id="openai",
            streaming=False,
            outcome_class=InvocationOutcomeClass.SUCCESS,
        )
        _persist_event(
            provider_id="anthropic",
            streaming=True,
            outcome_class=InvocationOutcomeClass.SUCCESS,
        )
        events = load_provider_events()
        report1 = generate_operations_report(events=list(events))
        report2 = generate_operations_report(events=list(events))
        assert report1.report_digest == report2.report_digest


class TestLedgerSchemaValidation:
    """Proves schema validation at the append boundary is fail-closed.

    No event enters the canonical ledger without passing the schema gate.
    All four failure modes are exercised through persist_provider_event().
    """

    def setup_method(self) -> None:
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        ledger = _ledger_path()
        if ledger.exists():
            ledger.unlink()

    def teardown_method(self) -> None:
        ledger = _ledger_path()
        if ledger.exists():
            ledger.unlink(missing_ok=True)

    def test_valid_event_passes_schema_validation_and_persists(self) -> None:
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
                input_tokens=100,
                output_tokens=50,
                usage_verified=True,
            )
        )
        digest = persist_provider_event(outcome, session_id="s-valid")
        events = load_provider_events()
        assert len(events) == 1
        assert events[0]["event_digest"] == digest
        assert events[0]["content_light"] is True

    def test_schema_invalid_event_refused_before_persistence(self) -> None:
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        persist_provider_event(outcome, session_id="s-invalid-1")
        assert len(load_provider_events()) == 1

        outcome2 = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        with mock.patch(
            "rig_relay.providers.evidence_ledger._validate_event_against_schema",
            side_effect=ValueError("Schema validation failed — event rejected"),
        ):
            with pytest.raises(ValueError):
                persist_provider_event(outcome2, session_id="s-invalid-2")

        assert len(load_provider_events()) == 1, (
            "ledger must remain unchanged after schema-invalid event refusal"
        )

    def test_missing_schema_file_hard_refusal(self) -> None:
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        persist_provider_event(outcome, session_id="s-file-1")
        assert len(load_provider_events()) == 1

        outcome2 = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        with (
            mock.patch("rig_relay.providers.evidence_ledger._schema_cache", None),
            mock.patch(
                "rig_relay.providers.evidence_ledger._resolve_schema_path",
                return_value=Path("/nonexistent/schema.json"),
            ),
        ):
            with pytest.raises(SchemaValidationUnavailableError):
                persist_provider_event(outcome2, session_id="s-file-2")

        assert len(load_provider_events()) == 1, (
            "ledger must remain unchanged after missing-schema-file refusal"
        )

    def test_missing_jsonschema_library_hard_refusal(self) -> None:
        outcome = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )
        persist_provider_event(outcome, session_id="s-lib-1")
        assert len(load_provider_events()) == 1

        outcome2 = build_invocation_outcome(
            InvocationOutcomeInput(
                requested_provider_id="openai",
                requested_model_id="gpt-4o",
                provider_class=ProviderClass.DIRECT_INFERENCE,
                api_style="openai",
                outcome_class=InvocationOutcomeClass.SUCCESS,
            )
        )

        saved_jsonschema = sys.modules.pop("jsonschema", None)
        try:
            with mock.patch(
                "rig_relay.providers.evidence_ledger._validate_event_against_schema",
                side_effect=SchemaValidationUnavailableError(
                    "Cannot validate provider evidence events: "
                    "jsonschema is not installed"
                ),
            ):
                with pytest.raises(SchemaValidationUnavailableError):
                    persist_provider_event(outcome2, session_id="s-lib-2")
        finally:
            if saved_jsonschema is not None:
                sys.modules["jsonschema"] = saved_jsonschema

        assert len(load_provider_events()) == 1, (
            "ledger must remain unchanged after missing-jsonschema refusal"
        )


def _persist_event(
    *,
    provider_id: str,
    streaming: bool = False,
    outcome_class: InvocationOutcomeClass = InvocationOutcomeClass.SUCCESS,
    refusal_class: InvocationRefusalClass | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_read_verified: bool | None = None,
    usage_verified: bool | None = None,
    safety_refusal_verified: bool | None = None,
    reasoning_tokens: int | None = None,
    reasoning_tokens_verified: bool | None = None,
    usage_discrepancy_detected: bool | None = None,
) -> str:
    """Persist a single event through the real evidence ledger and return its digest."""
    outcome = build_invocation_outcome(
        InvocationOutcomeInput(
            requested_provider_id=provider_id,
            requested_model_id=f"{provider_id}-test-model",
            provider_class=ProviderClass.DIRECT_INFERENCE,
            api_style=(
                "anthropic"
                if provider_id == "anthropic"
                else "gemini"
                if provider_id == "gemini"
                else "openai"
            ),
            outcome_class=outcome_class,
            refusal_class=refusal_class,
            streaming=streaming,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_read_verified=cache_read_verified,
            usage_verified=usage_verified,
            safety_refusal_verified=safety_refusal_verified,
            reasoning_tokens=reasoning_tokens,
            reasoning_tokens_verified=reasoning_tokens_verified,
            usage_discrepancy_detected=usage_discrepancy_detected,
        )
    )
    return persist_provider_event(outcome, session_id="s-ops")


class TestProviderBackendEmissionToReport:
    """Proves the non-streaming and terminal-streaming backend corridors
    emit canonical ledger events consumed by the operations report.

    True external HTTP is intercepted via respx. Internal observer logic,
    outcome builder, ledger append gate, and report generator are all
    exercised unmocked.
    """

    @pytest.fixture(autouse=True)
    def _setup_and_teardown(self):
        os.environ["OPENAI_API_KEY"] = "test-key"
        ledger = _ledger_path()
        if ledger.exists():
            ledger.unlink()
        yield
        if ledger.exists():
            ledger.unlink(missing_ok=True)
        os.environ.pop("OPENAI_API_KEY", None)

    @pytest.mark.asyncio
    async def test_non_streaming_backend_emission_to_report(self) -> None:
        import httpx
        import respx

        from rig_relay.core.config import (
            ModelConfig,
            ProviderConfig as CoreProviderConfig,
        )
        from rig_relay.core.llm.backend.generic import GenericBackend
        from rig_relay.core.types import LLMMessage, Role

        provider = CoreProviderConfig(
            name="openai",
            api_style="openai",
            api_base="https://api.openai.com/v1",
            api_key_env_var="OPENAI_API_KEY",
        )
        model = ModelConfig(name="gpt-4o", provider="openai", alias="gpt-4o")

        response_json = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }

        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=response_json)
            )
            backend = GenericBackend(provider=provider)
            try:
                chunk = await backend.complete(
                    model=model, messages=[LLMMessage(role=Role.user, content="Hello")]
                )
            finally:
                await backend.close()

        assert chunk.invocation_outcome is not None
        assert chunk.invocation_outcome.input_tokens == 100
        assert chunk.invocation_outcome.output_tokens == 50

        persist_provider_event(
            chunk.invocation_outcome, session_id="s-backend-nonstreaming"
        )

        events = load_provider_events()
        report = generate_operations_report(events=events)

        assert report.event_count == 1
        assert report.non_streaming_count == 1
        assert report.streaming_count == 0
        assert report.content_light_violations == 0
        assert report.integrity_verified is True
        assert "openai" in report.provider_identities

    @pytest.mark.asyncio
    async def test_terminal_streaming_backend_emission_to_report(self) -> None:
        import httpx
        import respx

        from rig_relay.core.config import (
            ModelConfig,
            ProviderConfig as CoreProviderConfig,
        )
        from rig_relay.core.llm.backend.generic import GenericBackend
        from rig_relay.core.types import LLMMessage, Role

        provider = CoreProviderConfig(
            name="openai",
            api_style="openai",
            api_base="https://api.openai.com/v1",
            api_key_env_var="OPENAI_API_KEY",
        )
        model = ModelConfig(name="gpt-4o", provider="openai", alias="gpt-4o")

        stream_chunks = [
            (
                b'data: {"choices":[{"delta":{"content":"Hello"},"index":0}],'
                b'"model":"gpt-4o"}\n\n'
            ),
            (b'data: {"choices":[{"delta":{"content":" world"},"index":0}]}\n\n'),
            (
                b'data: {"choices":[{"delta":{},"finish_reason":"stop","index":0}],'
                b'"model":"gpt-4o",'
                b'"usage":{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150}}'
                b"\n\n"
            ),
            b"data: [DONE]\n\n",
        ]
        stream_content = b"".join(stream_chunks)

        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, content=stream_content)
            )
            backend = GenericBackend(provider=provider)
            try:
                chunks: list = []
                async for chunk in backend.complete_streaming(
                    model=model, messages=[LLMMessage(role=Role.user, content="Hello")]
                ):
                    chunks.append(chunk)
            finally:
                await backend.close()

        assert len(chunks) >= 1
        terminal = chunks[-1]
        assert terminal.invocation_outcome is not None
        assert terminal.invocation_outcome.streaming is True

        persist_provider_event(
            terminal.invocation_outcome, session_id="s-backend-streaming"
        )

        events = load_provider_events()
        report = generate_operations_report(events=events)

        assert report.event_count == 1
        assert report.streaming_count >= 1
        assert report.content_light_violations == 0
        assert report.integrity_verified is True

    @pytest.mark.asyncio
    async def test_backend_absent_token_details_produce_null_fields(self) -> None:
        import httpx
        import respx

        from rig_relay.core.config import (
            ModelConfig,
            ProviderConfig as CoreProviderConfig,
        )
        from rig_relay.core.llm.backend.generic import GenericBackend
        from rig_relay.core.types import LLMMessage, Role

        provider = CoreProviderConfig(
            name="openai",
            api_style="openai",
            api_base="https://api.openai.com/v1",
            api_key_env_var="OPENAI_API_KEY",
        )
        model = ModelConfig(name="gpt-4o", provider="openai", alias="gpt-4o")

        response_json = {
            "id": "chatcmpl-456",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hi"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        }

        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=response_json)
            )
            backend = GenericBackend(provider=provider)
            try:
                chunk = await backend.complete(
                    model=model, messages=[LLMMessage(role=Role.user, content="Hi")]
                )
            finally:
                await backend.close()

        assert chunk.invocation_outcome is not None
        assert chunk.invocation_outcome.cache_read_tokens is None
        assert chunk.invocation_outcome.reasoning_tokens is None

        persist_provider_event(chunk.invocation_outcome, session_id="s-backend-null")

        events = load_provider_events()
        report = generate_operations_report(events=events)

        assert report.event_count == 1
        assert report.cached_tokens_events == 0
        assert report.reasoning_tokens_events == 0
        assert report.content_light_violations == 0
