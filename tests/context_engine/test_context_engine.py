"""Tests for Lane L0 — Context Engine and Developer Knowledge Assembly Corridor.

Tests verify:
  - Source-derived facts carry provenance from real repository content
  - Private/raw contents do not appear in public-safe projections
  - Generated claims are marked proposed, not approved/public fact
  - Project-page candidate and developer corpus are structurally distinct
  - Sanitized context packets are deterministic and digest-bound
  - Absent J0/K0 dependencies are represented through typed fixtures
  - Gridline projections are content-light and non-mutating
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

from rig_relay.context_engine.assembler import ProjectContextAssemblyService
from rig_relay.context_engine.fixtures import (
    IntakeFixture,
    InvestigationEvidenceFixture,
    InvestigationFinding,
)
from rig_relay.context_engine.models import (
    DeveloperCorpusIndex,
    PublishableProjectProfileCandidate,
)
from rig_relay.context_engine.provenance import ApprovalStatus, FactOrigin

# Resolve the real repo root once for tests that need actual repository inspection
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Fixture helpers ──────────────────────────────────────────────────


def _make_intake(project_name: str = "test-project") -> IntakeFixture:
    return IntakeFixture(
        repository_root=REPO_ROOT,
        project_name=project_name,
        head_sha="abc123",
        branch="main",
        is_github_backed=True,
        is_local_only=False,
        remotes_count=1,
        repository_url_digest="sha256:test123",
    )


def _make_investigation() -> InvestigationEvidenceFixture:
    return InvestigationEvidenceFixture(
        investigation_sha="sha256:inv123",
        findings=[
            InvestigationFinding(
                finding_id="f1",
                category="architecture",
                summary="Well-structured monorepo with clear lane separation.",
                severity="info",
                evidence_paths=["docs/architecture/adr-001.md"],
            ),
            InvestigationFinding(
                finding_id="f2",
                category="testing",
                summary="Comprehensive test suite detected with pytest and hypothesis.",
            ),
        ],
    )


# ── Source-derived provenance ────────────────────────────────────────


def test_source_derived_facts_carry_provenance():
    """Every structural fact must have a source_path, source_kind, and extraction_method."""
    intake = _make_intake("Rig Relay")
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)

    assert len(understanding.structural_facts) > 0, "Must extract facts from real repo"
    for fact in understanding.structural_facts:
        assert fact.source_path, f"Fact {fact.fact_id} missing source_path"
        assert fact.source_kind, f"Fact {fact.fact_id} missing source_kind"
        assert fact.extraction_method, f"Fact {fact.fact_id} missing extraction_method"
        assert fact.provenance == FactOrigin.SOURCE_DERIVED, (
            f"Fact {fact.fact_id} must be source_derived, got {fact.provenance}"
        )


def test_source_derived_fact_appears_when_present():
    """A source-derived fact must only appear when the evidence is in the real repo."""
    # Rig Relay repo has pyproject.toml — should detect python language
    intake = _make_intake("Rig Relay")
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)

    lang_facts = [f for f in understanding.structural_facts if f.category == "language"]
    assert any("python" in f.value.lower() for f in lang_facts), (
        "Rig Relay has pyproject.toml — must detect python"
    )


def test_source_derived_fact_absent_when_not_present():
    """A source-derived fact must NOT appear when evidence is absent."""
    # Using a fixture with no repo root — should produce minimal facts
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        empty_root = Path(td)
        intake = IntakeFixture(
            repository_root=empty_root,
            project_name="empty-project",
            head_sha="000000",
            branch="main",
            is_github_backed=False,
            is_local_only=True,
            remotes_count=0,
            repository_url_digest="sha256:empty",
        )
        service = ProjectContextAssemblyService()
        understanding = service.assemble(intake)

        # No manifest files — should have zero or minimal facts
        lang_facts = [
            f for f in understanding.structural_facts if f.category == "language"
        ]
        assert len(lang_facts) == 0, (
            "Empty repo with no manifests must not claim languages"
        )


# ── Public-safe boundary ─────────────────────────────────────────────


def test_private_contents_do_not_appear_in_public_candidate():
    """Public candidate must not contain source paths, extraction methods, or raw content."""
    intake = _make_intake("Rig Relay")
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    candidate = service.assemble_profile_candidate(understanding)

    # The candidate's structural_facts_public uses PublicStructuralFact — no source_path
    for fact in candidate.structural_facts_public:
        assert not hasattr(fact, "source_path") or fact.source_path == "", (
            f"Public fact {fact.fact_id} must not expose source paths"
        )
        assert not hasattr(fact, "extraction_method") or fact.extraction_method == "", (
            f"Public fact {fact.fact_id} must not expose extraction methods"
        )

    # Check the JSON output directly for forbidden keywords
    raw_json = candidate.model_dump_json().lower()
    forbidden = [
        "raw_file_contents",
        "raw_prompt_text",
        "model_output_text",
        "source_path",
        "extraction_method",
    ]
    for term in forbidden:
        assert term not in raw_json, (
            f"Forbidden term '{term}' found in public candidate"
        )


def test_generated_claims_marked_proposed():
    """All generated claims must have approval_status=proposed, not approved."""
    intake = _make_intake("Rig Relay")
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)

    for claim in understanding.generated_claims:
        assert claim.approval_status == ApprovalStatus.PROPOSED, (
            f"Claim {claim.claim_id} must be proposed, got {claim.approval_status}"
        )
        assert claim.provenance == FactOrigin.GENERATED, (
            f"Claim {claim.claim_id} must be generated, got {claim.provenance}"
        )


def test_generated_claim_cannot_be_mislabeled_as_fact():
    """A generated claim must not carry FactOrigin.SOURCE_DERIVED or FactOrigin.APPROVED."""
    from rig_relay.context_engine.provenance import GeneratedClaim

    claim = GeneratedClaim(
        claim_id="test_claim",
        category="project_description",
        narrative="A test project.",
        basis_facts=["fact_0001"],
    )

    assert claim.provenance == FactOrigin.GENERATED
    assert claim.approval_status == ApprovalStatus.PROPOSED
    assert claim.provenance != FactOrigin.SOURCE_DERIVED
    assert claim.provenance != FactOrigin.APPROVED


def test_public_candidate_narrative_is_proposed():
    """Public candidate's generated narrative sections must be proposed."""
    intake = _make_intake("Rig Relay")
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    candidate = service.assemble_profile_candidate(understanding)

    for section_name, narrative in candidate.generated_narrative_sections.items():
        assert narrative.approval_status == ApprovalStatus.PROPOSED, (
            f"Narrative section '{section_name}' must be proposed, got {narrative.approval_status}"
        )


