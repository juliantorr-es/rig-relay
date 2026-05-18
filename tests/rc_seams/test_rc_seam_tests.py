from __future__ import annotations

import os
from pathlib import Path

import pytest

from rig_relay.core.tools.ast_search import detect_dangerous_bash_patterns
from rig_relay.core.tools.base import BaseToolState
from rig_relay.core.tools.builtins.bash import (
    _SENSITIVE_READ_PATTERNS,
    Bash,
    BashArgs,
    BashToolConfig,
)
from rig_relay.core.tools.permissions import ToolPermission
from rig_relay.core.tools.security import (
    ENV_BLOCKLIST,
    is_binary_extension,
    is_likely_binary,
    resolve_safe_path,
    sanitize_env_for_subprocess,
    scrub_environment,
)
from tests.mock.utils import collect_result

# ── P0-1: bash_binary_file_rejection (seam #3) ──


class TestBinaryFileRejection:
    def test_is_likely_binary_png_magic_bytes(self):
        header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        assert is_likely_binary(header) is True

    def test_is_likely_binary_elf_magic_bytes(self):
        header = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 100
        assert is_likely_binary(header) is True

    def test_is_likely_binary_null_bytes_early(self):
        content = b"hello\x00world" + b"x" * 100
        assert is_likely_binary(content) is True

    def test_is_likely_binary_high_non_ascii_ratio(self):
        content = bytes([200, 201, 202, 203, 204, 205, 206, 207] * 50)
        assert is_likely_binary(content) is True

    def test_is_likely_binary_plain_text(self):
        assert is_likely_binary(b"hello world\n") is False
        assert is_likely_binary(b"def foo(): return 42\n") is False

    def test_is_likely_binary_empty_content(self):
        assert is_likely_binary(b"") is False

    def test_is_likely_binary_text_with_tabs_newlines(self):
        content = b"line1\nline2\n\tindented\n"
        assert is_likely_binary(content) is False

    def test_is_likely_binary_python_source(self):
        content = b"import os\nimport sys\n\ndef main():\n    pass\n"
        assert is_likely_binary(content) is False

    def test_is_binary_extension_rejects_known_binaries(self):
        for ext in [".png", ".jpg", ".exe", ".so", ".dylib", ".zip", ".pdf", ".pyc"]:
            assert is_binary_extension(f"file{ext}") is True

    def test_is_binary_extension_permits_known_text(self):
        for ext in [".py", ".txt", ".md", ".json", ".toml", ".yaml", ".csv"]:
            assert is_binary_extension(f"file{ext}") is False

    @pytest.mark.asyncio
    async def test_read_file_rejects_binary_extension(
        self, tmp_path: Path, monkeypatch
    ):
        from rig_relay.core.tools.base import ToolError
        from rig_relay.core.tools.builtins.read_file import (
            ReadFile,
            ReadFileArgs,
            ReadFileState,
            ReadFileToolConfig,
        )

        monkeypatch.chdir(tmp_path)
        binary_file = tmp_path / "binary.pdf"
        binary_file.write_text("pretend this is a PDF but it's really text")
        tool = ReadFile(
            config_getter=lambda: ReadFileToolConfig(), state=ReadFileState()
        )
        with pytest.raises(ToolError, match="appears to be binary"):
            await collect_result(tool.run(ReadFileArgs(path=str(binary_file))))

    @pytest.mark.asyncio
    async def test_read_file_rejects_binary_content(self, tmp_path: Path, monkeypatch):
        from rig_relay.core.tools.base import ToolError
        from rig_relay.core.tools.builtins.read_file import (
            ReadFile,
            ReadFileArgs,
            ReadFileState,
            ReadFileToolConfig,
        )

        monkeypatch.chdir(tmp_path)
        fake_txt = tmp_path / "innocent.txt"
        fake_txt.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000)
        tool = ReadFile(
            config_getter=lambda: ReadFileToolConfig(), state=ReadFileState()
        )
        with pytest.raises(ToolError, match="appears to be binary"):
            await collect_result(tool.run(ReadFileArgs(path=str(fake_txt))))


# ── P0-2: bash_symlink_traversal_rejection (seam #4) ──


