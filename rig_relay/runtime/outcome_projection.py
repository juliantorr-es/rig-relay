"""Runtime Outcome Projection Contract v1.

Converts a model-visible AgentToolOutcome into a durable, content-light
projection event suitable for read-side evidence, reporting, and future
Lane D1 recovered-intent integration.

Invariant: For every model-visible <rig-tool-outcome> emitted through
ToolResultRuntime, there is exactly one matching durable projection event
with the same canonical outcome digest and identity fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
import uuid


@dataclass
class OutcomeProjectionEvent:
    """Content-light projection of a model-visible tool outcome.

    Schema-bound to rig.relay.runtime_outcome_projection_event.v1.
    """

    schema_version: str = "rig.relay.runtime_outcome_projection_event.v1"
    event_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    correlation_id: str = ""
    causation_id: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    tool_mutation_class: str = ""
    tool_determinism_class: str = ""
    status: str = ""
    answer_kind: str = ""
    error_kind: str = ""
    refusal_code: str = ""
    recoverable: bool | None = None
    retryable: bool = False
    retryability_basis: str = ""
    mutation_disposition: str = "not_applicable"
    degraded_capabilities: list[str] = field(default_factory=list)
    investigation_outcome: str = ""
    authority_decision: str = ""
    authority_source: str = ""
    cache_hit: bool = False
    output_kind: str = "inline"
    artifact_evidence_sha256: str = ""
    git_summary_hash: str = ""
    model_visible_outcome_digest: str = ""
    outcome_annotation_hash: str = ""
    content_light: bool = True
    created_at: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)


def _sha256(data: str) -> str:
    return f"sha256:{hashlib.sha256(data.encode('utf-8')).hexdigest()}"


def build_projection_event(
    outcome: Any,
    *,
    output_kind: str = "inline",
    artifact_evidence_sha256: str = "",
    annotation_text: str = "",
) -> OutcomeProjectionEvent:
    """Build a durable projection event from a canonical AgentToolOutcome.

    Args:
        outcome: An AgentToolOutcome instance.
        output_kind: The ToolOutputKind classification for this result.
        artifact_evidence_sha256: SHA256 of artifact evidence, if artifacted.
        annotation_text: The full <rig-tool-outcome>...</rig-tool-outcome> annotation
                        text that was delivered to the model.

    Returns:
        An OutcomeProjectionEvent ready for durable persistence.
    """
    outcome_json = (
        outcome.model_dump_json(exclude_none=True)
        if hasattr(outcome, "model_dump_json")
        else json.dumps(asdict(outcome))
    )  # type: ignore[arg-type]
    outcome_digest = _sha256(outcome_json)

    annotation_hash = ""
    if annotation_text:
        annotation_hash = _sha256(annotation_text)

    return OutcomeProjectionEvent(
        event_id=str(uuid.uuid4()),
        session_id=getattr(outcome, "session_id", "") or "",
        turn_id=getattr(outcome, "turn_id", "") or "",
        correlation_id=getattr(outcome, "correlation_id", "") or "",
        causation_id=getattr(outcome, "causation_id", "") or "",
        tool_name=getattr(outcome, "tool_name", ""),
        tool_call_id=getattr(outcome, "tool_call_id", ""),
        status=getattr(outcome, "status", ""),
        answer_kind=getattr(outcome, "answer_kind", "") or "",
        error_kind=getattr(outcome, "error_kind", "") or "",
        refusal_code=getattr(outcome, "refusal_code", "") or "",
        recoverable=getattr(outcome, "recoverable", None),
        retryable=bool(getattr(outcome, "retryable", False)),
        retryability_basis=getattr(outcome, "retryability_basis", "") or "",
        mutation_disposition=getattr(outcome, "mutation_disposition", "not_applicable"),
        degraded_capabilities=list(getattr(outcome, "degraded_capabilities", []) or []),
        investigation_outcome=getattr(outcome, "investigation_outcome", "") or "",
        authority_decision=getattr(outcome, "authority_decision", "") or "",
        authority_source=getattr(outcome, "authority_source", "") or "",
        cache_hit=bool(getattr(outcome, "cache_hit", False)),
        output_kind=output_kind,
        artifact_evidence_sha256=artifact_evidence_sha256,
        git_summary_hash=getattr(outcome, "git_summary_hash", "") or "",
        model_visible_outcome_digest=outcome_digest,
        outcome_annotation_hash=annotation_hash,
        content_light=True,
        created_at=datetime.now(UTC).isoformat(),
    )


__all__ = ["OutcomeProjectionEvent", "build_projection_event"]