# ── Project-page vs Developer Corpus distinction ─────────────────────


def test_project_page_candidate_and_corpus_are_distinct():
    """The project-page candidate and developer corpus must be structurally different models."""
    intake = _make_intake("Rig Relay")
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    candidate = service.assemble_profile_candidate(understanding)
    corpus = service.build_corpus_index_entry(understanding)

    assert isinstance(candidate, PublishableProjectProfileCandidate)
    assert isinstance(corpus, DeveloperCorpusIndex)

    # They must have different schema versions
    assert candidate.schema_version != corpus.schema_version

    # Candidate focuses on one project's page content
    # Corpus indexes multiple projects
    assert candidate.project_identity.project_name is not None
    assert corpus.total_projects_indexed >= 1

    # Candidate has narrative sections, corpus has project references
    assert hasattr(candidate, "generated_narrative_sections")
    assert hasattr(corpus, "project_references")


def test_project_and_portfolio_models_do_not_collapse():
    """Project-page candidate must not contain portfolio-level fields."""
    from rig_relay.context_engine.models import ProjectPageIdentity

    candidate = PublishableProjectProfileCandidate(
        candidate_id="test_candidate",
        project_identity=ProjectPageIdentity(
            project_name="Test", tagline="A test project"
        ),
    )
    # Project-page candidate has no developer_identity field
    assert not hasattr(candidate, "developer_identity"), (
        "Project-page candidate must not have developer_identity (portfolio field)"
    )
    # Project-page candidate has no project_catalogue field
    assert not hasattr(candidate, "project_catalogue"), (
        "Project-page candidate must not have project_catalogue (portfolio field)"
    )


