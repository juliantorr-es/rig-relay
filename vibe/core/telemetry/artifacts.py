from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field

from vibe.core.telemetry.local import dump_canonical_json


class ArtifactEnvelope(BaseModel):
    schema_version: str = "rig.relay.artifact.envelope.v1"
    artifact_kind: str
    session_id: str
    tool_call_id: str | None = None
    event_name: str | None = None
    evidence_relative_path: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    payload_sha256: str
    artifact_record_sha256: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolOutputArtifact(BaseModel):
    schema_version: str = "rig.relay.artifact.envelope.v1"
    artifact_kind: str = "tool_result"
    session_id: str
    tool_call_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    payload_sha256: str
    artifact_record_sha256: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    # Metadata for telemetry and internal use
    artifact_id: str
    tool_name: str
    path: str
    byte_size: int
    truncated_for_prompt: bool = True
    prompt_excerpt: str | None = None


class SearchQueryArtifact(BaseModel):
    tool_name: str = "grep"
    query: str
    backend: str
    root: str
    include_globs: list[str] = Field(default_factory=list)
    exclude_globs: list[str] = Field(default_factory=list)
    case_sensitive: bool | None = None
    fixed_strings: bool | None = None
    regex: bool | None = None
    context_before: int | None = None
    context_after: int | None = None
    normalized_query_sha256: str


class SearchResultItem(BaseModel):
    relative_path: str
    line_number: int | None = None
    absolute_offset: int | None = None
    submatch_start: int | None = None
    submatch_end: int | None = None
    start_line: int | None = None
    end_line: int | None = None
    start_column: int | None = None
    end_column: int | None = None
    excerpt: str | None = None
    excerpt_sha256: str | None = None
    line_text: str | None = None
    match_text: str | None = None
    before_context: str | None = None
    after_context: str | None = None
    symbol_context: str | None = None
    score: float | None = None
    rank: int | None = None
    tie_breakers: dict[str, Any] | None = None


class SearchResultArtifact(BaseModel):
    query_sha256: str
    results: list[SearchResultItem] = Field(default_factory=list)
    truncated: bool = False
    tool_name: str = "grep"
    query: str = ""
    backend: str = ""
    root: str = ""
    include_globs: list[str] = Field(default_factory=list)
    exclude_globs: list[str] = Field(default_factory=list)
    case_sensitive: bool | None = None
    fixed_strings: bool | None = None
    regex: bool | None = None
    context_before: int | None = None
    context_after: int | None = None
    ordering_policy: str = ""
    total_match_count: int = 0
    returned_match_count: int = 0
    matched_file_count: int = 0
    returned_file_count: int = 0
    truncation_reason: str | None = None
    result_set_sha256: str = ""
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)


class GitStateFile(BaseModel):
    relative_path: str
    change_kind: str
    staged: bool = False
    unstaged: bool = False
    untracked: bool = False
    conflicted: bool = False
    rename_from: str | None = None
    rename_to: str | None = None


