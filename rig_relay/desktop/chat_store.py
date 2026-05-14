from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from rig_relay.desktop.chat_state import ChatMessage, ChatState
from rig_relay.core.utils.io import read_safe

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CHAT_ROOT = REPO_ROOT / ".build" / "rig-relay" / "desktop" / "chat"


class ChatStore:
    """Persistent storage for desktop chat state and events.

    Stores content-light chat history and append-only event log.
    Enforces content-light safeguards (SHA256 + short preview).
    """

    def __init__(self, chat_root: Path = DEFAULT_CHAT_ROOT) -> None:
        self._chat_root = chat_root
        self._state_path = chat_root / "chat_state.json"
        self._events_path = chat_root / "chat_events.jsonl"
        self._chat_root.mkdir(parents=True, exist_ok=True)

    def load_state(self) -> ChatState:
        """Load persisted chat state from disk."""
        if not self._state_path.is_file():
            return ChatState()
        try:
            result = read_safe(self._state_path)
            data = json.loads(result.text)
            return ChatState.model_validate(data)
        except Exception:
            # On corruption or parse error, return fresh state to avoid blocking the shell.
            # In a production environment we might archive the corrupt file.
            return ChatState()

    def save_state(self, state: ChatState) -> None:
        """Atomically save chat state to disk."""
        temp_path = self._state_path.with_suffix(f".tmp.{uuid4().hex}")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(
                    state.model_dump(mode="json"), f, indent=2, ensure_ascii=False
                )
            temp_path.replace(self._state_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def append_event(
        self,
        event_name: str,
        message: ChatMessage | None = None,
        warning_codes: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        """Append a content-light chat event to the event log."""
        event_id = str(uuid4())
        event = {
            "schema_version": 1,
            "event_id": event_id,
            "created_at": datetime.now(UTC).isoformat(),
            "event_name": event_name,
            "warning_codes": warning_codes or [],
        }

        if message:
            event.update({
                "message_id": message.message_id,
                "client_message_id": message.metadata.get("client_message_id"),
                "role": message.role,
                "status": message.status,
                "content_sha256": hashlib.sha256(
                    message.content.encode("utf-8")
                ).hexdigest(),
                "content_preview": message.content[:120],
            })

        event.update(kwargs)

        with open(self._events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

        return event_id
