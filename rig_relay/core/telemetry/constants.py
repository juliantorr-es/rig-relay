from __future__ import annotations

from enum import StrEnum


class EventName(StrEnum):
    REQUEST_ACCOUNTED = "rig.relay.context.request_accounted"
    TOOL_CALL_COMPLETED = "rig.relay.tool.call_completed"
    TOOL_CALLED = "rig.relay.tool.called"
    TOOL_REASONING_TRACE = "rig.relay.tool.reasoning_trace"
    SESSION_STARTED = "rig.relay.session.started"
    SESSION_CLOSED = "rig.relay.session.closed"
    AUTO_COMPACT_TRIGGERED = "rig.relay.context.auto_compact_triggered"
    READY = "rig.relay.ready"
    AT_MENTION_INSERTED = "rig.relay.at_mention_inserted"
    USER_RATING_FEEDBACK = "rig.relay.user_rating_feedback"
    TELEPORT_COMPLETED = "rig.relay.teleport_completed"
    TELEPORT_FAILED = "rig.relay.teleport_failed"
    USER_COPIED_TEXT = "rig.relay.user_copied_text"
    USER_CANCELLED_ACTION = "rig.relay.user_cancelled_action"
    SLASH_COMMAND_USED = "rig.relay.slash_command_used"
    ONBOARDING_API_KEY_ADDED = "rig.relay.onboarding_api_key_added"
    ARTIFACT_WRITTEN = "rig.relay.artifact.tool_output_written"
    CONTEXT_ASSEMBLY_REPORTED = "rig.relay.context.assembly_reported"
    CONTEXT_LAYOUT_PLANNED = "rig.relay.context.layout_planned"
    SHADOW_REQUEST_ASSEMBLED = "rig.relay.context.shadow_request_assembled"
    # Coordination events
    COORD_SESSION_REGISTERED = "coord.session.registered"
    COORD_SESSION_HEARTBEAT = "coord.session.heartbeat"
    COORD_TASK_CLAIMED = "coord.task.claimed"
    COORD_TASK_RELEASED = "coord.task.released"
    COORD_PATH_RESERVED = "coord.path.reserved"
    COORD_PATH_RELEASED = "coord.path.released"
    COORD_PATH_RESERVATION_REFUSED = "coord.path.reservation_refused"
    COORD_ARTIFACT_PUBLISHED = "coord.artifact.published"
    COORD_CONFLICT_REPORTED = "coord.conflict.reported"
    COORD_HANDOFF_REQUESTED = "coord.handoff.requested"
    COORD_HANDOFF_ACCEPTED = "coord.handoff.accepted"
    COORD_HANDOFF_REJECTED = "coord.handoff.rejected"
    COORD_PROJECTION_READ = "coord.projection.read"
    COORD_LEASE_EXPIRED = "coord.lease.expired"
    COORD_LEASE_MARKED_STALE = "coord.lease.marked_stale"
    COORD_TASK_CLAIM_REFUSED = "coord.task.claim_refused"
    # Release events
    RELEASE_BUNDLE_BUILT = "rig.relay.release.bundle_built"
    # Checkpoint commit events
    CHECKPOINT_COMMITTED = "rig.relay.checkpoint.committed"
    CHECKPOINT_REFUSED = "rig.relay.checkpoint.refused"
    CHECKPOINT_AUTHORIZATION_REFUSED = "governance.checkpoint_authorization_refused"
    # Model observation events
    MODEL_OBSERVATION_CAPTURED = "rig.relay.model_observation.captured"
    # Tool receipt events
    TOOL_RECEIPT_CAPTURED = "rig.relay.tool_receipt.captured"
    # Telemetry consent enforcement events
    TELEMETRY_REMOTE_UPLOAD_ALLOWED = "telemetry.remote_upload.allowed"
    TELEMETRY_REMOTE_UPLOAD_DENIED = "telemetry.remote_upload.denied"
    # Integration events
    INTEGRATION_STATUS_CHECKED = "rig.relay.integration.status_checked"
    INTEGRATION_CONNECTION_STATE_CHANGED = (
        "rig.relay.integration.connection_state_changed"
    )
    INTEGRATION_CAPABILITY_INVOKED = "rig.relay.integration.capability_invoked"
    INTEGRATION_SCOPE_GRANTED = "rig.relay.integration.scope_granted"
    INTEGRATION_SCOPE_REVOKED = "rig.relay.integration.scope_revoked"
    INTEGRATION_EVIDENCE_WRITTEN = "rig.relay.integration.evidence_written"
    INTEGRATION_MUTATION_GATED = "rig.relay.integration.mutation_gated"
    INTEGRATION_MUTATION_APPROVED = "rig.relay.integration.mutation_approved"
    INTEGRATION_MUTATION_REFUSED = "rig.relay.integration.mutation_refused"
    # Context envelope governance events
    CONTEXT_ENVELOPE_GOVERNED_COMPILED = "rig.relay.context_envelope.governed_compiled"
    CONTEXT_ENVELOPE_GOVERNED_AD_HOC = "rig.relay.context_envelope.governed_ad_hoc"
    # Governance gate decision events
    GOVERNANCE_GATE_DECISION = "rig.relay.governance.gate.decision"
