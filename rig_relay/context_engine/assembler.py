"""Project Context Assembly Service.

The primary service boundary for Lane L0. Transforms an imported
and investigated repository into:
  1. ProjectUnderstandingProjection (private, operator-facing)
  2. PublishableProjectProfileCandidate (public-safe, awaiting approval)
  3. DeveloperCorpusIndex entry (private, for portfolio synthesis)
  4. SanitizedContextPacket (bounded, provenance-rich context payload)

Consumes J0 intake fixtures (until live), K0 investigation fixtures
(until live), E0 frontend contracts, and source-derived structural
extraction. All generated interpretations are marked proposed.
"""

from __future__ import annotations

from hashlib import sha256

from rig_relay.context_engine.context_packet import build_sanitized_context_packet
from rig_relay.context_engine.extractor import SourceDerivedStructuralExtractor
from rig_relay.context_engine.fixtures import (
    IntakeFixture,
    InvestigationEvidenceFixture,
)
from rig_relay.context_engine.gridline_projection import (
    GridlineProjectUnderstandingProjection,
    PortfolioEligibilityState,
    build_gridline_project_understanding_projection,
)
from rig_relay.context_engine.models import (
    DeveloperCorpusIndex,
    ProjectIdentity,
    ProjectReference,
    ProjectUnderstandingProjection,
    PublicationAssets,
    PublishableProjectProfileCandidate,
    SanitizedContextPacket,
    TechnologyIndex,
    TechnologySignals,
    UncertaintyMarkers,
    WithheldItemsSummary,
)
from rig_relay.context_engine.provenance import (
    ApprovalStatus,
    ApprovedContent,
    EvidenceDerivedFact,
    GeneratedClaim,
)
from rig_relay.context_engine.redaction import ProjectRedactionEngine


