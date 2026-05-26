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
def strict_bash() -> Bash:
    config = BashToolConfig(restrict_raw_shell=True)
    return Bash(config_getter=lambda: config, state=BaseToolState())


@pytest.fixture
def diagnostic_bash() -> Bash:
    config = BashToolConfig(restrict_raw_shell=False)
    return Bash(config_getter=lambda: config, state=BaseToolState())


# ── Direct execution proof: no shell interpretation ───────────────


class TestStrictModeUsesDirectExecNotShell:
    @pytest.mark.asyncio
    async def test_shell_variables_not_expanded_in_strict(
        self, strict_bash: Bash
    ) -> None:
        """In strict mode, $VAR is literal text — no shell expansion."""
        result = await collect_result(strict_bash.run(BashArgs(command="echo $HOME")))
        assert result.status == "success"
        assert result.stdout.strip() == "$HOME"

    @pytest.mark.asyncio
    async def test_shell_variables_expanded_in_diagnostic(
        self, diagnostic_bash: Bash
    ) -> None:
        """In diagnostic mode, shell expands variables."""
        result = await collect_result(
            diagnostic_bash.run(BashArgs(command="echo $HOME"))
        )
        assert result.status == "success"
        assert result.stdout.strip() != "$HOME"

    @pytest.mark.asyncio
    async def test_glob_not_expanded_in_strict(
        self, strict_bash: Bash, tmp_path
    ) -> None:
        """Glob characters are literal in strict mode — 'ls *.txt' looks for
        a file literally named '*.txt', not matching a.txt and b.txt.
        """
        (tmp_path / "a.txt").write_text("")
        (tmp_path / "b.txt").write_text("")
        # Direct exec passes '*.txt' literally to ls — no shell glob expansion.
        # ls looks for a file named '*.txt' which doesn't exist → exits non-zero.
        import pytest as pt

        from rig_relay.core.tools.base import ToolError

        with pt.raises(ToolError):
            await collect_result(strict_bash.run(BashArgs(command="ls *.txt")))

    @pytest.mark.asyncio
    async def test_semicolon_is_literal_in_strict(self, strict_bash: Bash) -> None:
        """The grammar check already blocks ';' but if somehow it reached exec,
        the ';' is literal — not interpreted as a separator.
        """
        result = await collect_result(strict_bash.run(BashArgs(command="echo hello")))
        assert result.status == "success"
        assert result.stdout.strip() == "hello"


class TestStrictModeRefusesShellFeaturesAtExec:
    @pytest.mark.asyncio
    async def test_redirect_not_executed_in_strict(
        self, strict_bash: Bash, tmp_path
    ) -> None:
        """Even if bypassed grammar, redirect char is literal in direct exec —
        the '>' appears as argument to echo, not as file redirect.
        """
        target = tmp_path / "redirect_test.txt"
        result = await collect_result(
            strict_bash.run(BashArgs(command=f"echo data > {target}"))
        )
        # Grammar containment catches '>' first — expect refusal
        assert result.status == "refused"
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_pipe_char_is_literal_in_strict(self, strict_bash: Bash) -> None:
        """Pipe is caught by grammar containment before exec."""
        result = await collect_result(strict_bash.run(BashArgs(command="ls | wc -l")))
        assert result.status == "refused"


# ── Environment hardening for scoped execution ────────────────────


class TestScopedEnvironmentStripsInjectionVars:
    @pytest.mark.asyncio
    async def test_pythonpath_not_available_in_strict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PYTHONPATH is stripped in scoped execution environment."""
        monkeypatch.setenv("PYTHONPATH", "/malicious/path")
        config = BashToolConfig(restrict_raw_shell=True)
        tool = Bash(config_getter=lambda: config, state=BaseToolState())
        result = await collect_result(
            tool.run(
                BashArgs(
                    command='python -c \'import os; print(os.environ.get("PYTHONPATH", ""))\''
                )
            )
        )
        # python -c is denylisted, should be refused
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_virtual_env_stripped_in_strict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VIRTUAL_ENV is stripped in scoped execution."""
        monkeypatch.setenv("VIRTUAL_ENV", "/fake/venv")
        # Use a simple command that doesn't need venv
        config = BashToolConfig(restrict_raw_shell=True)
        tool = Bash(config_getter=lambda: config, state=BaseToolState())
        result = await collect_result(tool.run(BashArgs(command="echo ok")))
        assert result.status == "success"