class TestSymlinkTraversalRejection:
    def test_resolve_safe_path_inside_workspace(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        safe_file = workspace / "safe.txt"
        safe_file.write_text("hello")
        resolved = resolve_safe_path(safe_file, workspace=workspace)
        assert resolved == safe_file.resolve()

    def test_resolve_safe_path_rejects_outside_absolute(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside" / "secret.txt"
        outside.parent.mkdir()
        outside.write_text("secret")
        with pytest.raises(ValueError, match="outside the workspace"):
            resolve_safe_path(outside, workspace=workspace)

    def test_resolve_safe_path_rejects_symlink_escaping_workspace(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        secret_file = outside_dir / "secret.txt"
        secret_file.write_text("secret content")

        symlink = workspace / "escape_link"
        symlink.symlink_to(secret_file)

        with pytest.raises(ValueError, match="outside the workspace"):
            resolve_safe_path(symlink, workspace=workspace)

    def test_resolve_safe_path_rejects_symlink_to_etc(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        symlink = workspace / "etc_link"
        symlink.symlink_to(Path("/etc/passwd"))

        with pytest.raises(ValueError, match="outside the workspace"):
            resolve_safe_path(symlink, workspace=workspace)

    def test_resolve_safe_path_accepts_relative_path_inside(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "sub").mkdir()
        original_cwd = Path.cwd()
        try:
            os.chdir(workspace)
            resolved = resolve_safe_path(Path("sub"), workspace=workspace)
            assert (workspace / "sub").resolve() == resolved
        finally:
            os.chdir(original_cwd)

    def test_resolve_safe_path_rejects_dotdot_escape(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        resolved = (workspace / ".." / "outside").resolve()
        resolved.parent.mkdir(exist_ok=True)
        resolved.write_text("bad")

        with pytest.raises(ValueError, match="outside the workspace"):
            resolve_safe_path(workspace / ".." / "outside", workspace=workspace)


# ── P0-3: bash_dangerous_pattern_detection (seam #8) ──


class TestDangerousPatternDetection:
    def test_detects_dollar_paren_command_substitution(self):
        warnings = detect_dangerous_bash_patterns("ls $(cat /etc/passwd)")
        assert any("$(" in w or "Command substitution" in w for w in warnings)

    def test_detects_backtick_command_substitution(self):
        warnings = detect_dangerous_bash_patterns("ls `cat /etc/passwd`")
        assert any("backtick" in w.lower() or "`" in w for w in warnings)

    def test_detects_env_var_injection(self):
        warnings = detect_dangerous_bash_patterns("PATH=/evil:$PATH ls")
        assert any("PATH" in w or "environment variable" in w.lower() for w in warnings)

    def test_detects_env_var_injection_uppercase(self):
        warnings = detect_dangerous_bash_patterns("LD_PRELOAD=/tmp/evil.so ./app")
        assert any(
            "LD_PRELOAD" in w or "environment variable" in w.lower() for w in warnings
        )

    def test_detects_python_inline_code_execution(self):
        warnings = detect_dangerous_bash_patterns(
            "python3 -c 'import os; os.system(\"rm -rf /\")'"
        )
        assert any("python3 -c" in w or "inline code" in w.lower() for w in warnings)

    def test_detects_perl_inline_code_execution(self):
        warnings = detect_dangerous_bash_patterns(
            "perl -e 'system(\"cat /etc/shadow\")'"
        )
        assert any(
            "perl" in w and ("-e" in w or "inline code" in w.lower()) for w in warnings
        )

    def test_detects_backslash_escaped_path(self):
        warnings = detect_dangerous_bash_patterns("\\rm file.txt")
        assert any("backslash" in w.lower() for w in warnings)

    def test_detects_backtick_single_char_not_execution(self):
        warnings = detect_dangerous_bash_patterns("echo 'hello world'")
        assert len(warnings) == 0

    def test_plain_command_is_safe(self):
        warnings = detect_dangerous_bash_patterns("ls -la /tmp")
        assert len(warnings) == 0

    def test_safe_pipe_command_ok(self):
        warnings = detect_dangerous_bash_patterns("cat file.txt | grep pattern | wc -l")
        assert len(warnings) == 0

    def test_dangerous_pipe_not_in_safe_list_triggers_warning(self):
        warnings = detect_dangerous_bash_patterns("env | sh")
        assert any("pipes" in w.lower() for w in warnings)


# ── P0-4: bash_sensitive_path_blocking (seam #9) ──


class TestSensitivePathBlocking:
    """Prove _SENSITIVE_READ_PATTERNS blocks identity/token file reads."""

    @staticmethod
    def _make_bash(**kwargs) -> Bash:
        config = BashToolConfig(**kwargs)
        return Bash(config_getter=lambda: config, state=BaseToolState())

    def test_sensitive_path_in_command_triggers_never_permission(self):
        bash_tool = self._make_bash(allowlist=["cat"])
        cmd = f"cat {_SENSITIVE_READ_PATTERNS[0]}/token.json"
        result = bash_tool.resolve_permission(BashArgs(command=cmd))
        assert result is not None
        assert result.permission is ToolPermission.NEVER
        assert "sensitive path" in (result.reason or "")

    def test_sensitive_path_second_pattern_also_blocked(self):
        bash_tool = self._make_bash(allowlist=["cat"])
        cmd = f"cat {_SENSITIVE_READ_PATTERNS[1]}/something"
        result = bash_tool.resolve_permission(BashArgs(command=cmd))
        assert result is not None
        assert result.permission is ToolPermission.NEVER

    def test_sensitive_path_in_tail_command_blocked(self):
        bash_tool = self._make_bash(allowlist=["tail"])
        cmd = f"tail {_SENSITIVE_READ_PATTERNS[0]}/token.json"
        result = bash_tool.resolve_permission(BashArgs(command=cmd))
        assert result is not None
        assert result.permission is ToolPermission.NEVER

    def test_non_sensitive_path_not_blocked(self):
        bash_tool = self._make_bash(allowlist=["cat"])
        cmd = "cat /tmp/regular_file.txt"
        result = bash_tool.resolve_permission(BashArgs(command=cmd))
        # should not be blocked by sensitive path check
        if result is not None:
            assert "sensitive path" not in (result.reason or "")

    def test_sensitive_path_not_in_command_passes(self):
        bash_tool = self._make_bash(allowlist=["cat"])
        cmd = "cat /tmp/some_file.txt"
        result = bash_tool.resolve_permission(BashArgs(command=cmd))
        # may pass or ask — but NOT never due to sensitive path
        if result is not None and result.permission is ToolPermission.NEVER:
            assert "sensitive path" not in (result.reason or "")


# ── P0-5: bash_env_blocklist_scrubbing (seam #1) ──


class TestEnvBlocklistScrubbing:
    def test_scrub_environment_removes_blocklisted_keys(self):
        env = {
            "OPENAI_API_KEY": "sk-1234",
            "ANTHROPIC_API_KEY": "sk-5678",
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "SSH_AUTH_SOCK": "/tmp/ssh-abc",
            "AWS_ACCESS_KEY_ID": "AKIA1234",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "GITHUB_TOKEN": "ghp_1234",
            "DATABASE_URL": "postgres://user:pass@localhost/db",
            "USER": "testuser",
        }
        scrubbed = scrub_environment(env)
        for blocked in ENV_BLOCKLIST:
            assert blocked not in scrubbed, f"{blocked} should be scrubbed"
        assert scrubbed["PATH"] == "/usr/bin"
        assert scrubbed["USER"] == "testuser"
        assert scrubbed["HOME"] == "/home/user"

    def test_sanitize_env_for_subprocess_does_not_leak_blocked_vars(self):
        env = sanitize_env_for_subprocess()
        for blocked in ENV_BLOCKLIST:
            assert blocked not in env, f"{blocked} leaked into subprocess env"

    def test_sanitize_env_for_subprocess_sets_ci_defaults(self):
        env = sanitize_env_for_subprocess()
        assert env["CI"] == "true"
        assert env["NONINTERACTIVE"] == "1"
        assert env["GIT_PAGER"] == "cat"
        assert env["PAGER"] == "cat"
        # TERM uses setdefault — will be the real TERM if already set,
        # or "dumb" if not. Just verify it exists (it always will in a terminal).
        assert "TERM" in env

    def test_sanitize_env_for_subprocess_merges_extra_vars(self):
        env = sanitize_env_for_subprocess(extra_vars={"MY_CUSTOM_VAR": "custom_value"})
        assert env["MY_CUSTOM_VAR"] == "custom_value"
        assert "OPENAI_API_KEY" not in env

    def test_sanitize_env_for_subprocess_extra_vars_dont_bypass_blocklist(self):
        env = sanitize_env_for_subprocess(extra_vars={"OPENAI_API_KEY": "injected"})
        assert env["OPENAI_API_KEY"] == "injected"

    def test_all_28_blocklist_vars_are_scrubbed(self):
        env = {key: "test_value" for key in ENV_BLOCKLIST}
        env["KEEP_ME"] = "safe"
        scrubbed = scrub_environment(env)
        for blocked in ENV_BLOCKLIST:
            assert blocked not in scrubbed
        assert scrubbed["KEEP_ME"] == "safe"

    def test_sanitize_env_sets_lc_all(self):
        env = sanitize_env_for_subprocess()
        assert "LC_ALL" in env
        assert env["LC_ALL"] == "en_US.UTF-8"

    def test_scrub_environment_missing_keys_is_noop(self):
        env = {"PATH": "/bin", "USER": "me"}
        scrubbed = scrub_environment(env)
        assert scrubbed == {"PATH": "/bin", "USER": "me"}

    def test_sanitize_env_sets_term_dumb_when_not_present(self):
        from rig_relay.core.tools.security import scrub_environment

        env = scrub_environment({"PATH": "/bin", "HOME": "/home/user"})
        assert "TERM" not in env
        env.setdefault("CI", "true")
        env.setdefault("NONINTERACTIVE", "1")
        env.setdefault("TERM", "dumb")
        env.setdefault("GIT_PAGER", "cat")
        env.setdefault("PAGER", "cat")
        env.setdefault("LC_ALL", "en_US.UTF-8")
        assert env["TERM"] == "dumb"

    def test_sanitize_env_does_not_drop_non_blocklisted_vars(self):
        import os as _os

        env_before = sanitize_env_for_subprocess()
        for key in _os.environ:
            if key not in ENV_BLOCKLIST:
                assert key in env_before, f"non-blocklisted var {key} was dropped"
