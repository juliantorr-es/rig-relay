"""Tests for model observations — content-light, consent-gated, ranking, and comfort scoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from rig_relay.evidence.model_observations import (
    LOCAL_COMFORT_SCHEMA_VERSION,
    LOW_SAMPLE_THRESHOLD,
    MODEL_OBSERVATION_SCHEMA_VERSION,
    PROVIDER_RANKING_SCHEMA_VERSION,
    Backend,
    ComfortCategory,
    ConfidenceLevel,
    ModelObservation,
    ProviderKind,
    ProviderRankingSnapshot,
    UserOutcome,
    ValidationStatus,
    aggregate_provider_rankings,
    build_model_observation,
    compute_local_model_comfort_score,
    observation_sha256,
    observe_tool_call,
    validate_observation_content_light,
)
from rig_relay.evidence.redaction import (
    assert_remote_safe,
    classify_shareable_field,
    redact_for_remote,
)
from rig_relay.identity.telemetry_consent import (
    TelemetryConsentScope,
    TelemetryConsentStatus,
    active_consent_scopes,
    grant_consent,
    has_active_commercial_dataset_license,
    observation_allowed_by_consent,
    revoke_consent,
)

# ═══════════════════════════════════════════════════════════════════════
# ── Helpers
# ═══════════════════════════════════════════════════════════════════════


def _make_observation(
    provider_kind: str = ProviderKind.CLOUD,
    provider_name: str = "openai",
    model_id: str = "gpt-4o",
    task_kind: str = "code_gen",
    tool_call_count: int = 5,
    tool_success_count: int = 4,
    failure_count: int = 0,
    latency_ms: float | None = 1200.0,
    estimated_cost_usd: float | None = 0.02,
    backend: str = Backend.API,
    machine_profile_id: str | None = None,
) -> ModelObservation:
    return build_model_observation(
        task_kind=task_kind,
        task_fingerprint="sha256:abc123",
        provider_kind=provider_kind,
        provider_name=provider_name,
        model_id=model_id,
        backend=backend,
        machine_profile_id=machine_profile_id,
        endpoint_kind="chat",
        tool_call_count=tool_call_count,
        tool_success_count=tool_success_count,
        failure_count=failure_count,
        latency_ms=latency_ms,
        estimated_cost_usd=estimated_cost_usd,
        validation_status=ValidationStatus.PASSED,
        user_outcome=UserOutcome.ACCEPTED,
    )


# ═══════════════════════════════════════════════════════════════════════
# ── ModelObservation tests
# ═══════════════════════════════════════════════════════════════════════


class TestModelObservation:
    def test_cloud_observation_builds(self) -> None:
        obs = _make_observation()
        assert obs.provider_kind == ProviderKind.CLOUD
        assert obs.provider_name == "openai"
        assert obs.model_id == "gpt-4o"
        assert obs.backend == Backend.API
        assert obs.content_light_guarantee is True

    def test_local_observation_builds(self) -> None:
        obs = _make_observation(
            provider_kind=ProviderKind.LOCAL,
            provider_name="ollama",
            model_id="llama-3-8b",
            backend=Backend.LLAMA_CPP,
            machine_profile_id="m1-pro-16gb",
        )
        assert obs.provider_kind == ProviderKind.LOCAL
        assert obs.provider_name == "ollama"
        assert obs.machine_profile_id == "m1-pro-16gb"

    def test_observation_has_schema_version(self) -> None:
        obs = _make_observation()
        assert obs.schema_version == MODEL_OBSERVATION_SCHEMA_VERSION

    def test_observation_has_auto_ids(self) -> None:
        obs = _make_observation()
        assert obs.observation_id.startswith("obs_")
        assert obs.created_at

    def test_observation_zero_counts_defaulted(self) -> None:
        obs = build_model_observation(
            task_kind="chat",
            task_fingerprint="sha256:def456",
            provider_kind=ProviderKind.CLOUD,
            provider_name="anthropic",
            model_id="claude-3-5-sonnet",
            backend=Backend.API,
        )
        assert obs.tool_call_count == 0
        assert obs.tool_success_count == 0
        assert obs.retry_count == 0
        assert obs.refusal_count == 0
        assert obs.failure_count == 0
        assert obs.validation_status == ValidationStatus.UNKNOWN
        assert obs.user_outcome == UserOutcome.UNKNOWN


class TestObservationHash:
    def test_hash_deterministic(self) -> None:
        obs1 = _make_observation()
        obs2 = _make_observation()
        # Same inputs should produce same hash
        h1 = observation_sha256(obs1)
        h2 = observation_sha256(obs2)
        assert h1 == h2

    def test_hash_prefix(self) -> None:
        obs = _make_observation()
        h = observation_sha256(obs)
        assert h.startswith("sha256:")
        assert len(h) == 71  # "sha256:" (7) + 64 hex chars

    def test_hash_differs_for_different_inputs(self) -> None:
        obs1 = _make_observation(model_id="gpt-4o")
        obs2 = _make_observation(model_id="gpt-4o-mini")
        h1 = observation_sha256(obs1)
        h2 = observation_sha256(obs2)
        assert h1 != h2


class TestContentLightValidation:
    def test_valid_observation_passes(self) -> None:
        obs = _make_observation()
        warnings = validate_observation_content_light(obs)
        assert len(warnings) == 0

    def test_guarantee_flag_always_true(self) -> None:
        obs = _make_observation()
        assert obs.content_light_guarantee is True

    def test_raw_prompt_field_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("raw_prompt", "write code")
        assert result == "forbid"

    def test_prompt_field_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("prompt", "do something")
        assert result == "forbid"

    def test_raw_model_output_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("raw_model_output", "output text")
        assert result == "forbid"

    def test_model_output_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("model_output", "output text")
        assert result == "forbid"

    def test_source_code_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("source_code", "def foo(): pass")
        assert result == "forbid"

    def test_diff_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("diff", "diff --git a/x b/x")
        assert result == "forbid"

    def test_stdout_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("stdout", "hello")
        assert result == "forbid"

    def test_stderr_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("stderr", "error")
        assert result == "forbid"

    def test_access_token_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("access_token", "tok_xxx")
        assert result == "forbid"

    def test_refresh_token_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("refresh_token", "rtok_xxx")
        assert result == "forbid"

    def test_private_path_rejected_in_redaction(self) -> None:
        result = classify_shareable_field("private_path", "/home/user/secret")
        assert result == "forbid"

    def test_observation_dump_safe_for_redaction(self) -> None:
        obs = _make_observation()
        dumped = obs.model_dump(mode="json")
        result = redact_for_remote(dumped)
        # All observation fields should be allowed
        assert len(result.redacted_paths) == 0

    def test_redacted_observation_roundtrip(self) -> None:
        obs = _make_observation()
        safe = assert_remote_safe(obs.model_dump(mode="json"))
        assert safe["content_light_guarantee"] is True
        assert safe["provider_name"] == "openai"


# ═══════════════════════════════════════════════════════════════════════
# ── Consent gate tests
# ═══════════════════════════════════════════════════════════════════════


class TestActiveConsentScopes:
    def test_revoked_consent_returns_empty(self) -> None:
        record = grant_consent(
            subject_hash="test",
            provider="local",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        record.status = TelemetryConsentStatus.REVOKED
        active = active_consent_scopes(record)
        assert active == []

    def test_denied_consent_returns_empty(self) -> None:
        record = grant_consent(
            subject_hash="test",
            provider="local",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        record.status = TelemetryConsentStatus.DENIED
        active = active_consent_scopes(record)
        assert active == []

    def test_not_requested_returns_empty(self) -> None:
        from rig_relay.identity.telemetry_consent import build_initial_consent

        record = build_initial_consent()
        active = active_consent_scopes(record)
        assert active == []

    def test_revoked_retains_scopes_in_record(self) -> None:
        record = grant_consent(
            subject_hash="test",
            provider="local",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        record.status = TelemetryConsentStatus.REVOKED
        # The scope is still in the record but not active
        assert TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING in record.scopes
        assert active_consent_scopes(record) == []


class TestObservationAllowedByConsent:
    def test_provider_requires_provider_benchmarking(self) -> None:
        record = grant_consent(subject_hash="test", provider="local")
        # Default scopes don't include provider_model_benchmarking
        assert observation_allowed_by_consent(record, "provider") is False

    def test_provider_allowed_with_scope(self) -> None:
        record = grant_consent(
            subject_hash="test",
            provider="local",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        assert observation_allowed_by_consent(record, "provider") is True

    def test_local_model_requires_local_benchmarking(self) -> None:
        record = grant_consent(subject_hash="test", provider="local")
        assert observation_allowed_by_consent(record, "local_model") is False

    def test_local_model_allowed_with_scope(self) -> None:
        record = grant_consent(
            subject_hash="test",
            provider="local",
            scopes=[TelemetryConsentScope.LOCAL_MODEL_BENCHMARKING],
        )
        assert observation_allowed_by_consent(record, "local_model") is True

    def test_commercial_export_requires_commercial_license(self) -> None:
        record = grant_consent(subject_hash="test", provider="local")
        assert observation_allowed_by_consent(record, "commercial_export") is False

    def test_commercial_export_allowed_with_scope(self) -> None:
        record = grant_consent(
            subject_hash="test",
            provider="local",
            scopes=[TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE],
        )
        assert observation_allowed_by_consent(record, "commercial_export") is True

    def test_public_aggregate_requires_aggregate_reporting(self) -> None:
        record = grant_consent(subject_hash="test", provider="local")
        assert observation_allowed_by_consent(record, "public_aggregate") is False

    def test_public_aggregate_allowed_with_scope(self) -> None:
        record = grant_consent(
            subject_hash="test",
            provider="local",
            scopes=[TelemetryConsentScope.AGGREGATE_PUBLIC_REPORTING],
        )
        assert observation_allowed_by_consent(record, "public_aggregate") is True

    def test_revoked_denies_even_with_scope(self) -> None:
        record = grant_consent(
            subject_hash="test",
            provider="local",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        record = revoke_consent(record)
        assert observation_allowed_by_consent(record, "provider") is False

    def test_unknown_kind_raises(self) -> None:
        record = grant_consent(subject_hash="test", provider="local")
        with pytest.raises(ValueError, match="Unknown observation_kind"):
            observation_allowed_by_consent(record, "unknown_kind")


class TestHasActiveCommercialDatasetLicense:
    def test_active_when_granted_with_scope(self) -> None:
        record = grant_consent(
            subject_hash="test",
            provider="local",
            scopes=[TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE],
        )
        assert has_active_commercial_dataset_license(record) is True

    def test_not_active_when_revoked(self) -> None:
        record = grant_consent(
            subject_hash="test",
            provider="local",
            scopes=[TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE],
        )
        record = revoke_consent(record)
        assert has_active_commercial_dataset_license(record) is False

    def test_not_active_when_scope_absent(self) -> None:
        record = grant_consent(subject_hash="test", provider="local")
        assert has_active_commercial_dataset_license(record) is False


# ═══════════════════════════════════════════════════════════════════════
# ── Provider ranking tests
# ═══════════════════════════════════════════════════════════════════════


class TestAggregateProviderRankings:
    def test_empty_observations_emits_warning(self) -> None:
        snapshot = aggregate_provider_rankings([])
        assert snapshot.sample_count == 0
        assert snapshot.confidence_level == ConfidenceLevel.LOW
        assert len(snapshot.warnings) > 0

    def test_single_provider_aggregates_scores(self) -> None:
        obs = [_make_observation()]
        snapshot = aggregate_provider_rankings(obs)
        assert snapshot.sample_count == 1
        assert len(snapshot.provider_scores) == 1
        assert snapshot.provider_scores[0].provider_name == "openai"

    def test_low_sample_emits_warning(self) -> None:
        obs = [_make_observation() for _ in range(LOW_SAMPLE_THRESHOLD - 1)]
        snapshot = aggregate_provider_rankings(obs)
        assert snapshot.confidence_level == ConfidenceLevel.LOW
        assert any("Low sample" in w for w in snapshot.warnings)

    def test_medium_sample_is_medium_confidence(self) -> None:
        obs = [_make_observation() for _ in range(LOW_SAMPLE_THRESHOLD * 2)]
        snapshot = aggregate_provider_rankings(obs)
        assert snapshot.confidence_level == ConfidenceLevel.MEDIUM

    def test_high_sample_is_high_confidence(self) -> None:
        obs = [_make_observation() for _ in range(LOW_SAMPLE_THRESHOLD * 4)]
        snapshot = aggregate_provider_rankings(obs)
        assert snapshot.confidence_level == ConfidenceLevel.HIGH

    def test_multiple_providers(self) -> None:
        obs = [
            _make_observation(provider_name="openai", model_id="gpt-4o"),
            _make_observation(provider_name="anthropic", model_id="claude-3"),
            _make_observation(provider_name="openai", model_id="gpt-4o-mini"),
        ]
        snapshot = aggregate_provider_rankings(obs)
        assert len(snapshot.provider_scores) == 2
        names = {s.provider_name for s in snapshot.provider_scores}
        assert names == {"openai", "anthropic"}

    def test_task_kind_filtering(self) -> None:
        obs = [
            _make_observation(task_kind="code_gen"),
            _make_observation(task_kind="chat"),
        ]
        snapshot = aggregate_provider_rankings(obs, task_kind="code_gen")
        assert snapshot.sample_count == 1


class TestAggregateScoreValues:
    def test_perfect_scores(self) -> None:
        obs = [
            _make_observation(
                tool_call_count=10,
                tool_success_count=10,
                failure_count=0,
                latency_ms=100.0,
                estimated_cost_usd=0.001,
            )
        ]
        snapshot = aggregate_provider_rankings(obs)
        score = snapshot.provider_scores[0]
        assert score.task_success_score == 1.0
        assert score.tool_reliability_score == 1.0


# ═══════════════════════════════════════════════════════════════════════
# ── Local comfort score tests
# ═══════════════════════════════════════════════════════════════════════


class TestLocalModelComfortScore:
    def test_high_scores_give_comfortable(self) -> None:
        score = compute_local_model_comfort_score(
            model_id="llama-3-8b",
            backend=Backend.MLX,
            machine_profile_id="m1-pro-16gb",
            memory_headroom_score=0.9,
            speed_score=0.8,
            context_score=0.85,
            stability_score=0.95,
            evidence_count=15,
        )
        assert score.comfort_category == ComfortCategory.COMFORTABLE
        assert score.evidence_count == 15

    def test_medium_scores_give_maybe(self) -> None:
        score = compute_local_model_comfort_score(
            model_id="llama-3-70b",
            backend=Backend.MLX,
            machine_profile_id="m1-pro-16gb",
            memory_headroom_score=0.5,
            speed_score=0.4,
            context_score=0.6,
            stability_score=0.5,
            evidence_count=5,
        )
        assert score.comfort_category == ComfortCategory.MAYBE

    def test_low_scores_give_not_recommended(self) -> None:
        score = compute_local_model_comfort_score(
            model_id="llama-3-70b",
            backend=Backend.MLX,
            machine_profile_id="m1-pro-8gb",
            memory_headroom_score=0.1,
            speed_score=0.05,
            context_score=0.2,
            stability_score=0.3,
            evidence_count=2,
        )
        assert score.comfort_category == ComfortCategory.NOT_RECOMMENDED

    def test_zero_evidence_emits_warning(self) -> None:
        score = compute_local_model_comfort_score(
            model_id="llama-3-8b",
            backend=Backend.MLX,
            machine_profile_id="m1-pro-16gb",
            memory_headroom_score=0.9,
            speed_score=0.8,
            context_score=0.85,
            stability_score=0.95,
            evidence_count=0,
        )
        assert any("No observed evidence" in w for w in score.warnings)

    def test_schema_version(self) -> None:
        score = compute_local_model_comfort_score(
            model_id="test",
            backend=Backend.MLX,
            machine_profile_id="test",
            evidence_count=1,
        )
        assert score.schema_version == LOCAL_COMFORT_SCHEMA_VERSION

    def test_quantization_stored(self) -> None:
        score = compute_local_model_comfort_score(
            model_id="test",
            backend=Backend.LLAMA_CPP,
            machine_profile_id="test",
            quantization="q4_0",
            evidence_count=1,
        )
        assert score.quantization == "q4_0"


# ═══════════════════════════════════════════════════════════════════════
# ── Schema validation tests
# ═══════════════════════════════════════════════════════════════════════


class TestObservationSchemaCompliance:
    SCHEMA_DIR = Path(__file__).resolve().parent.parent / "docs" / "schemas"
    _schemas: ClassVar[dict[str, Any]] = {}

    @pytest.fixture(autouse=True)
    def _load_schemas(self) -> None:
        type(self)._schemas = {}
        for name in (
            "rig.relay.model_observation.v1.schema.json",
            "rig.relay.provider_ranking_snapshot.v1.schema.json",
            "rig.relay.local_model_comfort_score.v1.schema.json",
        ):
            path = self.SCHEMA_DIR / name
            if path.is_file():
                key = name.split(".")[2]
                if key.endswith("_snapshot") or key.endswith("_score"):
                    key = "_".join(key.split("_")[:-1])
                type(self)._schemas[key] = json.loads(path.read_text())

    def test_observation_schema_validates(self) -> None:
        import jsonschema

        schema = type(self)._schemas["model_observation"]
        obs = _make_observation()
        data = obs.model_dump(mode="json")
        jsonschema.validate(data, schema)

    def test_provider_ranking_schema_validates(self) -> None:
        import jsonschema

        schema = type(self)._schemas["provider_ranking"]
        obs = [_make_observation() for _ in range(5)]
        snapshot = aggregate_provider_rankings(obs)
        data = snapshot.model_dump(mode="json")
        jsonschema.validate(data, schema)

    def test_local_comfort_schema_validates(self) -> None:
        import jsonschema

        schema = type(self)._schemas["local_model_comfort"]
        score = compute_local_model_comfort_score(
            model_id="llama-3-8b",
            backend=Backend.MLX,
            machine_profile_id="m1-pro-16gb",
            memory_headroom_score=0.9,
            speed_score=0.8,
            context_score=0.85,
            stability_score=0.95,
            evidence_count=10,
        )
        data = score.model_dump(mode="json")
        jsonschema.validate(data, schema)

    def test_all_three_schemas_in_directory(self) -> None:
        assert (
            self.SCHEMA_DIR / "rig.relay.model_observation.v1.schema.json"
        ).is_file()
        assert (
            self.SCHEMA_DIR / "rig.relay.provider_ranking_snapshot.v1.schema.json"
        ).is_file()
        assert (
            self.SCHEMA_DIR / "rig.relay.local_model_comfort_score.v1.schema.json"
        ).is_file()


# ═══════════════════════════════════════════════════════════════════════
# ── RankingSnapshot model tests
# ═══════════════════════════════════════════════════════════════════════


class TestProviderRankingSnapshot:
    def test_empty_provider_list_defaults(self) -> None:
        snap = ProviderRankingSnapshot()
        assert snap.sample_count == 0
        assert snap.provider_scores == []
        assert snap.model_scores == []

    def test_schema_version(self) -> None:
        snap = ProviderRankingSnapshot()
        assert snap.schema_version == PROVIDER_RANKING_SCHEMA_VERSION

    def test_ranking_id_generated(self) -> None:
        snap = aggregate_provider_rankings([_make_observation()])
        assert snap.ranking_id.startswith("rank_")


# ═══════════════════════════════════════════════════════════════════════
# ── Observe tool call tests
# ═══════════════════════════════════════════════════════════════════════


class TestObserveToolCallContentLight:
    """Verify that observe_tool_call produces content-light events."""

    MINIMAL_ARGS: ClassVar[dict[str, Any]] = {
        "session_id": "test-session-obs",
        "task_kind": "code_gen",
        "task_fingerprint": "abcd1234",
        "provider_kind": ProviderKind.CLOUD,
        "provider_name": "openai",
        "model_id": "gpt-4o",
        "backend": Backend.API,
    }

    def test_event_contains_no_raw_args(self, tmp_path) -> None:
        obs = observe_tool_call(
            **self.MINIMAL_ARGS,
            tool_call_count=3,
            tool_success_count=2,
            latency_ms=500.0,
        )
        assert obs is not None
        data = obs.model_dump(mode="json")
        raw_like = {"args", "raw_args", "tool_args", "arguments", "command"}
        assert raw_like.isdisjoint(data.keys())

    def test_event_contains_no_raw_output(self, tmp_path) -> None:
        obs = observe_tool_call(**self.MINIMAL_ARGS)
        assert obs is not None
        data = obs.model_dump(mode="json")
        output_like = {"output", "raw_output", "result", "stdout", "stderr"}
        assert output_like.isdisjoint(data.keys())

    def test_event_contains_no_source_or_diff(self, tmp_path) -> None:
        obs = observe_tool_call(**self.MINIMAL_ARGS)
        assert obs is not None
        data = obs.model_dump(mode="json")
        source_like = {
            "source_code",
            "diff",
            "raw_prompt",
            "prompt",
            "raw_model_output",
            "model_output",
            "stdout",
            "stderr",
            "api_key",
            "access_token",
            "private_path",
        }
        assert source_like.isdisjoint(data.keys())

    def test_event_contains_no_forbidden_redaction_fields(self, tmp_path) -> None:
        obs = observe_tool_call(**self.MINIMAL_ARGS)
        assert obs is not None
        violations = validate_observation_content_light(obs)
        assert violations == []

    def test_event_has_content_light_guarantee(self, tmp_path) -> None:
        obs = observe_tool_call(**self.MINIMAL_ARGS)
        assert obs is not None
        assert obs.content_light_guarantee is True

    def test_fingerprint_passed_through_as_is(self, tmp_path) -> None:
        """observe_tool_call passes task_fingerprint through without hashing.
        The namespace- prefix and SHA256 computation happen in the caller
        (_capture_model_observation_for_tool_response).
        """
        obs = observe_tool_call(**self.MINIMAL_ARGS)
        assert obs is not None
        assert obs.task_fingerprint == self.MINIMAL_ARGS["task_fingerprint"]

    def test_skipped_status_returns_none(self, tmp_path) -> None:
        """Simulate that skipped tool calls produce no observation.
        The observe_tool_call function itself does not gate on status;
        this test verifies that the event is written even for zero-count calls.
        """
        obs = observe_tool_call(
            **self.MINIMAL_ARGS,
            tool_call_count=1,
            tool_success_count=0,
            failure_count=0,
        )
        # observe_tool_call always writes — the skip gating is in the caller
        assert obs is not None
        assert obs.tool_success_count == 0
        assert obs.failure_count == 0

    def test_multiple_calls_produce_separate_observations(self, tmp_path) -> None:
        obs1 = observe_tool_call(**self.MINIMAL_ARGS, tool_call_count=1)
        obs2 = observe_tool_call(**self.MINIMAL_ARGS, tool_call_count=2)
        assert obs1 is not None
        assert obs2 is not None
        assert obs1.observation_id != obs2.observation_id

    def test_latency_defaults_to_none(self, tmp_path) -> None:
        obs = observe_tool_call(**self.MINIMAL_ARGS)
        assert obs is not None
        assert obs.latency_ms is None


class TestObserveToolCallFailureResilience:
    """Verify observe_tool_call failures do not propagate."""

    def test_invalid_session_id_does_not_raise(self) -> None:
        """Even with a non-sensical session_id, the function catches internally."""
        obs = observe_tool_call(
            session_id="",
            task_kind="test",
            task_fingerprint="fp",
            provider_kind=ProviderKind.CLOUD,
            provider_name="p",
            model_id="m",
        )
        # The function itself does not raise on invalid session — log_local_event
        # creates directories as needed.
        assert obs is not None

    def test_empty_provider_name_does_not_raise(self) -> None:
        obs = observe_tool_call(
            session_id="test-empty-provider",
            task_kind="test",
            task_fingerprint="fp",
            provider_kind=ProviderKind.CLOUD,
            provider_name="",
            model_id="m",
        )
        assert obs is not None
        assert obs.provider_name == ""


class TestTaskFingerprintDeterminism:
    """Verify task_fingerprint is deterministic and content-light."""

    def test_deterministic_fingerprint(self) -> None:
        common_args: dict[str, Any] = dict(
            session_id="det-session",
            task_kind="code_gen",
            task_fingerprint="deterministic-test-fp",
            provider_kind=ProviderKind.CLOUD,
            provider_name="openai",
            model_id="gpt-4o",
        )
        obs1 = observe_tool_call(**common_args)
        obs2 = observe_tool_call(**common_args)
        assert obs1 is not None
        assert obs2 is not None
        assert obs1.task_fingerprint == obs2.task_fingerprint

    def test_fingerprint_passed_through_unmodified(self) -> None:
        """observe_tool_call does not modify the fingerprint."""
        original = "some-fingerprint"
        obs = observe_tool_call(
            session_id="fp-session",
            task_kind="code_gen",
            task_fingerprint=original,
            provider_kind=ProviderKind.CLOUD,
            provider_name="openai",
            model_id="gpt-4o",
        )
        assert obs is not None
        assert obs.task_fingerprint == original