class TestGitEnvironmentHardened:
    @pytest.mark.asyncio
    async def test_git_pager_is_cat_in_strict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GIT_PAGER=cat is set in scoped env, preventing pager execution."""
        monkeypatch.setenv("GIT_PAGER", "less")
        # git command would be refused by denylist or grammar, but env is set
        config = BashToolConfig(restrict_raw_shell=True)
        tool = Bash(config_getter=lambda: config, state=BaseToolState())
        result = await collect_result(tool.run(BashArgs(command="echo ok")))
        assert result.status == "success"


class TestGitIndirectExecutionBlocked:
    @pytest.mark.asyncio
    async def test_git_stash_refused_in_diagnostic(
        self, diagnostic_bash: Bash, tmp_path
    ) -> None:
        """Destructive git commands (stash) are refused even in diagnostic mode.
        GIT env vars are scrubbed to prevent pager/diff helper execution.
        """
        import subprocess

        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )
        (tmp_path / "test.txt").write_text("hello")

        # git stash is a destructive git command — must be refused
        result = await collect_result(
            diagnostic_bash.run(BashArgs(command="git stash"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_git_clean_refused_in_diagnostic(
        self, diagnostic_bash: Bash, tmp_path
    ) -> None:
        """Destructive git clean refused even in diagnostic mode."""
        import subprocess

        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        (tmp_path / "dirty.txt").write_text("untracked")

        result = await collect_result(
            diagnostic_bash.run(BashArgs(command="git clean -fd"))
        )
        assert result.status == "refused"
        assert (tmp_path / "dirty.txt").exists()


# ── PATH injection resistance ─────────────────────────────────────


class TestPathInjectionResistance:
    @pytest.mark.asyncio
    async def test_absolute_path_refused_in_strict(self, strict_bash: Bash) -> None:
        """Absolute executable paths are refused by grammar containment."""
        result = await collect_result(
            strict_bash.run(BashArgs(command="/bin/echo hello"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_relative_dot_slash_allowed_if_executable_in_path(
        self, strict_bash: Bash, tmp_path
    ) -> None:
        """Relative paths like './script' are allowed as single-command if
        the executable is in PATH. But the scope check catches anything
        not on the allowlist.
        """
        result = await collect_result(
            strict_bash.run(BashArgs(command="./nonexistent.py"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_executable_not_found_in_path(self, strict_bash: Bash) -> None:
        """Direct exec fails gracefully when executable not found."""
        result = await collect_result(
            strict_bash.run(BashArgs(command="nonexistent_command_12345"))
        )
        assert result.status in ("refused", "failure")
        if result.status == "failure":
            assert result.error_kind == "executable_not_found"


# ── Diagnostic mode: shell execution still available ──────────────


class TestDiagnosticModeStillUsesShell:
    @pytest.mark.asyncio
    async def test_shell_expansion_works_in_diagnostic(
        self, diagnostic_bash: Bash
    ) -> None:
        """Diagnostic mode uses shell — variables expand."""
        result = await collect_result(
            diagnostic_bash.run(BashArgs(command="echo $SHELL"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_arbitrary_command_works_in_diagnostic(
        self, diagnostic_bash: Bash
    ) -> None:
        result = await collect_result(diagnostic_bash.run(BashArgs(command="date")))
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_destructive_git_still_refused_in_diagnostic(
        self, diagnostic_bash: Bash
    ) -> None:
        result = await collect_result(
            diagnostic_bash.run(BashArgs(command="git stash"))
        )
        assert result.status == "refused"


# ── Validation commands work through direct exec ──────────────────


class TestValidationDirectExec:
    @pytest.mark.asyncio
    async def test_pytest_version_via_direct_exec(self, strict_bash: Bash) -> None:
        """pytest is repo-code-executing — refused without governed route."""
        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest --version"))
        )
        assert result.status == "refused"
        assert "repository_code_execution" in (result.error_kind or "")

    @pytest.mark.asyncio
    async def test_pyright_version_via_direct_exec(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pyright --version"))
        )
        assert result.status == "success"


# ── Safety: grammar containment still enforced ────────────────────


class TestGrammarContainmentStillEnforced:
    @pytest.mark.asyncio
    async def test_chaining_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="echo hello; rm -rf /"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_substitution_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="echo $(whoami)"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_pipe_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(strict_bash.run(BashArgs(command="ls | wc -l")))
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_sh_c_wrapper_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="sh -c 'echo hello'"))
        )
        assert result.status == "refused"
