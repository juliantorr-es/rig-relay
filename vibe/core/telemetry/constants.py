from __future__ import annotations

from enum import StrEnum


class EventName(StrEnum):
    REQUEST_ACCOUNTED = "rig.relay.context.request_accounted"
    TOOL_CALL_COMPLETED = "rig.relay.tool.call_completed"
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
    # Checkpoint commit events
    CHECKPOINT_COMMITTED = "rig.relay.checkpoint.committed"
    CHECKPOINT_REFUSED = "rig.relay.checkpoint.refused"
    # Model observation events
    MODEL_OBSERVATION_CAPTURED = "rig.relay.model_observation.captured"