class GitStateArtifact(BaseModel):
    tool_name: str = "git_status"
    repo_root: str
    branch: str | None = None
    head_sha: str | None = None
    head_short_sha: str | None = None
    upstream_branch: str | None = None
    upstream_ahead_count: int | None = None
    upstream_behind_count: int | None = None
    is_detached_head: bool | None = None
    is_dirty: bool = False
    dirty_file_count: int = 0
    staged_file_count: int = 0
    unstaged_file_count: int = 0
    untracked_file_count: int = 0
    conflict_file_count: int = 0
    ignored_file_count: int | None = None
    dirty_files: list[GitStateFile] = Field(default_factory=list)
    ordering_policy: str = "rig_normalized_path_kind"
    state_sha256: str
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)


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

        payload_bytes = dump_canonical_json(payload).encode("utf-8")
        payload_sha256 = f"sha256:{hashlib.sha256(payload_bytes).hexdigest()}"

        excerpt = make_prompt_excerpt(raw_output)

        # New Envelope v1 structure
        envelope = {
            "schema_version": "rig.relay.artifact.envelope.v1",
            "artifact_kind": "tool_result",
            "session_id": self.session_id,
            "tool_call_id": source_event_id,
            "created_at": datetime.now(UTC).isoformat(),
            "payload_sha256": payload_sha256,
            "payload": payload,
            "metadata": {
                "artifact_id": artifact_id,
                "tool_name": tool_name,
                "producer": "rig-relay",
                "producer_version": "2.9.6",
                "evidence_relative_path": str(
                    artifact_path.relative_to(self.artifact_dir.parent.parent.parent)
                ),
                "mime_type": "application/json",
                "encoding": "utf-8",
                "truncated_for_prompt": True,
                "prompt_visible_byte_size": len(excerpt.encode("utf-8")),
                "prompt_excerpt": excerpt,
            },
        }

        # Calculate artifact_record_sha256 over the envelope (excluding itself)
        envelope_bytes = dump_canonical_json(envelope).encode("utf-8")
        artifact_record_sha256 = f"sha256:{hashlib.sha256(envelope_bytes).hexdigest()}"
        envelope["artifact_record_sha256"] = artifact_record_sha256

        artifact_bytes = dump_canonical_json(envelope).encode("utf-8")

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
            tool_call_id=source_event_id,
            payload_sha256=payload_sha256,
            artifact_record_sha256=artifact_record_sha256,
            payload=payload,
            artifact_id=artifact_id,
            tool_name=tool_name,
            path=str(artifact_path),
            byte_size=len(payload_bytes),
            truncated_for_prompt=True,
            prompt_excerpt=excerpt,
        )

    def write_search_artifacts(
        self,
        *,
        query_artifact: SearchQueryArtifact,
        result_artifact: SearchResultArtifact,
        tool_call_id: str,
    ) -> tuple[Path, Path]:
        """Write search query and result artifacts.

        Returns:
            tuple[Path, Path]: (query_artifact_path, result_artifact_path)
        """
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        # 1. Write Query Artifact
        query_payload = query_artifact.model_dump()
        query_payload_bytes = dump_canonical_json(query_payload).encode("utf-8")
        query_payload_sha256 = (
            f"sha256:{hashlib.sha256(query_payload_bytes).hexdigest()}"
        )

        query_path = self.artifact_dir / f"search_query_{tool_call_id}.json"
        query_envelope = {
            "schema_version": "rig.relay.artifact.envelope.v1",
            "artifact_kind": "search_query",
            "session_id": self.session_id,
            "tool_call_id": tool_call_id,
            "created_at": datetime.now(UTC).isoformat(),
            "payload_sha256": query_payload_sha256,
            "payload": query_payload,
            "metadata": {
                "producer": "rig-relay",
                "producer_version": "2.9.6",
                "evidence_relative_path": str(
                    query_path.relative_to(self.artifact_dir.parent.parent.parent)
                ),
            },
        }
        query_envelope_bytes = dump_canonical_json(query_envelope).encode("utf-8")
        query_envelope["artifact_record_sha256"] = (
            f"sha256:{hashlib.sha256(query_envelope_bytes).hexdigest()}"
        )

        query_path.write_text(dump_canonical_json(query_envelope), encoding="utf-8")

        # 2. Write Result Artifact
        result_payload = result_artifact.model_dump()
        result_payload_bytes = dump_canonical_json(result_payload).encode("utf-8")
        result_payload_sha256 = (
            f"sha256:{hashlib.sha256(result_payload_bytes).hexdigest()}"
        )

        result_path = self.artifact_dir / f"search_result_{tool_call_id}.json"
        result_envelope = {
            "schema_version": "rig.relay.artifact.envelope.v1",
            "artifact_kind": "search_result",
            "session_id": self.session_id,
            "tool_call_id": tool_call_id,
            "created_at": datetime.now(UTC).isoformat(),
            "payload_sha256": result_payload_sha256,
            "payload": result_payload,
            "metadata": {
                "producer": "rig-relay",
                "producer_version": "2.9.6",
                "evidence_relative_path": str(
                    result_path.relative_to(self.artifact_dir.parent.parent.parent)
                ),
            },
        }
        result_envelope_bytes = dump_canonical_json(result_envelope).encode("utf-8")
        result_envelope["artifact_record_sha256"] = (
            f"sha256:{hashlib.sha256(result_envelope_bytes).hexdigest()}"
        )

        result_path.write_text(dump_canonical_json(result_envelope), encoding="utf-8")

        return query_path, result_path

    def write_git_state_artifact(
        self, *, artifact: GitStateArtifact, tool_call_id: str | None, sequence: int = 0
    ) -> ToolOutputArtifact:
        payload = artifact.model_dump(exclude_none=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

        artifact_id = str(uuid.uuid4())
        filename = f"{sequence:04d}_git_state_{artifact_id[:8]}.json"
        artifact_path = self.artifact_dir / filename
        payload_bytes = dump_canonical_json(payload).encode("utf-8")
        payload_sha256 = f"sha256:{hashlib.sha256(payload_bytes).hexdigest()}"
        envelope = {
            "schema_version": "rig.relay.artifact.envelope.v1",
            "artifact_kind": "git_state",
            "session_id": self.session_id,
            "tool_call_id": tool_call_id,
            "created_at": datetime.now(UTC).isoformat(),
            "payload_sha256": payload_sha256,
            "payload": payload,
            "metadata": {
                "artifact_id": artifact_id,
                "tool_name": artifact.tool_name,
                "producer": "rig-relay",
                "producer_version": "2.9.6",
                "evidence_relative_path": str(
                    artifact_path.relative_to(self.artifact_dir.parent.parent.parent)
                ),
                "mime_type": "application/json",
                "encoding": "utf-8",
            },
        }
        envelope_bytes = dump_canonical_json(envelope).encode("utf-8")
        artifact_record_sha256 = f"sha256:{hashlib.sha256(envelope_bytes).hexdigest()}"
        envelope["artifact_record_sha256"] = artifact_record_sha256
        artifact_path.write_text(dump_canonical_json(envelope), encoding="utf-8")
        return ToolOutputArtifact(
            session_id=self.session_id,
            tool_call_id=tool_call_id,
            payload_sha256=payload_sha256,
            artifact_record_sha256=artifact_record_sha256,
            payload=payload,
            artifact_id=artifact_id,
            tool_name=artifact.tool_name,
            path=str(artifact_path),
            byte_size=len(payload_bytes),
            truncated_for_prompt=False,
            prompt_excerpt=None,
        )
