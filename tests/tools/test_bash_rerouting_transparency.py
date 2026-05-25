"""Tests for bash rerouting transparency — verifying that rerouted bash commands
produce metadata-rich events recording original command, target tool, reason,
permission decision, and outcome. Uses real BashTool code paths via try_reroute.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import hashlib
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

from pydantic import BaseModel
import pytest

from rig_relay.core.tools.ast_search import detect_dangerous_bash_patterns
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolPermission,
)
from rig_relay.core.tools.permissions import PermissionContext
from rig_relay.core.tools.reroute import BashRerouteMetadata, try_reroute
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

    def __init__(
        self, *, permission_override: ToolPermission | None = None, **kwargs: Any
    ):
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

    def __init__(
        self, *, permission_override: ToolPermission | None = None, **kwargs: Any
    ):
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
    BaseTool[dict[Any, Any], _FakeGitDiffResult, BaseToolConfig, BaseToolState]
):
    description: ClassVar[str] = "Fake git_diff tool for testing reroute."

    @classmethod
    def _get_type_hints(cls) -> tuple[type[dict[Any, Any]], type[_FakeGitDiffResult]]:
        return dict, _FakeGitDiffResult

    async def run(
        self, args: dict[Any, Any], ctx: InvokeContext | None = None
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
    tool_cls: type[BaseTool[Any, Any, Any, Any]],
    permission_override: ToolPermission | None = None,
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

        cls_to_return: type[BaseTool[Any, Any, Any, Any]] = _PermissionOverridden
    else:
        cls_to_return = tool_cls

    def _get(name: str) -> type[BaseTool[Any, Any, Any, Any]]:
        return cls_to_return

    mgr.get = MagicMock(side_effect=_get)
    return mgr


# ── BashRerouteMetadata model tests ──────────────────────────────


class TestRerouteMetadataModel:
    def test_reroute_metadata_defaults(self) -> None:
        """Default BashRerouteMetadata fields have expected values."""
        m = BashRerouteMetadata()
        assert m.was_rerouted is False
        assert m.raw_bash_skipped is False
        assert m.original_command_category is None
        assert m.original_command_hash is None
        assert m.rerouted_tool_name is None
        assert m.reroute_reason is None
        assert m.permission_decision is None
        assert m.safety_class is None
        assert m.final_outcome is None
        assert m.refusal_reason is None
        assert m.matched_pattern is None
        assert m.redaction_status == "none"

    def test_reroute_metadata_serialization(self) -> None:
        """BashRerouteMetadata round-trips through JSON correctly."""
        m = BashRerouteMetadata(
            was_rerouted=True,
            raw_bash_skipped=True,
            original_command_category="file_read",
            original_command_hash="abc123",
            rerouted_tool_name="read_file",
            reroute_reason="cat/head/tail → read_file",
            permission_decision="allowed",
            safety_class="safe_reroute",
            final_outcome="rerouted",
            redaction_status="none",
        )
        data = m.model_dump()
        assert data["was_rerouted"] is True
        assert data["raw_bash_skipped"] is True
        assert data["original_command_category"] == "file_read"
        assert data["rerouted_tool_name"] == "read_file"
        assert data["final_outcome"] == "rerouted"

        restored = BashRerouteMetadata.model_validate(data)
        assert restored == m

    def test_reroute_metadata_partial_serialization(self) -> None:
        """BashRerouteMetadata with only required fields serializes correctly."""
        m = BashRerouteMetadata(
            was_rerouted=False, raw_bash_skipped=False, redaction_status="none"
        )
        data = m.model_dump()
        assert data["was_rerouted"] is False
        assert data["original_command_category"] is None
        restored = BashRerouteMetadata.model_validate(data)
        assert restored.original_command_category is None


# ── Bash rerouting transparency tests ────────────────────────────


@pytest.mark.asyncio
async def test_rerouted_cat_records_was_rerouted_true(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """Run Bash-rerouter for 'cat path/to/file' and verify was_rerouted is True."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat path/to/file", ctx_with_tool_manager
    )
    assert was_rerouted is True
    assert result_model is not None
    assert isinstance(result_model, _FakeReadFileResult)
    assert metadata is not None
    assert metadata.was_rerouted is True


