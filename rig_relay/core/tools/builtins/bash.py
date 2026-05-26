from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import hashlib
import os
from pathlib import Path
import sys
import time
from typing import Any, ClassVar, Literal, final

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.guard import get_guard
from rig_relay.core.scratchpad import is_scratchpad_path
from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tool_subprocess import ShellFeatureResult, ToolSubprocessRequest
from rig_relay.core.tools.arity import build_session_pattern
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from rig_relay.core.tools.determinism import parse_shell_commands
from rig_relay.core.tools.permissions import (
    PermissionContext,
    PermissionScope,
    RequiredPermission,
)
from rig_relay.core.tools.reroute import BashRerouteMetadata, try_reroute
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.tools.utils import is_path_within_workdir
from rig_relay.core.types import ToolResultEvent, ToolStreamEvent
from rig_relay.core.utils import is_windows, kill_async_subprocess


def _get_subprocess_encoding() -> str:
    if sys.platform == "win32":
        # Windows console uses OEM code page (e.g., cp850, cp1252)
        import ctypes

        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    return "utf-8"


def _get_shell_executable() -> str | None:
    if is_windows():
        return None
    return os.environ.get("SHELL")


def _get_base_env() -> dict[str, str]:
    """Build a safe base environment for subprocess execution.

    Strips sensitive env vars (API keys, tokens) and sets
    CI-safe defaults for terminal programs.
    """
    from rig_relay.core.tools.security import sanitize_env_for_subprocess

    return sanitize_env_for_subprocess()


# Environment variables that must be stripped for scoped (restricted)
# execution to prevent indirect code execution through plugins,
# configuration, or path injection.
_SCOPED_ENV_BLOCKLIST: frozenset[str] = frozenset({
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "COVERAGE_PROCESS_START",
    "VIRTUAL_ENV",
    "GIT_CONFIG",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_EXEC_PATH",
    "GIT_EXTERNAL_DIFF",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_COMMON_DIR",
})


def _get_scoped_env() -> dict[str, str]:
    """Build a hardened environment for scoped (restrict_raw_shell=True) execution.

    Starts from the base safe environment and additionally strips
    environment variables that could inject code through plugins,
    configuration, import paths, or executable resolution.
    """
    env = _get_base_env()
    for key in _SCOPED_ENV_BLOCKLIST:
        env.pop(key, None)
    return env


# Sensitive paths that should never be read via bash cat/head/etc.
_SENSITIVE_READ_PATTERNS: list[str] = [
    str(Path.home() / ".rig" / "relay" / "identity"),
    str(Path.home() / ".rig" / "relay" / "credentials"),
]


def _get_default_allowlist() -> list[str]:
    common = ["cd", "echo", "tree", "whoami"]

    if is_windows():
        return common + ["dir", "findstr", "more", "type", "ver", "where"]
    else:
        return common + [
            "cat",
            "env",
            "false",
            "file",
            "find",
            "head",
            "ls",
            "printf",
            "pwd",
            "sleep",
            "stat",
            "tail",
            "true",
            "uname",
            "wc",
            "which",
        ]


def _get_default_denylist() -> list[str]:
    common = [
        "gdb",
        "pdb",
        "passwd",
        "git reset",
        "git clean",
        "git restore",
        "git checkout",
        "git stash",
        "git rebase",
        "git merge",
        "git push --force",
        "git push --force-with-lease",
        "git commit",
        "git add",
        "rm -rf",
        "rm -fr",
    ]

    if is_windows():
        return common + ["cmd /k", "powershell -NoExit", "pwsh -NoExit", "notepad"]
    else:
        return common + [
            "nano",
            "vim",
            "vi",
            "emacs",
            "bash -i",
            "sh -i",
            "zsh -i",
            "fish -i",
            "dash -i",
            "screen",
            "tmux",
        ]


def _get_default_denylist_standalone() -> list[str]:
    common = ["python", "python3", "ipython"]

    if is_windows():
        return common + ["cmd", "powershell", "pwsh", "notepad"]
    else:
        return common + ["bash", "sh", "nohup", "vi", "vim", "emacs", "nano", "su"]


_PATH_COMMANDS = {
    "cat",
    "cd",
    "chmod",
    "chown",
    "cp",
    "head",
    "ls",
    "mkdir",
    "mv",
    "rm",
    "stat",
    "tail",
    "touch",
    "wc",
}

_FIND_EXECUTION_PREDICATES = {"-exec", "-execdir", "-ok", "-okdir"}


def _collect_outside_dirs(command_parts: list[str]) -> set[str]:
    """Collect parent directories referenced outside the workdir.

    Iterates file-manipulating commands (see _PATH_COMMANDS) and inspects
    their arguments as candidate paths. Skips flags (-r, --recursive) and
    chmod mode strings (+x). For any argument that resolves outside the current
    working directory, adds the parent directory (or the path itself when it is
    a directory) to the result set — suitable for building an OUTSIDE_DIRECTORY
    RequiredPermission.
    """
    dirs: set[str] = set()
    for part in command_parts:
        tokens = part.split()
        command = tokens[0] if tokens else None
        if not command or command not in _PATH_COMMANDS:
            continue
        for token in tokens[1:]:
            # Skip CLI flags like -r, --recursive
            if token.startswith("-"):
                continue
            # Skip chmod mode strings like +x, +rwx — they are not file paths
            if command == "chmod" and token.startswith("+"):
                continue
            # Only consider tokens that look like paths
            if not (
                token.startswith(os.sep)
                or token.startswith("~")
                or token.startswith(".")
                or os.sep in token
            ):
                continue
            if is_path_within_workdir(token):
                continue
            if is_scratchpad_path(token):
                continue
            # Resolve relative / home-relative paths, then collect parent dir
            resolved = Path(token).expanduser()
            if not resolved.is_absolute():
                resolved = Path.cwd() / resolved
            resolved = resolved.resolve()
            # For a directory target use the dir itself; for a file use its parent
            parent = str(resolved) if resolved.is_dir() else str(resolved.parent)
            dirs.add(parent)
    return dirs


