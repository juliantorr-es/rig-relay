"""Context envelope mixin for AgentLoop.

Extracted from agent_loop.py. Builds context envelopes from workspace
state (AGENTS.md, git state, dirty files) and injects them into the
message list. Also reports context assembly telemetry for layout
planning and prefix caching. Best-effort: failures are logged.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from rig_relay.core.logger import logger
from rig_relay.core.paths._vibe_home import SESSIONS_ROOT
from rig_relay.core.types import LLMMessage, Role

if TYPE_CHECKING:
    from rig_relay.core.config import ModelConfig


class ContextEnvelopeMixin:
    """Mixin providing context envelope construction and assembly telemetry."""

    async def _build_context_envelope(self, user_msg: str) -> None:
        compiler = self._context_compiler
        if compiler is None:
            return

        try:
            envelope = compiler.build_envelope(
                user_text=user_msg, snapshot=None, messages=list(self.messages)
            )
            self._current_context_envelope = envelope

            if envelope.rendered_prompt and envelope.section_count > 0:
                context_block = LLMMessage(
                    role=Role.system, content=envelope.rendered_prompt, injected=True
                )
                if self.messages and self.messages[-1].role == Role.user:
                    self.messages.insert(-1, context_block)
                else:
                    self.messages.append(context_block)
        except Exception:
            logger.warning("Failed to build context envelope", exc_info=True)

    async def _report_context_assembly(self, active_model: ModelConfig) -> None:
        if not self.config.enable_local_observability:
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
            if self.tool_manager.available_tools:
                tool_manager_info = {
                    tool_name: tool_class.get_parameters()
                    for tool_name, tool_class in self.tool_manager.available_tools.items()
                }

            report = build_context_assembly_report(
                session_id=self.session_id,
                messages=list(self.messages),
                model=active_model.alias,
                tool_manager_info=tool_manager_info,
            )

            assembly_path = await write_assembly_report(report)

            prev_layout = await load_latest_layout(self.session_id)
            layout = plan_context_layout(report, prev_layout)
            layout_path = await write_layout_plan(layout)
            session_root = SESSIONS_ROOT.path / self.session_id
            assembly_relative_path = assembly_path.relative_to(session_root).as_posix()
            layout_relative_path = layout_path.relative_to(session_root).as_posix()
            assembly_hash = (
                f"sha256:{hashlib.sha256(assembly_path.read_bytes()).hexdigest()}"
            )
            layout_hash = (
                f"sha256:{hashlib.sha256(layout_path.read_bytes()).hexdigest()}"
            )

            self.telemetry_client.send_context_assembly_reported(
                session_id=self.session_id,
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

            self.telemetry_client.send_context_layout_planned(
                session_id=self.session_id,
                layout_id=layout.layout_id,
                stable_prefix_fingerprint=layout.stable_prefix_fingerprint,
                dynamic_suffix_fingerprint=layout.dynamic_suffix_fingerprint,
                stable_prefix_fingerprint_short=layout.stable_prefix_fingerprint_short
                or "",
                dynamic_suffix_fingerprint_short=layout.dynamic_suffix_fingerprint_short
                or "",
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
                    session_id=self.session_id,
                    messages=list(self.messages),
                    report=report,
                    layout=layout,
                )
                shadow_path = await write_shadow_request_report(shadow_report)
                shadow_relative_path = shadow_path.relative_to(session_root).as_posix()
                shadow_hash = (
                    f"sha256:{hashlib.sha256(shadow_path.read_bytes()).hexdigest()}"
                )
                self.telemetry_client.send_shadow_request_assembled(
                    session_id=self.session_id,
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