class ProjectContextAssemblyService:
    """Transforms repository intake and investigation into typed understanding.

    The core service boundary for Lane L0. Consumers:
      - J0 RepositoryIntakeService (via IntakeFixture in this release)
      - K0 AgentLoop investigation (via InvestigationEvidenceFixture)
      - E0 frontend contracts (via PublishableProjectProfileCandidate shape)
      - SourceDerivedStructuralExtractor (deterministic repo analysis)

    Produces:
      - ProjectUnderstandingProjection (internal)
      - PublishableProjectProfileCandidate (public-safe, awaiting approval)
      - DeveloperCorpusIndex (private index update)
      - SanitizedContextPacket (for AgentLoop/local inference)
      - GridlineProjectUnderstandingProjection (for desktop cockpit)
    """

    def __init__(self) -> None:
        self._redaction_engine = ProjectRedactionEngine()

    def assemble(
        self,
        intake: IntakeFixture,
        investigation: InvestigationEvidenceFixture | None = None,
    ) -> ProjectUnderstandingProjection:
        """Assemble a full project understanding from intake and evidence.

        Args:
            intake: J0 repository intake fixture (or live service result).
            investigation: K0 investigation evidence fixture (or live result).
                May be None if no investigation has been performed.

        Returns:
            A provenance-bound project understanding projection.
        """
        extractor = SourceDerivedStructuralExtractor(intake.repository_root)

        structural_facts = extractor.extract_all(intake)
        technology_signals = extractor.extract_technology_signals(intake)
        publication_assets = extractor.extract_publication_assets()
        test_signals = extractor.extract_test_signals()
        bootstrap_gaps = extractor.extract_bootstrap_gaps()
        dependency_status = extractor.extract_intake_dependency_status()

        evidence_facts = _build_evidence_facts(investigation)

        generated_claims = _build_generated_claims(
            intake,
            structural_facts,
            technology_signals,
            publication_assets,
            bootstrap_gaps,
        )

        approved_content: list[ApprovedContent] = []

        withheld_items = _build_withheld_summary(structural_facts, intake)

        uncertainty = _build_uncertainty(structural_facts, evidence_facts)

        identity = ProjectIdentity(
            project_name=intake.project_name,
            repository_url_digest=intake.repository_url_digest,
            head_sha=intake.head_sha,
            branch=intake.branch,
            remotes_count=intake.remotes_count,
            is_github_backed=intake.is_github_backed,
            is_local_only=intake.is_local_only,
        )

        projection_id = _compute_projection_id(intake)

        understanding = ProjectUnderstandingProjection(
            projection_id=projection_id,
            project_identity=identity,
            structural_facts=structural_facts,
            evidence_facts=evidence_facts,
            generated_claims=generated_claims,
            approved_content=approved_content,
            technology_signals=technology_signals,
            publication_assets=publication_assets,
            test_signals=test_signals,
            bootstrap_gaps=bootstrap_gaps,
            withheld_items=withheld_items,
            uncertainty=uncertainty,
            intake_dependency_status=dependency_status,
        )
        understanding.projection_digest = understanding.compute_digest()
        return understanding

    def assemble_profile_candidate(
        self, understanding: ProjectUnderstandingProjection
    ) -> PublishableProjectProfileCandidate:
        """Produce a public-safe profile candidate from understanding.

        Redacts private/internal-only content through the redaction engine.
        All generated claims retain their proposed status.
        """
        return self._redaction_engine.redact_for_publication(understanding)

    def assemble_context_packet(
        self, understanding: ProjectUnderstandingProjection, total_tokens: int = 4096
    ) -> SanitizedContextPacket:
        """Build a sanitized context packet for AgentLoop or local inference."""
        return build_sanitized_context_packet(
            understanding_id=understanding.projection_id,
            project_name=understanding.project_identity.project_name,
            languages=understanding.technology_signals.languages,
            frameworks=understanding.technology_signals.frameworks,
            test_frameworks=understanding.technology_signals.test_frameworks,
            build_systems=understanding.technology_signals.build_systems,
            file_count=0,
            subsystem_count=0,
            has_documentation=understanding.publication_assets.has_readme,
            has_tests=understanding.test_signals.test_framework_detected,
            has_ci=understanding.test_signals.ci_test_pipeline_detected,
            total_tokens=total_tokens,
        )

    def assemble_gridline_projection(
        self,
        understanding: ProjectUnderstandingProjection,
        context_packet: SanitizedContextPacket | None = None,
    ) -> GridlineProjectUnderstandingProjection:
        """Build a content-light Gridline projection for desktop cockpit."""
        public_assets: list[str] = []
        if understanding.publication_assets.has_readme:
            public_assets.append("README.md")
        if understanding.publication_assets.has_license:
            public_assets.append("LICENSE")
        if understanding.publication_assets.has_documentation_site:
            public_assets.append("docs/ site")

        awaiting = sum(
            1
            for c in understanding.generated_claims
            if c.approval_status == ApprovalStatus.PROPOSED
        )

        portfolio_eligible = (
            PortfolioEligibilityState.CANDIDATE
            if understanding.structural_facts
            else PortfolioEligibilityState.NOT_INCLUDED
        )

        categories = sorted(set(f.category for f in understanding.structural_facts))

        return build_gridline_project_understanding_projection(
            projection_id=understanding.projection_id,
            project_name=understanding.project_identity.project_name,
            head_sha=understanding.project_identity.head_sha,
            branch=understanding.project_identity.branch,
            fact_count=len(understanding.structural_facts),
            fact_categories=categories,
            languages_detected=understanding.technology_signals.languages,
            frameworks_detected=understanding.technology_signals.frameworks,
            test_frameworks_detected=understanding.technology_signals.test_frameworks,
            public_assets=public_assets,
            withheld_count=understanding.withheld_items.count,
            withheld_reasons=understanding.withheld_items.reasons,
            draft_count=len(understanding.generated_claims),
            draft_awaiting=awaiting,
            bootstrap_gaps=understanding.bootstrap_gaps,
            context_packet_ready=context_packet is not None,
            context_packet_digest=context_packet.packet_digest
            if context_packet
            else "",
            portfolio_eligible=portfolio_eligible,
            approval_status=ApprovalStatus.PROPOSED,
        )

    def build_corpus_index_entry(
        self,
        understanding: ProjectUnderstandingProjection,
        existing_corpus: DeveloperCorpusIndex | None = None,
    ) -> DeveloperCorpusIndex:
        """Build or update the developer corpus index with this project."""
        ref = ProjectReference(
            project_ref_id=_compute_project_ref_id(understanding),
            project_name=understanding.project_identity.project_name,
            repository_url_digest=understanding.project_identity.repository_url_digest,
            profile_approval_status="pending_developer_review",
            portfolio_eligible=bool(understanding.structural_facts),
            technology_signals=understanding.technology_signals,
            case_study_eligible=bool(
                understanding.structural_facts and understanding.evidence_facts
            ),
            released_boundary_count=len(understanding.generated_claims),
            last_updated=understanding.generated_at,
            profile_candidate_digest=understanding.projection_digest,
        )

        tech_index = TechnologyIndex()
        if existing_corpus:
            tech_index = existing_corpus.technology_index
            # Merge in new project's technology signals
            for lang in understanding.technology_signals.languages:
                if lang not in tech_index.languages:
                    tech_index.languages[lang] = []
                if (
                    understanding.project_identity.project_name
                    not in tech_index.languages[lang]
                ):
                    tech_index.languages[lang].append(
                        understanding.project_identity.project_name
                    )

        # Build fresh corpus or update existing
        if existing_corpus:
            refs = list(existing_corpus.project_references)
            # Replace existing entry for same project or append
            replaced = False
            for i, existing_ref in enumerate(refs):
                if existing_ref.project_name == ref.project_name:
                    refs[i] = ref
                    replaced = True
                    break
            if not replaced:
                refs.append(ref)
        else:
            refs = [ref]

        profile_ready = sum(1 for r in refs if r.profile_approval_status == "approved")
        candidates = sum(
            1 for r in refs if r.profile_approval_status == "pending_developer_review"
        )

        corpus = DeveloperCorpusIndex(
            corpus_id=_compute_corpus_id(refs),
            project_references=refs,
            technology_index=tech_index,
            profile_ready_count=profile_ready,
            candidate_count=candidates,
            total_projects_indexed=len(refs),
            portfolio_synthesis_status=_synthesis_status(profile_ready, candidates),
        )
        corpus.corpus_digest = corpus.compute_digest()
        return corpus


