from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Literal
import uuid

from pydantic import BaseModel, Field


class ToolOutputArtifact(BaseModel):
    schema_version: str = "rig.relay.tool_output_artifact.v1"
    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    source_event_id: str | None = None
    tool_name: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    path: str
    sha256: str
    byte_size: int
    mime_type: str = "application/json"
    encoding: str = "utf-8"
    truncated_for_prompt: bool
    prompt_excerpt: str
    raw_payload_kind: Literal["text", "json"]
    payload_sha256: str
    artifact_record_sha256: str | None = None


class PromptVisibleToolResult(BaseModel):
    tool_name: str
    artifact_id: str | None = None
    artifact_path: str | None = None
    raw_byte_size: int
    prompt_visible_byte_size: int
    truncated: bool
    excerpt: str
    summary: str


from vibe.core.paths._vibe_home import SESSIONS_ROOT


def get_artifact_dir(session_id: str) -> Path:
    """Return the base directory for session artifacts."""
    return SESSIONS_ROOT.path / session_id / "artifacts" / "tool-results"


def should_artifact_tool_result(content: str, threshold_bytes: int = 16384) -> bool:
    """Return True if the content exceeds the artifacting threshold."""
    return len(content.encode("utf-8")) > threshold_bytes


def make_prompt_excerpt(content: str, max_bytes: int = 4096) -> str:
    """Create a bounded excerpt of the content for the model prompt.

    NOTE: Excerpt generation is lossy. It may truncate the middle of the content
    and uses 'errors=\"ignore\"' for UTF-8 decoding at boundaries to avoid crashes.
    The local artifact file remains the authoritative source of truth.
    """
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content

    # Keep first and last parts
    half = max_bytes // 2
    prefix = encoded[:half].decode("utf-8", errors="ignore")
    suffix = encoded[-half:].decode("utf-8", errors="ignore")

    return f"{prefix}\n\n... [TRUNCATED] ...\n\n{suffix}"


import os


class ToolOutputArtifactWriter:
    """Handles durable atomic writing of tool output artifacts and metadata.

    Artifacts are written using an atomic replace pattern backed by fsync
    on both the data file and the parent directory to ensure durability.
    They are the authoritative source of truth for raw tool results.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.artifact_dir = get_artifact_dir(session_id)

    def write_artifact(
        self,
        tool_name: str,
        raw_output: str,
        sequence: int = 0,
        source_event_id: str | None = None,
    ) -> ToolOutputArtifact:
        """Write a self-describing JSON artifact file."""
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

        artifact_id = str(uuid.uuid4())
        # Filename pattern: <sequence>_<tool_name>_<artifact_id>.json
        safe_tool_name = "".join(c if c.isalnum() else "_" for c in tool_name)
        filename = f"{sequence:04d}_{safe_tool_name}_{artifact_id[:8]}.json"
        artifact_path = self.artifact_dir / filename

        # Prepare payload
        raw_kind: Literal["text", "json"] = "text"
        try:
            json.loads(raw_output)
            raw_kind = "json"
        except json.JSONDecodeError:
            raw_kind = "text"

        payload = {
            "tool_name": tool_name,
            "raw_output": raw_output,
            "raw_payload_kind": raw_kind,
        }

        payload_bytes = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        payload_sha256 = f"sha256:{hashlib.sha256(payload_bytes).hexdigest()}"

        excerpt = make_prompt_excerpt(raw_output)
        envelope = {
            "schema_version": "rig.relay.tool_output_artifact.v1",
            "artifact_id": artifact_id,
            "session_id": self.session_id,
            "source_event_id": source_event_id,
            "tool_name": tool_name,
            "created_at": datetime.now(UTC).isoformat(),
            "payload_sha256": payload_sha256,
            "byte_size": len(payload_bytes),
            "mime_type": "application/json",
            "encoding": "utf-8",
            "raw_payload_kind": raw_kind,
            "truncated_for_prompt": True,
            "prompt_visible_byte_size": len(excerpt.encode("utf-8")),
            "prompt_excerpt": excerpt,
            "payload": payload,
            "metadata": {
                "producer": "rig-relay",
                "producer_version": "2.9.6",
                "path": str(artifact_path),
            },
        }
        envelope_bytes = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        artifact_record_sha256 = f"sha256:{hashlib.sha256(envelope_bytes).hexdigest()}"
        envelope["artifact_record_sha256"] = artifact_record_sha256
        artifact_bytes = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

        temp_path = artifact_path.with_suffix(".tmp")
        try:
            with temp_path.open("wb") as f:
                f.write(artifact_bytes)
                f.flush()
                os.fsync(f.fileno())

            temp_path.replace(artifact_path)

            # Sync parent directory to ensure the rename is durable
            dir_fd = os.open(str(self.artifact_dir), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if temp_path.exists():
                temp_path.unlink()

        return ToolOutputArtifact(
            session_id=self.session_id,
            source_event_id=source_event_id,
            tool_name=tool_name,
            path=str(artifact_path),
            sha256=payload_sha256,
            byte_size=len(payload_bytes),
            truncated_for_prompt=True,
            prompt_excerpt=excerpt,
            raw_payload_kind=raw_kind,
            artifact_id=artifact_id,
            payload_sha256=payload_sha256,
            artifact_record_sha256=artifact_record_sha256,
        )
