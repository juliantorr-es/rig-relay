"""Trace context propagation using contextvars — works across async boundaries."""

from __future__ import annotations

from contextvars import ContextVar

from rig_relay.tracing.models import new_span_id, new_trace_id

_current_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_current_span_id: ContextVar[str] = ContextVar("span_id", default="")
_current_session_id: ContextVar[str] = ContextVar("session_id", default="")
_current_mission_id: ContextVar[str] = ContextVar("mission_id", default="")
_current_lane_id: ContextVar[str] = ContextVar("lane_id", default="")
_current_turn_id: ContextVar[str] = ContextVar("turn_id", default="")
_current_tool_call_id: ContextVar[str] = ContextVar("tool_call_id", default="")


class TraceContext:
    __slots__ = (
        "trace_id",
        "span_id",
        "parent_span_id",
        "session_id",
        "mission_id",
        "lane_id",
        "turn_id",
        "tool_call_id",
    )

    def __init__(
        self,
        trace_id: str = "",
        span_id: str = "",
        parent_span_id: str | None = None,
        session_id: str = "",
        mission_id: str = "",
        lane_id: str = "",
        turn_id: str = "",
        tool_call_id: str = "",
        _no_defaults: bool = False,
    ) -> None:
        if _no_defaults:
            self.trace_id = trace_id
            self.span_id = span_id
        else:
            self.trace_id = trace_id or new_trace_id()
            self.span_id = span_id or new_span_id()
        self.parent_span_id = parent_span_id
        self.session_id = session_id
        self.mission_id = mission_id
        self.lane_id = lane_id
        self.turn_id = turn_id
        self.tool_call_id = tool_call_id

    def child(self) -> TraceContext:
        return TraceContext(
            trace_id=self.trace_id,
            span_id=new_span_id(),
            parent_span_id=self.span_id,
            session_id=self.session_id,
            mission_id=self.mission_id,
            lane_id=self.lane_id,
            turn_id=self.turn_id,
            tool_call_id=self.tool_call_id,
        )

    def set_on_current(self) -> None:
        _current_trace_id.set(self.trace_id)
        _current_span_id.set(self.span_id)
        _current_session_id.set(self.session_id)
        _current_mission_id.set(self.mission_id)
        _current_lane_id.set(self.lane_id)
        _current_turn_id.set(self.turn_id)
        _current_tool_call_id.set(self.tool_call_id)

    @staticmethod
    def get_current() -> TraceContext:
        return TraceContext(
            trace_id=_current_trace_id.get(),
            span_id=_current_span_id.get(),
            parent_span_id=None,
            session_id=_current_session_id.get(),
            mission_id=_current_mission_id.get(),
            lane_id=_current_lane_id.get(),
            turn_id=_current_turn_id.get(),
            tool_call_id=_current_tool_call_id.get(),
            _no_defaults=True,
        )

    @staticmethod
    def clear_current() -> None:
        _current_trace_id.set("")
        _current_span_id.set("")
        _current_session_id.set("")
        _current_mission_id.set("")
        _current_lane_id.set("")
        _current_turn_id.set("")
        _current_tool_call_id.set("")

    @staticmethod
    def set_current_session(session_id: str) -> None:
        _current_session_id.set(session_id)

    @staticmethod
    def set_current_mission(mission_id: str) -> None:
        _current_mission_id.set(mission_id)

    @staticmethod
    def set_current_lane(lane_id: str) -> None:
        _current_lane_id.set(lane_id)

    @staticmethod
    def set_current_turn(turn_id: str) -> None:
        _current_turn_id.set(turn_id)

    @staticmethod
    def set_current_tool_call(tool_call_id: str) -> None:
        _current_tool_call_id.set(tool_call_id)


def get_current_trace_context() -> TraceContext:
    return TraceContext.get_current()


def set_trace_context(ctx: TraceContext) -> None:
    ctx.set_on_current()


def clear_trace_context() -> None:
    TraceContext.clear_current()


def child_trace_context() -> TraceContext:
    current = TraceContext.get_current()
    if not current.trace_id:
        # No active trace — start a root span with no parent
        return TraceContext(
            trace_id=new_trace_id(),
            span_id=new_span_id(),
            parent_span_id=None,
            session_id=current.session_id,
            mission_id=current.mission_id,
            lane_id=current.lane_id,
            turn_id=current.turn_id,
            tool_call_id=current.tool_call_id,
        )
    if not current.span_id:
        current.span_id = new_span_id()
    return current.child()


__all__ = [
    "TraceContext",
    "child_trace_context",
    "clear_trace_context",
    "get_current_trace_context",
    "set_trace_context",
]
