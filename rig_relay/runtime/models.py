"""Rig Relay Runtime Model Types — Ported from Rig domain/runtime.py.

Provides the foundational runtime enums and models for provider kinds,
trust tiers, capabilities, and invocation status.

Provenance (Rig-to-Relay porting doctrine):
  Porting status: port_direct (Rig source: rig/domain/runtime.py).
  See docs/governance/rig-to-relay-pattern-inventory.md for pattern map.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

# =============================================================================
# Enums
# =============================================================================


class RuntimeProviderKind(StrEnum):
    """Kinds of runtime providers."""

    LOCAL = "local"
    CLI = "cli"
    CUSTOM = "custom"
    DRY_RUN = "dry_run"
    STUB = "stub"
    LOCAL_INFERENCE = "local_inference"


class RuntimeProviderTrustTier(StrEnum):
    """Trust tiers for runtime providers.

    Lower tiers have fewer permissions. Higher tiers have more capabilities.
    This is advisory — Rig Relay remains the final authority.
    """

    BLOCKED = "blocked"
    ADVISORY = "advisory"
    REVIEWER = "reviewer"
    PLANNER = "planner"
    EXECUTOR_CANDIDATE = "executor_candidate"
    VALIDATOR = "validator"


class RuntimeProviderStatus(StrEnum):
    """Operational status of a runtime provider."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    ERROR = "error"


class RuntimeCapabilityKind(StrEnum):
    """Kinds of runtime capabilities.

    Includes Rig's original capability kinds plus Rig Relay extensions.
    """

    # Rig-original capability kinds
    FILE_READ = "file_read"
    FILE_WRITE_PROPOSAL = "file_write_proposal"
    SHELL_PROPOSAL = "shell_proposal"
    PATCH_PROPOSAL = "patch_proposal"
    REPLAY_ACCESS = "replay_access"
    NETWORK_FETCH_PROPOSAL = "network_fetch_proposal"
    DOCS_FETCH_PROPOSAL = "docs_fetch_proposal"
    TELEMETRY_EXPORT_PROPOSAL = "telemetry_export_proposal"

    # Rig Relay extensions
    VALIDATION = "validation"
    RECEIPT_READ = "receipt_read"
    COORDINATION_READ = "coordination_read"
    COORDINATION_WRITE = "coordination_write"
    WORKTREE_READ = "worktree_read"
    WORKTREE_WRITE = "worktree_write"


class RuntimeInvocationStatus(StrEnum):
    """Status of a runtime invocation."""

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


# =============================================================================
# Models
# =============================================================================


class RuntimeCapability(BaseModel):
    """A runtime capability with kind and scope."""

    model_config = ConfigDict(extra="forbid")

    capability_kind: RuntimeCapabilityKind
    scope: str = "request"


class RuntimeProviderDescriptor(BaseModel):
    """Content-light descriptor for a runtime provider.

    Content-light subset of Rig's RuntimeProvider frozen dataclass.
    Contains only identifying metadata — no executable paths, manifests,
    or capability details.
    """

    model_config = ConfigDict(extra="forbid")

    provider_id: str
    kind: RuntimeProviderKind = RuntimeProviderKind.CUSTOM
    trust_tier: RuntimeProviderTrustTier = RuntimeProviderTrustTier.ADVISORY
    status: RuntimeProviderStatus = RuntimeProviderStatus.UNAVAILABLE
    version: str = "unknown"