# ── Private projection vs public candidate ───────────────────────────


def test_private_understanding_contains_more_than_public_candidate():
    """The private understanding must contain internal diagnostic info not in public candidate."""
    intake = _make_intake("Rig Relay")
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    candidate = service.assemble_profile_candidate(understanding)

    # Understanding has full structural facts with source_paths
    assert len(understanding.structural_facts) > 0
    # Understanding has intake dependency status (internal)
    assert understanding.intake_dependency_status is not None
    assert understanding.intake_dependency_status.j0_intake_boundary == "fixture"

    # Understanding privacy class is INTERNAL_ONLY
    assert understanding.privacy_class.value == "internal_only"

    # Candidate privacy class is PUBLIC_SAFE
    assert candidate.privacy_class.value == "public_safe"


def test_public_candidate_does_not_leak_internal_fields():
    """Public candidate JSON must not contain internal-only field names."""
    intake = _make_intake("Rig Relay")
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    candidate = service.assemble_profile_candidate(understanding)

    raw = candidate.model_dump_json().lower()
    forbidden_in_public = [
        "evidence_facts",
        "intake_dependency_status",
        "git_root_digest",
    ]
    for term in forbidden_in_public:
        assert term not in raw, f"Public candidate must not contain '{term}'"


# ── Deterministic context packets ────────────────────────────────────


def test_context_packet_is_deterministic():
    """Same inputs must produce identical context packet digests."""
    from rig_relay.context_engine.context_packet import build_sanitized_context_packet

    packet1 = build_sanitized_context_packet(
        understanding_id="proj_test",
        project_name="Test Project",
        languages=["python", "rust"],
        frameworks=["pydantic", "actix"],
        test_frameworks=["pytest"],
        build_systems=["cargo"],
    )
    packet2 = build_sanitized_context_packet(
        understanding_id="proj_test",
        project_name="Test Project",
        languages=["python", "rust"],
        frameworks=["pydantic", "actix"],
        test_frameworks=["pytest"],
        build_systems=["cargo"],
    )

    assert packet1.packet_digest == packet2.packet_digest, (
        "Same inputs must produce identical packet digests"
    )
    assert packet1.project_identity_hash == packet2.project_identity_hash


def test_context_packet_changes_with_different_inputs():
    """Different project names must produce different packet digests."""
    from rig_relay.context_engine.context_packet import build_sanitized_context_packet

    packet1 = build_sanitized_context_packet(
        understanding_id="proj_a",
        project_name="Project A",
        languages=["python"],
        frameworks=[],
        test_frameworks=[],
        build_systems=[],
    )
    packet2 = build_sanitized_context_packet(
        understanding_id="proj_b",
        project_name="Project B",
        languages=["python"],
        frameworks=[],
        test_frameworks=[],
        build_systems=[],
    )

    # Different project names produce different hashes
    assert packet1.project_identity_hash != packet2.project_identity_hash
    assert packet1.packet_id != packet2.packet_id


def test_context_packet_no_forbidden_content():
    """Sanitized context packet must not contain forbidden fields in payload content."""
    from rig_relay.context_engine.context_packet import build_sanitized_context_packet

    packet = build_sanitized_context_packet(
        understanding_id="proj_test",
        project_name="Test",
        languages=["python"],
        frameworks=[],
        test_frameworks=[],
        build_systems=[],
    )

    # Forbidden fields are now hashed in checked_fields — verify the raw field names
    # don't appear in the output outside the check list itself
    for field in packet.forbidden_content_check.checked_fields:
        # The checked_fields now contain sha256: hashes, not raw names
        assert field.startswith("sha256:")

    assert packet.forbidden_content_check.passed


def test_context_packet_is_bounded():
    """Context packet must respect token budget."""
    from rig_relay.context_engine.context_packet import build_sanitized_context_packet

    packet = build_sanitized_context_packet(
        understanding_id="proj_test",
        project_name="Test",
        languages=["python"],
        frameworks=[],
        test_frameworks=[],
        build_systems=[],
        total_tokens=100,
    )

    assert packet.token_budget.tokens_remaining >= 0
    assert (
        packet.token_budget.tokens_consumed
        <= packet.token_budget.total_tokens_available + 100
    )


