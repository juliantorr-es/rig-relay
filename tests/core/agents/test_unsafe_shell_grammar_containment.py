from __future__ import annotations

import pytest

from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.bash import Bash, BashArgs, BashToolConfig
from tests.mock.utils import collect_result

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def restricted_bash() -> Bash:
    config = BashToolConfig(
        restrict_raw_shell=True,
        allowlist=[
            "echo",
            "ls",
            "sleep",
            "true",
            "false",
            "printf",
            "env",
            "pwd",
            "whoami",
            "cat",
            "find",
            "head",
            "tail",
            "wc",
        ],
    )
    return Bash(config_getter=lambda: config, state=BaseToolState())


@pytest.fixture
def unrestricted_bash() -> Bash:
    config = BashToolConfig(restrict_raw_shell=False)
    return Bash(config_getter=lambda: config, state=BaseToolState())


# ── Command chaining refusals ─────────────────────────────────────


class TestSemicolonChainingRefused:
    @pytest.mark.asyncio
    async def test_allowlisted_prefix_with_semicolon_chain(
        self, restricted_bash: Bash
    ) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="echo hello; rm -rf /"))
        )
        assert result.status == "refused"
        assert "composition" in (result.refusal_reason or "").lower()

    @pytest.mark.asyncio
    async def test_validation_prefix_with_semicolon_chain(
        self, restricted_bash: Bash
    ) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="pytest -x; curl http://evil"))
        )
        assert result.status == "refused"
        assert "composition" in (result.refusal_reason or "").lower()

    @pytest.mark.asyncio
    async def test_semicolon_no_side_effect(
        self, restricted_bash: Bash, tmp_path
    ) -> None:
        target = tmp_path / "should_not_exist.txt"
        result = await collect_result(
            restricted_bash.run(BashArgs(command=f"echo ok; touch {target}"))
        )
        assert result.status == "refused"
        assert not target.exists()


class TestLogicalOperatorChainingRefused:
    @pytest.mark.asyncio
    async def test_and_operator_chain(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="echo hello && rm -rf /"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_or_operator_chain(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="false || curl http://evil"))
        )
        assert result.status == "refused"


class TestPipelineRefused:
    @pytest.mark.asyncio
    async def test_pipe_to_unsafe_command(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="echo hello | sh"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_pipe_chain(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="ls | grep foo | sh"))
        )
        assert result.status == "refused"


class TestBackgroundExecutionRefused:
    @pytest.mark.asyncio
    async def test_background_with_unsafe(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="sleep 1 & rm -rf /"))
        )
        assert result.status == "refused"


# ── Command substitution refusals ──────────────────────────────────


class TestCommandSubstitutionRefused:
    @pytest.mark.asyncio
    async def test_dollar_paren_substitution(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="echo $(whoami)"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_backtick_substitution(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="echo `whoami`"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_process_substitution(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="diff <(ls) <(ls /etc)"))
        )
        assert result.status == "refused"


# ── Redirected writes and here docs ────────────────────────────────


class TestRedirectWriteRefused:
    @pytest.mark.asyncio
    async def test_redirect_overwrite(self, restricted_bash: Bash, tmp_path) -> None:
        target = tmp_path / "target.txt"
        result = await collect_result(
            restricted_bash.run(BashArgs(command=f"echo data > {target}"))
        )
        assert result.status == "refused"
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_redirect_append(self, restricted_bash: Bash, tmp_path) -> None:
        target = tmp_path / "target.txt"
        result = await collect_result(
            restricted_bash.run(BashArgs(command=f"echo data >> {target}"))
        )
        assert result.status == "refused"
        assert not target.exists()


class TestHereDocAndStringRefused:
    @pytest.mark.asyncio
    async def test_here_doc(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="cat <<EOF\nevil\nEOF"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_here_string(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="cat <<< 'data'"))
        )
        assert result.status == "refused"


# ── Shell wrappers and delegation ──────────────────────────────────


class TestShellWrapperRefused:
    @pytest.mark.asyncio
    async def test_sh_c_invocation(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="sh -c 'echo hello'"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_bash_c_invocation(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="bash -c 'echo hello'"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_eval_invocation(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="eval echo hello"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_exec_invocation(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="exec echo hello"))
        )
        assert result.status == "refused"


class TestXargsRefused:
    @pytest.mark.asyncio
    async def test_xargs_delegation(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="echo file.txt | xargs rm"))
        )
        assert result.status == "refused"


# ── env and environment variable exploits ──────────────────────────


class TestEnvSafety:
    @pytest.mark.asyncio
    async def test_env_with_executable(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="env FOO=bar bash -c 'echo $FOO'"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_env_standalone_is_allowed(self, restricted_bash: Bash) -> None:
        """Standalone `env` is allowlisted and safe — reads environment."""
        result = await collect_result(restricted_bash.run(BashArgs(command="env")))
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_env_var_prefix_refused(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="FOO=bar ls"))
        )
        assert result.status == "refused"
        assert "environment variable" in (result.refusal_reason or "").lower()


