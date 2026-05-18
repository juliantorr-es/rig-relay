from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import tomli_w

from rig_relay.core.agent_loop import AgentLoop
from rig_relay.core.agents.models import BuiltinAgentName
from rig_relay.core.config._settings import (
    DEFAULT_MODELS,
    ModelConfig,
    SessionLoggingConfig,
    VibeConfig,
)
from rig_relay.core.config.harness_files import (
    init_harness_files_manager,
    reset_harness_files_manager,
)
from rig_relay.core.llm.types import BackendLike
from tests.stubs.fake_backend import FakeBackend


def get_base_config() -> dict[str, Any]:
    return {
        "active_model": "deepseek-v4-flash",
        "providers": [
            {
                "name": "deepseek",
                "api_base": "https://api.deepseek.com",
                "api_key_env_var": "DEEPSEEK_API_KEY",
                "api_style": "openai",
                "backend": "generic",
            }
        ],
        "models": [
            {
                "name": "deepseek-v4-flash",
                "provider": "deepseek",
                "alias": "deepseek-v4-flash",
            }
        ],
        "enable_auto_update": False,
        "enable_telemetry": False,
    }


@pytest.fixture(autouse=True)
def tmp_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    tmp_working_directory = tmp_path_factory.mktemp("test_cwd")
    monkeypatch.chdir(tmp_working_directory)
    return tmp_working_directory


@pytest.fixture(autouse=True)
def config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Generator[Path, None, None]:
    tmp_path = tmp_path_factory.mktemp("rig")
    config_dir = tmp_path / ".rig" / "relay"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.toml"
    config_file.write_text(tomli_w.dumps(get_base_config()), encoding="utf-8")

    monkeypatch.setattr(
        "rig_relay.core.paths._vibe_home._DEFAULT_RIG_RELAY_HOME", config_dir
    )
    monkeypatch.setattr(
        "rig_relay.core.paths._vibe_home._LEGACY_RIG_RELAY_HOME",
        tmp_path / ".rig-relay-mock",
    )
    monkeypatch.setattr(
        "rig_relay.core.paths._vibe_home._LEGACY_VIBE_HOME", tmp_path / ".vibe-mock"
    )

    init_harness_files_manager("user")

    yield config_dir

    reset_harness_files_manager()


@pytest.fixture(autouse=True)
def _mock_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "mock")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "mock")


@pytest.fixture(autouse=True)
def _mock_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("SHELL", "/bin/sh")


@pytest.fixture(autouse=True)
def _ensure_unlocked_test_profile(tmp_path_factory: pytest.TempPathFactory) -> Generator[None, None, None]:
    """Create unlocked profile so capability gate allows intents in all tests."""
    from rig_relay.governance.service_state import (
        ProfileStore,
        set_profile_store_override,
    )

    profile_root = tmp_path_factory.mktemp("test_profile")
    store = ProfileStore(root=profile_root)
    store.create_first_launch_profile()
    store.unlock()
    set_profile_store_override(store)
    yield
    set_profile_store_override(None)


@pytest.fixture(autouse=True)
def telemetry_events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def record_telemetry(
        self: Any,
        event_name: str,
        properties: dict[str, Any],
        *,
        correlation_id: str | None = None,
        receipt_candidate: bool = False,
    ) -> None:
        merged = self.build_client_event_metadata() | properties
        event: dict[str, Any] = {"event_name": event_name, "properties": merged}
        if correlation_id is not None:
            event["correlation_id"] = correlation_id
        event["receipt_candidate"] = receipt_candidate
        events.append(event)

    monkeypatch.setattr(
        "rig_relay.core.telemetry.send.TelemetryClient.send_telemetry_event",
        record_telemetry,
    )
    return events


@pytest.fixture
def vibe_config() -> VibeConfig:
    return build_test_vibe_config()


@pytest.fixture
def agent_loop() -> AgentLoop:
    return build_test_agent_loop()


def make_test_models(auto_compact_threshold: int) -> list[ModelConfig]:
    return [
        m.model_copy(update={"auto_compact_threshold": auto_compact_threshold})
        for m in DEFAULT_MODELS
    ]


def build_test_vibe_config(**kwargs) -> VibeConfig:
    session_logging = kwargs.pop("session_logging", None)
    resolved_session_logging = (
        SessionLoggingConfig(enabled=False)
        if session_logging is None
        else session_logging
    )
    enable_update_checks = kwargs.pop("enable_update_checks", None)
    resolved_enable_update_checks = (
        False if enable_update_checks is None else enable_update_checks
    )
    if kwargs.get("models"):
        kwargs.setdefault("active_model", kwargs["models"][0].alias)
    return VibeConfig(
        session_logging=resolved_session_logging,
        enable_update_checks=resolved_enable_update_checks,
        **kwargs,
    )


def build_test_agent_loop(
    *,
    config: VibeConfig | None = None,
    agent_name: str = BuiltinAgentName.DEFAULT,
    backend: BackendLike | None = None,
    enable_streaming: bool = False,
    **kwargs,
) -> AgentLoop:

    resolved_config = config or build_test_vibe_config()

    return AgentLoop(
        config=resolved_config,
        agent_name=agent_name,
        backend=backend or FakeBackend(),
        enable_streaming=enable_streaming,
        **kwargs,
    )
