from __future__ import annotations

from pathlib import Path

from rig_relay.investigation_timeline._assembler import InvestigationTimelineAssembler
from rig_relay.investigation_timeline._content_light import (
    enforce_content_light,
    enforce_content_light_dict,
)
from rig_relay.investigation_timeline._duckdb_export import build_duckdb_export
from rig_relay.investigation_timeline._models import (
    AuthorityClassification,
    DegradationSummary,
    DuckDBAuthorityAssertion,
    DuckDBDatasetDescriptor,
    DuckDBViewDefinition,
    InvestigationTimeline,
    InvestigationTimelineEvent,
    PostgresColumnDefinition,
    PostgresIndexDefinition,
    PostgresTimelineProjection,
    SourceDomain,
    TimelineAssemblyResult,
    TimelineDegradationMarker,
    TimelineDuckDBExport,
    TimelineEventKind,
    TimelineEvidenceSource,
    VerificationClass,
)
from rig_relay.investigation_timeline._pg_contract import build_postgres_projection

__all__ = [
    "AuthorityClassification",
    "DegradationSummary",
    "DuckDBAuthorityAssertion",
    "DuckDBDatasetDescriptor",
    "DuckDBViewDefinition",
    "InvestigationEvidenceTimelineService",
    "InvestigationTimeline",
    "InvestigationTimelineEvent",
    "PostgresColumnDefinition",
    "PostgresIndexDefinition",
    "PostgresTimelineProjection",
    "SourceDomain",
    "TimelineAssemblyResult",
    "TimelineDegradationMarker",
    "TimelineDuckDBExport",
    "TimelineEventKind",
    "TimelineEvidenceSource",
    "VerificationClass",
    "build_duckdb_export",
    "build_postgres_projection",
    "enforce_content_light",
    "enforce_content_light_dict",
]


class InvestigationEvidenceTimelineService:
    """Typed reconstruction boundary for investigation evidence timelines.

    Assembles content-light investigation timelines from canonical
    evidence domains, preserves provenance and authority status,
    and emits deterministic operational and analytical projection
    contracts for later PostgreSQL and DuckDB consumption.
    """

    def __init__(
        self,
        observability_path: str | Path | None = None,
        coordination_path: str | Path | None = None,
        disclosure_path: str | Path | None = None,
        publication_ledger_path: str | Path | None = None,
        investigation_id: str | None = None,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self._observability_path = observability_path
        self._coordination_path = coordination_path
        self._disclosure_path = disclosure_path
        self._publication_ledger_path = publication_ledger_path
        self._investigation_id = investigation_id
        self._session_id = session_id
        self._project_id = project_id

    def assemble_timeline(self) -> TimelineAssemblyResult:
        assembler = InvestigationTimelineAssembler(
            observability_path=self._observability_path,
            coordination_path=self._coordination_path,
            disclosure_path=self._disclosure_path,
            publication_ledger_path=self._publication_ledger_path,
            investigation_id=self._investigation_id,
            session_id=self._session_id,
            project_id=self._project_id,
        )
        return assembler.assemble()

    def build_postgres_projection(self) -> PostgresTimelineProjection:
        result = self.assemble_timeline()
        return build_postgres_projection(result.timeline)

    def build_duckdb_export(self, output_dir: str | Path) -> TimelineDuckDBExport:
        result = self.assemble_timeline()
        return build_duckdb_export(result.timeline, output_dir)
