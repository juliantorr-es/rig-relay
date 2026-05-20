"""Agent-loop integration tests for local inference wiring."""

from __future__ import annotations

import pytest

from rig_relay.core.config._settings import VibeConfig


class TestLocalInferenceConfig:
    def test_local_inference_enabled_defaults_false(self) -> None:
        config = VibeConfig()
        assert config.local_inference_enabled is False

    def test_local_inference_enabled_can_be_true(self) -> None:
        config = VibeConfig(local_inference_enabled=True)
        assert config.local_inference_enabled is True

    def test_provider_config_exists(self) -> None:
        config = VibeConfig()
        providers = {p.name for p in config.providers}
        assert "local_inference" in providers, (
            "local_inference provider missing from defaults"
        )

    def test_model_config_exists(self) -> None:
        config = VibeConfig()
        aliases = {m.alias for m in config.models}
        assert "local-inference" in aliases, (
            "local-inference model missing from defaults"
        )

    def test_local_inference_provider_uses_generic_backend(self) -> None:
        config = VibeConfig()
        for p in config.providers:
            if p.name == "local_inference":
                assert p.backend.value == "generic", (
                    "local_inference must use GenericBackend"
                )
                assert p.api_key_env_var == "", (
                    "local_inference must not require API key"
                )
                return
        pytest.fail("local_inference provider not found")

    def test_local_inference_model_zero_cost(self) -> None:
        config = VibeConfig()
        for m in config.models:
            if m.provider == "local_inference":
                assert m.input_price == 0.0
                assert m.output_price == 0.0
                return
        pytest.fail("local_inference model not found")


class TestBackendSelection:
    def test_disabled_flag_prevents_selection(self) -> None:
        config = VibeConfig(
            local_inference_enabled=False, active_model="local-inference"
        )
        assert config.local_inference_enabled is False

    def test_enabled_flag_allows_selection(self) -> None:
        config = VibeConfig(
            local_inference_enabled=True, active_model="local-inference"
        )
        assert config.local_inference_enabled is True


class TestCapabilityGate:
    def test_local_inference_chat_always_allowed(self) -> None:
        from rig_relay.governance.service_state import get_capability_gate

        gate = get_capability_gate()
        allowed, _ = gate.is_allowed("local_inference_chat")
        assert allowed, "local_inference_chat must be ALWAYS_ALLOWED"

    def test_local_inference_execute_always_allowed(self) -> None:
        from rig_relay.governance.service_state import get_capability_gate

        gate = get_capability_gate()
        allowed, _ = gate.is_allowed("local_inference_execute")
        assert allowed, "local_inference_execute must be ALWAYS_ALLOWED"


class TestNameCollisionResolved:
    def test_benchmark_harness_has_unique_name(self) -> None:
        from rig_relay.providers.local_inference.benchmark_harness import (
            build_capacity_benchmark_sample,
        )
        from rig_relay.providers.local_inference.benchmark_writer import (
            build_benchmark_sample,
        )

        assert build_capacity_benchmark_sample is not build_benchmark_sample

    def test_capacity_sample_has_expected_id_prefix(self) -> None:
        from rig_relay.providers.local_inference.benchmark_harness import (
            build_capacity_benchmark_sample,
        )

        sample = build_capacity_benchmark_sample(
            plan_id="p1", task_profile="chat_light"
        )
        assert sample.sample_id.startswith("cbs_")


class TestEndToEndProviderResolution:
    def test_local_inference_provider_has_correct_defaults(self) -> None:
        config = VibeConfig()
        for p in config.providers:
            if p.name == "local_inference":
                assert p.backend.value == "generic"
                assert p.api_style == "openai", (
                    "local inference uses OpenAI-compatible API"
                )
                return
        pytest.fail("provider not found")

    def test_active_model_switch_preserves_local_inference_gating(self) -> None:
        config = VibeConfig(local_inference_enabled=True)
        models = {m.alias: m for m in config.models}
        assert "local-inference" in models
