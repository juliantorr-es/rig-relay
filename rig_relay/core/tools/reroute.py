"""Command rerouting — detect when an agent calls bash with a command
that has a dedicated builtin tool, and reroute automatically.

This prevents agents from using bash for operations that have better,
more secure, and more structured tool implementations (cat→read_file,
git diff→git_diff, grep→grep, rg→grep, etc.).

The reroute is transparent: the agent doesn't need to do anything.
A ToolStreamEvent is emitted to explain the reroute, and the agent
receives the result from the dedicated tool as if it had called it.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from rig_relay.core.types import ToolStreamEvent

# ── Reroute registry ──────────────────────────────────────────────

RerouteEntry = tuple[
    str,  # tool_name
    callable,  # arg_builder(command: str, tokens: list[str]) -> dict | None
    str,  # description for the reroute message
]


def _parse_tokens(command: str) -> list[str]:
    """Parse the command into tokens, handling quoted strings."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _reroute_read_file(command: str, tokens: list[str]) -> dict[str, Any] | None:
    """Reroute 'cat file' or 'head/tail file' to read_file."""
    if not tokens:
        return None
    cmd = tokens[0]
    if cmd not in {"cat", "head", "tail", "less", "more", "bat"}:
        return None
    if len(tokens) < 2:
        return None
    path = None
    limit = None
    skip_next = False
    for i, tok in enumerate(tokens[1:], 1):
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("-"):
            if tok in {"-n", "--lines"} and i + 1 < len(tokens):
                try:
                    limit = int(tokens[i + 1])
                    skip_next = True
                except (ValueError, IndexError):
                    pass
            continue
        if not tok.startswith("-"):
            path = tok
            break
    if path is None:
        return None
    result: dict[str, Any] = {"path": path}
    if limit is not None:
        result["limit"] = limit
    return result


def _reroute_grep(command: str, tokens: list[str]) -> dict[str, Any] | None:
    """Reroute 'grep' or 'rg' to grep tool."""
    if not tokens:
        return None
    cmd = tokens[0]
    if cmd not in {"grep", "rg", "ripgrep"}:
        return None
    pattern = None
    path = "."
    skip_next = False
    for i, tok in enumerate(tokens[1:], 1):
        if skip_next:
            skip_next = False
            continue
        if tok == "-e" and i + 1 < len(tokens):
            pattern = tokens[i + 1]
            skip_next = True
            continue
        if tok.startswith("-"):
            continue
        if pattern is None:
            pattern = tok
        else:
            path = tok
    if pattern is None:
        return None
    return {"pattern": pattern, "path": path}


def _reroute_git(command: str, tokens: list[str]) -> dict[str, Any] | None:
    """Reroute git operations to the appropriate git tool.

    Maps: git status → git_status, git diff → git_diff, etc.
    Returns a dict with a `_tool_name` key that the registry
    uses to determine which tool to dispatch to.

    Each git subcommand has different args, so we build the
    args dict appropriate for the target tool:
      - git_branch: takes show_current: bool
      - git_status: no extra args
      - git_diff/git_log/git_show: take ref/path
      - git_ls_files: no extra args
    """
    if not tokens or tokens[0] != "git":
        return None
    if len(tokens) < 2:
        return None
    subcmd = tokens[1]

    if subcmd == "status":
        return {"_tool_name": "git_status"}
    if subcmd == "diff":
        # Collect paths from remaining tokens, skipping flags
        paths = [t for t in tokens[2:] if not t.startswith("-")]
        return {"_tool_name": "git_diff", "path": paths[0] if paths else "."}
    if subcmd == "log":
        return {"_tool_name": "git_log", "path": "."}
    if subcmd == "branch":
        return {"_tool_name": "git_branch", "show_current": True}
    if subcmd == "show":
        ref = tokens[2] if len(tokens) > 2 and not tokens[2].startswith("-") else "HEAD"
        return {"_tool_name": "git_show", "ref": ref}
    if subcmd in ("ls-files", "ls_files"):
        return {"_tool_name": "git_ls_files"}

    return None


