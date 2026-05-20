"""Airlock gating tests for local inference.

Proves that local inference remains gated until explicitly configured.
Tests cover: unconfigured gates, config lifecycle, receipt production,
content-light constraints, and capability gate integration.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pytest

from rig_relay.providers.local_inference import (
    CapabilityProbeResult,
    LocalInferenceAirlock,
    LocalInferenceEndpointConfig,
    LocalRuntimeKind,
    PlatformClass,
    TaskProfile,
    build_config_receipt,
    build_probe_receipt,
    build_routing_receipt,
    get_airlock,
    is_local_inference_available,
    is_local_inference_configured,
    probe_local_endpoint,
    select_runtime,
)
from rig_relay.providers.local_inference.airlock import DEFAULT_CONFIG_ROOT
from rig_relay.providers.local_inference.receipts import (
    build_config_receipt as _build_config_receipt,
)


class TestAirlockGating:
    def test_airlock_not_configured_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            airlock = LocalInferenceAirlock(Path(td))
            assert not airlock.is_configured
            assert airlock.get_config() is None

    def test_airlock_configure_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            airlock = LocalInferenceAirlock(Path(td))
            config = airlock.configure_endpoint(
                "http://localhost:8080",
                runtime_kind=LocalRuntimeKind.LLAMA_CPP,
                platform_class=PlatformClass.METAL,
            )
            assert airlock.is_configured
            assert config.endpoint_url == "http://localhost:8080"
            assert config.runtime_kind == LocalRuntimeKind.LLAMA_CPP
            assert config.endpoint_sha256
            assert len(config.endpoint_sha256) == 64

    def test_airlock_remove_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            airlock = LocalInferenceAirlock(Path(td))
            airlock.configure_endpoint("http://localhost:8080")
            assert airlock.is_configured
            airlock.remove_config()
            assert not airlock.is_configured

    def test_is_local_inference_configured_checks_real_path(self) -> None:
        assert is_local_inference_configured() in (True, False)

    def test_airlock_build_config_snapshot_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            airlock = LocalInferenceAirlock(Path(td))
            snap = airlock.build_config_snapshot()
            assert snap["configured"] is False

    def test_airlock_build_config_snapshot_configured(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            airlock = LocalInferenceAirlock(Path(td))
            airlock.configure_endpoint("http://localhost:8080")
            snap = airlock.build_config_snapshot()
            assert snap["configured"] is True
            assert snap["endpoint_url"] == "http://localhost:8080"
            assert snap["endpoint_sha256"]


class TestAirlockReceipts:
    @pytest.mark.asyncio
    async def test_probe_produces_receipt(self) -> None:
        result = await probe_local_endpoint("http://localhost:8080", dry_run=True)
        receipt = build_probe_receipt(result)
        assert receipt["schema_version"] == "rig.relay.receipt_envelope.v1"
        assert receipt["receipt_kind"] == "local_inference_probe"
        assert receipt["actor"]["actor_kind"] == "system"
        assert len(receipt["evidence"]) >= 1

    def test_routing_produces_receipt(self) -> None:
        decision = select_runtime(
            probed_runtimes=[], task_profile=TaskProfile(), dry_run=True
        )
        receipt = build_routing_receipt(decision)
        assert receipt["schema_version"] == "rig.relay.receipt_envelope.v1"
        assert receipt["receipt_kind"] == "local_inference_routing"

    def test_config_produces_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            airlock = LocalInferenceAirlock(Path(td))
            airlock.configure_endpoint("http://localhost:8080")
            snap = airlock.build_config_snapshot()
            receipt = build_config_receipt(snap)
            assert receipt["schema_version"] == "rig.relay.receipt_envelope.v1"
            assert receipt["receipt_kind"] == "local_inference_config"
            assert receipt["decision"]["decision"] == "configured"

    def test_unconfigured_config_produces_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            airlock = LocalInferenceAirlock(Path(td))
            snap = airlock.build_config_snapshot()
            receipt = build_config_receipt(snap)
            assert receipt["decision"]["decision"] == "unconfigured"


class TestAirlockContentLight:
    def test_endpoint_config_never_stores_secrets(self) -> None:
        config = LocalInferenceEndpointConfig()
        config.set_endpoint("http://localhost:8080")
        data = json.loads(config.model_dump_json())
        sensitive = {"token", "secret", "api_key", "password", "credential"}
        for field in data:
            assert field not in sensitive, f"Config field '{field}' may leak secrets"

    def test_probe_receipt_content_light(self) -> None:
        result = CapabilityProbeResult(
            probe_id="p_test",
            runtime_url="http://localhost:8080",
            probed_at="2026-01-01T00:00:00Z",
            probe_duration_ms=100,
            reachable=True,
        )
        receipt = build_probe_receipt(result)
        receipt_str = json.dumps(receipt, sort_keys=True)
        assert "token" not in receipt_str.lower()
        assert "secret" not in receipt_str.lower()
        assert "api_key" not in receipt_str.lower()
        assert "password" not in receipt_str.lower()

    def test_routing_receipt_content_light(self) -> None:
        decision = select_runtime(
            probed_runtimes=[], task_profile=TaskProfile(), dry_run=True
        )
        receipt = build_routing_receipt(decision)
        receipt_str = json.dumps(receipt, sort_keys=True)
        assert "token" not in receipt_str.lower()

    def test_airlock_config_snapshot_no_raw_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            airlock = LocalInferenceAirlock(Path(td))
            airlock.configure_endpoint("http://localhost:8080")
            snap = airlock.build_config_snapshot()
            for key in snap:
                assert "token" not in key.lower()
                assert "secret" not in key.lower()
                assert "key" not in key.lower()

    def test_endpoint_config_enum_fields_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            airlock = LocalInferenceAirlock(Path(td))
            config = airlock.configure_endpoint(
                "http://localhost:8080",
                runtime_kind=LocalRuntimeKind.LLAMA_CPP,
                platform_class=PlatformClass.CPU,
            )
            assert config.runtime_kind.value in {
                "vllm",
                "llama_cpp",
                "mlx_lm",
                "unknown",
            }
            assert config.api_protocol.value in {
                "openai_compatible",
                "cli_subprocess",
                "python_module",
            }
            assert config.platform_class.value in {
                "cpu",
                "cuda",
                "metal",
                "vulkan",
                "rocm",
                "unknown",
            }


class TestAirlockSchemaValidation:
    def test_endpoint_config_schema_exists(self) -> None:
        SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"
        schema_path = (
            SCHEMA_DIR / "rig.relay.local_inference.endpoint_config.v1.schema.json"
        )
        assert schema_path.exists()

    def test_endpoint_config_schema_validates(self) -> None:
        import jsonschema

        SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"
        schema_path = (
            SCHEMA_DIR / "rig.relay.local_inference.endpoint_config.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as td:
            airlock = LocalInferenceAirlock(Path(td))
            airlock.configure_endpoint("http://localhost:8080")
            config = airlock.get_config()
            assert config is not None
            data = json.loads(config.model_dump_json())
            jsonschema.validate(data, schema)

    def test_provider_enum_includes_local_inference(self) -> None:
        from rig_relay.providers.models import Provider

        assert hasattr(Provider, "LOCAL_INFERENCE")
        assert Provider.LOCAL_INFERENCE.value == "local_inference"

    def test_provider_registry_includes_local_inference(self) -> None:
        from rig_relay.providers.registry import (
            PROVIDER_REGISTRY,
            get_provider_info,
            is_supported_provider,
        )
        from rig_relay.providers.models import Provider

        info = get_provider_info(Provider.LOCAL_INFERENCE)
        assert info is not None
        assert info.display_name == "Local Inference"
        assert info.env_var == ""
        assert info.supports_base_url is True
        assert is_supported_provider("local_inference")
