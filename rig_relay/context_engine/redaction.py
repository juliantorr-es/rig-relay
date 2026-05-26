"""Redaction engine for public-safe projection.

Ensures private repository contents never leak into publication
projections. Classifies each field by privacy disposition and strips
or redacts fields that must not appear in public-safe output.
"""

from __future__ import annotations

from rig_relay.context_engine.models import (
    ProjectUnderstandingProjection,
    PublicStructuralFact,
    PublishableProjectProfileCandidate,
    RedactionLog,
    WithheldItemsSummary,
)
from rig_relay.context_engine.provenance import PrivacyDisposition


class ProjectRedactionEngine:
    """Strips private/internal-only content from project understanding.

    Transforms a full-fidelity ProjectUnderstandingProjection into a
    public-safe PublishableProjectProfileCandidate. All source paths,
    extraction methods, and internal-only facts are withheld or redacted.
    Generated claims retain their proposed status. No raw repository
    content survives the redaction boundary.
    """

    def redact_for_publication(
        self, understanding: ProjectUnderstandingProjection
    ) -> PublishableProjectProfileCandidate:
        """Produce a public-safe profile candidate from a full understanding.

        Only public-safe structural facts survive. Source paths, extraction
        methods, evidence references, and internal-only facts are stripped.
        Generated claims retain their proposed status.
        """
        withheld_count = 0
        redacted_count = 0
        reasons: list[str] = []
        categories_withheld: list[str] = []

        public_facts: list[PublicStructuralFact] = []
        for fact in understanding.structural_facts:
            if fact.privacy_disposition == PrivacyDisposition.PUBLIC_SAFE:
                public_facts.append(
                    PublicStructuralFact(
                        fact_id=fact.fact_id,
                        category=fact.category,
                        value=fact.value,
                        confidence=fact.confidence,
                    )
                )
            else:
                withheld_count += 1
                if fact.category not in categories_withheld:
                    categories_withheld.append(fact.category)

        if understanding.evidence_facts:
            redacted_count += len(understanding.evidence_facts)
            reasons.append(
                "Evidence-derived facts withheld: not public-safe by default"
            )
            categories_withheld.append("evidence_facts")

        if understanding.approved_content:
            for item in understanding.approved_content:
                if item.privacy_disposition == PrivacyDisposition.PUBLIC_SAFE:
                    pass

        if understanding.withheld_items.count > 0:
            withheld_count += understanding.withheld_items.count
            reasons.extend(understanding.withheld_items.reasons)

        reasons = list(dict.fromkeys(reasons))
        categories_withheld = list(dict.fromkeys(categories_withheld))

        from rig_relay.context_engine.models import (
            Accomplishments,
            GeneratedNarrative,
            ProjectPageIdentity,
            PublicationReadiness,
            ReleasedBoundary,
            StatusOverview,
        )

        identity = ProjectPageIdentity(
            project_name=understanding.project_identity.project_name,
            tagline=_derive_tagline(understanding),
            current_milestone="",
            product_identity_blurb=_derive_blurb(understanding),
        )

        from rig_relay.context_engine.provenance import ApprovalStatus

        narrative_sections: dict[str, GeneratedNarrative] = {}
        for claim in understanding.generated_claims:
            narrative_sections[claim.category] = GeneratedNarrative(
                narrative=claim.narrative,
                approval_status=claim.approval_status,
                basis_fact_ids=claim.basis_facts,
            )

        if understanding.bootstrap_gaps:
            if "bootstrap_gaps" not in narrative_sections:
                narrative_sections["bootstrap_gaps"] = GeneratedNarrative(
                    narrative="; ".join(understanding.bootstrap_gaps),
                    approval_status=ApprovalStatus.PROPOSED,
                    basis_fact_ids=[],
                )

        architecture: dict[str, str] = {}
        if public_facts:
            lang_str = ", ".join(
                sorted(set(f.value for f in public_facts if f.category == "language"))
            )
            fw_str = ", ".join(
                sorted(set(f.value for f in public_facts if f.category == "framework"))
            )
            if lang_str:
                architecture["languages"] = lang_str
            if fw_str:
                architecture["frameworks"] = fw_str

        boundaries: list[ReleasedBoundary] = []
        for claim in understanding.generated_claims:
            if claim.category == "released_boundary":
                boundaries.append(
                    ReleasedBoundary(
                        boundary_name=claim.claim_id, release_status="claimed"
                    )
                )

        missing_sections: list[str] = []
        if not public_facts:
            missing_sections.append("structural_facts")
        if not understanding.generated_claims:
            missing_sections.append("generated_narrative")

        candidate = PublishableProjectProfileCandidate(
            candidate_id=f"candidate_{understanding.projection_id}",
            project_identity=identity,
            structural_facts_public=public_facts,
            technology_capabilities=understanding.technology_signals,
            status_overview=StatusOverview(
                overall_status="alpha", evidence_backed=bool(public_facts)
            ),
            accomplishments=Accomplishments(),
            architecture_overview=architecture,
            released_boundaries=boundaries,
            generated_narrative_sections=narrative_sections,
            approval_status=ApprovalStatus.PROPOSED,
            redaction_log=RedactionLog(
                items_withheld=withheld_count,
                items_redacted=redacted_count,
                reasons=reasons,
            ),
            publication_readiness=PublicationReadiness(
                ready_for_publication=len(missing_sections) == 0,
                missing_sections=missing_sections,
            ),
        )
        candidate.candidate_digest = candidate.compute_digest()
        return candidate

    def build_withheld_summary(
        self, understanding: ProjectUnderstandingProjection
    ) -> WithheldItemsSummary:
        """Extract a content-light summary of withheld items."""
        return understanding.withheld_items


def _derive_tagline(understanding: ProjectUnderstandingProjection) -> str:
    for claim in understanding.generated_claims:
        if claim.category == "tagline":
            return claim.narrative
    languages = understanding.technology_signals.languages
    if languages:
        return f"A {', '.join(languages[:2])} project"
    return ""


def _derive_blurb(understanding: ProjectUnderstandingProjection) -> str:
    for claim in understanding.generated_claims:
        if claim.category in {"project_description", "product_identity_blurb"}:
            return claim.narrative
    return ""


__all__ = ["ProjectRedactionEngine"]
