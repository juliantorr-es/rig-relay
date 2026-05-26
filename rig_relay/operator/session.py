from __future__ import annotations

from collections.abc import AsyncGenerator
import hashlib as _hasher
from typing import TYPE_CHECKING

from rig_relay.core.agents.models import BuiltinAgentName
from rig_relay.core.logger import logger
from rig_relay.operator.models import (
    OperatorSession,
    OperatorSessionStatus,
    ProposalDisposition,
    ProposalResult,
    ToolActivity,
)
from rig_relay.operator.projection import OperatorSessionProjector

if TYPE_CHECKING:
    from rig_relay.core.agent_loop import AgentLoop
    from rig_relay.core.config import VibeConfig
    from rig_relay.core.types import BaseEvent, ToolResultEvent
    from rig_relay.digestion.intake import IntakeResult

_RIG_OPERATOR_MISSION_PREFIX = "rig-operator-mission"

_DEFAULT_INVESTIGATION_PROMPT = (
    "Study this repository thoroughly using read-only tools. "
    "Read project files (README, build configs, package manifests, CI configs, "
    "source structure, license files, contributing docs). "
    "Then propose the minimum publication bootstrap a public project page would need: "
    "project name and description, supported ecosystems, build/run instructions, "
    "dependency summary, license status, CI readiness, and documentation gaps. "
    "Do NOT modify any files. "
    "Report your findings as a structured summary, not raw file contents. "
    "Use the grep, read_file, git, and inspect_structure tools. "
    "For any required mutations (creating new files, editing), "
    "propose them as explicit governed proposals rather than executing them."
)


