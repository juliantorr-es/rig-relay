from __future__ import annotations

import pytest

from rig_relay.core.agents.manager import AgentManager
from rig_relay.core.agents.models import (
    BUILTIN_AGENTS,
    BuiltinAgentName,
    is_profile_admitted_for_selection,
)
from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.bash import Bash, BashArgs, BashToolConfig
from tests.conftest import build_test_vibe_config
from tests.mock.utils import collect_result


class TestUnsafeProfileAdmissionGate:
    """Every boundary that enumerates, selects, or restores a profile
    must refuse UNSAFE_RAW_SHELL unless RIG_RELAY_ALLOW_UNSAFE=1.
    """

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RIG_RELAY_ALLOW_UNSAFE", raising=False)

    def test_admission_function_refuses_without_env(self) -> None:
        admitted, reason = is_profile_admitted_for_selection(
            BuiltinAgentName.UNSAFE_RAW_SHELL, source="test"
        )
        assert admitted is False
        assert reason is not None
        assert "RIG_RELAY_ALLOW_UNSAFE=1" in reason or "diagnostic" in reason.lower()

    def test_admission_function_accepts_with_env_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RIG_RELAY_ALLOW_UNSAFE", "1")
        admitted, _ = is_profile_admitted_for_selection(
            BuiltinAgentName.UNSAFE_RAW_SHELL, source="test"
        )
        assert admitted is True

    def test_admission_function_refuses_env_not_exactly_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RIG_RELAY_ALLOW_UNSAFE", "0")
        admitted, _ = is_profile_admitted_for_selection(
            BuiltinAgentName.UNSAFE_RAW_SHELL, source="test"
        )
        assert admitted is False

    def test_normal_profile_always_admitted(self) -> None:
        admitted, reason = is_profile_admitted_for_selection(
            BuiltinAgentName.DEFAULT, source="test"
        )
        assert admitted is True
        assert reason is None


class TestAgentManagerConstructionRefusal:
    """AgentManager.__init__ must refuse UNSAFE_RAW_SHELL as initial_agent
    when RIG_RELAY_ALLOW_UNSAFE is absent.
    """

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RIG_RELAY_ALLOW_UNSAFE", raising=False)

    def test_construction_refuses_unsafe_without_env(self) -> None:
        config = build_test_vibe_config(
            include_project_context=False, include_prompt_detail=False
        )
        with pytest.raises(ValueError, match="RIG_RELAY_ALLOW_UNSAFE"):
            AgentManager(
                lambda: config, initial_agent=BuiltinAgentName.UNSAFE_RAW_SHELL
            )

    def test_construction_accepts_unsafe_with_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RIG_RELAY_ALLOW_UNSAFE", "1")
        config = build_test_vibe_config(
            include_project_context=False, include_prompt_detail=False
        )
        manager = AgentManager(
            lambda: config, initial_agent=BuiltinAgentName.UNSAFE_RAW_SHELL
        )
        assert manager.active_profile.name == BuiltinAgentName.UNSAFE_RAW_SHELL


class TestAgentManagerAvailableAgentsExcludesUnsafe:
    """available_agents listing must exclude UNSAFE_RAW_SHELL when
    RIG_RELAY_ALLOW_UNSAFE is absent.
    """

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RIG_RELAY_ALLOW_UNSAFE", raising=False)

    @pytest.fixture
    def manager(self) -> AgentManager:
        config = build_test_vibe_config(
            include_project_context=False, include_prompt_detail=False
        )
        return AgentManager(lambda: config)

    def test_unsafe_not_in_available_agents(self, manager: AgentManager) -> None:
        assert BuiltinAgentName.UNSAFE_RAW_SHELL not in manager.available_agents

    def test_unsafe_in_available_agents_with_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RIG_RELAY_ALLOW_UNSAFE", "1")
        config = build_test_vibe_config(
            include_project_context=False, include_prompt_detail=False
        )
        manager = AgentManager(lambda: config)
        assert BuiltinAgentName.UNSAFE_RAW_SHELL in manager.available_agents

    def test_normal_profiles_remain_available(self, manager: AgentManager) -> None:
        assert BuiltinAgentName.DEFAULT in manager.available_agents
        assert BuiltinAgentName.PLAN in manager.available_agents