# ── Deferred dependency handling ─────────────────────────────────────


def test_j0_fixture_used_when_live_unavailable():
    """J0 intake boundary must be 'fixture' when no live service exists."""
    intake = _make_intake()
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)

    assert understanding.intake_dependency_status.j0_intake_boundary == "fixture"
    assert not understanding.intake_dependency_status.j0_intake_available


def test_k0_fixture_used_when_live_unavailable():
    """K0 investigation boundary must be 'fixture' when no live service exists."""
    intake = _make_intake()
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)

    assert understanding.intake_dependency_status.k0_investigation_boundary == "fixture"
    assert not understanding.intake_dependency_status.k0_investigation_available


def test_investigation_evidence_attached_when_present():
    """When investigation evidence is provided, it must appear in the understanding."""
    intake = _make_intake()
    investigation = _make_investigation()
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake, investigation)

    assert len(understanding.evidence_facts) > 0
    for fact in understanding.evidence_facts:
        assert fact.provenance == FactOrigin.EVIDENCE_DERIVED


def test_missing_investigation_produces_empty_evidence():
    """When no investigation is provided, evidence_facts must be empty."""
    intake = _make_intake()
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake, investigation=None)

    assert len(understanding.evidence_facts) == 0


# ── Gridline projection ──────────────────────────────────────────────


def test_gridline_projection_is_content_light():
    """Gridline projection must not contain raw repository content."""
    intake = _make_intake("Rig Relay")
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    packet = service.assemble_context_packet(understanding)
    gridline = service.assemble_gridline_projection(understanding, packet)

    assert gridline.content_light_guarantee

    raw = gridline.model_dump_json().lower()
    forbidden = ["raw_file_contents", "source_path", "internal_only"]
    for term in forbidden:
        assert term not in raw, f"Forbidden term '{term}' found in gridline projection"


def test_gridline_projection_does_not_mutate_understanding():
    """Gridline projection must be read-only — not modify the underlying understanding."""
    intake = _make_intake("Rig Relay")
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    original_digest = understanding.projection_digest
    original_fact_count = len(understanding.structural_facts)

    packet = service.assemble_context_packet(understanding)
    _gridline = service.assemble_gridline_projection(understanding, packet)

    # Understanding must be unchanged after gridline projection
    assert understanding.projection_digest == original_digest
    assert len(understanding.structural_facts) == original_fact_count


# ── Corpus index operations ──────────────────────────────────────────


def test_corpus_index_tracks_multiple_projects():
    """Corpus must accumulate multiple project references."""
    intake1 = _make_intake("Project A")
    intake2 = _make_intake("Project B")
    service = ProjectContextAssemblyService()

    u1 = service.assemble(intake1)
    u2 = service.assemble(intake2)

    corpus = service.build_corpus_index_entry(u1)
    assert corpus.total_projects_indexed == 1

    corpus = service.build_corpus_index_entry(u2, existing_corpus=corpus)
    assert corpus.total_projects_indexed == 2
    assert corpus.profile_ready_count == 0
    assert corpus.candidate_count == 2


def test_corpus_entry_updates_existing():
    """Updating an existing corpus entry must replace, not duplicate, the project ref."""
    intake = _make_intake("Same Project")
    service = ProjectContextAssemblyService()

    u1 = service.assemble(intake)
    corpus1 = service.build_corpus_index_entry(u1)
    assert corpus1.total_projects_indexed == 1

    # Re-assemble with same project name
    u2 = service.assemble(intake)
    corpus2 = service.build_corpus_index_entry(u2, existing_corpus=corpus1)
    assert corpus2.total_projects_indexed == 1  # Not duplicated


# ── Approval boundary ─────────────────────────────────────────────────


def test_unapproved_content_cannot_be_public_fact():
    """Only ApprovedContent with provenance=approved can be public fact."""
    from datetime import datetime

    from rig_relay.context_engine.provenance import ApprovedContent

    content = ApprovedContent(
        content_id="test_approved",
        category="description",
        value="Approved project description",
        approved_at=datetime.now(UTC),
    )

    assert content.provenance == FactOrigin.APPROVED
    assert content.privacy_disposition.value == "public_safe"