def _matches_pattern(command: str, pattern: str) -> bool:
    return command == pattern or command.startswith(pattern + " ")


class BashToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    max_output_bytes: int = Field(
        default=16_000, description="Maximum bytes to capture from stdout and stderr."
    )
    default_timeout: int = Field(
        default=300, description="Default timeout for commands in seconds."
    )
    max_concurrent_processes: int = Field(
        default=4,
        description="Maximum number of concurrent subprocesses across all sessions.",
    )
    allowlist: list[str] = Field(
        default_factory=_get_default_allowlist,
        description="Command prefixes that are automatically allowed",
    )
    denylist: list[str] = Field(
        default_factory=_get_default_denylist,
        description="Command prefixes that are automatically denied",
    )
    denylist_standalone: list[str] = Field(
        default_factory=_get_default_denylist_standalone,
        description="Commands that are denied only when run without arguments",
    )
    sensitive_patterns: list[str] = Field(
        default=["sudo"],
        description="Command prefixes that trigger elevated sensitivity checks",
    )
    restrict_raw_shell: bool = Field(
        default=True,
        description=(
            "When True, raw shell commands that do not match the known "
            "validation reroute registry (pytest, ruff, pyright, git, "
            "cat->read_file, grep) are refused in scoped missions. "
            "Set to False for developer/unrestricted mode."
        ),
    )


class BashArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    timeout: int | None = Field(
        default=None, description="Override the default command timeout."
    )
    cwd: str | None = Field(
        default=None,
        description="Working directory for the command. Defaults to current directory.",
    )
    max_stdout_bytes: int | None = Field(
        default=None,
        description="Maximum bytes to capture from stdout. Overrides config max_output_bytes.",
    )
    max_stderr_bytes: int | None = Field(
        default=None,
        description="Maximum bytes to capture from stderr. Overrides config max_output_bytes.",
    )


class BashResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    stdout: str
    stderr: str
    returncode: int
    status: str = "success"
    duration_ms: float | None = None
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    error_kind: str | None = None
    refusal_reason: str | None = None
    supervisor_result_envelope: dict[str, object] | None = None
    supervisor_result_envelope_sha256: str | None = None
    supervisor_result_classification: str | None = None
    reroute: BashRerouteMetadata | None = None
    # Execution risk classification applied at the scoped-mission boundary.
    # Values: bounded_utility, repository_code_executing, static_analysis,
    # governed_tool_reroute, or diagnostic_raw_shell.
    execution_risk: str | None = None


