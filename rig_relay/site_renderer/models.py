from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SafetyStatus(StrEnum):
    PUBLIC_SAFE = "public_safe"
    CONTENT_LIGHT = "content_light"
    REDACTED = "redacted"
    INTERNAL_ONLY = "internal_only"


class StatusClass(StrEnum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    INFO = "info"


class SectionKind(StrEnum):
    HERO_STATUS = "hero_status"
    CARD_GRID = "card_grid"
    TABLE = "table"
    TIMELINE = "timeline"
    DEFINITION_LIST = "definition_list"
    ARTIFACT_NAV = "artifact_nav"
    CALLOUT = "callout"
    SCHEMA_INDEX = "schema_index"


class SourceType(StrEnum):
    JSON = "json"
    JSONL = "jsonl"
    CSV = "csv"
    SCHEMA = "schema"
    MERMAID = "mermaid"
    STATIC_ASSET = "static_asset"


class RendererKind(StrEnum):
    RELEASE_GATE = "release_gate"
    RC_VERDICT = "rc_verdict"
    GOLDEN_PATH = "golden_path"
    TEST_INVENTORY = "test_inventory"
    INTEGRATION_MANIFEST = "integration_manifest"
    MCP_MANIFEST = "mcp_manifest"
    TELEMETRY_POLICY = "telemetry_policy"
    BRIDGE_LIFECYCLE = "bridge_lifecycle"
    FRONTEND_MATURITY = "frontend_maturity"
    SECURITY_HYGIENE = "security_hygiene"
    SCHEMA_INDEX = "schema_index"
    README = "readme"
    COMPILER_CONTRACT = "compiler_contract"
    COMPILER_REFINEMENT = "compiler_refinement"
    A2A_READINESS = "a2a_readiness"
    IDE_IPC = "ide_ipc"
    MCP_TOOLS = "mcp_tools"
    PROTOCOL_SURFACES = "protocol_surfaces"
    OTEL_CONFIG = "otel_config"
    OTEL_INGESTION = "otel_ingestion"
    TRACING_MATRIX = "tracing_matrix"
    TRACING_POLICY = "tracing_policy"
    TEST_SEAMS = "test_seams"
    DEFERRED_RISKS = "deferred_risks"
    INPUT_MANIFEST = "input_manifest"
    EXPERIENCE_ELEVATION = "experience_elevation"


class HeroStatusSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[SectionKind.HERO_STATUS] = SectionKind.HERO_STATUS
    title: str
    status_label: str
    status_class: StatusClass
    summary: str = ""
    blocker_count: int | None = None
    ready_count: int | None = None
    failed_count: int | None = None


class CardGridCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body_html: str = ""
    status: str = "info"
    source_ref: str | None = None


class CardGridSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[SectionKind.CARD_GRID] = SectionKind.CARD_GRID
    title: str = ""
    cards: list[CardGridCard]


class TableSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[SectionKind.TABLE] = SectionKind.TABLE
    caption: str = ""
    headers: list[str]
    rows: list[list[str]]


class TimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str = ""
    title: str
    description: str = ""
    status: str | None = None


class TimelineSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[SectionKind.TIMELINE] = SectionKind.TIMELINE
    heading: str = ""
    entries: list[TimelineEntry]


class DefinitionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str
    definition: str


class DefinitionListSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[SectionKind.DEFINITION_LIST] = SectionKind.DEFINITION_LIST
    heading: str = ""
    items: list[DefinitionItem]


class ArtifactNavLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    href: str
    description: str = ""


class ArtifactNavSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[SectionKind.ARTIFACT_NAV] = SectionKind.ARTIFACT_NAV
    heading: str = ""
    links: list[ArtifactNavLink]


class CalloutSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[SectionKind.CALLOUT] = SectionKind.CALLOUT
    heading: str = ""
    body_html: str
    callout_class: StatusClass = StatusClass.INFO


class SchemaIndexEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: str
    file_path: str
    description: str = ""


class SchemaIndexSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[SectionKind.SCHEMA_INDEX] = SectionKind.SCHEMA_INDEX
    heading: str = ""
    entries: list[SchemaIndexEntry]


Section = Annotated[
    HeroStatusSection
    | CardGridSection
    | TableSection
    | TimelineSection
    | DefinitionListSection
    | ArtifactNavSection
    | CalloutSection
    | SchemaIndexSection,
    Field(discriminator="kind"),
]


class PageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.site.page.v1"
    page_id: str
    title: str
    route: str
    layout: Literal["default", "hero", "dashboard"] = "default"
    source_artifact_paths: list[str] = Field(default_factory=list)
    generated_from_schema_versions: list[str] = Field(default_factory=list)
    public_safety_status: SafetyStatus = SafetyStatus.PUBLIC_SAFE
    sections: list[Section] = Field(default_factory=list)
    generated_at: datetime | None = None


class InputEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    source_type: SourceType
    page_id: str
    renderer_kind: RendererKind
    schema_path: str | None = None
    freshness_policy: Literal["always", "if_schema_valid", "optional"] = "always"
    public_safe: bool
    redaction_required: bool = False


class InputManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.site.input_manifest.v1"
    generated_at: datetime | None = None
    head_sha: str = ""
    branch: str = "main"
    inputs: list[InputEntry]


class PageRenderResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str
    title: str
    route: str
    status: Literal["rendered", "warning", "failed"] = "rendered"
    source_artifact_paths: list[str] = Field(default_factory=list)
    safety_notes: str = ""


class RenderReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.site.render_report.v1"
    generated_at: datetime | None = None
    head_sha: str = ""
    branch: str = "main"
    render_duration_ms: int = 0
    pages_rendered: int = 0
    pages_failed: int = 0
    safety_passed: bool = False
    pages: list[PageRenderResult] = Field(default_factory=list)


__all__ = [
    "ArtifactNavLink",
    "ArtifactNavSection",
    "CalloutSection",
    "CardGridCard",
    "CardGridSection",
    "DefinitionItem",
    "DefinitionListSection",
    "HeroStatusSection",
    "InputEntry",
    "InputManifest",
    "PageModel",
    "PageRenderResult",
    "RenderReport",
    "RendererKind",
    "SafetyStatus",
    "SchemaIndexEntry",
    "SchemaIndexSection",
    "Section",
    "SectionKind",
    "SourceType",
    "StatusClass",
    "TableSection",
    "TimelineEntry",
    "TimelineSection",
]
