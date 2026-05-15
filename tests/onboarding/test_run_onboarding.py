from __future__ import annotations

from rig_relay.setup import onboarding
from rig_relay.setup.onboarding.screens import api_key, welcome


class TestWelcomeScreen:
    def test_returns_continue_on_enter(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda: "")
        result = welcome.show_welcome()
        assert result == "continue"

    def test_returns_none_on_skip(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda: "skip")
        result = welcome.show_welcome()
        assert result is None

    def test_returns_continue_on_other_input(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda: "hello")
        result = welcome.show_welcome()
        assert result == "continue"


class TestApiKeyScreen:
    def test_returns_none_on_skip(self, monkeypatch):
        monkeypatch.setattr(api_key, "show_provider_picker", lambda: None)
        result = api_key.run_api_key_screen()
        assert result is None

    def test_returns_provider_selected_for_llamacpp(self, monkeypatch):
        monkeypatch.setattr(
            api_key,
            "show_provider_picker",
            lambda: {
                "slug": "llamacpp",
                "env_var": "",
                "display": "Local",
                "key_url": "",
                "key_label": "",
            },
        )
        result = api_key.run_api_key_screen()
        assert result == "provider_selected:llamacpp"


class TestOnboarding:
    def test_returns_false_on_skip(self, monkeypatch):
        monkeypatch.setattr(onboarding, "show_welcome", lambda: None)
        result = onboarding.run_onboarding()
        assert result is False

    def test_returns_false_on_provider_skip(self, monkeypatch):
        monkeypatch.setattr(onboarding, "show_welcome", lambda: "continue")
        monkeypatch.setattr(onboarding, "run_api_key_screen", lambda: None)
        result = onboarding.run_onboarding()
        assert result is False

    def test_returns_true_on_completed(self, monkeypatch):
        monkeypatch.setattr(onboarding, "show_welcome", lambda: "continue")
        monkeypatch.setattr(
            onboarding,
            "run_api_key_screen",
            lambda: "completed:deepseek:DEEPSEEK_API_KEY",
        )
        result = onboarding.run_onboarding()
        assert result is True

    def test_returns_true_on_save_error(self, monkeypatch):
        monkeypatch.setattr(onboarding, "show_welcome", lambda: "continue")
        monkeypatch.setattr(
            onboarding, "run_api_key_screen", lambda: "save_error:disk full"
        )
        result = onboarding.run_onboarding()
        assert result is True

    def test_returns_false_on_unknown_result(self, monkeypatch):
        monkeypatch.setattr(onboarding, "show_welcome", lambda: "continue")
        monkeypatch.setattr(onboarding, "run_api_key_screen", lambda: "weird_result")
        result = onboarding.run_onboarding()
        assert result is False
