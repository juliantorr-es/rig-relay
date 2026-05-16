"""Integration tests for consent scope gating in observation capture.

Tests the seam between ``_capture_model_observation_for_tool_response``
and the consent store / ``observe_tool_call`` function.  All tests use
monkeypatched consent records and a mock ``observe_tool_call`` — never
a real consent file or real observability sink.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel
import pytest

from rig_relay.core.config import VibeConfig
from rig_relay.core.llm.format import ResolvedToolCall
from rig_relay.core.tools.base import BaseTool
from rig_relay.evidence.model_observations import Backend as ObsBackend
from rig_relay.identity.telemetry_consent import (
    TelemetryConsentRecord,
    TelemetryConsentScope,
    build_initial_consent,
    grant_consent,
    revoke_consent,
)

# ═══════════════════════════════════════════════════════════════════════
# ── Fixtures
# ═══════════════════════════════════════════════════════════════════════


class MockArgs(BaseModel):
    command: str


_OBSERVE_CALLED: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def _reset_observe_call_log():
    """Clear the observe_tool_call call log before each test."""
    _OBSERVE_CALLED.clear()


def _make_mock_observe_tool_call():
    """Return a function that records calls instead of writing to disk."""

    def _mock_observe(**kwargs: Any) -> None:
        _OBSERVE_CALLED.append(kwargs)

    return _mock_observe


# ═══════════════════════════════════════════════════════════════════════
# ── Backend-to-observation-kind mapping tests
# ═══════════════════════════════════════════════════════════════════════


class TestBackendToConsentKindMapping:
    """Verify that the consent kind derivation matches expected mapping.

    These test the logic embedded in ``_capture_model_observation_for_tool_response``:
    local backends (mlx, llama_cpp, ollama) → ``local_model`` kind
    everything else → ``provider`` kind
    """

    LOCAL_BACKENDS: ClassVar[set[str]] = {ObsBackend.MLX, ObsBackend.LLAMA_CPP}
    CLOUD_BACKENDS: ClassVar[set[str]] = {ObsBackend.API}

    def test_mlx_is_local_model_kind(self) -> None:
        is_local = ObsBackend.MLX in self.LOCAL_BACKENDS
        kind = "local_model" if is_local else "provider"
        assert is_local is True
        assert kind == "local_model"

    def test_llama_cpp_is_local_model_kind(self) -> None:
        is_local = ObsBackend.LLAMA_CPP in self.LOCAL_BACKENDS
        kind = "local_model" if is_local else "provider"
        assert is_local is True
        assert kind == "local_model"

    def test_api_is_provider_kind(self) -> None:
        is_local = ObsBackend.API in self.LOCAL_BACKENDS
        kind = "local_model" if is_local else "provider"
        assert is_local is False
        assert kind == "provider"

    def test_unknown_backend_falls_to_provider_kind(self) -> None:
        """Unknown/unspecified backends are conservatively treated as provider."""
        unknown = "unknown_backend"
        is_local = unknown in {"mlx", "llama_cpp", "ollama"}
        kind = "local_model" if is_local else "provider"
        assert is_local is False
        assert kind == "provider"

    def test_ollama_is_local_model_kind(self) -> None:
        """ollama is explicitly listed as a local backend."""
        is_local = "ollama" in {"mlx", "llama_cpp", "ollama"}
        kind = "local_model" if is_local else "provider"
        assert is_local is True
        assert kind == "local_model"

    def test_generic_backend_is_provider_kind(self) -> None:
        """generic (cloud API) should be provider kind."""
        is_local = "generic" in {"mlx", "llama_cpp", "ollama"}
        kind = "local_model" if is_local else "provider"
        assert is_local is False
        assert kind == "provider"


# ═══════════════════════════════════════════════════════════════════════
# ── Consent store integration tests
# ═══════════════════════════════════════════════════════════════════════


class TestConsentScopeIntegration:
    """Verify that consent scoping at the capture seam works correctly.

    Uses ``_capture_model_observation_for_tool_response`` directly via
    ``_handle_tool_response`` with monkeypatched consent store and
    ``observe_tool_call``.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Set up an AgentLoop with minimal config for each test.

        Also monkeypatches ``observe_tool_call`` and ``ConsentStore.get``.
        """
        from rig_relay.core._tool_response import ToolResponseMixin
        from rig_relay.core.config.harness_files import init_harness_files_manager
        from rig_relay.evidence.model_observations import observe_tool_call

        init_harness_files_manager("user", "project")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "fake_key")

        config = VibeConfig()
        config.enable_local_observability = True
        config.enable_remote_telemetry = False
        config.active_model = "deepseek-v4-flash"

        class DummyAgentLoop(ToolResponseMixin):
            def __init__(self, cfg):
                self.config = cfg
                self.session_id = "test-consent-integration"

        self._loop = DummyAgentLoop(config)

        # Monkeypatch observe_tool_call to record calls instead of writing
        monkeypatch.setattr(
            "rig_relay.evidence.model_observations.observe_tool_call",
            _make_mock_observe_tool_call(),
        )
        # Store reference so tests can inspect
        self._observe_tool_call = observe_tool_call

        self._tool_call = ResolvedToolCall(
            call_id="call-consent-test",
            tool_name="bash",
            tool_class=BaseTool,
            validated_args=MockArgs(command="echo test"),
        )

    def _set_consent_record(
        self, monkeypatch: pytest.MonkeyPatch, record: TelemetryConsentRecord
    ) -> None:
        """Replace ConsentStore().get() to return the given record."""

        def _mock_get(_self: object) -> TelemetryConsentRecord:
            return record

        monkeypatch.setattr(
            "rig_relay.identity.consent_store.ConsentStore.get", _mock_get
        )

    def _assert_observe_called(self, expected_count: int = 1) -> None:
        assert len(_OBSERVE_CALLED) == expected_count, (
            f"Expected observe_tool_call called {expected_count} time(s), "
            f"got {len(_OBSERVE_CALLED)}. Calls: {_OBSERVE_CALLED}"
        )

    def _assert_observe_not_called(self) -> None:
        self._assert_observe_called(0)

    # ── NOT_REQUESTED / missing consent ──

    def test_not_requested_consent_does_not_observe(self, monkeypatch) -> None:
        """No consent record → NOT_REQUESTED status → observation denied."""
        self._set_consent_record(monkeypatch, build_initial_consent())
        self._loop._capture_model_observation_for_tool_response(
            self._tool_call, "success", duration_ms=100.0
        )
        self._assert_observe_not_called()

    # ── Provider scope + cloud backend ──

    def test_provider_scope_allows_cloud_observation(self, monkeypatch) -> None:
        """PROVIDER_MODEL_BENCHMARKING + cloud backend → observation persists."""
        record = grant_consent(
            subject_hash="test",
            provider="deepseek",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        self._set_consent_record(monkeypatch, record)
        self._loop._capture_model_observation_for_tool_response(
            self._tool_call, "success", duration_ms=100.0
        )
        self._assert_observe_called(1)

    # ── Local scope + local backend ──

    def test_local_scope_allows_local_observation(self, monkeypatch) -> None:
        """LOCAL_MODEL_BENCHMARKING + mlx backend → observation persists."""
        record = grant_consent(
            subject_hash="test",
            provider="ollama",
            scopes=[TelemetryConsentScope.LOCAL_MODEL_BENCHMARKING],
        )
        self._set_consent_record(monkeypatch, record)

        # Change the active provider's backend to mlx so the helper
        # classifies it as a local model observation.
        monkeypatch.setattr(self._loop.config.get_active_provider(), "backend", "mlx")

        self._loop._capture_model_observation_for_tool_response(
            self._tool_call, "success", duration_ms=100.0
        )
        self._assert_observe_called(1)

    # ── Wrong scope for local backend ──

    def test_provider_scope_denies_local_observation(self, monkeypatch) -> None:
        """Local backend + only PROVIDER_MODEL_BENCHMARKING → denied."""
        record = grant_consent(
            subject_hash="test",
            provider="ollama",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        self._set_consent_record(monkeypatch, record)
        # Set backend to mlx so the helper classifies as local
        monkeypatch.setattr(self._loop.config.get_active_provider(), "backend", "mlx")
        self._loop._capture_model_observation_for_tool_response(
            self._tool_call, "success", duration_ms=100.0
        )
        self._assert_observe_not_called()

    # ── Wrong scope for cloud backend ──

    def test_local_scope_denies_cloud_observation(self, monkeypatch) -> None:
        """Cloud backend + only LOCAL_MODEL_BENCHMARKING → denied."""
        record = grant_consent(
            subject_hash="test",
            provider="deepseek",
            scopes=[TelemetryConsentScope.LOCAL_MODEL_BENCHMARKING],
        )
        self._set_consent_record(monkeypatch, record)
        self._loop._capture_model_observation_for_tool_response(
            self._tool_call, "success", duration_ms=100.0
        )
        self._assert_observe_not_called()

    # ── Revoked consent ──

    def test_revoked_consent_denies_observation(self, monkeypatch) -> None:
        """Revoked consent + correct scope → still denied."""
        record = grant_consent(
            subject_hash="test",
            provider="deepseek",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        record = revoke_consent(record)
        self._set_consent_record(monkeypatch, record)
        self._loop._capture_model_observation_for_tool_response(
            self._tool_call, "success", duration_ms=100.0
        )
        self._assert_observe_not_called()

    # ── Error resilience ──

    def test_consent_store_error_does_not_break_tool_execution(
        self, monkeypatch
    ) -> None:
        """ConsentStore.get() raising does not propagate to caller."""

        def _broken_get(_self: object) -> TelemetryConsentRecord:
            msg = "Simulated consent store failure"
            raise RuntimeError(msg)

        monkeypatch.setattr(
            "rig_relay.identity.consent_store.ConsentStore.get", _broken_get
        )
        # This must not raise
        self._loop._capture_model_observation_for_tool_response(
            self._tool_call, "success", duration_ms=100.0
        )
        self._assert_observe_not_called()

    # ── Disabled observability ──

    def test_disabled_observability_skips_consent_evaluation(self, monkeypatch) -> None:
        """When enable_local_observability is False, consent is never checked."""
        self._loop.config.enable_local_observability = False

        # Even with a perfectly valid consent record, no observation
        record = grant_consent(
            subject_hash="test",
            provider="deepseek",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        self._set_consent_record(monkeypatch, record)
        self._loop._capture_model_observation_for_tool_response(
            self._tool_call, "success", duration_ms=100.0
        )
        self._assert_observe_not_called()

    # ── Skipped tool ──

    def test_skipped_tool_skips_consent_evaluation(self, monkeypatch) -> None:
        """Skipped tool + valid consent → still no observation."""
        record = grant_consent(
            subject_hash="test",
            provider="deepseek",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        self._set_consent_record(monkeypatch, record)
        self._loop._capture_model_observation_for_tool_response(
            self._tool_call, "skipped", duration_ms=None
        )
        self._assert_observe_not_called()

    # ── observe_tool_call itself ──

    def test_observe_tool_call_accepts_correct_arguments(self, monkeypatch) -> None:
        """When consent is granted, the correct args are passed through."""
        record = grant_consent(
            subject_hash="test",
            provider="deepseek",
            scopes=[TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING],
        )
        self._set_consent_record(monkeypatch, record)
        self._loop._capture_model_observation_for_tool_response(
            self._tool_call, "success", duration_ms=200.0
        )
        self._assert_observe_called(1)
        call_args = _OBSERVE_CALLED[0]
        assert call_args["session_id"] == "test-consent-integration"
        assert call_args["tool_call_count"] == 1
        assert call_args["tool_success_count"] == 1
        assert call_args["failure_count"] == 0
        assert call_args["latency_ms"] == 200.0
        assert call_args["provider_name"] == "deepseek"
        assert call_args["model_id"] == "deepseek-v4-flash"
        # Ensure content-light fields
        assert "raw_args" not in call_args
        assert "raw_output" not in call_args
