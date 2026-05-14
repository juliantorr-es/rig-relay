"""RigConsoleBackend — authoritative façade for the pywebview Rig Console.

Owns: SessionService, ProjectionService, ReceiptStore, WebSocket server.
All mutation goes through intent path. All reads go through projection path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.context.compiler import ContextCompiler
from rig_relay.evidence.receipt_store import FilesystemReceiptStore
from vibe.cli.textual_ui.rig_console.session_bridge import (
    CodingSessionBridge,
    FixtureSessionAdapter,
    SessionBridge,
)


class SessionService:
    """Manages prompt turn lifecycle and event streaming."""

    def __init__(self, session_id: str, bridge: Any) -> None:
        self._session_id = session_id
        self._bridge = bridge
        self._compiler: ContextCompiler | None = None

    @property
    def bridge(self) -> Any:
        return self._bridge

    async def start_turn(
        self, text: str, workspace_root: Path | None = None
    ) -> dict[str, Any]:
        snapshot = (
            await self._bridge.snapshot() if hasattr(self._bridge, "snapshot") else None
        )
        self._compiler = ContextCompiler(
            session_id=self._session_id, workspace_root=workspace_root
        )
        envelope = self._compiler.build_envelope(user_text=text, snapshot=snapshot)
        result = await self._bridge.submit_user_message(text, context_envelope=envelope)
        return {
            "accepted": result.accepted,
            "status": result.status,
            "refusal_reason": result.refusal_reason,
            "turn_id": self._bridge.active_turn_id
            if hasattr(self._bridge, "active_turn_id")
            else "",
            "section_count": envelope.section_count if envelope else 0,
        }

    async def cancel(self) -> None:
        await self._bridge.cancel_turn()

    @property
    def is_active(self) -> bool:
        return (
            self._bridge.is_turn_active
            if hasattr(self._bridge, "is_turn_active")
            else False
        )

    @property
    def status(self) -> str:
        return (
            self._bridge.turn_status if hasattr(self._bridge, "turn_status") else "idle"
        )

    @property
    def active_turn_id(self) -> str:
        return (
            self._bridge.active_turn_id
            if hasattr(self._bridge, "active_turn_id")
            else ""
        )


class ProjectionService:
    """Builds content-light projection snapshots for the frontend."""

    def __init__(self, session_id: str, bridge: Any) -> None:
        self._session_id = session_id
        self._bridge = bridge

    async def snapshot(self) -> dict[str, Any]:
        snap = (
            await self._bridge.snapshot() if hasattr(self._bridge, "snapshot") else None
        )
        transcript = []
        if snap and snap.transcript:
            for item in snap.transcript.items:
                transcript.append({
                    "item_id": item.item_id,
                    "turn_id": item.turn_id,
                    "kind": item.kind,
                    "title": item.title,
                    "body_text": item.body_text,
                    "tool_name": item.tool_name,
                    "status": item.status,
                    "error_kind": item.error_kind,
                })
        return {
            "session_id": self._session_id,
            "turn_status": self._bridge.turn_status
            if hasattr(self._bridge, "turn_status")
            else "idle",
            "is_turn_active": self._bridge.is_turn_active
            if hasattr(self._bridge, "is_turn_active")
            else False,
            "dropped_count": self._bridge.dropped_count
            if hasattr(self._bridge, "dropped_count")
            else 0,
            "transcript": transcript,
        }


class RigConsoleBackend:
    """Top-level façade: owns session, projection, receipts, and WebSocket server.

    All external access goes through this class.
    """

    def __init__(
        self,
        session_id: str = "default",
        workspace_root: Path | None = None,
        receipt_root: Path | None = None,
        mode: str = "runtime",
    ) -> None:
        self._session_id = session_id
        self._workspace_root = (workspace_root or Path.cwd()).resolve()
        self._mode = mode
        receipt_path = (receipt_root or Path.home() / ".rig" / "relay").resolve()
        self._receipt_store = FilesystemReceiptStore(receipt_path)
        if mode == "fixture":
            self._bridge = FixtureSessionAdapter(session_id=session_id)
        else:
            self._bridge = CodingSessionBridge(
                session_id=session_id, receipt_store=self._receipt_store
            )
        self._session = SessionService(session_id, self._bridge)
        self._projection = ProjectionService(session_id, self._bridge)

    @property
    def session(self) -> SessionService:
        return self._session

    @property
    def projection(self) -> ProjectionService:
        return self._projection

    @property
    def receipt_store(self) -> FilesystemReceiptStore:
        return self._receipt_store

    @property
    def bridge(self) -> SessionBridge:
        return self._bridge

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root


__all__ = ["ProjectionService", "RigConsoleBackend", "SessionService"]
