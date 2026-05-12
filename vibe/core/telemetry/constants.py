from __future__ import annotations

from enum import StrEnum, auto


class EventName(StrEnum):
    REQUEST_ACCOUNTED = "rig.relay.context.request_accounted"
    TOOL_CALL_COMPLETED = "rig.relay.tool.call_completed"
    SESSION_STARTED = "rig.relay.session.started"
    SESSION_CLOSED = "rig.relay.session.closed"
    AUTO_COMPACT_TRIGGERED = "rig.relay.context.auto_compact_triggered"
    READY = "rig.relay.ready"
    AT_MENTION_INSERTED = "rig.relay.at_mention_inserted"
    USER_RATING_FEEDBACK = "rig.relay.user_rating_feedback"
    TELEPORT_COMPLETED = "rig.relay.teleport_completed"
    TELEPORT_FAILED = "rig.relay.teleport_failed"