class RepositoryOperatorSessionService:
    """Typed application service for repository operator investigation sessions.

    Runs the real AgentLoop over an imported workspace through hardened
    built-in tools and surfaced tool refusal/proposal-needed dispositions.
    Produces content-light projections for Gridline rendering.

    Does NOT create governed proposal artifacts — only records that a
    mutation was refused and a governed proposal would be required.
    Real proposal creation through the authoritative proposal boundary
    (PatchGatingService, ProposalWorkflowStore, CouncilGate) is deferred
    to a K/L integration pass.

    Owns: AgentLoop product-integration, repository-operator session lifecycle,
    tool refusal/proposal-needed disposition tracking, and projector assembly.

    Consumes: digestion (IntakeResult), VibeConfig, hardened tool boundary.
    Deferred: recovery/materialization (Lane B not remotely published),
              local inference (M0 not released),
              real governed proposal creation (K/L integration pass).
    """

    def __init__(self, *, config: VibeConfig | None = None) -> None:
        self._sessions: dict[str, OperatorSession] = {}
        self._config = config

    @property
    def active_sessions(self) -> int:
        _terminal = {
            OperatorSessionStatus.COMPLETED,
            OperatorSessionStatus.FAILED,
            OperatorSessionStatus.REFUSED,
        }
        return sum(1 for s in self._sessions.values() if s.status not in _terminal)

    def open_session(
        self,
        intake_result: IntakeResult,
        purpose: str,
        *,
        agent_profile_name: str = BuiltinAgentName.PLAN,
    ) -> OperatorSession:
        """Open a bounded operator investigation session.

        Args:
            intake_result: The preview intake result from RepositoryIntakeService.
            purpose: Investigation purpose (e.g., "study for publication bootstrap").
            agent_profile_name: Which built-in agent profile to use (default: plan).

        Returns:
            An OperatorSession with OPENED status and workspace metadata.
        """
        repo = intake_result.repository
        workspace_root = repo.root_path
        workspace_digest = _hasher.sha256(
            f"{workspace_root}:{repo.head_sha or 'no-head'}".encode()
        ).hexdigest()

        session = OperatorSession(
            workspace_root=workspace_root,
            workspace_digest=workspace_digest,
            repository_label=repo.root_path.rsplit("/", 1)[-1],
            purpose=purpose,
            status=OperatorSessionStatus.OPENED,
            agent_profile_name=agent_profile_name,
        )
        self._sessions[session.session_id] = session
        logger.info(
            "operator session opened: session_id=%s repo=%s purpose=%s",
            session.session_id,
            session.repository_label,
            purpose,
        )
        return session

    def get_session(self, session_id: str) -> OperatorSession | None:
        return self._sessions.get(session_id)

    def get_projection(self, session_id: str) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return OperatorSessionProjector.build_projection(session)

    def close_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        if session.status not in {
            OperatorSessionStatus.COMPLETED,
            OperatorSessionStatus.REFUSED,
            OperatorSessionStatus.FAILED,
        }:
            session.status = OperatorSessionStatus.COMPLETED
        session.evidence_sha256 = OperatorSessionProjector._compute_evidence_digest(
            session
        )

    async def investigate(
        self, session_id: str, *, prompt: str | None = None
    ) -> AsyncGenerator[dict, None]:
        """Run AgentLoop investigation on the session's workspace.

        Yields content-light projection snapshots as AgentLoop executes
        tool calls and produces results. The plan agent profile prevents
        direct mutations — any write attempt is refused and recorded as a
        proposed disposition.

        Args:
            session_id: Session to investigate.
            prompt: Investigation prompt (defaults to publication-bootstrap study).

        Yields:
            Dict projections suitable for Gridline rendering.
        """
        session = self._sessions.get(session_id)
        if session is None:
            yield {"error": "session_not_found", "session_id": session_id}
            return

        if session.status not in {
            OperatorSessionStatus.OPENED,
            OperatorSessionStatus.AWAITING_PROPOSAL,
        }:
            yield {
                "error": "session_not_investigable",
                "session_id": session_id,
                "status": session.status.value,
            }
            return

        investigation_prompt = prompt or _DEFAULT_INVESTIGATION_PROMPT

        agent_loop = self._create_agent_loop(session)
        if agent_loop is None:
            session.status = OperatorSessionStatus.INFERENCE_NEEDED
            session.error_message = (
                "No LLM backend configured. Configure a provider and model "
                "in ~/.rig/relay/config.toml before running investigations."
            )
            yield OperatorSessionProjector.build_projection(session)
            return

        session.status = OperatorSessionStatus.INVESTIGATING
        yield OperatorSessionProjector.build_projection(session)

        try:
            client_message_id = f"{_RIG_OPERATOR_MISSION_PREFIX}-{session_id[:8]}"
            async for event in agent_loop.act(
                investigation_prompt, client_message_id=client_message_id
            ):
                self._record_event(session, event)
                yield OperatorSessionProjector.build_projection(session)

        except Exception as exc:
            logger.error(
                "operator investigation failed: session_id=%s error=%s",
                session_id,
                exc,
                exc_info=True,
            )
            session.status = OperatorSessionStatus.FAILED
            # Content-safe: hash the exception to avoid leaking file paths
            # or API error details into projections. Full error is
            # available in the logger output only.
            session.error_message = (
                f"{type(exc).__name__}: investigation failed "
                f"(error_hash={_hasher.sha256(str(exc).encode()).hexdigest()[:16]})"
            )
            yield OperatorSessionProjector.build_projection(session)
        else:
            if session.status == OperatorSessionStatus.INVESTIGATING:
                session.status = OperatorSessionStatus.PROPOSAL_GENERATED
            yield OperatorSessionProjector.build_projection(session)

    def _create_agent_loop(self, session: OperatorSession) -> AgentLoop | None:
        """Create a plan-profile AgentLoop for the session workspace.

        Returns None if no backend is configured (surfaces INFERENCE_NEEDED).
        """
        from pathlib import Path

        from rig_relay.core.agent_loop import AgentLoop
        from rig_relay.core.config import VibeConfig
        from rig_relay.core.telemetry.types import EntrypointMetadata

        config = self._config or VibeConfig.load()

        try:
            config.get_active_model()
        except ValueError:
            return None

        entrypoint_metadata = EntrypointMetadata(
            agent_entrypoint="unknown",
            agent_version="0.1.0",
            client_name="rig_relay_operator",
            client_version="0.1.0",
        )

        workspace_root = Path(session.workspace_root)

        try:
            return AgentLoop(
                config,
                agent_name=session.agent_profile_name,
                enable_streaming=False,
                entrypoint_metadata=entrypoint_metadata,
                defer_heavy_init=False,
                workspace_root=workspace_root,
            )
        except Exception as exc:
            logger.error(
                "failed to create agent loop for operator session: %s",
                exc,
                exc_info=True,
            )
            return None

    def _record_event(self, session: OperatorSession, event: BaseEvent) -> None:
        """Record tool activity and proposal dispositions from AgentLoop events."""
        from rig_relay.core.types import ToolResultEvent

        if isinstance(event, ToolResultEvent):
            self._record_tool_result(session, event)

    def _record_tool_result(
        self, session: OperatorSession, event: ToolResultEvent
    ) -> None:
        tool_name = event.tool_name
        activity = _find_or_create_activity(session, tool_name)

        if event.error:
            activity.failure_count += 1
        elif event.skipped:
            activity.refusal_count += 1
            session.refusal_count += 1
            if tool_name in {"write_file", "search_replace", "bash"}:
                # Content-safe: description never includes skip_reason
                # which could leak file paths. Uses a generic label.
                session.proposals.append(
                    ProposalResult(
                        session_id=session.session_id,
                        scope=tool_name,
                        description=(
                            f"Mutation tool '{tool_name}' refused by governed "
                            f"permission boundary. A governed proposal would be "
                            f"required to proceed."
                        ),
                        disposition=ProposalDisposition.BLOCKED_BY_PERMISSION,
                    )
                )
        else:
            activity.success_count += 1

        activity.call_count += 1
        activity.last_call_at = _now_iso()


def _find_or_create_activity(session: OperatorSession, tool_name: str) -> ToolActivity:
    for act in session.tool_activities:
        if act.tool_name == tool_name:
            return act
    act = ToolActivity(tool_name=tool_name)
    session.tool_activities.append(act)
    return act


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
