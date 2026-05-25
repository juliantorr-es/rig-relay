"""ContextRuntime — context-envelope assembly and injection.

Phase 2 extraction — absorbed from former ContextEnvelopeMixin;
that mixin module is now deleted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rig_relay.core.logger import logger
from rig_relay.core.paths._vibe_home import SESSIONS_ROOT
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
        "_tool_manager",
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
        tool_manager: Any = None,
    ) -> None:
        self._config = config
        self._workspace_root = workspace_root
        self._session_id = session_id
        self._messages: MessageList = messages
        self._telemetry_client = telemetry_client
        self._context_compiler = context_compiler
        self._governed_context_enabled = governed_context_enabled
        self._tool_manager = tool_manager

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

    async def report_context_assembly(self, active_model: Any) -> None:
        if not getattr(self._config, "enable_local_observability", False):
            return

        try:
            from rig_relay.context.assembler import (
                build_context_assembly_report,
                build_shadow_request_report,
                load_latest_layout,
                plan_context_layout,
                write_assembly_report,
                write_layout_plan,
                write_shadow_request_report,
            )

            tool_manager_info = None
            if self._tool_manager is not None and hasattr(
                self._tool_manager, "available_tools"
            ):
                tm = self._tool_manager
                if tm.available_tools:
                    tool_manager_info = {
                        tool_name: tool_class.get_parameters()
                        for tool_name, tool_class in tm.available_tools.items()
                    }

            report = build_context_assembly_report(
                session_id=self._session_id,
                messages=list(self._messages),
                model=active_model.alias,
                tool_manager_info=tool_manager_info,
            )

            import hashlib as _hashlib

            assembly_path = await write_assembly_report(report)

            prev_layout = await load_latest_layout(self._session_id)
            layout = plan_context_layout(report, prev_layout)
            layout_path = await write_layout_plan(layout)
            session_root = SESSIONS_ROOT.path / self._session_id
            assembly_relative_path = assembly_path.relative_to(session_root).as_posix()
            layout_relative_path = layout_path.relative_to(session_root).as_posix()
            assembly_hash = (
                f"sha256:{_hashlib.sha256(assembly_path.read_bytes()).hexdigest()}"
            )
            layout_hash = (
                f"sha256:{_hashlib.sha256(layout_path.read_bytes()).hexdigest()}"
            )

            self._telemetry_client.send_context_assembly_reported(
                session_id=self._session_id,
                report_id=report.report_id,
                total_bytes=report.total_bytes,
                total_estimated_tokens=report.total_estimated_tokens,
                stable_prefix_bytes=report.stable_prefix_bytes,
                dynamic_suffix_bytes=report.dynamic_suffix_bytes,
                cache_candidate_bytes=report.cache_candidate_bytes,
                stable_prefix_fingerprint=report.stable_prefix_fingerprint,
                dynamic_suffix_fingerprint=report.dynamic_suffix_fingerprint,
                largest_blocks=report.largest_blocks,
                optimization_hints=report.optimization_hints,
                evidence_relative_path=assembly_relative_path,
                evidence_sha256=assembly_hash,
            )

            self._telemetry_client.send_context_layout_planned(
                session_id=self._session_id,
                layout_id=layout.layout_id,
                stable_prefix_fingerprint=layout.stable_prefix_fingerprint,
                dynamic_suffix_fingerprint=layout.dynamic_suffix_fingerprint,
                stable_prefix_fingerprint_short=(
                    layout.stable_prefix_fingerprint_short or ""
                ),
                dynamic_suffix_fingerprint_short=(
                    layout.dynamic_suffix_fingerprint_short or ""
                ),
                stable_prefix_bytes=layout.stable_prefix_bytes,
                dynamic_suffix_bytes=layout.dynamic_suffix_bytes,
                ephemeral_bytes=layout.ephemeral_bytes,
                cache_candidate_bytes=layout.cache_candidate_bytes,
                cacheability_ratio=layout.cacheability_ratio,
                prefix_stability_status=layout.prefix_stability_status,
                prefix_change_reasons=layout.prefix_change_reasons,
                optimization_hints=layout.optimization_hints,
                layout_path=layout_relative_path,
                layout_hash=layout_hash,
                evidence_relative_path=layout_relative_path,
                evidence_sha256=layout_hash,
            )
            try:
                shadow_report = build_shadow_request_report(
                    session_id=self._session_id,
                    messages=list(self._messages),
                    report=report,
                    layout=layout,
                )
                shadow_path = await write_shadow_request_report(shadow_report)
                shadow_relative_path = shadow_path.relative_to(session_root).as_posix()
                shadow_hash = (
                    f"sha256:{_hashlib.sha256(shadow_path.read_bytes()).hexdigest()}"
                )
                self._telemetry_client.send_shadow_request_assembled(
                    session_id=self._session_id,
                    actual_message_count=shadow_report.actual_message_count,
                    shadow_message_count=shadow_report.shadow_message_count,
                    actual_estimated_tokens=shadow_report.actual_estimated_tokens,
                    shadow_estimated_tokens=shadow_report.shadow_estimated_tokens,
                    stable_prefix_bytes=shadow_report.stable_prefix_bytes,
                    dynamic_suffix_bytes=shadow_report.dynamic_suffix_bytes,
                    cache_candidate_bytes=shadow_report.cache_candidate_bytes,
                    estimated_token_delta=shadow_report.estimated_token_delta,
                    byte_delta=shadow_report.byte_delta,
                    unchanged_stable_prefix=shadow_report.unchanged_stable_prefix,
                    shadow_diff_summary=shadow_report.shadow_diff_summary,
                    stable_prefix_fingerprint=shadow_report.stable_prefix_fingerprint,
                    dynamic_suffix_fingerprint=shadow_report.dynamic_suffix_fingerprint,
                    evidence_relative_path=shadow_relative_path,
                    evidence_sha256=shadow_hash,
                )
            except Exception:
                pass
        except Exception as e:
            logger.warning("Failed to generate context assembly report: %s", e)
