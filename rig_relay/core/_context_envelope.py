"""Context envelope mixin for AgentLoop — DEPRECATED.

Replaced by ContextRuntime (rig_relay/core/context_runtime).
All methods (build_context_envelope, report_context_assembly) now
delegate to ContextRuntime via explicit AgentLoop delegation methods.
This mixin remains in the MRO only for compatibility during migration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rig_relay.core.config import ModelConfig


class ContextEnvelopeMixin:
    """[DEPRECATED] Replaced by ContextRuntime.

    All methods are dead code. AgentLoop overrides them with
    delegations to ContextRuntime. Kept only for MRO compatibility.
    """

    async def _build_context_envelope(self, user_msg: str) -> None:
        raise NotImplementedError(
            "ContextEnvelopeMixin._build_context_envelope is deprecated. "
            "Use ContextRuntime.build_context() instead."
        )

    async def _build_context_envelope_governed(self) -> None:
        raise NotImplementedError(
            "ContextEnvelopeMixin._build_context_envelope_governed is deprecated. "
            "Use ContextRuntime.build_context() instead."
        )

    async def _build_context_envelope_ad_hoc(self, user_msg: str) -> None:
        raise NotImplementedError(
            "ContextEnvelopeMixin._build_context_envelope_ad_hoc is deprecated. "
            "Use ContextRuntime.build_context() instead."
        )

    async def _report_context_assembly(self, active_model: ModelConfig) -> None:
        raise NotImplementedError(
            "ContextEnvelopeMixin._report_context_assembly is deprecated. "
            "Use ContextRuntime.report_context_assembly() instead."
        )