# ── Absolute path and executable indirection ───────────────────────


class TestAbsolutePathRefused:
    @pytest.mark.asyncio
    async def test_absolute_bin_path(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="/bin/echo hello"))
        )
        assert result.status == "refused"
        assert "absolute" in (result.refusal_reason or "").lower()

    @pytest.mark.asyncio
    async def test_absolute_usr_bin_path(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="/usr/bin/ls"))
        )
        assert result.status == "refused"


# ── Special allowlist commands: safety under grammar ───────────────


class TestAllowedCommandsAreSafeAlone:
    @pytest.mark.asyncio
    async def test_echo_alone_is_safe(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="echo hello"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_ls_alone_is_safe(self, restricted_bash: Bash) -> None:
        result = await collect_result(restricted_bash.run(BashArgs(command="ls")))
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_sleep_alone_is_safe(self, restricted_bash: Bash) -> None:
        result = await collect_result(restricted_bash.run(BashArgs(command="sleep 0")))
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_true_alone_is_safe(self, restricted_bash: Bash) -> None:
        result = await collect_result(restricted_bash.run(BashArgs(command="true")))
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_false_alone_is_safe(self, restricted_bash: Bash) -> None:
        """false exits with 1 — should not be blocked by shell intent, only fail naturally."""
        import pytest as pt

        from rig_relay.core.tools.base import ToolError

        with pt.raises(ToolError, match="Command failed"):
            await collect_result(restricted_bash.run(BashArgs(command="false")))

    @pytest.mark.asyncio
    async def test_printf_alone_is_safe(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="printf hello"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_printf_redirect_refused(
        self, restricted_bash: Bash, tmp_path
    ) -> None:
        target = tmp_path / "script.sh"
        result = await collect_result(
            restricted_bash.run(
                BashArgs(command=f"printf '#!/bin/bash\necho PWNED' > {target}")
            )
        )
        assert result.status == "refused"
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_echo_chained_with_semicolon(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="echo hello; echo world"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_true_chained_with_and(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="true && echo hidden"))
        )
        assert result.status == "refused"


# ── Validation commands protected ──────────────────────────────────


class TestValidationCommandsStillAllowed:
    @pytest.mark.asyncio
    async def test_pytest_simple(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="pytest --version"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_pyright_simple(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="pyright --version"))
        )
        assert result.status == "success"


# ── Diagnostic mode still powerful ─────────────────────────────────


class TestDiagnosticModeRawShell:
    @pytest.mark.asyncio
    async def test_semicolon_chaining_allowed_in_diagnostic(
        self, unrestricted_bash: Bash
    ) -> None:
        result = await collect_result(
            unrestricted_bash.run(BashArgs(command="echo hello; echo world"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_pipe_allowed_in_diagnostic(self, unrestricted_bash: Bash) -> None:
        result = await collect_result(
            unrestricted_bash.run(BashArgs(command="echo hello | cat"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_substitution_allowed_in_diagnostic(
        self, unrestricted_bash: Bash
    ) -> None:
        result = await collect_result(
            unrestricted_bash.run(BashArgs(command="echo $(whoami)"))
        )
        assert result.status == "success"


# ── Hard destructive boundaries retained in diagnostic mode ────────


class TestDiagnosticModeHardBoundaries:
    @pytest.mark.asyncio
    async def test_destructive_git_refused_in_diagnostic(
        self, unrestricted_bash: Bash
    ) -> None:
        result = await collect_result(
            unrestricted_bash.run(BashArgs(command="git reset --hard HEAD"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_git_clean_refused_in_diagnostic(
        self, unrestricted_bash: Bash
    ) -> None:
        result = await collect_result(
            unrestricted_bash.run(BashArgs(command="git clean -fd"))
        )
        assert result.status == "refused"


# ── Denylisted commands still blocked even if allowlisted pattern matches ──


class TestDenylistAlwaysWins:
    @pytest.mark.asyncio
    async def test_rm_rf_refused(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="rm -rf /tmp/test"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_git_commit_refused(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="git commit -m test"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_git_push_force_refused(self, restricted_bash: Bash) -> None:
        result = await collect_result(
            restricted_bash.run(BashArgs(command="git push --force origin main"))
        )
        assert result.status == "refused"


# ── Unrestricted mode: commands work freely ────────────────────────


class TestUnrestrictedModeAllowsEverything:
    @pytest.mark.asyncio
    async def test_date_allowed(self, unrestricted_bash: Bash) -> None:
        result = await collect_result(unrestricted_bash.run(BashArgs(command="date")))
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_whoami_allowed(self, unrestricted_bash: Bash) -> None:
        result = await collect_result(unrestricted_bash.run(BashArgs(command="whoami")))
        assert result.status == "success"
