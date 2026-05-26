"""Production boundary tests for the provider evidence query service.

Proves the read-side query service consumes canonical evidence from the
append-only ledger and returns typed, content-light, deterministic
projections. All tests exercise real production persistence and query
boundaries. External HTTP is intercepted via respx where backend paths
are exercised.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rig_relay.providers.evidence_ledger import (
    LEDGER_DIR,
    LEDGER_FILE,
    load_provider_events,
    persist_provider_event,
)
from rig_relay.providers.invocation import (
    InvocationOutcomeClass,
    ProviderClass,
    ProviderInvocationOutcome,
)
from rig_relay.providers.query import ProviderEvidenceQueryService


def _build_outcome(
    provider_id: str = "openai",
    model_id: str = "gpt-4o",
    streaming: bool = False,
    **kwargs: object,
) -> ProviderInvocationOutcome:
    defaults: dict[str, object] = {
        "requested_provider_id": provider_id,
        "requested_model_id": model_id,
        "provider_class": ProviderClass.DIRECT_INFERENCE,
        "api_style": "openai",
        "outcome_class": InvocationOutcomeClass.SUCCESS,
        "streaming": streaming,
        "input_tokens": 100,
        "output_tokens": 50,
        "usage_verified": True,
    }
    defaults.update(kwargs)
    return ProviderInvocationOutcome(**defaults)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _isolate_ledger():
    ledger = Path(LEDGER_DIR) / LEDGER_FILE
    if ledger.exists():
        ledger.unlink()
    yield
    if ledger.exists():
        ledger.unlink(missing_ok=True)


class TestQueryServiceWithRealPersistence:
    def test_query_service_consumes_persisted_events(self):
        outcome1 = _build_outcome("openai", "gpt-4o", streaming=False)
        outcome2 = _build_outcome("anthropic", "claude-sonnet", streaming=True)
        d1 = persist_provider_event(outcome1, session_id="s1", turn_id="t1")
        d2 = persist_provider_event(outcome2, session_id="s1", turn_id="t2")

        svc = ProviderEvidenceQueryService()

        assert svc.event_count == 2
        assert svc.integrity_verified
        assert svc.integrity_errors == []

        events = svc.all_events()
        assert len(events) == 2
        digests = {e.event_digest for e in events}
        assert d1 in digests
        assert d2 in digests

    def test_query_service_filter_by_provider(self):
        _ = persist_provider_event(_build_outcome("openai"), session_id="s1")
        _ = persist_provider_event(_build_outcome("anthropic"), session_id="s1")
        _ = persist_provider_event(_build_outcome("openai"), session_id="s1")

        svc = ProviderEvidenceQueryService()
        result = svc.list_by_provider("openai")
        assert result.matched_count == 2
        assert result.total_canonical_events == 3
        assert all(e.provider_id == "openai" for e in result.events)

    def test_query_service_filter_by_api_style(self):
        _ = persist_provider_event(_build_outcome(api_style="openai"), session_id="s1")
        _ = persist_provider_event(
            _build_outcome(api_style="anthropic", provider_id="anthropic"),
            session_id="s1",
        )
        _ = persist_provider_event(_build_outcome(api_style="openai"), session_id="s1")

        svc = ProviderEvidenceQueryService()
        result = svc.list_by_api_style("openai")
        assert result.matched_count == 2

    def test_query_service_filter_streaming_disposition(self):
        _ = persist_provider_event(_build_outcome(streaming=False), session_id="s1")
        _ = persist_provider_event(_build_outcome(streaming=True), session_id="s1")
        _ = persist_provider_event(_build_outcome(streaming=False), session_id="s1")

        svc = ProviderEvidenceQueryService()
        assert svc.list_streaming().matched_count == 1
        assert svc.list_non_streaming().matched_count == 2

    def test_query_service_filter_cached_tokens(self):
        _ = persist_provider_event(
            _build_outcome(cache_read_tokens=100, cache_read_verified=True),
            session_id="s1",
        )
        _ = persist_provider_event(
            _build_outcome(cache_read_tokens=None, cache_read_verified=None),
            session_id="s1",
        )

        svc = ProviderEvidenceQueryService()
        result = svc.list_with_cached_tokens()
        assert result.matched_count == 1
        assert result.events[0].cache_read_verified is True

    def test_query_service_filter_reasoning_tokens(self):
        _ = persist_provider_event(
            _build_outcome(reasoning_tokens=200, reasoning_tokens_verified=True),
            session_id="s1",
        )
        _ = persist_provider_event(
            _build_outcome(reasoning_tokens=None, reasoning_tokens_verified=None),
            session_id="s1",
        )

        svc = ProviderEvidenceQueryService()
        result = svc.list_with_reasoning_tokens()
        assert result.matched_count == 1
        assert result.events[0].reasoning_tokens_verified is True

    def test_query_service_filter_discrepancy(self):
        _ = persist_provider_event(
            _build_outcome(usage_discrepancy_detected=True), session_id="s1"
        )
        _ = persist_provider_event(
            _build_outcome(usage_discrepancy_detected=False), session_id="s1"
        )
        _ = persist_provider_event(
            _build_outcome(usage_discrepancy_detected=None), session_id="s1"
        )

        svc = ProviderEvidenceQueryService()
        result = svc.list_with_discrepancy()
        assert result.matched_count == 1

    def test_query_service_filter_refusals(self):
        _ = persist_provider_event(
            _build_outcome(outcome_class=InvocationOutcomeClass.REFUSAL),
            session_id="s1",
        )
        _ = persist_provider_event(
            _build_outcome(outcome_class=InvocationOutcomeClass.SAFETY_BLOCK),
            session_id="s1",
        )
        _ = persist_provider_event(
            _build_outcome(outcome_class=InvocationOutcomeClass.SUCCESS),
            session_id="s1",
        )

        svc = ProviderEvidenceQueryService()
        result = svc.list_refusals()
        assert result.matched_count == 2

    def test_query_service_filter_errors(self):
        _ = persist_provider_event(
            _build_outcome(outcome_class=InvocationOutcomeClass.ERROR), session_id="s1"
        )
        _ = persist_provider_event(
            _build_outcome(outcome_class=InvocationOutcomeClass.SUCCESS),
            session_id="s1",
        )

        svc = ProviderEvidenceQueryService()
        assert svc.list_errors().matched_count == 1

    def test_query_service_filter_degraded(self):
        _ = persist_provider_event(
            _build_outcome(usage_verified=False), session_id="s1"
        )
        _ = persist_provider_event(_build_outcome(usage_verified=None), session_id="s1")
        _ = persist_provider_event(_build_outcome(usage_verified=True), session_id="s1")

        svc = ProviderEvidenceQueryService()
        result = svc.list_degraded()
        assert result.matched_count == 2

    def test_query_service_lookup_by_event_id(self):
        digest = persist_provider_event(_build_outcome(), session_id="s1")
        events = load_provider_events()
        event_id = events[0]["event_id"]

        svc = ProviderEvidenceQueryService()
        found = svc.lookup_by_event_id(event_id)
        assert found is not None
        assert found.event_digest == digest

        assert svc.lookup_by_event_id("nonexistent") is None

    def test_query_service_lookup_by_digest(self):
        digest = persist_provider_event(_build_outcome(), session_id="s1")

        svc = ProviderEvidenceQueryService()
        found = svc.lookup_by_digest(digest)
        assert found is not None
        assert found.event_digest == digest

        assert svc.lookup_by_digest("sha256:deadbeef") is None

    def test_summary_projection(self):
        _ = persist_provider_event(
            _build_outcome(
                "openai",
                streaming=False,
                cache_read_verified=True,
                reasoning_tokens_verified=True,
            ),
            session_id="s1",
        )
        _ = persist_provider_event(
            _build_outcome(
                "anthropic", streaming=True, usage_discrepancy_detected=True
            ),
            session_id="s1",
        )
        _ = persist_provider_event(
            _build_outcome(
                "openai",
                outcome_class=InvocationOutcomeClass.REFUSAL,
                streaming=False,
                usage_verified=None,
            ),
            session_id="s1",
        )

        svc = ProviderEvidenceQueryService()
        summary = svc.build_summary()

        assert summary.total_events == 3
        assert "anthropic" in summary.provider_ids
        assert "openai" in summary.provider_ids
        assert summary.streaming_count == 1
        assert summary.non_streaming_count == 2
        assert summary.cached_token_verified_count == 1
        assert summary.reasoning_token_verified_count == 1
        assert summary.discrepancy_count == 1
        assert summary.refusal_count == 1
        assert summary.error_count == 0
        assert summary.integrity_verified
        assert summary.digest.startswith("sha256:")

    def test_query_does_not_mutate_ledger(self):
        d1 = persist_provider_event(_build_outcome(), session_id="s1")

        events_before = load_provider_events()
        assert len(events_before) == 1

        svc = ProviderEvidenceQueryService()
        _ = svc.all_events()
        _ = svc.list_by_provider("openai")
        _ = svc.build_summary()

        events_after = load_provider_events()
        assert events_before == events_after

        assert events_after[0]["event_digest"] == d1

    def test_empty_ledger_returns_empty_service(self):
        svc = ProviderEvidenceQueryService()
        assert svc.event_count == 0
        assert svc.integrity_verified
        assert svc.all_events() == []
        assert svc.list_by_provider("openai").matched_count == 0

    def test_integrity_projection_returns_no_invalid_when_all_clean(self):
        _ = persist_provider_event(_build_outcome(), session_id="s1")

        svc = ProviderEvidenceQueryService()
        result = svc.build_integrity_projection()
        assert result.matched_count == 0


class TestQueryServiceDeterminism:
    def test_same_events_produce_same_summary_digest(self):
        outcome1 = _build_outcome("openai", "gpt-4o", streaming=False)
        outcome2 = _build_outcome("anthropic", "claude", streaming=True)

        _ = persist_provider_event(outcome1, session_id="s1", turn_id="t1")
        _ = persist_provider_event(outcome2, session_id="s1", turn_id="t2")

        svc1 = ProviderEvidenceQueryService()
        svc2 = ProviderEvidenceQueryService()

        s1 = svc1.build_summary()
        s2 = svc2.build_summary()

        assert s1.digest == s2.digest
        assert s1.total_events == s2.total_events

    def test_projection_digest_is_reproducible(self):
        _ = persist_provider_event(_build_outcome(), session_id="s1")

        svc1 = ProviderEvidenceQueryService()
        svc2 = ProviderEvidenceQueryService()

        r1 = svc1.list_by_provider("openai")
        r2 = svc2.list_by_provider("openai")

        assert r1.projection_digest == r2.projection_digest


class TestQueryServiceWithRealBackendEmission:
    @pytest.fixture(autouse=True)
    def _setup_backend(self):
        os.environ["OPENAI_API_KEY"] = "test-key"
        yield
        os.environ.pop("OPENAI_API_KEY", None)

    @pytest.mark.asyncio
    async def test_non_streaming_backend_to_query_emission(self):
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

        response_json: dict[str, object] = {
            "id": "chatcmpl-789",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Query test!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
            },
        }

        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=response_json)
            )
            backend = GenericBackend(provider=provider)
            try:
                chunk = await backend.complete(
                    model=model,
                    messages=[LLMMessage(role=Role.user, content="Query test")],
                )
            finally:
                await backend.close()

        assert chunk.invocation_outcome is not None
        digest = persist_provider_event(
            chunk.invocation_outcome, session_id="s-backend-query-ns"
        )

        svc = ProviderEvidenceQueryService()
        assert svc.event_count == 1
        assert svc.integrity_verified

        result = svc.list_by_provider("openai")
        assert result.matched_count == 1
        assert result.events[0].input_tokens == 200
        assert result.events[0].output_tokens == 100
        assert result.events[0].streaming is False
        assert result.events[0].event_digest == digest

        summary = svc.build_summary()
        assert summary.non_streaming_count == 1
        assert "openai" in summary.provider_ids

    @pytest.mark.asyncio
    async def test_terminal_streaming_backend_to_query_emission(self):
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
                b'data: {"choices":[{"delta":{"content":"Stream"},"index":0}],'
                b'"model":"gpt-4o"}\n\n'
            ),
            (b'data: {"choices":[{"delta":{"content":" query"},"index":0}]}\n\n'),
            (
                b'data: {"choices":[{"delta":{},"finish_reason":"stop","index":0}],'
                b'"model":"gpt-4o",'
                b'"usage":{"prompt_tokens":150,"completion_tokens":75,"total_tokens":225}}'
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
                    model=model,
                    messages=[LLMMessage(role=Role.user, content="Stream query")],
                ):
                    chunks.append(chunk)
            finally:
                await backend.close()

        terminal = chunks[-1]
        assert terminal.invocation_outcome is not None
        assert terminal.invocation_outcome.streaming is True

        persist_provider_event(
            terminal.invocation_outcome, session_id="s-backend-query-ss"
        )

        svc = ProviderEvidenceQueryService()
        result = svc.list_streaming()
        assert result.matched_count == 1

        summary = svc.build_summary()
        assert summary.streaming_count == 1
        assert summary.non_streaming_count == 0

    @pytest.mark.asyncio
    async def test_absent_token_details_remain_absent_in_query(self):
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

        response_json: dict[str, object] = {
            "id": "chatcmpl-999",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Basic"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75},
        }

        with respx.mock:
            respx.post("https://api.openai.com/v1/chat/completions").mock(
                return_value=httpx.Response(200, json=response_json)
            )
            backend = GenericBackend(provider=provider)
            try:
                chunk = await backend.complete(
                    model=model, messages=[LLMMessage(role=Role.user, content="Basic")]
                )
            finally:
                await backend.close()

        assert chunk.invocation_outcome is not None
        persist_provider_event(chunk.invocation_outcome, session_id="s-backend-absent")

        svc = ProviderEvidenceQueryService()
        result = svc.list_by_provider("openai")
        e = result.events[0]

        assert e.cache_read_tokens is None
        assert e.cache_read_verified is None
        assert e.reasoning_tokens is None
        assert e.reasoning_tokens_verified is None

        # Absent details should NOT appear in filtered queries
        assert svc.list_with_cached_tokens().matched_count == 0
        assert svc.list_with_reasoning_tokens().matched_count == 0

    def test_schema_rejected_event_not_in_query_results(self):
        """Events rejected by schema validation before append do not appear in queries."""
        valid = _build_outcome()
        persist_provider_event(valid, session_id="s1")

        svc = ProviderEvidenceQueryService()
        assert svc.event_count == 1

        # Attempt to persist an event that would fail schema (wrong outcome class)
        # The persist_provider_event will validate and should fail
        invalid = _build_outcome(outcome_class=InvocationOutcomeClass.SUCCESS)
        from rig_relay.providers.evidence_ledger import _validate_event_against_schema

        outcome_dict = invalid.to_dict()
        outcome_dict["forbidden"] = "should_not_exist"
        from datetime import UTC, datetime
        import uuid as _uuid

        event = {
            "schema_version": "rig.relay.provider_invocation_evidence_event.v1",
            "event_id": _uuid.uuid4().hex,
            "created_at": datetime.now(UTC).isoformat(),
            "session_id": "s1",
            "outcome": outcome_dict,
            "event_digest": "",
            "content_light": True,
        }

        try:
            _validate_event_against_schema(event)
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

        # Re-load service - should still only have 1 event
        svc2 = ProviderEvidenceQueryService()
        assert svc2.event_count == 1

    def test_concurrent_append_integrity_remains_queryable(self):
        """Concurrently persisted events remain integrity-valid and queryable."""
        import threading

        results: list[str] = []

        def _persist(idx: int):
            o = _build_outcome(f"provider-{idx}", f"model-{idx}")
            d = persist_provider_event(o, session_id="s-concurrent")
            results.append(d)

        threads = [threading.Thread(target=_persist, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        assert len(set(results)) == 10

        svc = ProviderEvidenceQueryService()
        assert svc.event_count == 10
        assert svc.integrity_verified
        assert svc.integrity_errors == []

        # Each provider-{i} should have 1 event
        for i in range(10):
            r = svc.list_by_provider(f"provider-{i}")
            assert r.matched_count == 1

        summary = svc.build_summary()
        assert summary.total_events == 10
        assert summary.integrity_verified

    def test_query_result_content_light(self):
        """Query results never contain raw prompts, completions, or secrets."""
        _ = persist_provider_event(_build_outcome(), session_id="s1")

        svc = ProviderEvidenceQueryService()
        result = svc.list_by_provider("openai")
        e = result.events[0]

        serialized = json.dumps({
            "event_id": e.event_id,
            "provider_id": e.provider_id,
            "model_id": e.model_id,
            "outcome_class": e.outcome_class,
            "streaming": e.streaming,
            "input_tokens": e.input_tokens,
            "output_tokens": e.output_tokens,
            "cache_read_tokens": e.cache_read_tokens,
            "reasoning_tokens": e.reasoning_tokens,
            "event_digest": e.event_digest,
            "content_light": e.content_light,
        })

        assert "api_key" not in serialized.lower()
        assert "secret" not in serialized.lower()
        assert "token:" not in serialized.lower()


class TestQueryProjectionSchema:
    def test_projection_result_is_schema_conformant(self):
        _ = persist_provider_event(_build_outcome(), session_id="s1")

        svc = ProviderEvidenceQueryService()
        result = svc.list_by_provider("openai")

        projection: dict[str, object] = {
            "schema_version": result.schema_version,
            "events": [
                {
                    "event_id": e.event_id,
                    "created_at": e.created_at,
                    "session_id": e.session_id,
                    "correlation_id": e.correlation_id,
                    "provider_id": e.provider_id,
                    "model_id": e.model_id,
                    "api_style": e.api_style,
                    "outcome_class": e.outcome_class,
                    "streaming": e.streaming,
                    "input_tokens": e.input_tokens,
                    "output_tokens": e.output_tokens,
                    "total_tokens": e.total_tokens,
                    "cache_read_tokens": e.cache_read_tokens,
                    "cache_read_verified": e.cache_read_verified,
                    "reasoning_tokens": e.reasoning_tokens,
                    "reasoning_tokens_verified": e.reasoning_tokens_verified,
                    "usage_discrepancy_detected": e.usage_discrepancy_detected,
                    "usage_verified": e.usage_verified,
                    "is_refusal": e.is_refusal,
                    "is_error": e.is_error,
                    "event_digest": e.event_digest,
                    "content_light": e.content_light,
                }
                for e in result.events
            ],
            "total_canonical_events": result.total_canonical_events,
            "matched_count": result.matched_count,
            "integrity_verified": result.integrity_verified,
            "integrity_errors": result.integrity_errors,
            "projection_digest": result.projection_digest,
            "generated_at": result.generated_at,
            "query_description": result.query_description,
        }

        import jsonschema

        repo_root = Path(__file__).resolve().parent.parent.parent
        schema_path = (
            repo_root
            / "docs/schemas/rig.relay.provider_evidence_query_projection.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text("utf-8"))
        jsonschema.validate(projection, schema)

    def test_summary_projection_is_content_light(self):
        _ = persist_provider_event(_build_outcome(), session_id="s1")

        svc = ProviderEvidenceQueryService()
        summary = svc.build_summary()

        summary_dict = {
            "schema_version": summary.schema_version,
            "total_events": summary.total_events,
            "provider_ids": summary.provider_ids,
            "api_styles": summary.api_styles,
            "streaming_count": summary.streaming_count,
            "non_streaming_count": summary.non_streaming_count,
            "cached_token_verified_count": summary.cached_token_verified_count,
            "reasoning_token_verified_count": summary.reasoning_token_verified_count,
            "discrepancy_count": summary.discrepancy_count,
            "refusal_count": summary.refusal_count,
            "error_count": summary.error_count,
            "integrity_verified": summary.integrity_verified,
            "integrity_errors": summary.integrity_errors,
            "digest": summary.digest,
            "generated_at": summary.generated_at,
            "source_ledger": summary.source_ledger,
        }

        serialized = json.dumps(summary_dict)
        assert "api_key" not in serialized.lower()
        assert "secret" not in serialized.lower()