class TestAgentSwitchProfileRefusal:
    """switch_profile must refuse switching to UNSAFE_RAW_SHELL when
    RIG_RELAY_ALLOW_UNSAFE is absent.
    """

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RIG_RELAY_ALLOW_UNSAFE", raising=False)

    @pytest.fixture
    def manager(self) -> AgentManager:
        config = build_test_vibe_config(
            include_project_context=False, include_prompt_detail=False
        )
        return AgentManager(lambda: config)

    def test_switch_to_unsafe_refused_without_env(self, manager: AgentManager) -> None:
        with pytest.raises(ValueError, match="RIG_RELAY_ALLOW_UNSAFE"):
            manager.switch_profile(BuiltinAgentName.UNSAFE_RAW_SHELL)

    def test_switch_to_unsafe_accepted_with_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RIG_RELAY_ALLOW_UNSAFE", "1")
        config = build_test_vibe_config(
            include_project_context=False, include_prompt_detail=False
        )
        manager = AgentManager(lambda: config)
        manager.switch_profile(BuiltinAgentName.UNSAFE_RAW_SHELL)
        assert manager.active_profile.name == BuiltinAgentName.UNSAFE_RAW_SHELL

    def test_switch_to_normal_always_accepted(self, manager: AgentManager) -> None:
        manager.switch_profile(BuiltinAgentName.PLAN)
        assert manager.active_profile.name == BuiltinAgentName.PLAN