class BashReceipt(BaseModel):
    """Content-light receipt for a bash invocation.

    Contains no raw stdout/stderr — only metadata, byte counts,
    hashes, exit code, and timing information.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.bash_receipt.v1"
    command: str
    status: str
    exit_code: int
    duration_ms: float | None = None
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
    supervisor_result_envelope_sha256: str | None = None
    supervisor_result_envelope_id: str | None = None
    supervisor_result_classification: str | None = None
    reroute: BashRerouteMetadata | None = None


class Bash(
    BaseTool[BashArgs, BashResult, BashToolConfig, BaseToolState],
    ToolUIData[BashArgs, BashResult],
):
    description: ClassVar[str] = "Run a one-off bash command and capture its output."
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.NONDETERMINISTIC_EXTERNAL_IO
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.WRITES_WORKSPACE

    @classmethod
    def format_call_display(cls, args: BashArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"bash: {args.command}")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, BashResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        return ToolResultDisplay(success=True, message=f"Ran {event.result.command}")

    @classmethod
    def get_status_text(cls) -> str:
        return "Running command"

    @staticmethod
    def _extract_reroute_stdout(events: list[Any]) -> str:
        if not events:
            return ""
        last = events[-1]
        for attr in ("stdout", "content", "matches"):
            if hasattr(last, attr) and (val := getattr(last, attr)):
                return str(val)
        return ""

    @staticmethod
    def _has_find_execution_predicate(command: str) -> bool:
        """Defensive check for find -exec, -execdir, -ok, -okdir predicates."""
        if not _matches_pattern(command, "find"):
            return False
        return any(predicate in command for predicate in _FIND_EXECUTION_PREDICATES)

    @staticmethod
    def _build_command_required_permission(
        invocation_pattern: str, session_pattern: str, label: str
    ) -> RequiredPermission:
        return RequiredPermission(
            scope=PermissionScope.COMMAND_PATTERN,
            invocation_pattern=invocation_pattern,
            session_pattern=session_pattern,
            label=label,
        )

    @staticmethod
    def _build_outside_directory_permission(glob: str) -> RequiredPermission:
        return RequiredPermission(
            scope=PermissionScope.OUTSIDE_DIRECTORY,
            invocation_pattern=glob,
            session_pattern=glob,
            label=f"outside workdir ({glob})",
        )

    @staticmethod
    def _build_timeout_error(command: str, timeout: int) -> ToolError:
        return ToolError(f"Command timed out after {timeout}s: {command[:200]}")

    def _find_denylist_match(self, command: str) -> str | None:
        return next(
            (p for p in self.config.denylist if _matches_pattern(command, p)), None
        )

    def _is_standalone_denylisted(self, command: str) -> bool:
        parts = command.split()
        if not parts:
            return False
        base_command = parts[0]
        if len(parts) == 1:
            command_name = os.path.basename(base_command)
            if command_name in self.config.denylist_standalone:
                return True
            if base_command in self.config.denylist_standalone:
                return True
        return False

    def _is_allowlisted(self, command: str) -> bool:
        return any(
            _matches_pattern(command, pattern) for pattern in self.config.allowlist
        )

    def _is_sensitive(self, command: str) -> bool:
        tokens = command.split()
        if not tokens:
            return False
        return tokens[0] in self.config.sensitive_patterns

    # ── Shell Grammar Containment ────────────────────────────────────────
    # Scoped missions must refuse any command that chains, redirects,
    # substitutes, wraps, or delegates beyond a single safe executable.

    # Execution risk categories for scoped-mission classification.
    # Only BOUNDED_UTILITY may execute via direct exec without governed
    # containment. REPOSITORY_CODE_EXECUTING requires a governed native
    # validation route; without one it must fail closed.
    EXECUTION_RISK_BOUNDED_UTILITY: ClassVar[str] = "bounded_utility"
    EXECUTION_RISK_REPOSITORY_CODE: ClassVar[str] = "repository_code_executing"
    EXECUTION_RISK_STATIC_ANALYSIS: ClassVar[str] = "static_analysis"
    EXECUTION_RISK_GOVERNED_REROUTE: ClassVar[str] = "governed_tool_reroute"
    EXECUTION_RISK_DIAGNOSTIC_SHELL: ClassVar[str] = "diagnostic_raw_shell"

    # Commands that, when invoked, execute repository-controlled Python code.
    # This includes any form of pytest or python invocation that may load
    # conftest.py, plugins, fixtures, or test modules from the workspace.
    _REPOSITORY_CODE_EXECUTING_COMMANDS: ClassVar[frozenset[str]] = frozenset({
        "pytest",
        "pytest3",
        "python",
        "python3",
    })

    _SHELL_WRAPPER_COMMANDS: ClassVar[frozenset[str]] = frozenset({
        "sh",
        "bash",
        "zsh",
        "dash",
        "fish",
        "eval",
        "exec",
        "env",
        "xargs",
        "nohup",
        "su",
        "sudo",
        "nice",
    })

    _SHELL_SEPARATOR_TOKENS: ClassVar[frozenset[str]] = frozenset({
        ";",
        "||",
        "&&",
        "|",
        "|&",
    })

    _SHELL_REDIRECT_PREFIXES: ClassVar[tuple[str, ...]] = (
        ">",
        ">>",
        ">&",
        "<",
        "<<",
        "<&",
        "<<<",
        "&>",
    )

    _SHELL_SUBSTITUTION_MARKERS: ClassVar[tuple[str, ...]] = (
        "$(",
        "`",
        "$((",
        "<(",
        ">(",
    )

    @staticmethod
    def _parse_shell_tokens(command: str) -> list[str] | None:
        """Tokenize a shell command using shlex, returning tokens or None on failure."""
        import shlex

        try:
            tokens = shlex.split(command, comments=True)
        except ValueError:
            return None
        if not tokens:
            return None
        return tokens

    @classmethod
    def _has_shell_composition(cls, command: str) -> bool:
        """Check raw string for shell composition constructs.

        Detects: semicolons, AND/OR, pipelines, backgrounding,
        process substitution, command substitution, here docs/strings,
        and shell control operators.

        Returns True if shell composition is detected.
        """
        import re

        # Strip comments so they don't hide trailing composition
        stripped = command.strip()
        if not stripped:
            return False

        # Pipeline or logical chaining (needs context — we check bare tokens too)
        if any(sep in stripped for sep in cls._SHELL_SEPARATOR_TOKENS):
            return True

        # Background execution: & at end or before a space/separator
        if re.search(r"(?<!\&)&(?!\&)\s*$|\s&\s", stripped):
            return True

        # Semicolon command separator
        if re.search(r"[^;];\s", stripped) or stripped.rstrip().endswith(";"):
            return True

        # Command substitution: $(...) or backticks
        if any(marker in stripped for marker in cls._SHELL_SUBSTITUTION_MARKERS):
            return True

        # Redirection operators
        for prefix in cls._SHELL_REDIRECT_PREFIXES:
            if re.search(
                rf"(?:^|\s){re.escape(prefix)}(?:\s|&|\d|[a-zA-Z./~])", stripped
            ):
                return True

        # Here documents and here strings: << or <<<
        if re.search(r"<<\s*[A-Za-z_]", stripped) or "<<<" in stripped:
            return True

        return False

    @classmethod
    def _classify_shell_intent(
        cls,
        command: str,
        *,
        allowlist: list[str],
        denylist: list[str],
        denylist_standalone: list[str],
    ) -> tuple[bool, str | None]:
        """Classify a shell command's executable intent for scoped missions.

        Returns (admitted, refusal_reason). Only single, simple
        commands that match the allowlist or validation registry are
        admitted. Multi-command sequences, shell features, wrappers,
        indirection, and ambiguous constructs are refused.

        This is the canonical shell-intent classification authority
        for scoped (restrict_raw_shell=True) execution.
        """
        # ── Quick check: multi-command composition ──────────
        if cls._has_shell_composition(command):
            return False, (
                "Shell composition (pipes, redirects, separators, or "
                "substitutions) is prohibited in scoped missions. Use "
                "governed tools for reads, edits, and validation."
            )

        # ── Tokenize into shell words ───────────────────────
        tokens = cls._parse_shell_tokens(command)
        if tokens is None:
            return False, (
                "Could not parse shell command safely. "
                "Use governed tools instead of raw shell."
            )

        if not tokens:
            return False, "Empty command after parsing."

        executable = tokens[0]

        # ── Absolute path bypass ────────────────────────────
        if executable.startswith("/"):
            return False, (
                "Absolute executable paths are prohibited in scoped missions. "
                "Use governed tools for reads, edits, and validation."
            )

        # ── Shell wrapper or delegation ─────────────────────
        if executable in cls._SHELL_WRAPPER_COMMANDS:
            # env alone is safe — only block if it's wrapping another command
            if executable == "env" and len(tokens) == 1:
                pass  # allow standalone env
            elif executable == "env":
                return False, (
                    "Command 'env' with arguments is prohibited in scoped "
                    "missions. Use governed tools."
                )
            else:
                return False, (
                    f"Command '{executable}' is a shell wrapper or delegation "
                    f"utility that is prohibited in scoped missions. "
                    f"Use governed tools."
                )

        # ── Environment variable prefix (VAR=val cmd) ──────
        if "=" in executable and not executable.startswith("-"):
            return False, (
                "Environment variable prefixes are prohibited in scoped "
                "missions. Use governed tools."
            )

        # ── Denylist check ──────────────────────────────────
        for pattern in denylist:
            if command == pattern or command.startswith(pattern + " "):
                return False, (
                    f"Command matches denylist pattern '{pattern}' and is "
                    f"prohibited in scoped missions."
                )

        # ── Standalone denylist check ───────────────────────
        if len(tokens) == 1:
            cmd_name = os.path.basename(executable)
            if cmd_name in denylist_standalone or executable in denylist_standalone:
                return False, (
                    f"Command '{executable}' is not allowed as a standalone "
                    f"command in scoped missions."
                )

        # ── Validation-equivalent check ─────────────────────
        if cls._matches_validate_reroute(command):
            return True, None

        # ── Allowlist check ─────────────────────────────────
        if any(
            command == pattern or command.startswith(pattern + " ")
            for pattern in allowlist
        ):
            return True, None

        # ── Not in any admitted set ─────────────────────────
        return False, (
            "Raw shell execution is unavailable in this workspace-contained "
            "mission. Use governed file tools for reads or edits, or the "
            "validation tool for approved tests and static checks."
        )

    @classmethod
    def _is_repository_code_executing(cls, command: str) -> bool:
        """Determine whether *command* executes repository-controlled code.

        Recognises pytest (any invocation), python -m pytest, python3 -m pytest,
        and uv run pytest. Returns True for any form that loads workspace
        plugins, conftest.py, fixtures, or test modules.
        """
        import shlex

        try:
            tokens = shlex.split(command)
        except ValueError:
            return False
        if not tokens:
            return False

        root = tokens[0]

        # Direct pytest / pytest3
        if root in ("pytest", "pytest3"):
            return True

        # python -m pytest / python3 -m pytest
        if root in ("python", "python3") and len(tokens) >= 3:
            if tokens[1] == "-m" and tokens[2] == "pytest":
                return True

        # uv run pytest
        if root == "uv" and len(tokens) >= 3:
            if tokens[1] == "run" and tokens[2] in ("pytest", "pytest3"):
                return True
            # uv run python -m pytest
            if (
                tokens[1] == "run"
                and tokens[2] in ("python", "python3")
                and len(tokens) >= 5
                and tokens[3] == "-m"
                and tokens[4] == "pytest"
            ):
                return True

        return False

    @classmethod
    def _classify_execution_risk(cls, command: str) -> str:
        """Classify the execution risk of a command admitted by grammar containment.

        Returns one of the EXECUTION_RISK_* categories.

        This is the canonical authority for distinguishing repository-code-
        executing validation from bounded utilities and static analysis.
        It must be applied before direct execution and before reroute fallback.
        """
        # Check for repository-code execution first — highest risk
        if cls._is_repository_code_executing(command):
            return cls.EXECUTION_RISK_REPOSITORY_CODE

        # Validation-equivalent commands that are not repo-code-executing
        # are static analysis (ruff check, pyright)
        if cls._matches_validate_reroute(command):
            return cls.EXECUTION_RISK_STATIC_ANALYSIS

        # Everything else admitted by grammar containment is a bounded utility
        return cls.EXECUTION_RISK_BOUNDED_UTILITY

    @staticmethod
    def _matches_validate_reroute(command: str) -> bool:
        """Check if command matches the validate tool reroute patterns.
        Only pytest, ruff check, and pyright are recognized. cat, grep,
        git, and python -c are deliberately excluded — the agent must
        use dedicated governed tools for those operations.
        """
        try:
            tokens = command.split()
        except Exception:
            return False
        if not tokens:
            return False
        root = tokens[0]
        # pytest / pytest3
        if root in ("pytest", "pytest3"):
            return True
        # python -m pytest
        if (
            root == "python"
            and len(tokens) >= 3
            and tokens[1] == "-m"
            and tokens[2] == "pytest"
        ):
            return True
        # ruff check
        if root == "ruff" and len(tokens) >= 2 and tokens[1] == "check":
            return True
        # pyright
        if root == "pyright":
            return True
        return False

    def _resolve_guardrail_permission(
        self, command_parts: list[str]
    ) -> PermissionContext | None:
        from rig_relay.core.tools.ast_search import detect_dangerous_bash_patterns

        find_execution_required: list[RequiredPermission] = []
        seen_find_execution: set[str] = set()

        full_command = " ".join(command_parts)

        # Check for dangerous patterns that bypass allowlists
        safety_warnings = detect_dangerous_bash_patterns(full_command)
        if safety_warnings:
            return PermissionContext(
                permission=ToolPermission.NEVER, reason="; ".join(safety_warnings)
            )

        # Check for sensitive file reads (token store, credentials)
        for sensitive_path in _SENSITIVE_READ_PATTERNS:
            if sensitive_path in full_command:
                return PermissionContext(
                    permission=ToolPermission.NEVER,
                    reason=f"Command references sensitive path '{sensitive_path}'. "
                    f"Use the built-in tools for operations on credential files.",
                )

        for part in command_parts:
            if matched := self._find_denylist_match(part):
                return PermissionContext(
                    permission=ToolPermission.NEVER,
                    reason=f"Command denied: '{part}' matches denylist pattern '{matched}'. Do not attempt to run this command.",
                )
            if self._is_standalone_denylisted(part):
                return PermissionContext(
                    permission=ToolPermission.NEVER,
                    reason=f"Command denied: '{part}' is not allowed as a standalone command. Do not attempt to run this command.",
                )
            if not self._has_find_execution_predicate(part):
                continue
            if part in seen_find_execution:
                continue
            seen_find_execution.add(part)
            find_execution_required.append(
                self._build_command_required_permission(
                    invocation_pattern=part, session_pattern=part, label=part
                )
            )

        if not find_execution_required:
            # Governed Command Execution Airlock v1:
            # In contained missions (restrict_raw_shell=True), refuse raw
            # commands that don't pass shell-intent classification.
            if getattr(self.config, "restrict_raw_shell", False):
                admitted, reason = Bash._classify_shell_intent(
                    full_command,
                    allowlist=self.config.allowlist,
                    denylist=self.config.denylist,
                    denylist_standalone=self.config.denylist_standalone,
                )
                if not admitted:
                    return PermissionContext(
                        permission=ToolPermission.NEVER,
                        reason=(
                            reason
                            or (
                                "Raw shell execution is unavailable in this "
                                "workspace-contained mission. Use governed file "
                                "tools for reads or edits, or the validation "
                                "tool for approved tests and static checks."
                            )
                        ),
                    )
            return None
        return PermissionContext(
            permission=ToolPermission.ASK, required_permissions=find_execution_required
        )

    def _is_unconditionally_allowed(
        self, command_parts: list[str], outside_dirs: set[str]
    ) -> bool:
        if any(self._is_sensitive(part) for part in command_parts):
            return False

        if self.config.permission == ToolPermission.ALWAYS:
            return True

        return all(self._is_allowlisted(part) for part in command_parts) and (
            not outside_dirs
        )

    def _build_required_permissions(
        self, command_parts: list[str], outside_dirs: set[str]
    ) -> list[RequiredPermission]:
        required: list[RequiredPermission] = []
        seen_session: set[str] = set()

        for part in command_parts:
            if not part:
                continue
            tokens = part.split()
            if not tokens:
                continue

            is_sensitive = self._is_sensitive(part)
            if not is_sensitive and self._is_allowlisted(part):
                continue

            if is_sensitive:
                required.append(
                    self._build_command_required_permission(
                        invocation_pattern=part, session_pattern=part, label=part
                    )
                )
                continue

            session_pat = build_session_pattern(tokens)
            if session_pat in seen_session:
                continue
            seen_session.add(session_pat)
            required.append(
                self._build_command_required_permission(
                    invocation_pattern=part,
                    session_pattern=session_pat,
                    label=session_pat,
                )
            )

        for glob in sorted(str(Path(d) / "*") for d in outside_dirs):
            required.append(self._build_outside_directory_permission(glob))

        return required

    def resolve_permission(self, args: BashArgs) -> PermissionContext | None:
        if is_windows():
            return None

        command_parts = parse_shell_commands(args.command)
        if not command_parts:
            return None

        guardrail_permission = self._resolve_guardrail_permission(command_parts)
        if (
            guardrail_permission
            and guardrail_permission.permission == ToolPermission.NEVER
        ):
            return guardrail_permission
        outside_dirs = _collect_outside_dirs(command_parts)
        if (
            self._is_unconditionally_allowed(command_parts, outside_dirs)
            and not guardrail_permission
        ):
            return PermissionContext(permission=ToolPermission.ALWAYS)

        required = self._build_required_permissions(command_parts, outside_dirs)
        if guardrail_permission:
            required.extend(guardrail_permission.required_permissions)
        if not required:
            return None

        return PermissionContext(
            permission=ToolPermission.ASK, required_permissions=required
        )

    @final
    def _build_result(
        self,
        *,
        command: str,
        stdout: str,
        stderr: str,
        returncode: int,
        duration_ms: float | None = None,
        stdout_bytes: int = 0,
        stderr_bytes: int = 0,
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
    ) -> BashResult:
        if returncode != 0:
            error_msg = f"Command failed: {command!r}\n"
            error_msg += f"Return code: {returncode}"
            if stderr:
                error_msg += f"\nStderr: {stderr}"
            if stdout:
                error_msg += f"\nStdout: {stdout}"
            raise ToolError(error_msg.strip())

        return BashResult(
            command=command,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            status="success",
            duration_ms=duration_ms,
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            error_kind=None,
            refusal_reason=None,
        )

    @final
    def _build_timeout_result(
        self,
        *,
        command: str,
        duration_ms: float | None = None,
        timeout: int = 0,
        stdout_bytes: int = 0,
        stderr_bytes: int = 0,
    ) -> BashResult:
        return BashResult(
            command=command,
            stdout="",
            stderr="",
            returncode=-1,
            status="timed_out",
            duration_ms=duration_ms,
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
            stdout_truncated=False,
            stderr_truncated=False,
            error_kind="timeout",
            refusal_reason=f"Command timed out after {timeout}s",
        )

    @final
    def build_receipt(self, result: BashResult) -> BashReceipt:
        """Build a content-light receipt from a command result.

        The receipt contains no raw stdout/stderr — only byte counts,
        SHA256 hashes, exit code, timing, and metadata.
        """
        stdout_sha256 = None
        stderr_sha256 = None
        if result.stdout:
            stdout_sha256 = hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()
        if result.stderr:
            stderr_sha256 = hashlib.sha256(result.stderr.encode("utf-8")).hexdigest()

        return BashReceipt(
            command=result.command,
            status=result.status,
            exit_code=result.returncode,
            duration_ms=result.duration_ms,
            stdout_bytes=result.stdout_bytes,
            stderr_bytes=result.stderr_bytes,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
            stdout_sha256=stdout_sha256,
            stderr_sha256=stderr_sha256,
            error_kind=result.error_kind,
            refusal_reason=result.refusal_reason,
            supervisor_result_envelope_sha256=result.supervisor_result_envelope_sha256,
            supervisor_result_envelope_id=(
                str(result.supervisor_result_envelope.get("result_id"))
                if result.supervisor_result_envelope
                else None
            ),
            supervisor_result_classification=result.supervisor_result_classification,
            reroute=result.reroute,
        )

    @final
    async def _run_subprocess(
        self,
        command: str,
        cwd: str | None,
        timeout: int,
        max_stdout: int,
        max_stderr: int,
        start: float,
    ) -> BashResult:
        """Execute a subprocess and return a structured result.

        Handles process creation, timeout, output decoding, and truncation.
        Raises ``ToolError`` for non-zero exit codes (preserving existing
        contract); yields timed_out/refused results for those specific cases.
        """
        kwargs: dict[Literal["start_new_session"], bool] = (
            {} if is_windows() else {"start_new_session": True}
        )

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=_get_base_env(),
            executable=_get_shell_executable(),
            cwd=cwd,
            **kwargs,
        )

        try:
            try:
                raw_stdout, raw_stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except TimeoutError:
                await kill_async_subprocess(proc)
                elapsed = (time.perf_counter() - start) * 1000
                return self._build_timeout_result(
                    command=command,
                    duration_ms=elapsed,
                    timeout=timeout,
                    stdout_bytes=0,
                    stderr_bytes=0,
                )

            encoding = _get_subprocess_encoding()
            total_stdout_bytes = len(raw_stdout) if raw_stdout else 0
            total_stderr_bytes = len(raw_stderr) if raw_stderr else 0

            stdout_str = (
                raw_stdout.decode(encoding, errors="replace")[:max_stdout]
                if raw_stdout
                else ""
            )
            stderr_str = (
                raw_stderr.decode(encoding, errors="replace")[:max_stderr]
                if raw_stderr
                else ""
            )

            stdout_truncated = total_stdout_bytes > max_stdout
            stderr_truncated = total_stderr_bytes > max_stderr
            returncode = proc.returncode or 0
            elapsed = (time.perf_counter() - start) * 1000

            return self._build_result(
                command=command,
                stdout=stdout_str,
                stderr=stderr_str,
                returncode=returncode,
                duration_ms=elapsed,
                stdout_bytes=total_stdout_bytes,
                stderr_bytes=total_stderr_bytes,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
            )
        finally:
            await kill_async_subprocess(proc)

    @final
    async def _run_direct_exec(
        self,
        command: str,
        argv: list[str],
        cwd: str | None,
        timeout: int,
        max_stdout: int,
        max_stderr: int,
        start: float,
    ) -> BashResult:
        """Execute via create_subprocess_exec with explicit argv.

        No shell interpretation — the program and arguments are passed
        directly to the OS process launcher. Used only in restricted
        scoped execution (restrict_raw_shell=True) after grammar
        containment and argv parsing have validated the intent.
        """
        if not argv:
            return BashResult(
                command=command,
                stdout="",
                stderr="",
                returncode=-1,
                status="failure",
                duration_ms=(time.perf_counter() - start) * 1000,
                error_kind="internal_error",
                refusal_reason="Empty argv after parsing.",
            )

        program = argv[0]
        program_args = argv[1:]
        kwargs: dict[Literal["start_new_session"], bool] = (
            {} if is_windows() else {"start_new_session": True}
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                program,
                *program_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                env=_get_scoped_env(),
                cwd=cwd,
                **kwargs,
            )
        except FileNotFoundError:
            elapsed = (time.perf_counter() - start) * 1000
            return BashResult(
                command=command,
                stdout="",
                stderr="",
                returncode=-1,
                status="failure",
                duration_ms=elapsed,
                error_kind="executable_not_found",
                refusal_reason=f"Executable not found: {program}",
            )
        except PermissionError:
            elapsed = (time.perf_counter() - start) * 1000
            return BashResult(
                command=command,
                stdout="",
                stderr="",
                returncode=-1,
                status="failure",
                duration_ms=elapsed,
                error_kind="executable_not_executable",
                refusal_reason=f"Executable not executable: {program}",
            )

        try:
            try:
                raw_stdout, raw_stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except TimeoutError:
                await kill_async_subprocess(proc)
                elapsed = (time.perf_counter() - start) * 1000
                return self._build_timeout_result(
                    command=command,
                    duration_ms=elapsed,
                    timeout=timeout,
                    stdout_bytes=0,
                    stderr_bytes=0,
                )

            encoding = _get_subprocess_encoding()
            total_stdout_bytes = len(raw_stdout) if raw_stdout else 0
            total_stderr_bytes = len(raw_stderr) if raw_stderr else 0

            stdout_str = (
                raw_stdout.decode(encoding, errors="replace")[:max_stdout]
                if raw_stdout
                else ""
            )
            stderr_str = (
                raw_stderr.decode(encoding, errors="replace")[:max_stderr]
                if raw_stderr
                else ""
            )

            stdout_truncated = total_stdout_bytes > max_stdout
            stderr_truncated = total_stderr_bytes > max_stderr
            returncode = proc.returncode or 0
            elapsed = (time.perf_counter() - start) * 1000

            return self._build_result(
                command=command,
                stdout=stdout_str,
                stderr=stderr_str,
                returncode=returncode,
                duration_ms=elapsed,
                stdout_bytes=total_stdout_bytes,
                stderr_bytes=total_stderr_bytes,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
            )
        finally:
            await kill_async_subprocess(proc)

    async def _run_supervised(
        self,
        subprocess_runner: Any,
        command: str,
        argv: list[str],
        cwd: str | None,
        timeout: int,
        max_stdout: int,
        max_stderr: int,
        start: float,
    ) -> BashResult:

        req = ToolSubprocessRequest(
            argv=argv,
            cwd=cwd or ".",
            timeout_seconds=float(timeout),
            stdout_limit_bytes=max_stdout,
            stderr_limit_bytes=max_stderr,
            tool_name="bash",
        )
        result = await subprocess_runner.run(req)
        elapsed = (time.perf_counter() - start) * 1000
        status = result.status
        if status == "completed":
            status = "success" if result.exit_code == 0 else "failure"
        elif status == "timed_out":
            status = "timed_out"
        elif status == "refused":
            status = "refused"
        else:
            status = "failure"
        return BashResult(
            command=command,
            stdout=result.stdout_text,
            stderr=result.stderr_text,
            returncode=result.exit_code if result.exit_code is not None else -1,
            status=status,
            duration_ms=elapsed,
            stdout_bytes=result.stdout_bytes,
            stderr_bytes=result.stderr_bytes,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
            error_kind=(
                result.refusal_code if status in {"refused", "failure"} else None
            ),
            refusal_reason=result.error_message,
            supervisor_result_envelope=result.supervisor_result_envelope,
            supervisor_result_envelope_sha256=result.supervisor_result_envelope_sha256,
            supervisor_result_classification=result.supervisor_result_classification,
        )

    @staticmethod
    def _classify_shell_command(command: str) -> ShellFeatureResult:
        from rig_relay.core.tool_subprocess import ShellFeatureResult
        from rig_relay.runtime.supervisor_invoker import SupervisorCommandInvoker

        if SupervisorCommandInvoker.has_shell_metacharacters(command):
            return ShellFeatureResult(
                safe_for_argv=False, argv=[], detected_features=["shell_metacharacters"]
            )
        parsed = SupervisorCommandInvoker.parse_shell_to_argv(command)
        if isinstance(parsed, str):
            return ShellFeatureResult(
                safe_for_argv=False, argv=[], detected_features=["parse_error"]
            )
        return ShellFeatureResult(safe_for_argv=True, argv=parsed, detected_features=[])

    async def run(
        self, args: BashArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | BashResult, None]:
        start = time.perf_counter()

        # ── Command rerouting ─────────────────────────────────
        # Check if the command is better handled by a dedicated tool
        rerouted, result_model, events, reroute_meta = await try_reroute(
            args.command, ctx, args.cwd
        )
        if rerouted:
            yield BashResult(
                command=args.command,
                stdout=self._extract_reroute_stdout(events),
                stderr="",
                returncode=0,
                status="success",
                duration_ms=(time.perf_counter() - start) * 1000,
                reroute=reroute_meta,
                execution_risk=Bash.EXECUTION_RISK_GOVERNED_REROUTE,
            )
            for event in events:
                yield event
            return

        if reroute_meta.raw_bash_skipped:
            elapsed = (time.perf_counter() - start) * 1000
            yield BashResult(
                command=args.command,
                stdout="",
                stderr="",
                returncode=-1,
                status="refused",
                duration_ms=elapsed,
                error_kind="refused",
                refusal_reason=reroute_meta.refusal_reason,
                reroute=reroute_meta,
            )
            return

        for event in events:
            yield event

        guard = get_guard()
        is_destructive, reason = guard.is_destructive_git_command(args.command)
        if is_destructive:
            elapsed = (time.perf_counter() - start) * 1000
            yield BashResult(
                command=args.command,
                stdout="",
                stderr="",
                returncode=-1,
                status="refused",
                duration_ms=elapsed,
                stdout_bytes=0,
                stderr_bytes=0,
                stdout_truncated=False,
                stderr_truncated=False,
                error_kind="refused",
                refusal_reason=reason,
                reroute=reroute_meta,
            )
            return

        # ── Runtime restrict_raw_shell enforcement ────────────
        # Hard safety boundary: enforced regardless of permission bypass.
        # Uses canonical shell-intent classification to reject:
        #  - Multi-command sequences (;, &&, ||, |, &, newlines)
        #  - Shell features (redirects, substitutions, here docs)
        #  - Shell wrappers (sh -c, bash -c, eval, exec, env)
        #  - Executable indirection (absolute paths, xargs, find -exec)
        #  - Environment-prefixed execution (VAR=val cmd)
        # Only single-command, simple invocations of allowlisted or
        # validation-equivalent executables pass through.
        if getattr(self.config, "restrict_raw_shell", False):
            admitted, refusal_reason = Bash._classify_shell_intent(
                args.command,
                allowlist=self.config.allowlist,
                denylist=self.config.denylist,
                denylist_standalone=self.config.denylist_standalone,
            )
            if not admitted:
                elapsed = (time.perf_counter() - start) * 1000
                yield BashResult(
                    command=args.command,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    status="refused",
                    duration_ms=elapsed,
                    stdout_bytes=0,
                    stderr_bytes=0,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    error_kind="refused",
                    refusal_reason=refusal_reason
                    or (
                        "Raw shell execution is unavailable in this workspace-contained "
                        "mission. Use governed file tools for reads or edits, or the "
                        "validation tool for approved tests and static checks."
                    ),
                    reroute=reroute_meta,
                )
                return

        timeout = args.timeout or self.config.default_timeout
        max_stdout_cap = (
            args.max_stdout_bytes
            if args.max_stdout_bytes is not None
            else self.config.max_output_bytes
        )
        max_stderr_cap = (
            args.max_stderr_bytes
            if args.max_stderr_bytes is not None
            else self.config.max_output_bytes
        )

        is_strict = getattr(self.config, "restrict_raw_shell", False)

        # ── Try supervised subprocess path ─────────────────
        subprocess_runner = getattr(ctx, "subprocess_runner", None) if ctx else None
        if subprocess_runner is not None:
            shell_check = self._classify_shell_command(args.command)
            if shell_check.safe_for_argv:
                result = await self._run_supervised(
                    subprocess_runner=subprocess_runner,
                    command=args.command,
                    argv=shell_check.argv,
                    cwd=args.cwd,
                    timeout=timeout,
                    max_stdout=max_stdout_cap,
                    max_stderr=max_stderr_cap,
                    start=start,
                )
                result.reroute = reroute_meta
                yield result
                return
            else:
                # Shell features detected — refuse under supervised path
                elapsed = (time.perf_counter() - start) * 1000
                yield BashResult(
                    command=args.command,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    status="refused",
                    duration_ms=elapsed,
                    stdout_bytes=0,
                    stderr_bytes=0,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    error_kind="refused",
                    refusal_reason=(
                        f"Shell features require explicit policy and are not executed "
                        f"by the supervised subprocess runner. "
                        f"Detected: {', '.join(shell_check.detected_features)}"
                    ),
                    reroute=reroute_meta,
                )
                return

        # ── Two-path execution airlock ──────────────────────
        if is_strict:
            # ── Execution-risk classification ─────────────────
            # Before direct execution, classify the risk profile.
            # Repository-code-executing validation (pytest etc.) must
            # fail closed when no governed native validation route
            # is available. Only bounded utilities may proceed to direct exec.
            execution_risk = Bash._classify_execution_risk(args.command)
            if execution_risk == Bash.EXECUTION_RISK_REPOSITORY_CODE:
                elapsed = (time.perf_counter() - start) * 1000
                yield BashResult(
                    command=args.command,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    status="refused",
                    duration_ms=elapsed,
                    stdout_bytes=0,
                    stderr_bytes=0,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    error_kind="repository_code_execution_requires_governed_validation",
                    refusal_reason=(
                        "Pytest and equivalent repository-code-executing validation "
                        "commands are not available through unsandboxed strict Bash "
                        "execution. This command loads and executes repository-controlled "
                        "Python code (plugins, conftest.py, fixtures, tests) and cannot "
                        "be launched without a governed native validation authority. "
                        "Use the native Validate tool or explicitly enable diagnostic "
                        "mode for manual developer investigation."
                    ),
                    execution_risk=execution_risk,
                    reroute=reroute_meta,
                )
                return

            # Scoped execution: direct argv launch, no shell interpretation.
            # Use shlex to parse the command into program + arguments,
            # then launch via create_subprocess_exec with a hardened
            # scoped environment.
            import shlex

            try:
                parsed_argv = shlex.split(args.command)
            except ValueError:
                elapsed = (time.perf_counter() - start) * 1000
                yield BashResult(
                    command=args.command,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    status="refused",
                    duration_ms=elapsed,
                    stdout_bytes=0,
                    stderr_bytes=0,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    error_kind="refused",
                    refusal_reason="Could not parse command arguments safely.",
                    reroute=reroute_meta,
                )
                return

            if not parsed_argv:
                elapsed = (time.perf_counter() - start) * 1000
                yield BashResult(
                    command=args.command,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    status="refused",
                    duration_ms=elapsed,
                    stdout_bytes=0,
                    stderr_bytes=0,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    error_kind="refused",
                    refusal_reason="Empty command after parsing.",
                    reroute=reroute_meta,
                )
                return

            try:
                result = await self._run_direct_exec(
                    command=args.command,
                    argv=parsed_argv,
                    cwd=args.cwd,
                    timeout=timeout,
                    max_stdout=max_stdout_cap,
                    max_stderr=max_stderr_cap,
                    start=start,
                )
                result.reroute = reroute_meta
                result.execution_risk = execution_risk
                yield result
            except (ToolError, asyncio.CancelledError):
                raise
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                yield BashResult(
                    command=args.command,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    status="failure",
                    duration_ms=elapsed,
                    stdout_bytes=0,
                    stderr_bytes=0,
                    stdout_truncated=False,
                    stderr_truncated=False,
                    error_kind="internal_error",
                    refusal_reason=str(exc),
                    reroute=reroute_meta,
                )
            return

        # ── Diagnostic mode: shell execution path ────────────
        # Only reachable when restrict_raw_shell=False,
        # behind the explicit unsafe-profile admission gate.
        try:
            result = await self._run_subprocess(
                command=args.command,
                cwd=args.cwd,
                timeout=timeout,
                max_stdout=max_stdout_cap,
                max_stderr=max_stderr_cap,
                start=start,
            )
            result.reroute = reroute_meta
            yield result
        except (ToolError, asyncio.CancelledError):
            raise
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            yield BashResult(
                command=args.command,
                stdout="",
                stderr="",
                returncode=-1,
                status="failure",
                duration_ms=elapsed,
                stdout_bytes=0,
                stderr_bytes=0,
                stdout_truncated=False,
                stderr_truncated=False,
                error_kind="internal_error",
                refusal_reason=str(exc),
                reroute=reroute_meta,
            )