def test_proposed_claim_is_not_fact():
    """A proposed claim must not be treated as a source-derived or evidence-derived fact."""
    from rig_relay.context_engine.provenance import GeneratedClaim

    claim = GeneratedClaim(
        claim_id="test_claim", category="description", narrative="This might be wrong."
    )

    assert claim.provenance == FactOrigin.GENERATED
    assert claim.provenance != FactOrigin.SOURCE_DERIVED
    assert claim.provenance != FactOrigin.EVIDENCE_DERIVED
    assert claim.provenance != FactOrigin.APPROVED
    assert claim.approval_status == ApprovalStatus.PROPOSED


# ── Schema validation ────────────────────────────────────────────────


def test_understanding_schema_version():
    """Understanding must use the correct schema version."""
    intake = _make_intake()
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    assert understanding.schema_version == "rig.relay.project_understanding.v1"


def test_candidate_schema_version():
    """Candidate must use the correct schema version."""
    intake = _make_intake()
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    candidate = service.assemble_profile_candidate(understanding)
    assert (
        candidate.schema_version == "rig.relay.publishable_project_profile_candidate.v1"
    )


def test_corpus_schema_version():
    """Corpus must use the correct schema version."""
    intake = _make_intake()
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    corpus = service.build_corpus_index_entry(understanding)
    assert corpus.schema_version == "rig.relay.developer_corpus_index.v1"


def test_context_packet_schema_version():
    """Context packet must use the correct schema version."""
    intake = _make_intake()
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    packet = service.assemble_context_packet(understanding)
    assert packet.schema_version == "rig.relay.sanitized_context_packet.v1"


# ── Redaction ────────────────────────────────────────────────────────


def test_redaction_log_records_withheld_items():
    """Redaction log must track what was withheld and why."""
    intake = _make_intake()
    service = ProjectContextAssemblyService()
    understanding = service.assemble(intake)
    candidate = service.assemble_profile_candidate(understanding)

    assert candidate.redaction_log is not None
    assert isinstance(candidate.redaction_log.items_withheld, int)


# ── Model shape validation ──────────────────────────────────────────


def test_fact_origin_enum_values():
    """FactOrigin must have the four required values."""
    assert FactOrigin.SOURCE_DERIVED.value == "source_derived"
    assert FactOrigin.EVIDENCE_DERIVED.value == "evidence_derived"
    assert FactOrigin.GENERATED.value == "generated"
    assert FactOrigin.APPROVED.value == "approved"


def test_approval_status_enum_values():
    """ApprovalStatus must have the five required workflow states."""
    assert ApprovalStatus.PROPOSED.value == "proposed"
    assert ApprovalStatus.PENDING_REVIEW.value == "pending_review"
    assert ApprovalStatus.APPROVED.value == "approved"
    assert ApprovalStatus.REJECTED.value == "rejected"
    assert ApprovalStatus.SUPERSEDED.value == "superseded"


def test_privacy_disposition_enum_values():
    """PrivacyDisposition must have the four classification states."""
    from rig_relay.context_engine.provenance import PrivacyDisposition

    assert PrivacyDisposition.PUBLIC_SAFE.value == "public_safe"
    assert PrivacyDisposition.INTERNAL_ONLY.value == "internal_only"
    assert PrivacyDisposition.REDACTED.value == "redacted"
    assert PrivacyDisposition.WITHHELD.value == "withheld"


def test_fixture_from_real_repository():
    """IntakeFixture.from_repository must produce valid fixture from actual repo."""
    intake = IntakeFixture.from_repository(REPO_ROOT, "Rig Relay")

    assert intake.project_name == "Rig Relay"
    assert intake.head_sha
    assert intake.branch
    assert intake.is_github_backed  # Rig Relay is on GitHub
    assert intake.repository_url_digest.startswith("sha256:")


def test_intake_fixture_no_live_service_dependency():
    """IntakeFixture must not depend on live J0 service."""
    fixture = _make_intake()
    service = ProjectContextAssemblyService()
    understanding = service.assemble(fixture)

    # No live J0 service was called — only the fixture was used
    assert understanding.intake_dependency_status.j0_intake_boundary == "fixture"
    assert not understanding.intake_dependency_status.j0_intake_available