# ── Private helpers ───────────────────────────────────────────────────


def _build_evidence_facts(
    investigation: InvestigationEvidenceFixture | None,
) -> list[EvidenceDerivedFact]:
    if investigation is None:
        return []
    facts: list[EvidenceDerivedFact] = []
    for i, finding in enumerate(investigation.findings):
        facts.append(
            EvidenceDerivedFact(
                fact_id=f"evidence_{i:04d}",
                category=finding.category,
                value=finding.summary,
                evidence_ref=investigation.investigation_sha,
                confidence="medium",
            )
        )
    return facts


def _build_generated_claims(
    intake: IntakeFixture,
    structural_facts: list,
    technology_signals: TechnologySignals,
    publication_assets: PublicationAssets,
    bootstrap_gaps: list[str],
) -> list[GeneratedClaim]:
    claims: list[GeneratedClaim] = []
    fact_ids = [f.fact_id for f in structural_facts]

    # Project description claim
    lang_str = (
        ", ".join(technology_signals.languages)
        if technology_signals.languages
        else "unknown language"
    )
    fw_str = (
        ", ".join(technology_signals.frameworks[:5])
        if technology_signals.frameworks
        else ""
    )
    desc = f"A {lang_str} project"
    if fw_str:
        desc += f" using {fw_str}"
    desc += "."

    claims.append(
        GeneratedClaim(
            claim_id="claim_project_description",
            category="project_description",
            narrative=desc,
            basis_facts=fact_ids[:10],
            approval_status=ApprovalStatus.PROPOSED,
        )
    )

    # Tagline claim
    if technology_signals.languages:
        tagline = f"{intake.project_name} — a {technology_signals.languages[0]} project"
        claims.append(
            GeneratedClaim(
                claim_id="claim_tagline",
                category="tagline",
                narrative=tagline,
                basis_facts=fact_ids[:5],
                approval_status=ApprovalStatus.PROPOSED,
            )
        )

    # Publication readiness claim
    if bootstrap_gaps:
        claims.append(
            GeneratedClaim(
                claim_id="claim_bootstrap_gaps",
                category="bootstrap_recommendations",
                narrative="; ".join(bootstrap_gaps),
                basis_facts=[],
                approval_status=ApprovalStatus.PROPOSED,
            )
        )

    # Architecture claim from frameworks
    if technology_signals.frameworks:
        arch_desc = "Built with: " + ", ".join(technology_signals.frameworks[:8])
        if technology_signals.test_frameworks:
            arch_desc += ". Testing: " + ", ".join(
                technology_signals.test_frameworks[:4]
            )
        claims.append(
            GeneratedClaim(
                claim_id="claim_architecture_overview",
                category="architecture_overview",
                narrative=arch_desc,
                basis_facts=fact_ids[:10],
                approval_status=ApprovalStatus.PROPOSED,
            )
        )

    # Capability labels from tool signals
    caps: list[str] = []
    if technology_signals.lint_tools:
        caps.append(f"lint: {', '.join(technology_signals.lint_tools)}")
    if technology_signals.type_checkers:
        caps.append(f"type-check: {', '.join(technology_signals.type_checkers)}")
    if technology_signals.formatters:
        caps.append(f"format: {', '.join(technology_signals.formatters)}")
    if caps:
        claims.append(
            GeneratedClaim(
                claim_id="claim_capability_labels",
                category="capability_label",
                narrative="; ".join(caps),
                basis_facts=fact_ids[:10],
                approval_status=ApprovalStatus.PROPOSED,
            )
        )

    return claims


