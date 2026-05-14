"""Compatibility bridge between Rig Console and the base vibe session path.

Phase 6: push-driven event stream replaces polling. RuntimeSessionAdapter
exposes stream_events() via asyncio.Queue. Dashboard consumes events in a
Textual worker. Polling is demoted to fallback/replay.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import inspect
from typing import Protocol
from uuid import uuid4

from rig_relay.context.models import ContextEnvelopeReceipt
from rig_relay.evidence.receipt_envelope import (
    ReceiptActor,
    ReceiptActorKind,
    ReceiptDecision,
    ReceiptSubject,
    ReceiptSubjectKind,
    build_receipt_envelope,
)
from rig_relay.evidence.receipt_store import ReceiptStore
from vibe.cli.textual_ui.rig_console.progress_events import (
    ProgressEventFactory,
    TurnProgressEvent,
)
from vibe.cli.textual_ui.rig_console.session_events import (
    CodingSessionEvents,
    CodingSessionSnapshot,
    CodingTranscriptItemProjection,
    CodingTranscriptProjection,
    SubmitPromptResult,
)
from vibe.core.agent_loop import AgentLoop
from vibe.core.config import VibeConfig
from vibe.core.programmatic import _DEFAULT_CLIENT_METADATA
from vibe.core.telemetry.build_metadata import build_entrypoint_metadata
from vibe.core.types import (
    AssistantEvent,
    BaseEvent,
    LLMMessage,
    ReasoningEvent,
    Role,
    ToolCallEvent,
    ToolResultEvent,
    UserMessageEvent,
    WaitingForInputEvent,
)

_ITEMS_MAX = 500
_POLL_INTERVAL = 0.05
_QUEUE_MAX = 500
_COALESCE_INTERVAL = 0.06

SubscriptionCallback = Callable[[list[CodingTranscriptItemProjection]], None]

# ── SessionTurnState ──────────────────────────────────────────────


class SessionTurnState:
    """Unified turn state. All dashboard/bridge status derives from this."""

    def __init__(self) -> None:
        self.status: str = "idle"
        self.turn_id: str = ""
        self.started_at: str | None = None
        self.completed_at: str | None = None
        self.last_event_index: int = 0
        self.dropped_count: int = 0

    @property
    def is_active(self) -> bool:
        return self.status in {"starting", "running", "cancelling"}

    def start(self, turn_id: str) -> None:
        self.status = "running"
        self.turn_id = turn_id
        self.started_at = datetime.now(UTC).isoformat()
        self.completed_at = None

    def complete(self) -> None:
        self.status = "completed"
        self.completed_at = datetime.now(UTC).isoformat()

    def fail(self) -> None:
        self.status = "failed"
        self.completed_at = datetime.now(UTC).isoformat()

    def cancel(self) -> None:
        self.status = "cancelled"
        self.completed_at = datetime.now(UTC).isoformat()

    def set_cancelling(self) -> None:
        self.status = "cancelling"


# ── Subscription (legacy, used by tests) ──────────────────────────


class Subscription:
    def __init__(self, callback: SubscriptionCallback) -> None:
        self._callback = callback
        self._active = True

    def emit(self, items: list[CodingTranscriptItemProjection]) -> None:
        if self._active:
            self._callback(items)

    def unsubscribe(self) -> None:
        self._active = False

    @property
    def active(self) -> bool:
        return self._active


# ── Protocol ──────────────────────────────────────────────────────


class SessionBridge(Protocol):
    async def submit_user_message(
        self, text: str, context_envelope: ContextEnvelopeReceipt | None = None
    ) -> SubmitPromptResult: ...

    async def stream_events(
        self, turn_id: str
    ) -> AsyncIterator[CodingTranscriptItemProjection]: ...

    async def snapshot(self) -> CodingSessionSnapshot: ...

    async def events_since(self, cursor: str | None) -> CodingSessionEvents: ...

    async def cancel_turn(self) -> None: ...

    async def wait_for_turn(self) -> None: ...

    @property
    def is_turn_active(self) -> bool: ...

    @property
    def turn_status(self) -> str: ...

    @property
    def dropped_count(self) -> int: ...

    @property
    def active_turn_id(self) -> str: ...

    def subscribe(self, callback: SubscriptionCallback) -> Subscription: ...


# ── FixtureSessionAdapter ─────────────────────────────────────────


@dataclass(slots=True)
class FixtureSessionAdapter:
    session_id: str
    receipt_store: ReceiptStore | None = None
    _items: list[CodingTranscriptItemProjection] = field(default_factory=list)
    _dropped_count: int = 0
    _subscribers: list[Subscription] = field(default_factory=list)
    _event_queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_MAX)
    )
    _turn_state: SessionTurnState = field(default_factory=SessionTurnState)
    _turn_seq: int = 0

    async def submit_user_message(
        self, text: str, context_envelope: ContextEnvelopeReceipt | None = None
    ) -> SubmitPromptResult:
        if not text.strip():
            return SubmitPromptResult(
                accepted=False, status="refused", refusal_reason="Empty prompt"
            )
        self._turn_seq += 1
        tid = f"{self.session_id}:{self._turn_seq}"
        self._turn_state.start(tid)
        self._append("user_message", "User", body_text=text)
        self._append("assistant_message", "Assistant", body_text="Fixture reply")
        self._append("turn_status", "Turn", status="completed")
        self._turn_state.complete()
        return SubmitPromptResult(
            accepted=True,
            status="completed",
            cursor=str(len(self._items) + self._dropped_count),
        )

    async def stream_events(
        self, turn_id: str
    ) -> AsyncIterator[CodingTranscriptItemProjection]:
        while True:
            try:
                item = await asyncio.wait_for(self._event_queue.get(), timeout=30.0)
            except TimeoutError:
                return
            if item.kind == "turn_status" and item.status in {
                "completed",
                "failed",
                "cancelled",
            }:
                yield item
                return
            if item.turn_id != turn_id:
                continue
            yield item

    async def snapshot(self) -> CodingSessionSnapshot:
        return CodingSessionSnapshot(
            session_id=self.session_id,
            transcript=CodingTranscriptProjection(
                session_id=self.session_id,
                cursor=str(len(self._items) + self._dropped_count),
                items=list(self._items),
                dropped_count=self._dropped_count,
            ),
        )

    async def events_since(self, cursor: str | None) -> CodingSessionEvents:
        start_abs = int(cursor or "0")
        start_rel = max(0, start_abs - self._dropped_count)
        return CodingSessionEvents(
            cursor=str(len(self._items) + self._dropped_count),
            items=list(self._items[start_rel:]),
        )

    async def cancel_turn(self) -> None:
        pass

    async def wait_for_turn(self) -> None:
        pass

    @property
    def is_turn_active(self) -> bool:
        return self._turn_state.is_active

    @property
    def turn_status(self) -> str:
        return self._turn_state.status

    @property
    def active_turn_id(self) -> str:
        return self._turn_state.turn_id

    def _append(
        self,
        kind: str,
        title: str,
        *,
        body_text: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
        refusal_reason: str | None = None,
        error_kind: str | None = None,
    ) -> None:
        item = CodingTranscriptItemProjection(
            item_id=f"{self.session_id}:{len(self._items) + 1}",
            turn_id=self._turn_state.turn_id,
            kind=kind,
            title=title,
            body_text=body_text,
            tool_name=tool_name,
            status=status,
            refusal_reason=refusal_reason,
            error_kind=error_kind,
        )
        self._items.append(item)
        self._prune_items()
        for sub in self._subscribers:
            sub.emit([item])
        self._push_event(item)

    def _prune_items(self) -> None:
        if len(self._items) > _ITEMS_MAX:
            excess = len(self._items) - _ITEMS_MAX
            pruned = self._items[:excess]
            self._items = self._items[excess:]
            self._dropped_count += excess
            self._emit_compaction_receipt(pruned)

    def _emit_compaction_receipt(self, pruned: list) -> None:
        if not pruned or self.receipt_store is None:
            return
        kinds: dict[str, int] = {}
        for item in pruned:
            kinds[item.kind] = kinds.get(item.kind, 0) + 1
        summary = ", ".join(f"{c} {k}" for k, c in sorted(kinds.items()))
        summary_text = f"Dropped {len(pruned)} items: {summary}"
        try:
            receipt = build_receipt_envelope(
                receipt_kind="compaction",
                actor=ReceiptActor(
                    actor_id="runtime", actor_kind=ReceiptActorKind.RUNTIME
                ),
                subject=ReceiptSubject(
                    subject_id=f"{self.session_id}:compaction:{datetime.now(UTC).isoformat()}",
                    subject_kind=ReceiptSubjectKind.SESSION,
                    session_id=self.session_id,
                ),
                receipt_payload={"dropped_count": len(pruned), "kinds": dict(kinds)},
                decision=ReceiptDecision(decision="pruned", rationale=summary_text),
            )
            self.receipt_store.append(receipt)
        except Exception:
            pass

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    def subscribe(self, callback: SubscriptionCallback) -> Subscription:
        sub = Subscription(callback)
        self._subscribers.append(sub)
        return sub

    def _push_event(self, item: CodingTranscriptItemProjection) -> None:
        try:
            self._event_queue.put_nowait(item)
        except asyncio.QueueFull:
            if item.kind in {"turn_status", "error"}:
                self._event_queue.put_nowait(item)


@dataclass(slots=True)
class RuntimeSessionAdapter:
    session_id: str
    receipt_store: ReceiptStore | None = None
    config: VibeConfig | None = None
    previous_messages: list[LLMMessage] = field(default_factory=list)
    _items: list[CodingTranscriptItemProjection] = field(default_factory=list)
    _cursor: int = 0
    _config_error: str | None = None
    _turn_state: SessionTurnState = field(default_factory=SessionTurnState)
    _turn_task: asyncio.Task | None = None
    _dropped_count: int = 0
    _queue_dropped_count: int = 0
    _subscribers: list[Subscription] = field(default_factory=list)
    _event_queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_MAX)
    )
    _turn_seq: int = 0

    async def submit_user_message(
        self, text: str, context_envelope: ContextEnvelopeReceipt | None = None
    ) -> SubmitPromptResult:
        if not text.strip():
            return SubmitPromptResult(
                accepted=False, status="refused", refusal_reason="Empty prompt"
            )
        if self._turn_state.is_active:
            return SubmitPromptResult(
                accepted=False, status="refused", refusal_reason="Turn already active"
            )
        try:
            config = self.config or VibeConfig()
        except Exception as exc:
            reason = type(exc).__name__
            self._append("error", "Error", status="blocked", error_kind=reason)
            self._config_error = reason
            return SubmitPromptResult(
                accepted=False, status="blocked", refusal_reason=reason
            )
        self._turn_seq += 1
        tid = f"{self.session_id}:{self._turn_seq}"
        self._turn_state.start(tid)
        self._items.clear()
        self._cursor = 0
        prompt = context_envelope.rendered_prompt if context_envelope else text
        if context_envelope:
            self._append(
                "context_envelope",
                "Context",
                body_text=f"{context_envelope.section_count} sections · cache {'hit' if context_envelope.is_cached else 'miss'}",
            )
        self._turn_task = asyncio.create_task(self._run_turn_background(config, prompt))
        return SubmitPromptResult(accepted=True, status="running", cursor="0")

    async def stream_events(
        self, turn_id: str
    ) -> AsyncIterator[CodingTranscriptItemProjection]:
        while True:
            try:
                item = await asyncio.wait_for(self._event_queue.get(), timeout=30.0)
            except TimeoutError:
                return
            if item.turn_id != turn_id:
                continue
            if item.kind == "turn_status" and item.status in {
                "completed",
                "failed",
                "cancelled",
            }:
                yield item
                return
            yield item

    async def snapshot(self) -> CodingSessionSnapshot:
        return CodingSessionSnapshot(
            session_id=self.session_id,
            transcript=CodingTranscriptProjection(
                session_id=self.session_id,
                cursor=str(self._cursor),
                items=list(self._items),
                dropped_count=self._dropped_count,
            ),
        )

    async def events_since(self, cursor: str | None) -> CodingSessionEvents:
        start_abs = int(cursor or "0")
        start_rel = max(0, start_abs - self._dropped_count)
        return CodingSessionEvents(
            cursor=str(self._cursor), items=list(self._items[start_rel:])
        )

    async def cancel_turn(self) -> None:
        self._turn_state.set_cancelling()
        if self._turn_task is not None and not self._turn_task.done():
            self._turn_task.cancel()
            try:
                await self._turn_task
            except asyncio.CancelledError:
                pass
        self._turn_state.cancel()

    async def wait_for_turn(self) -> None:
        if self._turn_task is not None:
            try:
                await self._turn_task
            except asyncio.CancelledError:
                pass

    @property
    def is_turn_active(self) -> bool:
        return self._turn_state.is_active

    @property
    def turn_status(self) -> str:
        return self._turn_state.status

    @property
    def active_turn_id(self) -> str:
        return self._turn_state.turn_id

    async def _run_turn_background(self, config: VibeConfig, text: str) -> None:
        try:
            agent_loop = AgentLoop(
                config,
                enable_streaming=False,
                headless=True,
                entrypoint_metadata=build_entrypoint_metadata(
                    agent_entrypoint="desktop",
                    agent_version="rig-relay",
                    client_name=_DEFAULT_CLIENT_METADATA.name,
                    client_version=_DEFAULT_CLIENT_METADATA.version,
                ),
            )
            try:
                if self.previous_messages:
                    non_system_messages = [
                        msg for msg in self.previous_messages if msg.role != Role.system
                    ]
                    agent_loop.messages.extend(non_system_messages)
                else:
                    agent_loop.emit_new_session_telemetry()

                async for event in agent_loop.act(text, client_message_id=str(uuid4())):
                    self._record_event(event)
                    if isinstance(event, WaitingForInputEvent):
                        self._append("status", "Status", status="blocked")
                messages = getattr(agent_loop, "messages", None)
                if messages is not None:
                    self.previous_messages = [
                        msg for msg in messages if msg.role != Role.system
                    ]
            finally:
                await self._maybe_await(agent_loop.aclose())
                telemetry_client = getattr(agent_loop, "telemetry_client", None)
                if telemetry_client is not None and hasattr(telemetry_client, "aclose"):
                    await self._maybe_await(telemetry_client.aclose())
        except asyncio.CancelledError:
            self._turn_state.cancel()
            self._append_from_progress(ProgressEventFactory.turn_cancelled())
            self._cursor = len(self._items)
            return
        except Exception as exc:
            reason = type(exc).__name__
            self._turn_state.fail()
            self._append_from_progress(ProgressEventFactory.turn_failed(reason))
            self._cursor = len(self._items)
            return
        self._turn_state.complete()
        self._append_from_progress(ProgressEventFactory.turn_completed())
        self._cursor = len(self._items)

    def _record_event(self, event: BaseEvent) -> None:
        match event:
            case UserMessageEvent(content=content):
                self._append_from_progress(ProgressEventFactory.user_message(content))
            case AssistantEvent(content=content):
                self._append_from_progress(
                    ProgressEventFactory.assistant_completed(content)
                )
            case ReasoningEvent(content=content):
                self._append("status", "Reasoning", body_text=content)
            case ToolCallEvent(tool_name=tool_name):
                self._append_from_progress(ProgressEventFactory.tool_started(tool_name))
            case ToolResultEvent(tool_name=tool_name, duration=duration, error=error):
                if error:
                    self._append_from_progress(
                        ProgressEventFactory.tool_failed(
                            tool_name, type(error).__name__
                        )
                    )
                else:
                    self._append_from_progress(
                        ProgressEventFactory.tool_completed(tool_name)
                    )
                if duration is not None:
                    self._append(
                        "status",
                        "Status",
                        body_text=f"{tool_name} took {duration:.2f}s",
                    )
            case WaitingForInputEvent():
                self._append_from_progress(ProgressEventFactory.status_blocked())

    def _append_from_progress(self, p: TurnProgressEvent) -> None:
        kind_mapping: dict[str, str] = {
            "user_message.accepted": "user_message",
            "assistant_message.completed": "assistant_message",
            "tool.started": "tool_activity",
            "tool.completed": "tool_result",
            "tool.failed": "tool_result",
            "tool.refused": "tool_result",
            "turn.completed": "turn_status",
            "turn.failed": "turn_status",
            "turn.cancelled": "turn_status",
            "status.blocked": "status",
            "error": "error",
        }
        kind = kind_mapping.get(p.phase, "status")
        self._append(
            kind,
            p.tool_name or p.phase.replace("_", " ").title(),
            body_text=p.message,
            tool_name=p.tool_name,
            status=p.status,
            error_kind=p.error_kind,
            refusal_reason=p.refusal_reason,
        )

    def _append(
        self,
        kind: str,
        title: str,
        *,
        body_text: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
        refusal_reason: str | None = None,
        error_kind: str | None = None,
    ) -> None:
        item = CodingTranscriptItemProjection(
            item_id=f"{self.session_id}:{len(self._items) + 1}",
            turn_id=self._turn_state.turn_id,
            kind=kind,
            title=title,
            body_text=body_text,
            tool_name=tool_name,
            status=status,
            refusal_reason=refusal_reason,
            error_kind=error_kind,
        )
        self._items.append(item)
        self._prune_items()
        for sub in self._subscribers:
            sub.emit([item])
        # Push to event queue with backpressure
        self._push_event(item)

    def _push_event(self, item: CodingTranscriptItemProjection) -> None:
        if self._event_queue.qsize() >= _QUEUE_MAX:
            if item.kind in {"turn_status", "error"}:
                self._event_queue.put_nowait(item)
                return
            self._queue_dropped_count += 1
            return
        try:
            self._event_queue.put_nowait(item)
        except asyncio.QueueFull:
            if item.kind in {"turn_status", "error"}:
                self._event_queue.put_nowait(item)
            else:
                self._queue_dropped_count += 1

    def _prune_items(self) -> None:
        if len(self._items) > _ITEMS_MAX:
            excess = len(self._items) - _ITEMS_MAX
            pruned = self._items[:excess]
            self._items = self._items[excess:]
            self._dropped_count += excess
            self._emit_compaction_receipt(pruned)

    def _emit_compaction_receipt(self, pruned: list) -> None:
        if not pruned or self.receipt_store is None:
            return
        kinds: dict[str, int] = {}
        for item in pruned:
            kinds[item.kind] = kinds.get(item.kind, 0) + 1
        summary = ", ".join(f"{c} {k}" for k, c in sorted(kinds.items()))
        summary_text = f"Dropped {len(pruned)} items: {summary}"
        try:
            receipt = build_receipt_envelope(
                receipt_kind="compaction",
                actor=ReceiptActor(
                    actor_id="runtime", actor_kind=ReceiptActorKind.RUNTIME
                ),
                subject=ReceiptSubject(
                    subject_id=f"{self.session_id}:compaction:{datetime.now(UTC).isoformat()}",
                    subject_kind=ReceiptSubjectKind.SESSION,
                    session_id=self.session_id,
                ),
                receipt_payload={"dropped_count": len(pruned), "kinds": dict(kinds)},
                decision=ReceiptDecision(decision="pruned", rationale=summary_text),
            )
            self.receipt_store.append(receipt)
        except Exception:
            pass

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    def subscribe(self, callback: SubscriptionCallback) -> Subscription:
        sub = Subscription(callback)
        self._subscribers.append(sub)
        return sub

    async def _maybe_await(self, value: object) -> None:
        if inspect.isawaitable(value):
            await value


CodingSessionBridge = RuntimeSessionAdapter

__all__ = [
    "CodingSessionBridge",
    "FixtureSessionAdapter",
    "RuntimeSessionAdapter",
    "SessionBridge",
    "SessionTurnState",
]