def _reroute_read_file_by_python(
    command: str, tokens: list[str]
) -> dict[str, Any] | None:
    """Reroute 'python3 -c \"open(...).read()\"' to read_file."""
    if not tokens:
        return None
    if tokens[0] not in {"python3", "python"} or "-c" not in tokens:
        return None
    code = " ".join(tokens[2:]) if len(tokens) > 2 else ""
    m = re.search(r'open\([\'"]([^\'"]+)[\'"]\)', code)
    return {"path": m.group(1)} if m else None


# ── Registry ──────────────────────────────────────────────────────

REROUTE_REGISTRY: list[RerouteEntry] = [
    ("read_file", _reroute_read_file, "cat/head/tail → read_file"),
    ("grep", _reroute_grep, "grep/rg → grep"),
    ("git_tool", _reroute_git, "git subcmd → git_<subcmd>"),
    ("read_file", _reroute_read_file_by_python, "python3 -c open().read() → read_file"),
]


def detect_and_advertise_reroute(command: str) -> str | None:
    """Check if the command could be better handled by a builtin tool.

    No side effects — only produces advisory info.
    Returns a human-readable suggestion string, or None.
    """
    tokens = _parse_tokens(command)
    if not tokens:
        return None
    for tool_name, builder, _description in REROUTE_REGISTRY:
        args = builder(command, tokens)
        if args is not None:
            # Allow builder to override the advertised tool name
            advertised = args.get("_tool_name", tool_name)
            return (
                f"This command could be handled by the '{advertised}' tool "
                f"instead of bash."
            )
    return None


async def try_reroute(
    command: str, ctx: Any | None
) -> tuple[bool, Any | None, list[ToolStreamEvent | Any]]:
    """Attempt to reroute a bash command to its dedicated builtin tool.

    Args:
        command: The full bash command string.
        ctx: The InvokeContext from the bash tool call.

    Returns:
        Tuple of (was_rerouted, result_model_or_None, events_list).
        If was_rerouted is True, the caller should yield events_list
        and NOT execute the bash command.
    """
    tokens = _parse_tokens(command)
    if not tokens:
        return False, None, []

    for tool_name, builder, description in REROUTE_REGISTRY:
        args_dict = builder(command, tokens)
        if args_dict is None:
            continue

        events: list[ToolStreamEvent | Any] = []

        # Emit reroute advisory
        events.append(
            ToolStreamEvent(
                tool_name="bash",
                message=f"\u21aa Rerouting to {tool_name}. ({description})",
                tool_call_id=ctx.tool_call_id if ctx else "",
            )
        )

        # Allow builder to override the target tool name via _tool_name key
        actual_tool = args_dict.pop("_tool_name", tool_name)

        try:
            mgr = getattr(ctx, "tool_manager", None)
            if mgr is None:
                return False, None, []

            tool_cls = mgr.get(actual_tool)
            if tool_cls is None:
                return False, None, []

            # ── Build args model and instantiate tool ──────────
            args_model_cls, _ = tool_cls._get_type_hints()
            args = args_model_cls(**args_dict)

            _cfg_cls = tool_cls._get_tool_config_class()
            _st_cls = tool_cls._get_tool_state_class()
            tool_instance = tool_cls(
                config_getter=lambda c=_cfg_cls: c(), state=_st_cls()
            )

            # ── Permission check ────────────────────────────────
            # The rerouted tool must pass its own permission check,
            # same as if the agent had called it directly.
            perm_ctx = tool_instance.resolve_permission(args)
            if perm_ctx is not None and not perm_ctx.is_allowed():
                events.append(
                    ToolStreamEvent(
                        tool_name="bash",
                        message=f"\u26a0 Reroute to {actual_tool} refused: {perm_ctx.reason}. "
                        f"Reroute requires permission from the target tool.",
                        tool_call_id=ctx.tool_call_id if ctx else "",
                    )
                )
                return False, None, events

            async for event in tool_instance.run(args, ctx):
                events.append(event)

            return True, events[-1] if events else None, events

        except Exception as e:
            events.append(
                ToolStreamEvent(
                    tool_name="bash",
                    message=f"\u26a0 Reroute to {actual_tool} failed: {e}. Falling back to bash.",
                    tool_call_id=ctx.tool_call_id if ctx else "",
                )
            )
            return False, None, events

    return False, None, []


__all__ = ["detect_and_advertise_reroute", "try_reroute"]