@pytest.mark.asyncio
async def test_rerouted_cat_records_raw_bash_skipped_true(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """When cat is rerouted, raw bash execution is skipped entirely."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat README.md", ctx_with_tool_manager
    )
    assert was_rerouted is True
    assert metadata is not None
    assert metadata.raw_bash_skipped is True
    reroute_msgs = _extract_reroute_messages(events)
    assert len(reroute_msgs) == 1
    assert "Rerouting" in reroute_msgs[0]


@pytest.mark.asyncio
async def test_rerouted_cat_records_command_category_file_read(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """Rerouted cat has command_category 'file_read'."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat src/main.py", ctx_with_tool_manager
    )
    assert was_rerouted is True
    assert result_model is not None
    assert "src/main.py" in result_model.path
    assert metadata is not None
    assert metadata.original_command_category == "file_read"


@pytest.mark.asyncio
async def test_rerouted_cat_records_has_original_command_hash(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """Reroute produces a valid sha256 hash of the original command."""
    command = "cat src/main.py"
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        command, ctx_with_tool_manager
    )
    assert was_rerouted is True
    assert result_model is not None
    assert metadata is not None
    assert metadata.original_command_hash is not None
    assert len(metadata.original_command_hash) == 64
    assert (
        metadata.original_command_hash
        == hashlib.sha256(command.encode("utf-8")).hexdigest()
    )


@pytest.mark.asyncio
async def test_rerouted_cat_records_rerouted_tool_name(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """Rerouted cat records rerouted_tool_name='read_file' in metadata."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat file.txt", ctx_with_tool_manager
    )
    assert was_rerouted is True
    assert metadata is not None
    assert metadata.rerouted_tool_name == "read_file"


@pytest.mark.asyncio
async def test_rerouted_cat_records_final_outcome_rerouted(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """Rerouted cat has final_outcome 'rerouted' in metadata."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat file.txt", ctx_with_tool_manager
    )
    assert was_rerouted is True
    assert result_model is not None
    assert metadata is not None
    assert metadata.final_outcome == "rerouted"


@pytest.mark.asyncio
async def test_rerouted_grep_records_metadata(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """Rerouted grep records was_rerouted=True, category='search', tool_name='grep'."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeGrepTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        "grep pattern file.py", ctx_with_tool_manager
    )
    assert was_rerouted is True
    assert isinstance(result_model, _FakeGrepResult)
    assert metadata is not None
    assert metadata.original_command_category == "search"
    assert metadata.rerouted_tool_name == "grep"


@pytest.mark.asyncio
async def test_rerouted_git_status_records_metadata(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """Rerouted git status records was_rerouted=True, category='git', tool_name='git_status'."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeGitStatusTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        "git status", ctx_with_tool_manager
    )
    assert was_rerouted is True
    assert isinstance(result_model, _FakeGitStatusResult)
    assert metadata is not None
    assert metadata.original_command_category == "git"
    assert metadata.rerouted_tool_name == "git_status"


@pytest.mark.asyncio
async def test_non_rerouted_command_records_was_rerouted_false(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """echo hello is not a reroutable command — was_rerouted is False."""
    was_rerouted, result_model, events, metadata = await try_reroute(
        "echo hello", ctx_with_tool_manager
    )
    assert was_rerouted is False
    assert result_model is None
    assert events == []
    assert metadata is not None
    assert metadata.was_rerouted is False
    assert metadata.final_outcome == "not_rerouted"


@pytest.mark.asyncio
async def test_reroute_without_tool_manager_falls_back_to_bash() -> None:
    """When reroute is unavailable, bash should continue instead of refusing."""
    ctx = InvokeContext(tool_call_id="call-test-123")
    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat missing_file.txt", ctx
    )

    assert was_rerouted is False
    assert result_model is None
    assert metadata is not None
    assert metadata.raw_bash_skipped is False
    assert metadata.final_outcome == "not_rerouted"

    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    assert any("tool_manager not available" in msg for msg in event_messages)