def _build_withheld_summary(
    structural_facts: list, intake: IntakeFixture
) -> WithheldItemsSummary:
    internal_only = [
        f
        for f in structural_facts
        if f.privacy_disposition.value in {"internal_only", "withheld", "redacted"}
    ]
    return WithheldItemsSummary(
        count=len(internal_only),
        reasons=["source_paths_redacted_in_public_candidate"] if internal_only else [],
        categories=sorted(set(f.category for f in internal_only)),
    )


def _build_uncertainty(
    structural_facts: list, evidence_facts: list[EvidenceDerivedFact]
) -> UncertaintyMarkers:
    low_conf = sum(1 for f in structural_facts if f.confidence == "low")
    indeterminate = sum(
        1 for f in structural_facts if f.confidence in {"low", "medium"}
    )
    needs_inv = 0
    if not structural_facts:
        needs_inv += 1
    return UncertaintyMarkers(
        indeterminate_count=indeterminate,
        low_confidence_count=low_conf,
        needs_investigation_count=needs_inv,
    )


def _compute_projection_id(intake: IntakeFixture) -> str:
    body = f"{intake.project_name}:{intake.head_sha}:{intake.branch}"
    return f"proj_understanding_{sha256(body.encode()).hexdigest()[:12]}"


def _compute_project_ref_id(understanding: ProjectUnderstandingProjection) -> str:
    return f"proj_ref_{understanding.projection_id[-12:]}"


def _compute_corpus_id(refs: list[ProjectReference]) -> str:
    body = ",".join(sorted(r.project_name for r in refs))
    return f"corpus_{sha256(body.encode()).hexdigest()[:12]}"


def _synthesis_status(profile_ready: int, candidates: int) -> str:
    if profile_ready == 0:
        return "not_started"
    if candidates > 0:
        return "waiting_approvals"
    return "ready_for_synthesis"


__all__ = ["ProjectContextAssemblyService"]
