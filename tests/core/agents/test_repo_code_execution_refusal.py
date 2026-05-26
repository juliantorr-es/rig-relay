from __future__ import annotations

import asyncio
import os
import subprocess

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


def _init_git_repo(workspace: str) -> None:
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )


# ── All pytest-family forms refused ───────────────────────────────


class TestAllPytestFormsRefused:
    @pytest.mark.asyncio
    async def test_pytest_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(strict_bash.run(BashArgs(command="pytest")))
        assert result.status == "refused"
        assert (
            result.error_kind
            == "repository_code_execution_requires_governed_validation"
        )

    @pytest.mark.asyncio
    async def test_pytest3_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(strict_bash.run(BashArgs(command="pytest3")))
        assert result.status == "refused"
        assert (
            result.error_kind
            == "repository_code_execution_requires_governed_validation"
        )

    @pytest.mark.asyncio
    async def test_pytest_dash_version_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest --version"))
        )
        assert result.status == "refused"
        assert (
            result.error_kind
            == "repository_code_execution_requires_governed_validation"
        )

    @pytest.mark.asyncio
    async def test_pytest_minus_q_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(strict_bash.run(BashArgs(command="pytest -q")))
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_pytest_test_path_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest tests/test_foo.py"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_pytest_filter_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest -k 'test_foo'"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_python_minus_m_pytest_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="python -m pytest"))
        )
        assert result.status == "refused"
        assert (
            result.error_kind
            == "repository_code_execution_requires_governed_validation"
        )

    @pytest.mark.asyncio
    async def test_python3_minus_m_pytest_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="python3 -m pytest"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_uv_run_pytest_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="uv run pytest"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_uv_run_pytest_version_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="uv run pytest --version"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_uv_run_python_m_pytest_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="uv run python -m pytest"))
        )
        assert result.status == "refused"


# ── Static analysis still works ───────────────────────────────────


class TestStaticAnalysisStillAllowed:
    @pytest.mark.asyncio
    async def test_pyright_version_allowed(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pyright --version"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_ruff_check_allowed(self, strict_bash: Bash) -> None:
        result = await collect_result(strict_bash.run(BashArgs(command="ruff check .")))
        assert result.status == "success"


# ── Bounded utilities still work ──────────────────────────────────


class TestBoundedUtilitiesStillWork:
    @pytest.mark.asyncio
    async def test_echo_allowed(self, strict_bash: Bash) -> None:
        result = await collect_result(strict_bash.run(BashArgs(command="echo hello")))
        assert result.status == "success"
        assert result.stdout.strip() == "hello"

    @pytest.mark.asyncio
    async def test_ls_allowed(self, strict_bash: Bash) -> None:
        result = await collect_result(strict_bash.run(BashArgs(command="ls")))
        assert result.status == "success"


# ── Execution risk truth marker ───────────────────────────────────


class TestExecutionRiskTruthMarker:
    @pytest.mark.asyncio
    async def test_bounded_utility_has_correct_risk_marker(
        self, strict_bash: Bash
    ) -> None:
        result = await collect_result(strict_bash.run(BashArgs(command="echo hello")))
        assert result.execution_risk == Bash.EXECUTION_RISK_BOUNDED_UTILITY

    @pytest.mark.asyncio
    async def test_repo_code_refusal_has_correct_risk_marker(
        self, strict_bash: Bash
    ) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest --version"))
        )
        assert result.execution_risk == Bash.EXECUTION_RISK_REPOSITORY_CODE

    @pytest.mark.asyncio
    async def test_static_analysis_has_correct_risk_marker(
        self, strict_bash: Bash
    ) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pyright --version"))
        )
        assert result.execution_risk == Bash.EXECUTION_RISK_STATIC_ANALYSIS


# ── Diagnostic mode still allows pytest ───────────────────────────