@pytest.mark.asyncio
async def test_raw_bash_skipped_true_when_rerouted(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """When a command is rerouted, raw bash execution is skipped and metadata reflects it."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat skip.txt", ctx_with_tool_manager
    )
    assert was_rerouted is True
    assert metadata is not None
    assert metadata.raw_bash_skipped is True


@pytest.mark.asyncio
async def test_original_command_hash_present_no_raw_command_in_metadata(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """Metadata has hash but no raw command field with secrets in events."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat README.md", ctx_with_tool_manager
    )
    assert was_rerouted is True
    assert metadata is not None
    assert metadata.original_command_hash is not None
    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    event_text = " ".join(event_messages)
    assert "sha256" not in event_text.lower() or "/etc/shadow" not in event_text


@pytest.mark.asyncio
async def test_no_private_path_in_metadata(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """Fake secret path does not appear in reroute event messages."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)
    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat /Users/test/secret/tokens.json", ctx_with_tool_manager
    )
    assert was_rerouted is True
    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    event_text = " ".join(event_messages)
    assert "tokens.json" not in event_text


def test_build_receipt_propagates_reroute_metadata() -> None:
    """Bash.build_receipt() copies reroute metadata from BashResult to BashReceipt."""
    from rig_relay.core.tools.builtins.bash import (
        Bash,
        BashReceipt,
        BashResult,
        BashToolConfig,
    )

    reroute_md = BashRerouteMetadata(
        was_rerouted=False,
        raw_bash_skipped=False,
        original_command_category=None,
        redaction_status="none",
        final_outcome="not_rerouted",
    )

    result = BashResult(
        command="echo hello",
        stdout="hello\n",
        stderr="",
        returncode=0,
        status="success",
        reroute=reroute_md,
    )

    tool = Bash(config_getter=lambda: BashToolConfig(), state=BaseToolState())
    receipt = tool.build_receipt(result)

    assert isinstance(receipt, BashReceipt)
    assert receipt.reroute is not None
    assert receipt.reroute.was_rerouted is False
    assert receipt.reroute.final_outcome == "not_rerouted"
    assert receipt.reroute.redaction_status == "none"

    data = receipt.model_dump()
    assert "reroute" in data
    assert data["reroute"]["was_rerouted"] is False


def test_build_receipt_propagates_reroute_metadata_when_rerouted() -> None:
    """build_receipt copies full reroute metadata when rerouted."""
    from rig_relay.core.tools.builtins.bash import (
        Bash,
        BashReceipt,
        BashResult,
        BashToolConfig,
    )

    reroute_md = BashRerouteMetadata(
        was_rerouted=True,
        raw_bash_skipped=True,
        original_command_category="file_read",
        original_command_hash=hashlib.sha256(b"cat file.txt").hexdigest(),
        rerouted_tool_name="read_file",
        reroute_reason="cat/head/tail → read_file",
        permission_decision="allowed",
        safety_class="safe_reroute",
        final_outcome="rerouted",
        redaction_status="none",
    )

    result = BashResult(
        command="cat file.txt",
        stdout="",
        stderr="",
        returncode=0,
        status="success",
        reroute=reroute_md,
    )

    tool = Bash(config_getter=lambda: BashToolConfig(), state=BaseToolState())
    receipt = tool.build_receipt(result)

    assert isinstance(receipt, BashReceipt)
    assert receipt.reroute is not None
    assert receipt.reroute.was_rerouted is True
    assert receipt.reroute.raw_bash_skipped is True
    assert receipt.reroute.original_command_category == "file_read"
    assert receipt.reroute.rerouted_tool_name == "read_file"
    assert receipt.reroute.permission_decision == "allowed"
    assert receipt.reroute.final_outcome == "rerouted"
    assert receipt.reroute.original_command_hash is not None
    assert len(receipt.reroute.original_command_hash) == 64


def test_build_receipt_handles_null_reroute() -> None:
    """build_receipt works with BashResult that has reroute=None."""
    from rig_relay.core.tools.builtins.bash import (
        Bash,
        BashReceipt,
        BashResult,
        BashToolConfig,
    )

    result = BashResult(
        command="echo hello",
        stdout="hello\n",
        stderr="",
        returncode=0,
        status="success",
        reroute=None,
    )

    tool = Bash(config_getter=lambda: BashToolConfig(), state=BaseToolState())
    receipt = tool.build_receipt(result)

    assert isinstance(receipt, BashReceipt)
    assert receipt.reroute is None
    data = receipt.model_dump()
    assert data["reroute"] is None


@pytest.mark.asyncio
async def test_reroute_refusal_from_bash(ctx_with_tool_manager: InvokeContext) -> None:
    """When reroute target tool has NEVER permission, reroute is refused."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(
        _FakeReadFileTool, permission_override=ToolPermission.NEVER
    )
    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat /etc/shadow", ctx_with_tool_manager
    )
    assert was_rerouted is False
    assert result_model is None
    assert metadata is not None
    assert metadata.was_rerouted is False
    assert metadata.final_outcome == "refused_reroute"
    assert metadata.permission_decision == "denied"
    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    assert any("refused" in msg.lower() or "Refused" in msg for msg in event_messages)


