from __future__ import annotations

from rig_relay.publication._models import (
    ProjectPagePreviewReport,
    ProposedContentSummary,
    PublicationReadinessSummary,
    WithheldSummary,
    _digest_sha256,
    _now_iso,
)

_VALID_APPROVAL_STATUSES: frozenset[str] = frozenset({
    "proposed",
    "pending_review",
    "approved",
    "rejected",
    "superseded",
})


def build_preview_report(
    projection: dict,
    compiler_input: dict,
    safety_passed: bool,
    schema_validation_passed: bool,
) -> ProjectPagePreviewReport:
    """Construct a preview report from the compiled projection and input state.

    Describes what is public, what is withheld, what is proposed pending approval,
    and what publication readiness/action remains.
    """
    now = _now_iso()
    projection_id = projection.get("projection_id", "unknown")
    report_id = _digest_sha256(f"preview_report:{projection_id}:{now}")[:30]

    withheld = _build_withheld_summary(projection)
    proposed_content = _build_proposed_content_summary(projection, compiler_input)
    publication_readiness = _build_publication_readiness_summary(compiler_input)

    public_section_count = _count_public_sections(projection)

    approval_gate = _check_approval_gate(projection, compiler_input)
    ready_for_preview = safety_passed and schema_validation_passed and approval_gate
    ready_for_deployment = (
        ready_for_preview
        and compiler_input.get("publication_policy", "preview_only") != "preview_only"
        and publication_readiness.publication_eligible
    )

    warnings: list[str] = []
    recommendations: list[str] = []

    if proposed_content.requires_developer_review:
        warnings.append(
            f"{proposed_content.sections_proposed} generated sections require developer review before publication"
        )
        recommendations.append(
            "Review and approve generated narrative sections before deploying"
        )

    if not publication_readiness.publication_eligible:
        warnings.append(
            "Repository is not currently eligible for GitHub Pages publication"
        )
        if publication_readiness.blockers:
            for blocker in publication_readiness.blockers:
                recommendations.append(f"Resolve blocker: {blocker}")

    if publication_readiness.pages_action_state == "planned":
        recommendations.append(
            "Developer approval required before GitHub Pages configuration"
        )

    if withheld.total_items_withheld > 0:
        warnings.append(
            f"{withheld.total_items_withheld} items withheld from public output for safety"
        )

    if not safety_passed:
        warnings.append("Publication safety scan failed — output must not be deployed")
        recommendations.append("Fix safety scan issues before any deployment")

    return ProjectPagePreviewReport(
        report_id=report_id,
        projection_id=projection_id,
        generated_at=now,
        public_section_count=public_section_count,
        withheld=withheld,
        proposed_content=proposed_content,
        publication_readiness=publication_readiness,
        approval_gate_passed=approval_gate,
        safety_scan_passed=safety_passed,
        schema_validation_passed=schema_validation_passed,
        ready_for_preview=ready_for_preview,
        ready_for_deployment=ready_for_deployment,
        warnings=warnings,
        recommendations=recommendations,
    )


def _build_withheld_summary(projection: dict) -> WithheldSummary:
    redaction_log = projection.get("redaction_log", {})
    if not isinstance(redaction_log, dict):
        redaction_log = {}

    total_withheld = redaction_log.get("items_withheld", 0)
    total_redacted = redaction_log.get("items_redacted", 0)
    reasons = redaction_log.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = []

    internal_facts = 0
    raw_paths = 0
    structural_facts = projection.get("structural_facts_public", [])
    if isinstance(structural_facts, list):
        internal_facts = sum(
            1
            for f in structural_facts
            if isinstance(f, dict) and f.get("disposition") == "internal_only"
        )

    return WithheldSummary(
        total_items_withheld=total_withheld,
        total_items_redacted=total_redacted,
        internal_facts_count=internal_facts,
        evidence_references_count=0,
        raw_paths_removed=raw_paths,
        reasons=reasons,
    )


