"""Local project inference assistance models — M0.

Typed models for the Local Project Inference Service: sanitized project
context packets, assistance task definitions, and content-light evidence
results. All models are content-light: hashes, counts, classifications,
and review-required draft references only. No raw prompts, completions,
or private file contents.

M0 owns these models. They consume Lane D's EnforcementClass from
rig_relay/recovery/capability_admission.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.recovery.capability_admission import EnforcementClass


class AssistanceTaskKind(StrEnum):
    PROJECT_SUMMARY = "project_summary"
    PAGE_SECTION_ORDERING = "page_section_ordering"
    CAPABILITY_CLASSIFICATION = "capability_classification"
    MISSING_MATERIAL_CHECKLIST = "missing_material_checklist"


class OutputDisposition(StrEnum):
    DRAFT_REQUIRES_REVIEW = "draft_requires_review"
    INTERNAL_ONLY = "internal_only"
    REFUSED_PUBLICATION = "refused_publication"
    NO_OUTPUT_PRODUCED = "no_output_produced"


class PublicationApplicability(StrEnum):
    PROJECT_PAGE = "project_page"
    PORTFOLIO = "portfolio"
    INTERNAL_ONLY = "internal_only"
    NONE = "none"


class AssistanceExecutionStatus(StrEnum):
    EXECUTED = "executed"
    REFUSED_UNSUPPORTED_ENFORCEMENT = "refused_unsupported_enforcement"
    REFUSED_RUNTIME_UNAVAILABLE = "refused_runtime_unavailable"
    REFUSED_UNSAFE_PACKET = "refused_unsafe_packet"
    REFUSED_CAPABILITY_UNPROVEN = "refused_capability_unproven"
    REFUSED_MODEL_ERROR = "refused_model_error"
    DEGRADED_JSON_OBJECT_ONLY = "degraded_json_object_only"


_PROJECT_CONTEXT_SCHEMA = "rig.relay.local_inference.project_context_packet.v1"
_ASSISTANCE_TASK_SCHEMA = "rig.relay.local_inference.assistance_task.v1"
_ASSISTANCE_RESULT_SCHEMA = "rig.relay.local_inference.assistance_result.v1"


class ProjectContextPacket(BaseModel):
    """Sanitized project context for M0 assistance tasks.

    Content-light: project identity, technology summary, and public-safe
    description only. Never contains raw file contents, private code
    paths, secrets, or unbounded repository context.

    M0-owned fixture until L0 publishes its sanitized project context
    packet contract. When L0 releases, M0 will consume L0's contract
    through its published boundary.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=_PROJECT_CONTEXT_SCHEMA, frozen=True)
    packet_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    project_name: str = ""
    project_summary: str = ""
    technology_keywords: list[str] = Field(default_factory=list)
    package_dependency_summary: str = ""
    component_architecture_summary: str = ""
    current_milestone: str = ""
    public_safe: bool = True
    provenance: str = "m0_synthetic_fixture"
    packet_digest: str = ""

    def compute_digest(self) -> str:
        data = self.model_dump(mode="json", exclude={"packet_digest", "created_at"})
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

    def seal(self) -> ProjectContextPacket:
        self.packet_digest = self.compute_digest()
        return self

    def is_public_safe(self) -> bool:
        return self.public_safe and len(self.packet_digest) > 0

    def build_prompt_context(self) -> str:
        lines: list[str] = []
        if self.project_name:
            lines.append(f"Project: {self.project_name}")
        if self.project_summary:
            lines.append(f"Summary: {self.project_summary}")
        if self.technology_keywords:
            lines.append(f"Technologies: {', '.join(self.technology_keywords)}")
        if self.package_dependency_summary:
            lines.append(f"Dependencies: {self.package_dependency_summary}")
        if self.component_architecture_summary:
            lines.append(f"Architecture: {self.component_architecture_summary}")
        if self.current_milestone:
            lines.append(f"Milestone: {self.current_milestone}")
        return "\n".join(lines)


