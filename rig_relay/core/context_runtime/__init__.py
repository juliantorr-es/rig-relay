"""ContextRuntime — governed and ad-hoc context assembly and injection.

Phase 2 extraction target:
  ContextEnvelopeMixin → ContextRuntime

Fixes Defect 2: governed context packet output now reaches the model
by setting _current_context_envelope and injecting system messages
in both code paths (not just the ad-hoc path).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rig_relay.core.logger import logger
from rig_relay.core.types import LLMMessage, Role

if TYPE_CHECKING:
    from pathlib import Path

    from rig_relay.context.compiler import ContextCompiler
    from rig_relay.context.models import ContextEnvelopeReceipt
    from rig_relay.core.telemetry.send import TelemetryClient
    from rig_relay.core.types import MessageList
    from rig_relay.governance.mission_context_packet import (
        MissionContextPacket,
        MissionContextPacketReceipt,
    )


class ContextRuntime:
    """Owns context assembly and injection.

    Replaces ContextEnvelopeMixin with explicit dependency injection.
    """

    __slots__ = (
        "_config",
        "_workspace_root",
        "_session_id",
        "_messages",
        "_telemetry_client",
        "_context_compiler",
        "_governed_context_enabled",
        "_current_context_envelope",
        "_governed_context_packet",
        "_governed_context_receipt",
    )

    def __init__(
        self,
        *,
        config: Any,
        workspace_root: Path,
        session_id: str,
        messages: MessageList,
        telemetry_client: TelemetryClient,
        context_compiler: ContextCompiler | None,
        governed_context_enabled: bool,
    ) -> None:
        self._config = config
        self._workspace_root = workspace_root
        self._session_id = session_id
        self._messages: MessageList = messages
        self._telemetry_client = telemetry_client
        self._context_compiler = context_compiler
        self._governed_context_enabled = governed_context_enabled

        self._current_context_envelope: ContextEnvelopeReceipt | None = None
        self._governed_context_packet: MissionContextPacket | None = None
        self._governed_context_receipt: MissionContextPacketReceipt | None = None

    @property
    def current_envelope(self) -> ContextEnvelopeReceipt | None:
        return self._current_context_envelope

    async def build_context(self, user_msg: str) -> ContextEnvelopeReceipt | None:
        """Build context envelope and inject system messages.

        Returns the ContextEnvelopeReceipt (or None) for turn tracking.
        """
        if self._governed_context_enabled:
            return await self._build_governed()
        return await self._build_ad_hoc(user_msg)

    async def _build_governed(self) -> ContextEnvelopeReceipt | None:
        try:
            from rig_relay.context.models import ContextEnvelopeReceipt
            from rig_relay.governance.context_envelope_bridge import (
                compile_governed_context,
            )

            packet, receipt, issues = compile_governed_context(
                repo_root=self._workspace_root,
                mission_id=self._session_id,
                title=f"AgentLoop session {self._session_id[:8]}",
            )

            self._governed_context_packet = packet
            self._governed_context_receipt = receipt

            governed_prompt = self._render_governed_prompt(packet, issues)
            if governed_prompt:
                context_block = LLMMessage(
                    role=Role.system, content=governed_prompt, injected=True
                )
                if self._messages and self._messages[-1].role == Role.user:
                    self._messages.insert(-1, context_block)
                else:
                    self._messages.append(context_block)

            envelope = ContextEnvelopeReceipt(
                session_id=self._session_id,
                envelope_id=packet.packet_id,
                rendered_prompt=governed_prompt or "",
                section_count=len(packet.source_refs),
                dirty_file_count=len(packet.dirty_file_states),
            )
            self._current_context_envelope = envelope

            if getattr(self._config, "enable_local_observability", False):
                try:
                    self._telemetry_client.send_context_envelope_governed_compiled(
                        session_id=self._session_id,
                        packet_id=packet.packet_id,
                        source_ref_count=len(packet.source_refs),
                        dirty_file_count=len(packet.dirty_file_states),
                        blocker_count=len(packet.blockers),
                        warning_count=len(packet.warnings),
                    )
                except Exception:
                    pass

            return envelope

        except Exception:
            logger.warning("Failed to build governed context envelope", exc_info=True)
            return None

    async def _build_ad_hoc(self, user_msg: str) -> ContextEnvelopeReceipt | None:
        compiler = self._context_compiler
        if compiler is None:
            return None

        try:
            envelope = compiler.build_envelope(
                user_text=user_msg, snapshot=None, messages=list(self._messages)
            )
            self._current_context_envelope = envelope

            if envelope.rendered_prompt and envelope.section_count > 0:
                context_block = LLMMessage(
                    role=Role.system, content=envelope.rendered_prompt, injected=True
                )
                if self._messages and self._messages[-1].role == Role.user:
                    self._messages.insert(-1, context_block)
                else:
                    self._messages.append(context_block)

            if getattr(self._config, "enable_local_observability", False):
                try:
                    self._telemetry_client.send_context_envelope_governed_ad_hoc(
                        session_id=self._session_id
                    )
                except Exception:
                    pass

            return envelope

        except Exception:
            logger.warning("Failed to build context envelope", exc_info=True)
            return None

    @staticmethod
    def _render_governed_prompt(packet: Any, issues: list[str]) -> str:
        lines: list[str] = []
        lines.append("[GOVERNED CONTEXT]")
        lines.append(f"Workspace: {packet.repo_root}")
        lines.append(f"Branch: {packet.branch}")
        lines.append(f"HEAD: {packet.head}")

        if packet.source_refs:
            lines.append("\nSource references:")
            for ref in packet.source_refs:
                lines.append(
                    f"  - {ref.path}: {ref.sha256[:8] if ref.sha256 else 'no-sha'}"
                )

        if hasattr(packet, "dirty_file_states") and packet.dirty_file_states:
            lines.append("\nDirty files (protected):")
            for df in packet.dirty_file_states:
                lines.append(f"  - {df.path} [{df.status}]")

        if hasattr(packet, "blockers") and packet.blockers:
            lines.append("\nBLOCKERS:")
            for b in packet.blockers:
                lines.append(f"  - {b.message}")

        if hasattr(packet, "warnings") and packet.warnings:
            lines.append("\nWarnings:")
            for w in packet.warnings:
                lines.append(f"  - {w.message}")

        if issues:
            lines.append("\nIssues:")
            for issue in issues:
                lines.append(f"  - {issue}")

        return "\n".join(lines)