def _build_proposed_content_summary(
    projection: dict, compiler_input: dict
) -> ProposedContentSummary:
    generated_sections = projection.get("generated_narrative_sections", {})
    if not isinstance(generated_sections, dict):
        generated_sections = {}

    sections: list[dict] = []
    proposed_count = 0
    approved_count = 0
    rejected_count = 0

    narrative_approvals = compiler_input.get("narrative_approvals", {})
    if not isinstance(narrative_approvals, dict):
        narrative_approvals = {}

    for section_key, section_data in generated_sections.items():
        if not isinstance(section_data, dict):
            continue
        status = narrative_approvals.get(section_key, "proposed")
        if status not in _VALID_APPROVAL_STATUSES:
            status = "proposed"

        sections.append({
            "section_key": section_key,
            "approval_status": status,
            "has_content": bool(section_data.get("narrative", "")),
            "source": "generated",
            "basis_fact_ids": section_data.get("basis_fact_ids", []),
        })

        if status in {"proposed", "pending_review"}:
            proposed_count += 1
        elif status == "approved":
            approved_count += 1
        elif status in {"rejected", "superseded"}:
            rejected_count += 1

    total = len(sections)

    return ProposedContentSummary(
        total_sections=total,
        sections_proposed=proposed_count,
        sections_approved=approved_count,
        sections_rejected=rejected_count,
        sections=sections,
        requires_developer_review=(proposed_count > 0),
    )


def _build_publication_readiness_summary(
    compiler_input: dict,
) -> PublicationReadinessSummary:
    readiness = compiler_input.get("publication_readiness") or {}
    if not isinstance(readiness, dict):
        readiness = {}

    pages_action = compiler_input.get("pages_action") or {}
    if not isinstance(pages_action, dict):
        pages_action = {}

    return PublicationReadinessSummary(
        has_pages=readiness.get("has_pages", False),
        pages_build_status=readiness.get("pages_build_status"),
        publication_eligible=readiness.get("publication_eligible", False),
        readiness_state=readiness.get("readiness_state", "unknown"),
        blockers=readiness.get("blockers", [])
        if isinstance(readiness.get("blockers"), list)
        else [],
        pages_action_state=pages_action.get("approval_status", "planned"),
        pages_action_requires_approval=pages_action.get("requires_approval", True),
        pages_action_will_mutate_remote=pages_action.get("will_mutate_remote", False),
        suggested_next_action=pages_action.get("suggested_next_action"),
    )


def _count_public_sections(projection: dict) -> int:
    count = 0
    public_section_keys = {
        "project_identity",
        "status_overview",
        "accomplishments",
        "released_boundaries",
        "mission_timeline",
        "architecture_overview",
        "capability_views",
        "audit_proofs",
        "changelog",
        "screenshots_demos",
        "structural_facts_public",
        "technology_capabilities",
        "generated_narrative_sections",
        "redaction_log",
    }
    for key in projection:
        if key in public_section_keys and projection[key]:
            count += 1
    return count


def _check_approval_gate(projection: dict, compiler_input: dict) -> bool:
    profile = compiler_input.get("profile_candidate", {})
    approval_status = projection.get("approval_status") or profile.get(
        "approval_status", "proposed"
    )
    if approval_status == "rejected":
        return False
    policy = compiler_input.get("publication_policy", "preview_only")
    if policy == "developer_approved" and approval_status != "approved":
        return False
    narrative_sections = projection.get("generated_narrative_sections", {})
    if isinstance(narrative_sections, dict):
        narrative_approvals = compiler_input.get("narrative_approvals", {})
        for section_key, section_data in narrative_sections.items():
            if isinstance(section_data, dict) and section_data.get("narrative"):
                status = narrative_approvals.get(section_key, "proposed")
                if policy == "public_release" and status != "approved":
                    return False
    return True
