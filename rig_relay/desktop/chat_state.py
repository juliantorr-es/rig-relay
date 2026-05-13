from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ChatRole(StrEnum):
    USER = auto()
    ASSISTANT = auto()
    SYSTEM = auto()
    TOOL = auto()
    STATUS = auto()


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    role: ChatRole
    content: str
    status: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ChatState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    backend_wired: bool = False
    messages: list[ChatMessage] = Field(default_factory=list)
    pending_response: bool = False
    warnings: list[str] = Field(default_factory=list)
