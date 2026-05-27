from __future__ import annotations

from pathlib import Path
import time

from rig_relay.investigation_timeline._adapters import (
    adapt_checkpoint_events,
    adapt_coordination_events,
    adapt_disclosure_transitions,
    adapt_observability_events,
    adapt_publication_preview_events,
)
from rig_relay.investigation_timeline._content_light import enforce_content_light
from rig_relay.investigation_timeline._degradation import build_degraded_evidence_event
from rig_relay.investigation_timeline._models import (
    AuthorityClassification,
    DegradationSummary,
    InvestigationTimeline,
    InvestigationTimelineEvent,
    SourceDomain,
    TimelineAssemblyResult,
    TimelineEvidenceSource,
)


class InvestigationTimelineAssembler:
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
        self._observability_path = (
            Path(observability_path) if observability_path else None
        )
        self._coordination_path = Path(coordination_path) if coordination_path else None
        self._disclosure_path = Path(disclosure_path) if disclosure_path else None
        self._publication_ledger_path = (
            Path(publication_ledger_path) if publication_ledger_path else None
        )
        self._investigation_id = investigation_id
        self._session_id = session_id
        self._project_id = project_id

    def assemble(self) -> TimelineAssemblyResult:
        start_time = time.monotonic()
        all_events: list[InvestigationTimelineEvent] = []
        sources: list[TimelineEvidenceSource] = []
        warnings: list[str] = []
        errors: list[str] = []

        domains = [
            (
                SourceDomain.OBSERVABILITY,
                self._observability_path,
                self._ingest_observability,
            ),
            (
                SourceDomain.COORDINATION,
                self._coordination_path,
                self._ingest_coordination,
            ),
            (SourceDomain.DISCLOSURE, self._disclosure_path, self._ingest_disclosure),
            (
                SourceDomain.CHECKPOINT,
                self._observability_path,
                self._ingest_checkpoints,
            ),
            (
                SourceDomain.PUBLICATION,
                self._publication_ledger_path,
                self._ingest_publication,
            ),
        ]

        unsupported_domains: list[str] = []
        for domain, path, ingest_fn in domains:
            if path is None:
                unsupported_domains.append(domain.value)
                sources.append(
                    TimelineEvidenceSource(
                        source_domain=domain,
                        events_ingested=0,
                        errors=0,
                        status="unsupported",
                    )
                )
                continue

            try:
                events, ingest_errors = ingest_fn()
                all_events.extend(events)
                src = TimelineEvidenceSource(
                    source_domain=domain,
                    source_path=str(path),
                    events_ingested=len(events),
                    errors=len(ingest_errors),
                    status="ok" if not ingest_errors else "partial",
                    schema_version="rig.relay.investigation_timeline_event.v1",
                )
                sources.append(src)
                errors.extend(ingest_errors)
            except Exception as exc:
                errors.append(f"ingest failed for {domain.value}: {exc}")
                all_events.append(
                    build_degraded_evidence_event(
                        domain=domain,
                        detail=f"ingest exception: {exc}",
                        investigation_id=self._investigation_id,
                        session_id=self._session_id,
                    )
                )
                sources.append(
                    TimelineEvidenceSource(
                        source_domain=domain,
                        source_path=str(path),
                        events_ingested=0,
                        errors=1,
                        status="failed",
                    )
                )

        if unsupported_domains:
            warnings.append(
                f"unsupported domains (no path provided): {', '.join(unsupported_domains)}"
            )

        all_events = _sort_events_deterministically(all_events)

        for i, event in enumerate(all_events):
            event.timeline_sequence = i

        content_light_violations = enforce_content_light(all_events)
        if content_light_violations:
            warnings.append(
                f"content-light violations detected: {len(content_light_violations)} violations"
            )
            errors.extend(content_light_violations)

        domain_coverage: dict[str, int] = {}
        for src in sources:
            if src.events_ingested > 0:
                domain_coverage[src.source_domain.value] = src.events_ingested

        deg_summary = _build_degradation_summary(all_events)

        timeline = InvestigationTimeline(
            investigation_id=self._investigation_id,
            session_id=self._session_id,
            project_id=self._project_id,
            events=all_events,
            event_count=len(all_events),
            domain_coverage=domain_coverage,
            unsupported_domains=unsupported_domains,
            degradation_summary=deg_summary,
        )
        timeline.projection_digest = timeline.compute_projection_digest()

        elapsed_ms = (time.monotonic() - start_time) * 1000

        return TimelineAssemblyResult(
            timeline=timeline,
            sources=sources,
            assembly_duration_ms=elapsed_ms,
            warnings=warnings,
            errors=errors,
        )

    def _ingest_observability(
        self,
    ) -> tuple[list[InvestigationTimelineEvent], list[str]]:
        if self._observability_path is None:
            return [], ["no observability path"]
        return adapt_observability_events(
            self._observability_path, investigation_id=self._investigation_id
        )

    def _ingest_coordination(
        self,
    ) -> tuple[list[InvestigationTimelineEvent], list[str]]:
        if self._coordination_path is None:
            return [], ["no coordination path"]
        return adapt_coordination_events(
            self._coordination_path, investigation_id=self._investigation_id
        )

    def _ingest_disclosure(self) -> tuple[list[InvestigationTimelineEvent], list[str]]:
        if self._disclosure_path is None:
            return [], ["no disclosure path"]
        return adapt_disclosure_transitions(
            self._disclosure_path, investigation_id=self._investigation_id
        )

    def _ingest_checkpoints(self) -> tuple[list[InvestigationTimelineEvent], list[str]]:
        if self._observability_path is None:
            return [], ["no observability path for checkpoints"]
        return adapt_checkpoint_events(
            self._observability_path, investigation_id=self._investigation_id
        )

    def _ingest_publication(self) -> tuple[list[InvestigationTimelineEvent], list[str]]:
        if self._publication_ledger_path is None:
            return [], ["no publication ledger path"]
        return adapt_publication_preview_events(
            self._publication_ledger_path, investigation_id=self._investigation_id
        )


def _sort_events_deterministically(
    events: list[InvestigationTimelineEvent],
) -> list[InvestigationTimelineEvent]:
    return sorted(
        events,
        key=lambda e: (
            e.observed_at or "",
            e.source_sequence if e.source_sequence is not None else 0,
            e.source_event_id or "",
            e.event_id,
        ),
    )


def _build_degradation_summary(
    events: list[InvestigationTimelineEvent],
) -> DegradationSummary:
    summary = DegradationSummary(total_events=len(events))
    for event in events:
        match event.authority_classification:
            case AuthorityClassification.CANONICAL_LIVE:
                summary.canonical_live_count += 1
            case AuthorityClassification.MISSING:
                summary.missing_count += 1
            case AuthorityClassification.CONTRADICTORY:
                summary.contradictory_count += 1
            case AuthorityClassification.CORRUPT:
                summary.corrupt_count += 1
            case AuthorityClassification.STALE:
                summary.stale_count += 1
            case _:
                summary.degraded_count += 1
    return summary