class TestDiagnosticModeAllowsPytest:
    @pytest.mark.asyncio
    async def test_pytest_version_in_diagnostic(self, diagnostic_bash: Bash) -> None:
        result = await collect_result(
            diagnostic_bash.run(BashArgs(command="pytest --version"))
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_uv_run_pytest_in_diagnostic(self, diagnostic_bash: Bash) -> None:
        result = await collect_result(
            diagnostic_bash.run(BashArgs(command="uv run pytest --version"))
        )
        assert result.status == "success"


# ── Adversarial: hostile repository with conftest.py ──────────────


class TestHostileConftestIsNotExecuted:
    """A disposable repository containing a conftest.py that would
    write a sentinel outside the workspace, read from an absolute path,
    connect to a loopback listener, and spawn a descendant.  Strict
    Bash must refuse BEFORE any of these side effects occur.
    """

    _outside_dir: str
    _inside_path: str

    @pytest.fixture(autouse=True)
    def _hostile_repo(self, tmp_path) -> None:
        """Create a hostile disposable repository."""
        workspace = tmp_path / "hostile_repo"
        workspace.mkdir()
        os.chdir(str(workspace))

        outside = tmp_path / "outside_sentinels"
        outside.mkdir()
        self._outside_dir = str(outside)
        self._inside_path = str(workspace)

        _init_git_repo(str(workspace))

        # conftest.py that would create side effects if executed
        sentinel_write = outside / "write_sentinel.txt"
        sentinel_read = outside / "read_sentinel.txt"
        sentinel_read.write_text("secret data")
        evidence = workspace / "read_evidence.txt"
        desc_sentinel = outside / "descendant_sentinel.txt"

        conftest = workspace / "conftest.py"
        conftest.write_text(f'''
import os
import socket
import subprocess
import sys
from pathlib import Path

# 1. Write sentinel outside the workspace
Path("{sentinel_write}").write_text("PWNED by conftest.py")

# 2. Read from an absolute external path and copy evidence back
try:
    data = Path("{sentinel_read}").read_text()
    Path("{evidence}").write_text(data)
except Exception:
    pass

# 3. Connect to loopback listener
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    s.connect(("127.0.0.1", 9999))
    s.send(b"PWNED")
    s.close()
except Exception:
    pass

# 4. Spawn a descendant that writes a sentinel
try:
    child = subprocess.Popen(
        [sys.executable, "-c", f"Path('{desc_sentinel}').write_text('descendant')"],
        start_new_session=True,
    )
except Exception:
    pass

# Define a dummy plugin so pytest doesn't error on bare conftest
def pytest_configure(config):
    pass
''')

    @pytest.mark.asyncio
    async def test_pytest_refused_no_outside_write(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest --collect-only"))
        )
        assert result.status == "refused"
        sentinel = os.path.join(self._outside_dir, "write_sentinel.txt")
        assert not os.path.exists(sentinel), "conftest.py should NOT have executed"

    @pytest.mark.asyncio
    async def test_pytest_refused_no_absolute_read(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest --collect-only"))
        )
        assert result.status == "refused"
        evidence = os.path.join(self._inside_path, "read_evidence.txt")
        assert not os.path.exists(evidence), "conftest.py should NOT have executed"

    @pytest.mark.asyncio
    async def test_pytest_refused_no_loopback_connection(
        self, strict_bash: Bash
    ) -> None:
        """Start a loopback listener, attempt pytest, verify no connection received."""
        received: list[bytes] = []

        async def _listen() -> None:
            server = await asyncio.start_server(
                lambda r, w: received.append(b"connected"), "127.0.0.1", 9999
            )
            async with server:
                try:
                    await asyncio.wait_for(server.serve_forever(), timeout=2.0)
                except (TimeoutError, asyncio.CancelledError):
                    pass

        listen_task = asyncio.create_task(_listen())
        await asyncio.sleep(0.1)

        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest --collect-only"))
        )
        assert result.status == "refused"

        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass

        assert len(received) == 0, "conftest.py should NOT have connected"

    @pytest.mark.asyncio
    async def test_pytest_refused_no_descendant(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest --collect-only"))
        )
        assert result.status == "refused"
        sentinel = os.path.join(self._outside_dir, "descendant_sentinel.txt")
        assert not os.path.exists(sentinel), (
            "conftest.py should NOT have spawned descendant"
        )

    @pytest.mark.asyncio
    async def test_uv_run_pytest_refused_no_side_effects(
        self, strict_bash: Bash
    ) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="uv run pytest --collect-only"))
        )
        assert result.status == "refused"
        sentinel = os.path.join(self._outside_dir, "write_sentinel.txt")
        assert not os.path.exists(sentinel)

    @pytest.mark.asyncio
    async def test_python_m_pytest_refused_no_side_effects(
        self, strict_bash: Bash
    ) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="python -m pytest --collect-only"))
        )
        assert result.status == "refused"
        sentinel = os.path.join(self._outside_dir, "write_sentinel.txt")
        assert not os.path.exists(sentinel)


# ── Grammar containment still enforced ────────────────────────────


class TestGrammarContainmentStillEnforcedForPytestVariants:
    @pytest.mark.asyncio
    async def test_pytest_chained_with_semicolon_refused(
        self, strict_bash: Bash
    ) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest; rm -rf /"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_pytest_with_substitution_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="pytest $(echo test)"))
        )
        assert result.status == "refused"

    @pytest.mark.asyncio
    async def test_pytest_with_env_prefix_refused(self, strict_bash: Bash) -> None:
        result = await collect_result(
            strict_bash.run(BashArgs(command="PYTHONPATH=/evil pytest"))
        )
        assert result.status == "refused"


# ── Diagnostic mode preserves hard boundaries ─────────────────────


class TestDiagnosticHardBoundariesPreserved:
    @pytest.mark.asyncio
    async def test_destructive_git_still_refused(self, diagnostic_bash: Bash) -> None:
        result = await collect_result(
            diagnostic_bash.run(BashArgs(command="git reset --hard HEAD"))
        )
        assert result.status == "refused"
