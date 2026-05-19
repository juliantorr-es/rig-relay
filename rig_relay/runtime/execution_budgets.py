"""Execution budget constants and model for the agent execution spine.

CPU, memory, IO, and network budget constants that the supervisor,
agent loop, and tool execution machinery can reference for hard
boundaries.

See docs/json/roadmaps/ for the Agent Execution Spine v1 architecture
that consumes these budgets.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# CPU budgets (seconds)
# ---------------------------------------------------------------------------

# Maximum wall-clock time a single agent loop session may run.
AGENT_LOOP_MAX_TOTAL_RUNTIME_SECONDS = 1800

# Maximum wall-clock time a subagent (dispatched by orchestrator/fleet)
# may run before the supervisor cancels it.
SUBAGENT_MAX_RUNTIME_SECONDS = 300

# Default maximum wall-clock time for a single tool invocation.
# Individual tools may override this with a tighter bound.
TOOL_MAX_RUNTIME_SECONDS = 120

# ---------------------------------------------------------------------------
# Memory budgets (bytes)
# ---------------------------------------------------------------------------

# Maximum stdout bytes from a single bash invocation before truncation.
BASH_MAX_STDOUT_BYTES = 65536

# Maximum stderr bytes from a single bash invocation before truncation.
BASH_MAX_STDERR_BYTES = 65536

# Maximum size of a single context packet (mode=packet) in bytes.
CONTEXT_MAX_PACKET_BYTES = 5_000_000

# Maximum payload bytes for a single tool-call receipt.
RECEIPT_MAX_PAYLOAD_BYTES = 1_048_576

# ---------------------------------------------------------------------------
# IO budgets
# ---------------------------------------------------------------------------

# Maximum distinct files that a single context assembly may read.
CONTEXT_MAX_FILES_READ = 100

# Maximum output bytes (stdout + stderr combined) for a bash invocation.
BASH_MAX_OUTPUT_BYTES = 65536

# ---------------------------------------------------------------------------
# Network budget
# ---------------------------------------------------------------------------

# By default all outbound network calls are blocked. Individual tools
# or agent profiles may opt-in to network access through explicit
# NETWORK_FETCH_PROPOSAL capability gating.
NETWORK_DISABLED_BY_DEFAULT = True


class AgentExecutionBudgets(BaseModel):
    """Pydantic model validating execution budget constants.

    Provides a structured, serializable view of the budget constants
    so the agent execution spine, supervisor, and telemetry can
    reference them without importing bare module-level ints.
    """

    model_config = ConfigDict(extra="forbid")

    agent_loop_max_total_runtime_seconds: int = Field(
        default=AGENT_LOOP_MAX_TOTAL_RUNTIME_SECONDS, ge=1, le=86400
    )
    subagent_max_runtime_seconds: int = Field(
        default=SUBAGENT_MAX_RUNTIME_SECONDS, ge=1, le=86400
    )
    tool_max_runtime_seconds: int = Field(
        default=TOOL_MAX_RUNTIME_SECONDS, ge=1, le=3600
    )
    bash_max_stdout_bytes: int = Field(
        default=BASH_MAX_STDOUT_BYTES, ge=1, le=100_000_000
    )
    bash_max_stderr_bytes: int = Field(
        default=BASH_MAX_STDERR_BYTES, ge=1, le=100_000_000
    )
    context_max_packet_bytes: int = Field(
        default=CONTEXT_MAX_PACKET_BYTES, ge=1, le=50_000_000
    )
    receipt_max_payload_bytes: int = Field(
        default=RECEIPT_MAX_PAYLOAD_BYTES, ge=1, le=10_000_000
    )
    context_max_files_read: int = Field(default=CONTEXT_MAX_FILES_READ, ge=1, le=10000)
    bash_max_output_bytes: int = Field(
        default=BASH_MAX_OUTPUT_BYTES, ge=1, le=100_000_000
    )
    network_disabled_by_default: bool = Field(default=NETWORK_DISABLED_BY_DEFAULT)


__all__ = [
    "AGENT_LOOP_MAX_TOTAL_RUNTIME_SECONDS",
    "BASH_MAX_OUTPUT_BYTES",
    "BASH_MAX_STDERR_BYTES",
    "BASH_MAX_STDOUT_BYTES",
    "CONTEXT_MAX_FILES_READ",
    "CONTEXT_MAX_PACKET_BYTES",
    "NETWORK_DISABLED_BY_DEFAULT",
    "RECEIPT_MAX_PAYLOAD_BYTES",
    "SUBAGENT_MAX_RUNTIME_SECONDS",
    "TOOL_MAX_RUNTIME_SECONDS",
    "AgentExecutionBudgets",
]