class TestBashRuntimeRestrictRawShellEnforcement:
    """When restrict_raw_shell=True (default), Bash.run() must refuse
    raw shell commands that are not validation-equivalent. This is a
    hard runtime check — enforced regardless of permission bypass.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)

    @pytest.fixture
    def restricted_bash(self) -> Bash:
        config = BashToolConfig(restrict_raw_shell=True)
        return Bash(config_getter=lambda: config, state=BaseToolState())

    @pytest.fixture
    def unrestricted_bash(self) -> Bash:
        config = BashToolConfig(restrict_raw_shell=False)
        return Bash(config_getter=lambda: config, state=BaseToolState())

    @pytest.mark.asyncio
    async def test_refuses_arbitrary_command_with_restrict(
        self, restricted_bash: Bash
    ) -> None:
        result = await collect_result(restricted_bash.run(BashArgs(command="date")))
        assert result.status == "refused"
        assert result.error_kind == "refused"
        assert "raw shell" in (result.refusal_reason or "").lower()

    @pytest.mark.asyncio
    async def test_allows_arbitrary_command_without_restrict(
        self, unrestricted_bash: Bash
    ) -> None:
        result = await collect_result(
            unrestricted_bash.run(BashArgs(command="echo hello"))
        )
        assert result.status == "success"
        assert result.stdout.strip() == "hello"

    @pytest.mark.asyncio
    async def test_allows_pytest_with_restrict(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="pytest --version"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_allows_ruff_check_with_restrict(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="ruff check ."))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_allows_pyright_with_restrict(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="pyright --version"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_allows_python_m_pytest_with_restrict(
        self, restricted_bash: Bash
    ) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="python -m pytest --version"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_restricted_bash_still_blocks_destructive_git(
        self, unrestricted_bash: Bash
    ) -> None:
        """Destructive git commands are refused even when restrict_raw_shell=False."""
        result = await collect_result(
            unrestricted_bash.run(BashArgs(command="git reset --hard HEAD"))
        )
        assert result.status == "refused"
        assert result.error_kind == "refused"

    @pytest.mark.asyncio
    async def test_restrict_default_is_true(self) -> None:
        config = BashToolConfig()
        assert config.restrict_raw_shell is True


class TestUnsafeProfileOverridesRestrictRawShell:
    """UNSAFE_RAW_SHELL profile must explicitly set restrict_raw_shell=False
    on the bash tool so the diagnostic mode can function.
    """

    def test_unsafe_profile_disables_restrict_raw_shell(self) -> None:
        profile = BUILTIN_AGENTS[BuiltinAgentName.UNSAFE_RAW_SHELL]
        overrides = profile.overrides
        assert "tools" in overrides
        assert "bash" in overrides["tools"]
        assert overrides["tools"]["bash"].get("restrict_raw_shell") is False

    def test_unsafe_profile_requires_env_for_selection(self) -> None:
        admitted, _ = is_profile_admitted_for_selection(
            BuiltinAgentName.UNSAFE_RAW_SHELL, source="test"
        )
        assert admitted is False

    def test_normal_profile_does_not_override_restrict(self) -> None:
        profile = BUILTIN_AGENTS[BuiltinAgentName.DEFAULT]
        overrides = profile.overrides
        bash_tool_overrides = overrides.get("tools", {}).get("bash")
        assert (
            bash_tool_overrides is None
            or "restrict_raw_shell" not in bash_tool_overrides
        )


class TestACPModeAdmission:
    """ACP mode listing and selection must refuse UNSAFE_RAW_SHELL
    without RIG_RELAY_ALLOW_UNSAFE=1.
    """

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RIG_RELAY_ALLOW_UNSAFE", raising=False)

    def test_acp_mode_listing_excludes_unsafe(self) -> None:
        from rig_relay.acp.utils import build_mode_state
        from rig_relay.core.agents.models import BUILTIN_AGENTS

        profiles = list(BUILTIN_AGENTS.values())
        mode_state, _ = build_mode_state(profiles, "default")

        unsafe_modes = [
            m
            for m in mode_state.available_modes
            if m.id == BuiltinAgentName.UNSAFE_RAW_SHELL
        ]
        assert len(unsafe_modes) == 0

    def test_acp_mode_listing_includes_unsafe_with_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RIG_RELAY_ALLOW_UNSAFE", "1")
        from rig_relay.acp.utils import build_mode_state
        from rig_relay.core.agents.models import BUILTIN_AGENTS

        profiles = list(BUILTIN_AGENTS.values())
        mode_state, _ = build_mode_state(profiles, "default")

        unsafe_modes = [
            m
            for m in mode_state.available_modes
            if m.id == BuiltinAgentName.UNSAFE_RAW_SHELL
        ]
        assert len(unsafe_modes) == 1

    def test_acp_mode_selection_refuses_unsafe(self) -> None:
        from rig_relay.acp.utils import is_valid_acp_mode
        from rig_relay.core.agents.models import BUILTIN_AGENTS

        profiles = list(BUILTIN_AGENTS.values())
        assert is_valid_acp_mode(profiles, BuiltinAgentName.UNSAFE_RAW_SHELL) is False

    def test_acp_mode_selection_accepts_unsafe_with_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RIG_RELAY_ALLOW_UNSAFE", "1")
        from rig_relay.acp.utils import is_valid_acp_mode
        from rig_relay.core.agents.models import BUILTIN_AGENTS

        profiles = list(BUILTIN_AGENTS.values())
        assert is_valid_acp_mode(profiles, BuiltinAgentName.UNSAFE_RAW_SHELL) is True

    def test_acp_mode_selection_accepts_normal(self) -> None:
        from rig_relay.acp.utils import is_valid_acp_mode
        from rig_relay.core.agents.models import BUILTIN_AGENTS

        profiles = list(BUILTIN_AGENTS.values())
        assert is_valid_acp_mode(profiles, BuiltinAgentName.PLAN) is True