class AssistanceTask(BaseModel):
    """Typed local-model assistance task definition.

    Each task states its required enforcement class. A task requiring
    structured output must refuse if the local runtime lacks sufficient
    evidence-backed admission.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=_ASSISTANCE_TASK_SCHEMA, frozen=True)
    task_id: str
    task_kind: AssistanceTaskKind
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    required_enforcement_class: EnforcementClass = (
        EnforcementClass.JSON_OBJECT_FORMATTING_ONLY
    )
    context_packet_digest: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    target_publication_applicability: PublicationApplicability = (
        PublicationApplicability.INTERNAL_ONLY
    )

    def compute_task_digest(self) -> str:
        data = self.model_dump(mode="json", exclude={"created_at"})
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


class AssistanceResult(BaseModel):
    """Content-light result of a local-model assistance task.

    Raw model output exists only in the reviewable draft domain; it is
    never copied into content-light telemetry/evidence or public
    publication automatically. Draft content is referenced by SHA256
    digest only.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=_ASSISTANCE_RESULT_SCHEMA, frozen=True)
    result_id: str
    task_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: AssistanceExecutionStatus
    execution_latency_ms: int = 0
    model_safe_id: str = ""
    required_enforcement_class: EnforcementClass = EnforcementClass.UNSUPPORTED
    enforcement_class_used: EnforcementClass = EnforcementClass.UNSUPPORTED
    capability_admission_decision_digest: str = ""
    capability_admission_decision_id: str = ""
    output_disposition: OutputDisposition = OutputDisposition.NO_OUTPUT_PRODUCED
    publication_applicability: PublicationApplicability = PublicationApplicability.NONE
    draft_sha256: str = ""
    draft_byte_count: int = 0
    context_packet_digest: str = ""
    refusal_reason: str = ""
    refusal_code: str = ""
    output_token_count: int = 0
    input_token_count: int = 0
    content_light: bool = True

    def compute_result_digest(self) -> str:
        exclude = {"schema_version", "created_at"}
        data = self.model_dump(mode="json", exclude=exclude)
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


class AssistanceRefusal(BaseModel):
    """Typed refusal when a task cannot be executed safely."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    refusal_code: str
    reason: str
    required_enforcement_class: EnforcementClass
    available_enforcement_class: EnforcementClass = EnforcementClass.UNSUPPORTED
    context_packet_digest: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def build_rig_relay_project_packet() -> ProjectContextPacket:
    """Build a sanitized project context packet for Rig Relay itself.

    This is an M0-owned synthetic fixture containing public-safe information
    derived from the repository's published README and pyproject.toml.
    It does not crawl or embed raw repository content.
    """
    return ProjectContextPacket(
        packet_id="pkt_rig_relay_m0_fixture",
        project_name="Rig Relay",
        project_summary=(
            "A governed local server/control-plane with a desktop cockpit "
            "for coordinating agent work, observing runtime/tool behavior, "
            "and producing structured evidence. Features receipt-backed "
            "evidence, worktree isolation, multi-provider consultation "
            "(Council), and fleet orchestration."
        ),
        technology_keywords=[
            "Python 3.12+",
            "asyncio",
            "Pydantic",
            "httpx",
            "DuckDB",
            "WebSocket",
            "pywebview",
            "MCP",
            "Agent Client Protocol",
            "governed agent tools",
            "local inference",
            "fleet orchestration",
        ],
        package_dependency_summary=(
            "Core: pydantic, httpx, websockets, mcp, anyio, duckdb. "
            "Desktop: pywebview. CLI: rich, textual. "
            "Local: google-api-python-client, cryptography."
        ),
        component_architecture_summary=(
            "Packages: core (engine, agent loop, tools), desktop (cockpit backend, "
            "WebSocket server, projections), context (compiler, symbol indexing), "
            "recovery (constrained execution, capability admission), "
            "providers (model capabilities, local inference stack), "
            "coordination (store, leases, fleet), governance (auth, receipts)."
        ),
        current_milestone="Integration Wave 1: Lane M0 — Local Project Inference Service",
        public_safe=True,
        provenance="m0_synthetic_fixture",
    ).seal()


__all__ = [
    "AssistanceExecutionStatus",
    "AssistanceRefusal",
    "AssistanceResult",
    "AssistanceTask",
    "AssistanceTaskKind",
    "OutputDisposition",
    "ProjectContextPacket",
    "PublicationApplicability",
    "build_rig_relay_project_packet",
]
