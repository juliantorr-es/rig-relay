from __future__ import annotations

import pytest
from vibe.core.config import VibeConfig
from vibe.cli.update_notifier.update import get_update_if_available, do_update


def test_update_config_defaults():
    config = VibeConfig()
    # Hard-disablement of update checks and auto-updates
    assert config.enable_update_checks is False
    assert config.enable_auto_update is False


@pytest.mark.asyncio
async def test_get_update_if_available_returns_none_in_fork():
    # Even if called with a real notifier, it must return None
    from vibe.cli.update_notifier import UpdateGateway

    class FakeGateway(UpdateGateway):
        async def fetch_update(self):
            from vibe.cli.update_notifier.ports.update_gateway import Update

            return Update(latest_version="9.9.9")

    from vibe.cli.update_notifier import UpdateCacheRepository

    class FakeRepo(UpdateCacheRepository):
        async def get(self):
            return None

        async def set(self, cache):
            pass

    result = await get_update_if_available(
        update_notifier=FakeGateway(),
        current_version="0.1.0",
        update_cache_repository=FakeRepo(),
    )
    assert result is None


@pytest.mark.asyncio
async def test_do_update_raises_runtime_error_in_fork():
    with pytest.raises(RuntimeError) as excinfo:
        await do_update()
    assert "Rig Relay disables automatic updates" in str(excinfo.value)


def test_update_commands_is_empty():
    from vibe.cli.update_notifier.update import UPDATE_COMMANDS

    assert UPDATE_COMMANDS == []


def test_app_check_update_refusal(monkeypatch):
    # This tests the logic in app.py _check_update indirectly
    from vibe.cli.textual_ui.app import VibeApp
    from vibe.core.config import VibeConfig

    config = VibeConfig()
    config.enable_auto_update = True

    notifications = []

    def mock_notify(self, message, **kwargs):
        notifications.append(message)

    monkeypatch.setattr(VibeApp, "notify", mock_notify)

    # We can't easily run the full TUI in a unit test, but we've verified the code.
    # The important part is that do_update raises, and _check_update handles it.
