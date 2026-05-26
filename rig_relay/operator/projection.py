from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from rig_relay.operator.models import (
    OperatorSession,
    OperatorSessionProjection,
    OperatorSessionStatus,
    ProposalDisposition,
)

_STATE_PHASE_MAP: Mapping[OperatorSessionStatus, str] = {
    OperatorSessionStatus.OPENED: "ready",
    OperatorSessionStatus.INVESTIGATING: "investigating",
    OperatorSessionStatus.AWAITING_PROPOSAL: "awaiting_proposal",
    OperatorSessionStatus.PROPOSAL_GENERATED: "proposal_generated",
    OperatorSessionStatus.COMPLETED: "completed",
    OperatorSessionStatus.BLOCKED: "blocked",
    OperatorSessionStatus.REFUSED: "refused",
    OperatorSessionStatus.INFERENCE_NEEDED: "inference_needed",
    OperatorSessionStatus.FAILED: "failed",
}

_DEFERRED_INTEGRATIONS = [
    "recovery_materialization: Lane B canonical materialization boundary not "
    "remotely published; materialization and recovery handoff deferred.",
    "local_inference: M0 local inference product orchestration not released; "
    "local model execution unavailable.",
    "github_publication: J0 GitHub/publication authority not released; "
    "publication operations deferred.",
    "project_profile: L0 context assembly/project-profile derivation not yet "
    "consumed; final project-page compilation deferred.",
    "governed_proposal_creation: real proposal artifacts through the "
    "authoritative proposal boundary (PatchGatingService, ProposalWorkflowStore) "
    "deferred to K/L integration pass. K0 records refusal dispositions only.",
    "workspace_live_integration: J0 imported-workspace contract not yet "
    "released; K0 consumes IntakeResult fixture-backed contract. Live "
    "imported-workspace integration deferred to J post-release.",
]


class OperatorSessionProjector:
    """Projects operator session state for Gridline rendering.

    Builds content-light projections that never include raw file contents,
    prompts, model outputs, or secrets. All content references use SHA256
    hashes or structured counts.
    """

    @staticmethod
    def build_projection(session: OperatorSession) -> dict:
        """Build a content-light projection from an operator session.

        Args:
            session: The operator session to project.

        Returns:
            A dict conforming to the OperatorSessionProjection model.
        """
        disposition_counts: dict[str, int] = {}
        for p in session.proposals:
            key = p.disposition.value
            disposition_counts[key] = disposition_counts.get(key, 0) + 1

        pending_decisions: list[str] = []
        for p in session.proposals:
            if p.disposition == ProposalDisposition.PROPOSED:
                pending_decisions.append(f"proposal:{p.scope}:{p.description[:80]}")

        blocked_capabilities: list[str] = []
        if session.status == OperatorSessionStatus.INFERENCE_NEEDED:
            blocked_capabilities.append(
                "llm_backend: no configured provider/model found"
            )
        if session.error_message and session.status == OperatorSessionStatus.FAILED:
            # Safe: error_message now uses a hash, not raw exception text
            blocked_capabilities.append(f"error:{session.error_message[:120]}")

        evidence_integrity = "ok"
        if session.status == OperatorSessionStatus.FAILED:
            evidence_integrity = "compromised"
        elif session.evidence_sha256 is None:
            evidence_integrity = "pending"

        projection = OperatorSessionProjection(
            session_id=session.session_id,
            repository_label=session.repository_label,
            purpose=session.purpose,
            status=session.status.value,
            phase=_STATE_PHASE_MAP.get(session.status, "unknown"),
            tool_summary=session.tool_activities,
            proposal_count=len(session.proposals),
            proposal_dispositions=disposition_counts,
            refusal_count=session.refusal_count,
            pending_decisions=pending_decisions,
            blocked_capabilities=blocked_capabilities,
            deferred_integrations=_DEFERRED_INTEGRATIONS,
            recovery_materialization_available=False,
            evidence_integrity=evidence_integrity,
            error_message=session.error_message,
            created_at=session.created_at,
            updated_at=datetime.now(UTC).isoformat(),
        )
        return projection.model_dump()

    @staticmethod
    def _compute_evidence_digest(session: OperatorSession) -> str:
        """Compute a deterministic evidence digest from session state.

        Content-light: uses tool counts, status, and proposal IDs,
        not raw content.
        """
        import hashlib

        parts: list[str] = [
            session.session_id,
            session.workspace_digest,
            session.status.value,
            str(session.refusal_count),
        ]
        for a in sorted(session.tool_activities, key=lambda x: x.tool_name):
            parts.append(
                f"{a.tool_name}:{a.call_count}:{a.success_count}:"
                f"{a.failure_count}:{a.refusal_count}"
            )
        for p in sorted(session.proposals, key=lambda x: x.proposal_id):
            parts.append(f"{p.proposal_id}:{p.disposition.value}")
        return f"sha256:{hashlib.sha256(':'.join(parts).encode()).hexdigest()}"
