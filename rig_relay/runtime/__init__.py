"""rig_relay.runtime — Agent loop, provider boundary, tool registry.

Target package for migrating:
  vibe/core/agent_loop.py
  vibe/core/llm/
  vibe/core/tools/builtins/
"""

from __future__ import annotations

from rig_relay.runtime.context import RuntimeContext, RuntimeContextResolution
from rig_relay.runtime.context_resolver import RuntimeContextResolver
from rig_relay.runtime.models import (
    RuntimeCapability,
    RuntimeCapabilityKind,
    RuntimeInvocationStatus,
    RuntimeProviderDescriptor,
    RuntimeProviderKind,
    RuntimeProviderStatus,
    RuntimeProviderTrustTier,
)

__all__ = [
    "RuntimeCapability",
    "RuntimeCapabilityKind",
    "RuntimeContext",
    "RuntimeContextResolution",
    "RuntimeContextResolver",
    "RuntimeInvocationStatus",
    "RuntimeProviderDescriptor",
    "RuntimeProviderKind",
    "RuntimeProviderStatus",
    "RuntimeProviderTrustTier",
]
