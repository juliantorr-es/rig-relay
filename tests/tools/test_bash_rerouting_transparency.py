"""Tests for bash rerouting transparency — verifying that rerouted bash commands
produce metadata-rich events recording original command, target tool, reason,
permission decision, and outcome.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import ClassVar
from unittest.mock import MagicMock, patch

from pydantic import BaseModel
import pytest

from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from rig_relay.core.tools.permissions import PermissionContext
from rig_relay.core.types import ToolStreamEvent

# ── Minimal args/result models mimicking the real tools ──────────


class _FakeReadFileArgs(BaseModel):
    path: str
    offset: int = 0
    limit: int | None = None


class _FakeReadFileResult(BaseModel):
    path: str
    content: str
    offset: int = 0
    lines_read: int = 1
    limit: int | None = None
    was_truncated: bool = False


class _FakeGrepArgs(BaseModel):
    pattern: str
    path: str = "."
    max_matches: int | None = None
    use_default_ignore: bool = True


class _FakeGrepResult(BaseModel):
    matches: str
    match_count: int
    total_match_count: int = 0
    was_truncated: bool = False


class _FakeGitStatusArgs(BaseModel):
    short: bool = False
    branch: bool = False
    porcelain: bool = False


class _FakeGitStatusResult(BaseModel):
    stdout: str
    stderr: str = ""


class _FakeGitDiffResult(BaseModel):
    stdout: str
    stderr: str = ""


class _FakeReadFileToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


# ── Fake tool classes — duck-typed to satisfy try_reroute ────────


class _FakeReadFileTool(
    BaseTool[
        _FakeReadFileArgs, _FakeReadFileResult, _FakeReadFileToolConfig, BaseToolState
    ]
):
    description: ClassVar[str] = "Fake read_file tool for testing reroute."

    def __init__(self, *, permission_override: ToolPermission | None = None, **kwargs):
        super().__init__(**kwargs)
        self._permission_override = permission_override

    @classmethod
    def _get_type_hints(
        cls,
    ) -> tuple[type[_FakeReadFileArgs], type[_FakeReadFileResult]]:
        return _FakeReadFileArgs, _FakeReadFileResult

    async def run(
        self, args: _FakeReadFileArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | _FakeReadFileResult, None]:
        yield _FakeReadFileResult(
            path=args.path,
            content="fake content",
            lines_read=args.limit or 1,
            limit=args.limit,
        )

    def resolve_permission(self, args: _FakeReadFileArgs) -> PermissionContext | None:
        if self._permission_override is not None:
            return PermissionContext(
                permission=self._permission_override,
                reason="permission overridden for test",
            )
        return None


class _FakeGrepTool(
    BaseTool[_FakeGrepArgs, _FakeGrepResult, BaseToolConfig, BaseToolState]
):
    description: ClassVar[str] = "Fake grep tool for testing reroute."

    def __init__(self, *, permission_override: ToolPermission | None = None, **kwargs):
        super().__init__(**kwargs)
        self._permission_override = permission_override

    @classmethod
    def _get_type_hints(cls) -> tuple[type[_FakeGrepArgs], type[_FakeGrepResult]]:
        return _FakeGrepArgs, _FakeGrepResult

    async def run(
        self, args: _FakeGrepArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | _FakeGrepResult, None]:
        yield _FakeGrepResult(matches=f"{args.path}:1:{args.pattern}", match_count=1)

    def resolve_permission(self, args: _FakeGrepArgs) -> PermissionContext | None:
        if self._permission_override is not None:
            return PermissionContext(
                permission=self._permission_override, reason="test"
            )
        return None


class _FakeGitStatusTool(
    BaseTool[_FakeGitStatusArgs, _FakeGitStatusResult, BaseToolConfig, BaseToolState]
):
    description: ClassVar[str] = "Fake git_status tool for testing reroute."

    @classmethod
    def _get_type_hints(
        cls,
    ) -> tuple[type[_FakeGitStatusArgs], type[_FakeGitStatusResult]]:
        return _FakeGitStatusArgs, _FakeGitStatusResult

    async def run(
        self, args: _FakeGitStatusArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | _FakeGitStatusResult, None]:
        yield _FakeGitStatusResult(stdout="fake git status")


class _FakeGitDiffTool(
    BaseTool[dict, _FakeGitDiffResult, BaseToolConfig, BaseToolState]
):
    description: ClassVar[str] = "Fake git_diff tool for testing reroute."

    @classmethod
    def _get_type_hints(cls) -> tuple[type[dict], type[_FakeGitDiffResult]]:
        return dict, _FakeGitDiffResult

    async def run(
        self, args: dict, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | _FakeGitDiffResult, None]:
        yield _FakeGitDiffResult(stdout="fake git diff")


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_reroute_deps() -> None:
    """Patch is_allowed on PermissionContext — pending from a parallel refactoring lane."""
    with patch.object(
        PermissionContext,
        "is_allowed",
        lambda self: self.permission is not ToolPermission.NEVER,
        create=True,
    ):
        yield


@pytest.fixture
def ctx_with_tool_manager() -> InvokeContext:
    """InvokeContext with a tool_call_id for event emission."""
    return InvokeContext(tool_call_id="call-test-123")


def _make_tool_manager(
    tool_cls: type[BaseTool], permission_override: ToolPermission | None = None
) -> MagicMock:
    """Create a mock ToolManager whose get() returns the tool CLASS.
    try_reroute expects mgr.get() to return a class and then constructs its own instance.
    When permission_override is set, creates a subclass with overridden resolve_permission.
    """
    mgr = MagicMock()

    if permission_override is not None:
        _perm = permission_override

        class _PermissionOverridden(tool_cls):  # type: ignore[valid-type]
            def resolve_permission(self, args: BaseModel) -> PermissionContext | None:
                return PermissionContext(
                    permission=_perm, reason="permission overridden for test"
                )

        cls_to_return: type[BaseTool] = _PermissionOverridden
    else:
        cls_to_return = tool_cls

    def _get(name: str) -> type[BaseTool]:
        return cls_to_return

    mgr.get = MagicMock(side_effect=_get)
    return mgr


# ── Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rerouted_cat_records_reroute_metadata(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """integration/contract/real-artifact — rerouted cat records original command,
    target tool, and skip reason.
    """
    from rig_relay.core.tools.reroute import try_reroute

    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)

    was_rerouted, result_model, events = await try_reroute(
        "cat src/main.py", ctx_with_tool_manager
    )

    assert was_rerouted is True
    assert result_model is not None
    assert isinstance(result_model, _FakeReadFileResult)
    assert "src/main.py" in result_model.path

    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    reroute_msgs = [m for m in event_messages if "Rerouting" in m]
    assert len(reroute_msgs) == 1
    assert "\u21aa Rerouting to read_file" in reroute_msgs[0]
    assert "cat/head/tail → read_file" in reroute_msgs[0]


@pytest.mark.asyncio
async def test_rerouted_cat_with_head_flag_includes_limit(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """contract — cat-equivalent reroute with -n flag propagates limit arg."""
    from rig_relay.core.tools.reroute import try_reroute

    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)

    was_rerouted, result_model, _ = await try_reroute(
        "head -n 3 README.md", ctx_with_tool_manager
    )

    assert was_rerouted is True
    assert result_model.path == "README.md"
    assert result_model.limit == 3


@pytest.mark.asyncio
async def test_rerouted_grep_records_reroute_metadata(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """integration/contract/real-artifact — rerouted grep records metadata."""
    from rig_relay.core.tools.reroute import try_reroute

    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeGrepTool)

    was_rerouted, result_model, events = await try_reroute(
        "grep pattern file.py", ctx_with_tool_manager
    )

    assert was_rerouted is True
    assert isinstance(result_model, _FakeGrepResult)
    assert result_model.match_count == 1

    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    reroute_msgs = [m for m in event_messages if "Rerouting" in m]
    assert len(reroute_msgs) == 1
    assert "\u21aa Rerouting to grep" in reroute_msgs[0]
    assert "grep/rg → grep" in reroute_msgs[0]


@pytest.mark.asyncio
async def test_rerouted_git_status_records_metadata(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """integration/contract/real-artifact — rerouted git status records metadata."""
    from rig_relay.core.tools.reroute import try_reroute

    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeGitStatusTool)

    was_rerouted, result_model, events = await try_reroute(
        "git status", ctx_with_tool_manager
    )

    assert was_rerouted is True
    assert isinstance(result_model, _FakeGitStatusResult)

    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    reroute_msgs = [m for m in event_messages if "Rerouting" in m]
    assert len(reroute_msgs) >= 1
    reroute_text = " ".join(reroute_msgs)
    assert "\u21aa Rerouting to git_tool" in reroute_text
    assert "git subcmd → git_<subcmd>" in reroute_text


@pytest.mark.asyncio
async def test_reroute_permission_refusal_recorded(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """integration/contract/adversarial — reroute blocked by permission records refusal event."""
    from rig_relay.core.tools.reroute import try_reroute

    ctx_with_tool_manager.tool_manager = _make_tool_manager(
        _FakeReadFileTool, permission_override=ToolPermission.NEVER
    )

    was_rerouted, result_model, events = await try_reroute(
        "cat /etc/shadow", ctx_with_tool_manager
    )

    assert was_rerouted is False
    assert result_model is None

    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    refusal_msgs = [
        m for m in event_messages if "refused" in m or "Refused" in m or "\u26a0" in m
    ]
    assert len(refusal_msgs) >= 1
    assert "refused" in refusal_msgs[0].lower()
    assert "read_file" in refusal_msgs[0]


@pytest.mark.asyncio
async def test_unknown_command_does_not_reroute(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """integration/contract — unknown command returns was_rerouted=False."""
    from rig_relay.core.tools.reroute import try_reroute

    was_rerouted, result_model, events = await try_reroute(
        "unknown-cmd arg1", ctx_with_tool_manager
    )

    assert was_rerouted is False
    assert result_model is None
    assert events == []


@pytest.mark.asyncio
async def test_reroute_event_is_content_light(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """contract — reroute events contain no raw paths, no raw content, no secrets."""
    from rig_relay.core.tools.reroute import try_reroute

    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)

    _, _, events = await try_reroute(
        "cat /Users/test/secret.txt", ctx_with_tool_manager
    )

    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    combined = " ".join(event_messages)

    # Reroute advisory should mention tool, not raw path
    assert "/Users/test/secret.txt" not in combined
    # Should reference tool names and descriptions, not raw paths
    assert "read_file" in combined.lower() or "Rerouting" in combined


@pytest.mark.asyncio
async def test_reroute_event_has_all_expected_fields(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """contract — each reroute ToolStreamEvent has tool_name, message, tool_call_id."""
    from rig_relay.core.tools.reroute import try_reroute

    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)

    _, _, events = await try_reroute("cat README.md", ctx_with_tool_manager)

    for event in events:
        if isinstance(event, ToolStreamEvent):
            assert event.tool_name == "bash"
            assert isinstance(event.message, str)
            assert len(event.message) > 0
            assert event.tool_call_id == "call-test-123"


@pytest.mark.asyncio
async def test_reroute_preserves_api_signature(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """contract — try_reroute returns tuple[bool, Any|None, list]."""
    from rig_relay.core.tools.reroute import try_reroute

    result = await try_reroute("echo hello", MagicMock())
    was_rerouted, model, events = result

    assert isinstance(was_rerouted, bool)
    assert isinstance(events, list)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_rerouted_tool_result_is_pydantic_model(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """contract — rerouted tool produces a valid Pydantic result model."""
    from rig_relay.core.tools.reroute import try_reroute

    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)

    was_rerouted, result_model, _ = await try_reroute(
        "cat README.md", ctx_with_tool_manager
    )

    assert was_rerouted is True
    assert isinstance(result_model, BaseModel)
    # Should have structured fields, not a raw blob
    assert hasattr(result_model, "path")
    assert hasattr(result_model, "content")


@pytest.mark.asyncio
async def test_empty_command_not_rerouted() -> None:
    """contract — empty command string returns was_rerouted=False."""
    from unittest.mock import MagicMock

    from rig_relay.core.tools.reroute import try_reroute

    was_rerouted, result_model, events = await try_reroute("", MagicMock())

    assert was_rerouted is False
    assert result_model is None
    assert events == []


@pytest.mark.parametrize(
    "command,description_fragment",
    [
        ("cat file.txt", "cat/head/tail → read_file"),
        ("bat file.txt", "cat/head/tail → read_file"),
        ("head -n 5 file.txt", "cat/head/tail → read_file"),
        ("tail file.txt", "cat/head/tail → read_file"),
        ("grep foo file.py", "grep/rg → grep"),
        ("rg foo file.py", "grep/rg → grep"),
        ("git status", "git subcmd → git_<subcmd>"),
        ("git diff", "git subcmd → git_<subcmd>"),
    ],
)
@pytest.mark.asyncio
async def test_reroute_description_matches_category(
    ctx_with_tool_manager: InvokeContext, command: str, description_fragment: str
) -> None:
    """contract — reroute advisory includes the correct category description for
    each command family.
    """
    from rig_relay.core.tools.reroute import try_reroute

    if "cat" in command or "bat" in command or "head" in command or "tail" in command:
        tool_cls = _FakeReadFileTool
    elif "grep" in command or "rg" in command:
        tool_cls = _FakeGrepTool
    elif "git status" in command:
        tool_cls = _FakeGitStatusTool
    elif "git diff" in command:
        tool_cls = _FakeGitDiffTool
    else:
        tool_cls = _FakeReadFileTool

    ctx_with_tool_manager.tool_manager = _make_tool_manager(tool_cls)

    _, _, events = await try_reroute(command, ctx_with_tool_manager)

    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    reroute_msgs = [m for m in event_messages if "Rerouting" in m]
    assert len(reroute_msgs) == 1
    assert description_fragment in reroute_msgs[0]