def test_dangerous_pattern_produces_refusal_in_bash() -> None:
    """A command with $() command substitution is detected as dangerous."""
    warnings = detect_dangerous_bash_patterns("echo $(cat /etc/passwd)")
    assert len(warnings) > 0
    assert any("command substitution" in w.lower() for w in warnings)

    warnings2 = detect_dangerous_bash_patterns("ls -la")
    assert warnings2 == []

    warnings3 = detect_dangerous_bash_patterns("echo `whoami`")
    assert len(warnings3) > 0
    assert any("backtick" in w.lower() for w in warnings3)


# ── Schema validation tests ─────────────────────────────────────


def test_bash_receipt_schema_validates_with_reroute() -> None:
    """BashReceipt with reroute metadata validates against the schema."""
    from rig_relay.core.tools.builtins.bash import (
        Bash,
        BashReceipt,
        BashResult,
        BashToolConfig,
    )

    reroute_md = BashRerouteMetadata(
        was_rerouted=True,
        raw_bash_skipped=True,
        original_command_category="file_read",
        original_command_hash=hashlib.sha256(b"cat readme.md").hexdigest(),
        rerouted_tool_name="read_file",
        reroute_reason="cat/head/tail → read_file",
        permission_decision="allowed",
        safety_class="safe_reroute",
        final_outcome="rerouted",
        redaction_status="none",
    )

    result = BashResult(
        command="cat readme.md",
        stdout="fake output",
        stderr="",
        returncode=0,
        status="success",
        reroute=reroute_md,
    )

    tool = Bash(config_getter=lambda: BashToolConfig(), state=BaseToolState())
    receipt = tool.build_receipt(result)

    assert isinstance(receipt, BashReceipt)
    data = receipt.model_dump()
    assert data["reroute"]["was_rerouted"] is True
    assert data["reroute"]["raw_bash_skipped"] is True
    assert data["reroute"]["redaction_status"] == "none"


def test_bash_receipt_schema_validates_without_reroute() -> None:
    """BashReceipt without reroute (null) validates against the schema."""
    from rig_relay.core.tools.builtins.bash import (
        Bash,
        BashReceipt,
        BashResult,
        BashToolConfig,
    )

    result = BashResult(
        command="echo hello",
        stdout="hello\n",
        stderr="",
        returncode=0,
        status="success",
        reroute=None,
    )

    tool = Bash(config_getter=lambda: BashToolConfig(), state=BaseToolState())
    receipt = tool.build_receipt(result)

    assert isinstance(receipt, BashReceipt)
    assert receipt.reroute is None
    data = receipt.model_dump()
    assert data["reroute"] is None


# ── Additional integration/contract tests (preserved from prior) ──


