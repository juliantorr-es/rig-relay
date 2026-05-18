"""rig.get_context — governed repository context front door.

Read-only built-in tool. Returns a structured context packet with:
  - repo topology (branch, HEAD, dirty state)
  - subsystem map (entry points, config, schemas, docs, tests)
  - active work lanes and collision warnings
  - recommended context files
  - do-not-touch paths

Agents should call this before planning or editing to understand the
repository landscape and avoid colliding with other active agents.

Tier: 0 (read-only context)
Determinism: DETERMINISTIC_REPO_STATE (cached by repo fingerprint)
Mutation: READ_ONLY
Policy: ALWAYS (read-only, no side effects)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rig_relay.context.compiler import build_receipt, execute
from rig_relay.context.models import (
    CompressionMode,
    ContextBudget,
    ContextMode,
    ContextRequest,
    ContextScope,
    DetailLevel,
)
from rig_relay.core.telemetry.tool_contract import (
    ToolDeterminismClass,
    ToolMutationClass,
)
from rig_relay.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from rig_relay.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from rig_relay.core.types import ToolStreamEvent


class GetContextArgs(BaseModel):
    """Arguments for rig.get_context."""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(
        default="map",
        description="Context mode: map (fast topology), packet (heavy mission-ready), "
        "handoff (agent transfer), collision (path conflict check), symbols (symbol table), "
        "digest (coordination store digestion with cache).",
    )
    mission_id: str | None = Field(
        default=None, description="Optional mission identifier for scoping context."
    )
    agent_id: str | None = Field(
        default=None, description="Optional agent identifier for scoping context."
    )
    scope_paths: list[str] = Field(
        default_factory=list, description="Optional path prefixes to scope the context."
    )
    scope_symbols: list[str] = Field(
        default_factory=list,
        description="Optional symbol names to include definitions for.",
    )
    include_tests: bool = True
    include_docs: bool = True
    include_receipts: bool = True
    include_other_agents: bool = True
    max_tokens: int = Field(
        default=60000, description="Maximum estimated tokens for the context output."
    )
    compression: str = Field(
        default="none",
        description="Compression mode: none, light, symbol_substitution, aggressive.",
    )
    detail: str = Field(
        default="standard", description="Detail level: summary, standard, deep."
    )

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        valid = {"map", "packet", "handoff", "collision", "symbols", "digest"}
        if v not in valid:
            raise ValueError(
                f"Invalid mode '{v}'. Must be one of: {', '.join(sorted(valid))}"
            )
        return v

    @field_validator("compression")
    @classmethod
    def _validate_compression(cls, v: str) -> str:
        valid = {"none", "light", "symbol_substitution", "aggressive"}
        if v not in valid:
            raise ValueError(
                f"Invalid compression '{v}'. Must be one of: {', '.join(sorted(valid))}"
            )
        return v

    @field_validator("detail")
    @classmethod
    def _validate_detail(cls, v: str) -> str:
        valid = {"summary", "standard", "deep"}
        if v not in valid:
            raise ValueError(
                f"Invalid detail '{v}'. Must be one of: {', '.join(sorted(valid))}"
            )
        return v


class GetContextResult(BaseModel):
    """Result from rig.get_context."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.context_packet.v1"
    context_id: str = ""
    mode: str = "map"
    request_sha256: str = ""
    repo: dict[str, Any] = Field(default_factory=dict)
    subsystems: list[dict[str, Any]] = Field(default_factory=list)
    active_work: dict[str, Any] = Field(default_factory=dict)
    recommended_context: list[dict[str, Any]] = Field(default_factory=list)
    do_not_touch: list[dict[str, Any]] = Field(default_factory=list)
    summary_text: str = ""
    receipt: dict[str, Any] = Field(default_factory=dict)
    canonical_packet_sha256: str | None = None
    optimized_packet_sha256: str | None = None


class GetContextToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_subsystems: int = Field(
        default=20, description="Maximum number of subsystems to return."
    )
    max_recommendations: int = Field(
        default=10, description="Maximum recommended context entries."
    )


class GetContextState(BaseToolState):
    pass


class GetContext(
    BaseTool[GetContextArgs, GetContextResult, GetContextToolConfig, GetContextState],
    ToolUIData[GetContextArgs, GetContextResult],
):
    description: ClassVar[str] = (
        "Get governed repository context: repo topology, subsystem map, "
        "active work lanes, collision warnings, and recommended context files. "
        "Call this BEFORE planning or editing to understand the landscape "
        "and avoid colliding with other agents. Read-only, receipt-backed."
    )
    determinism_class: ClassVar[ToolDeterminismClass] = (
        ToolDeterminismClass.DETERMINISTIC_REPO_STATE
    )
    mutation_class: ClassVar[ToolMutationClass] = ToolMutationClass.READ_ONLY

    @classmethod
    def format_call_display(cls, args: GetContextArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary=f"Getting context (mode={args.mode})")

    @classmethod
    def get_result_display(cls, event: Any) -> Any:
        if not isinstance(event.result, GetContextResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        r = event.result
        sys_count = len(r.subsystems)
        lane_count = len(r.active_work.get("lanes", []))
        coll_count = len(r.active_work.get("collision_warnings", []))
        msg = f"Context: {sys_count} subsystems, {lane_count} active lanes"
        if coll_count:
            msg += f", {coll_count} collision warnings"
        return ToolResultDisplay(success=True, message=msg)

    @classmethod
    def get_status_text(cls) -> str:
        return "Gathering context"

    async def run(
        self, args: GetContextArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | GetContextResult, None]:
        try:
            # Build the request model
            request = ContextRequest(
                mode=ContextMode(args.mode),
                mission_id=args.mission_id,
                agent_id=args.agent_id,
                scope=ContextScope(
                    paths=args.scope_paths,
                    symbols=args.scope_symbols,
                    include_tests=args.include_tests,
                    include_docs=args.include_docs,
                    include_receipts=args.include_receipts,
                    include_other_agents=args.include_other_agents,
                ),
                budget=ContextBudget(
                    max_tokens=args.max_tokens,
                    compression=CompressionMode(args.compression),
                    detail=DetailLevel(args.detail),
                ),
            )

            # Execute (read-only, no side effects)
            packet = execute(request)

            # Build receipt
            receipt = build_receipt(packet)

            yield GetContextResult(
                context_id=packet.context_id,
                mode=packet.mode.value,
                request_sha256=packet.request_sha256,
                repo=packet.repo.model_dump(mode="json"),
                subsystems=[s.model_dump(mode="json") for s in packet.subsystems],
                active_work=packet.active_work,
                recommended_context=[
                    r.model_dump(mode="json") for r in packet.recommended_context
                ],
                do_not_touch=[d.model_dump(mode="json") for d in packet.do_not_touch],
                summary_text=packet.summary_text,
                receipt=receipt.model_dump(mode="json"),
                canonical_packet_sha256=packet.canonical_packet_sha256,
                optimized_packet_sha256=packet.optimized_packet_sha256,
            )

        except Exception as e:
            raise ToolError(f"get_context failed: {e}") from e