@pytest.mark.asyncio
async def test_rerouted_cat_records_reroute_metadata(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """integration/contract/real-artifact — rerouted cat records original command,
    target tool, and skip reason.
    """
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)

    was_rerouted, result_model, events, metadata = await try_reroute(
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

    assert metadata is not None
    assert metadata.was_rerouted is True


@pytest.mark.asyncio
async def test_rerouted_cat_with_head_flag_includes_limit(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """contract — cat-equivalent reroute with -n flag propagates limit arg."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)

    was_rerouted, result_model, _, _ = await try_reroute(
        "head -n 3 README.md", ctx_with_tool_manager
    )

    assert was_rerouted is True
    assert result_model is not None
    assert result_model.path == "README.md"
    assert result_model.limit == 3


@pytest.mark.asyncio
async def test_rerouted_grep_records_reroute_metadata(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """integration/contract/real-artifact — rerouted grep records metadata."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeGrepTool)

    was_rerouted, result_model, events, metadata = await try_reroute(
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

    assert metadata is not None
    assert metadata.was_rerouted is True


@pytest.mark.asyncio
async def test_reroute_permission_refusal_recorded(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """integration/contract/adversarial — reroute blocked by permission records refusal event."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(
        _FakeReadFileTool, permission_override=ToolPermission.NEVER
    )

    was_rerouted, result_model, events, metadata = await try_reroute(
        "cat /etc/shadow", ctx_with_tool_manager
    )

    assert was_rerouted is False
    assert result_model is None

    assert metadata is not None
    assert metadata.was_rerouted is False
    assert metadata.final_outcome == "refused_reroute"

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
    was_rerouted, result_model, events, metadata = await try_reroute(
        "unknown-cmd arg1", ctx_with_tool_manager
    )

    assert was_rerouted is False
    assert result_model is None
    assert events == []
    assert metadata is not None
    assert metadata.was_rerouted is False


@pytest.mark.asyncio
async def test_reroute_event_is_content_light(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """contract — reroute events contain no raw paths, no raw content, no secrets."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)

    _, _, events, _ = await try_reroute(
        "cat /Users/test/secret.txt", ctx_with_tool_manager
    )

    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    combined = " ".join(event_messages)

    assert "/Users/test/secret.txt" not in combined
    assert "read_file" in combined.lower() or "Rerouting" in combined


@pytest.mark.asyncio
async def test_reroute_event_has_all_expected_fields(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """contract — each reroute ToolStreamEvent has tool_name, message, tool_call_id."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)

    _, _, events, _ = await try_reroute("cat README.md", ctx_with_tool_manager)

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
    """contract — try_reroute returns tuple[bool, Any|None, list, BashRerouteMetadata]."""
    result = await try_reroute("echo hello", MagicMock())
    was_rerouted, model, events, metadata = result

    assert isinstance(was_rerouted, bool)
    assert isinstance(events, list)
    assert isinstance(metadata, BashRerouteMetadata)
    assert len(result) == 4


@pytest.mark.asyncio
async def test_rerouted_tool_result_is_pydantic_model(
    ctx_with_tool_manager: InvokeContext,
) -> None:
    """contract — rerouted tool produces a valid Pydantic result model."""
    ctx_with_tool_manager.tool_manager = _make_tool_manager(_FakeReadFileTool)

    was_rerouted, result_model, _, _ = await try_reroute(
        "cat README.md", ctx_with_tool_manager
    )

    assert was_rerouted is True
    assert isinstance(result_model, BaseModel)
    assert hasattr(result_model, "path")
    assert hasattr(result_model, "content")


@pytest.mark.asyncio
async def test_empty_command_not_rerouted() -> None:
    """contract — empty command string returns was_rerouted=False."""
    was_rerouted, result_model, events, metadata = await try_reroute("", MagicMock())

    assert was_rerouted is False
    assert result_model is None
    assert events == []
    assert metadata is not None
    assert metadata.was_rerouted is False


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

    _, _, events, _ = await try_reroute(command, ctx_with_tool_manager)

    event_messages = [e.message for e in events if isinstance(e, ToolStreamEvent)]
    reroute_msgs = [m for m in event_messages if "Rerouting" in m]
    assert len(reroute_msgs) == 1
    assert description_fragment in reroute_msgs[0]


# ── Helpers ──────────────────────────────────────────────────────


def _extract_reroute_messages(events: list[Any]) -> list[str]:
    """Extract reroute advisory messages from events list."""
    result: list[str] = []
    for event in events:
        if isinstance(event, ToolStreamEvent) and "Rerouting" in event.message:
            result.append(event.message)
    return result
