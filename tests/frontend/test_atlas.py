from __future__ import annotations

from hashlib import sha256

from rig_relay.frontend.atlas import (
    ApplicabilityClass,
    AtlasDigestResult,
    AtlasPrinciple,
    InteractionGrammarImplication,
    PrincipleKind,
    SourceIdentity,
    SurfaceApplicability,
    SurfaceTarget,
    VisualGrammarImplication,
    compute_atlas_digest_id,
    principle_is_traceable,
    validate_surface_distinction,
)


def _make_source(video_id: str = "test_VID") -> SourceIdentity:
    return SourceIdentity(
        source_kind="youtube_transcript",
        channel_or_author="Pixelgrid UI",
        video_id=video_id,
        transcript_file=f"transcript_{video_id}.txt",
        transcript_sha256=sha256(b"test content").hexdigest(),
        retrieval_date="2026-05-26",
    )


def _make_principle(
    source: SourceIdentity,
    kind: PrincipleKind = PrincipleKind.VISUAL_GRAMMAR,
    statement: str = "Test principle",
) -> AtlasPrinciple:
    principle = AtlasPrinciple(
        principle_id=f"principle_{kind.value}_{source.video_id}",
        source=source,
        principle_kind=kind,
        principle_statement=statement,
    )
    principle.principle_digest = principle.compute_digest()
    return principle


class TestSourceIdentity:
    def test_minimal_source_identity(self):
        source = SourceIdentity(
            source_kind="youtube_transcript",
            video_id="abc123",
            transcript_sha256="sha256:deadbeef",
        )
        assert source.source_kind == "youtube_transcript"
        assert source.video_id == "abc123"
        assert source.transcript_sha256 == "sha256:deadbeef"
        assert source.channel_or_author == "Pixelgrid UI"

    def test_source_identity_serialization_roundtrip(self):
        source = _make_source("test_X1")
        data = source.model_dump()
        reloaded = SourceIdentity.model_validate(data)
        assert reloaded.video_id == source.video_id
        assert reloaded.transcript_sha256 == source.transcript_sha256


class TestAtlasPrinciple:
    def test_compute_digest_deterministic(self):
        source = _make_source("det_1")
        p1 = _make_principle(
            source, PrincipleKind.LAYOUT_STRATEGY, "Use grid consistently"
        )
        p2 = _make_principle(
            source, PrincipleKind.LAYOUT_STRATEGY, "Use grid consistently"
        )
        assert p1.compute_digest() == p2.compute_digest()

    def test_compute_digest_varies_with_content(self):
        source = _make_source("det_2")
        p1 = _make_principle(source, PrincipleKind.VISUAL_GRAMMAR, "A")
        p2 = _make_principle(source, PrincipleKind.VISUAL_GRAMMAR, "B")
        assert p1.compute_digest() != p2.compute_digest()

    def test_is_applicable_to_returns_false_when_not_marked(self):
        source = _make_source()
        p = _make_principle(source)
        assert not p.is_applicable_to(SurfaceTarget.GRIDLINE)
        assert not p.is_applicable_to(SurfaceTarget.PROJECT_PAGE)

    def test_is_applicable_to_returns_true_when_marked(self):
        source = _make_source("app_1")
        p = _make_principle(source)
        p.surface_applicability = [
            SurfaceApplicability(
                target=SurfaceTarget.PROJECT_PAGE,
                applicable=True,
                rationale="Good for static sites",
                implementation_class=ApplicabilityClass.NOW,
            )
        ]
        assert p.is_applicable_to(SurfaceTarget.PROJECT_PAGE)
        assert not p.is_applicable_to(SurfaceTarget.PORTFOLIO_SITE)

    def test_multiple_surfaces_can_be_applicable(self):
        source = _make_source("multi_1")
        p = _make_principle(source)
        p.surface_applicability = [
            SurfaceApplicability(
                target=SurfaceTarget.GRIDLINE,
                applicable=True,
                rationale="Desktop needs this",
                implementation_class=ApplicabilityClass.LATER,
            ),
            SurfaceApplicability(
                target=SurfaceTarget.PROJECT_PAGE,
                applicable=True,
                rationale="Static page benefits",
                implementation_class=ApplicabilityClass.NOW,
            ),
        ]
        assert p.is_applicable_to(SurfaceTarget.GRIDLINE)
        assert p.is_applicable_to(SurfaceTarget.PROJECT_PAGE)
        assert not p.is_applicable_to(SurfaceTarget.PORTFOLIO_SITE)

    def test_tension_notes_preserved(self):
        source = _make_source("tension_1")
        p = _make_principle(source)
        p.tension_with_rig_relay_requirements = [
            "Cannot expose raw evidence in public static pages"
        ]
        assert len(p.tension_with_rig_relay_requirements) == 1
        assert "raw evidence" in p.tension_with_rig_relay_requirements[0]


class TestPrincipleIsTraceable:
    def test_traceable_when_all_fields_present(self):
        source = _make_source("trace_1")
        p = _make_principle(source)
        assert principle_is_traceable(p)

    def test_not_traceable_when_missing_video_id(self):
        source = _make_source("")
        source.video_id = ""
        p = _make_principle(source)
        assert not principle_is_traceable(p)

    def test_not_traceable_when_missing_transcript_hash(self):
        source = _make_source("trace_3")
        source.transcript_sha256 = ""
        p = _make_principle(source)
        assert not principle_is_traceable(p)

    def test_not_traceable_when_missing_principle_digest(self):
        source = _make_source("trace_4")
        p = _make_principle(source)
        p.principle_digest = ""
        assert not principle_is_traceable(p)


class TestVisualGrammarImplication:
    def test_empty_by_default(self):
        vg = VisualGrammarImplication()
        assert vg.spacing == []
        assert vg.typography == []
        assert vg.hierarchy == []

    def test_populated_fields(self):
        vg = VisualGrammarImplication(
            spacing=["8px grid baseline"],
            typography=["system font stack"],
            hierarchy=["z-index stacking context isolation"],
            color_semantics=["semantic token layer"],
        )
        assert "8px grid baseline" in vg.spacing
        assert "system font stack" in vg.typography
        assert "z-index stacking context isolation" in vg.hierarchy
        assert "semantic token layer" in vg.color_semantics


class TestInteractionGrammarImplication:
    def test_empty_by_default(self):
        ig = InteractionGrammarImplication()
        assert ig.progressive_disclosure == []
        assert ig.loading_states == []
        assert ig.error_states == []

    def test_populated_fields(self):
        ig = InteractionGrammarImplication(
            progressive_disclosure=["details/summary for accordion"],
            loading_states=["skeleton cards"],
            refusal_states=["authorization required modal"],
        )
        assert "accordion" in ig.progressive_disclosure[0]
        assert "skeleton cards" in ig.loading_states[0]
        assert "authorization required" in ig.refusal_states[0]


class TestValidateSurfaceDistinction:
    def test_zero_principles_returns_zeros(self):
        result = validate_surface_distinction([])
        assert result[SurfaceTarget.GRIDLINE] == 0
        assert result[SurfaceTarget.PROJECT_PAGE] == 0
        assert result[SurfaceTarget.PORTFOLIO_SITE] == 0

    def test_counts_per_surface(self):
        source = _make_source("counts_1")
        p1 = _make_principle(source, PrincipleKind.COMPONENT_PRIMITIVE)
        p1.surface_applicability = [
            SurfaceApplicability(
                target=SurfaceTarget.PROJECT_PAGE,
                applicable=True,
                implementation_class=ApplicabilityClass.NOW,
            ),
            SurfaceApplicability(
                target=SurfaceTarget.PORTFOLIO_SITE,
                applicable=True,
                implementation_class=ApplicabilityClass.NOW,
            ),
        ]
        p2 = _make_principle(source, PrincipleKind.NATIVE_SURFACE)
        p2.surface_applicability = [
            SurfaceApplicability(
                target=SurfaceTarget.GRIDLINE,
                applicable=True,
                implementation_class=ApplicabilityClass.NOW,
            )
        ]
        result = validate_surface_distinction([p1, p2])
        assert result[SurfaceTarget.GRIDLINE] == 1
        assert result[SurfaceTarget.PROJECT_PAGE] == 1
        assert result[SurfaceTarget.PORTFOLIO_SITE] == 1

    def test_non_applicable_not_counted(self):
        source = _make_source("counts_2")
        p = _make_principle(source)
        p.surface_applicability = [
            SurfaceApplicability(
                target=SurfaceTarget.PROJECT_PAGE,
                applicable=False,
                implementation_class=ApplicabilityClass.REFERENCE,
            )
        ]
        result = validate_surface_distinction([p])
        assert result[SurfaceTarget.PROJECT_PAGE] == 0


class TestAtlasDigestResult:
    def test_digest_metadata(self):
        source = _make_source("digest_1")
        result = AtlasDigestResult(
            digest_id="test_digest",
            input_source=source,
            extraction_note="Synthesized from transcript analysis",
        )
        assert result.schema_version == "rig.relay.frontend_atlas_digest.v1"
        assert result.content_light
        assert result.principles_extracted == []

    def test_compute_atlas_digest_id_deterministic(self):
        source = _make_source("id_1")
        id1 = compute_atlas_digest_id(source)
        id2 = compute_atlas_digest_id(source)
        assert id1 == id2
        assert id1.startswith("atlas_digest_")

    def test_compute_atlas_digest_id_varies_per_source(self):
        s1 = _make_source("A")
        s2 = _make_source("B")
        assert compute_atlas_digest_id(s1) != compute_atlas_digest_id(s2)


class TestSurfaceApplicability:
    def test_applicability_classes(self):
        assert ApplicabilityClass.NOW.value == "now"
        assert ApplicabilityClass.LATER.value == "later"
        assert ApplicabilityClass.REFERENCE.value == "reference"

    def test_surface_targets(self):
        assert SurfaceTarget.GRIDLINE.value == "gridline"
        assert SurfaceTarget.PROJECT_PAGE.value == "project_page"
        assert SurfaceTarget.PORTFOLIO_SITE.value == "portfolio_site"

    def test_principle_kinds(self):
        assert PrincipleKind.VISUAL_GRAMMAR.value == "visual_grammar"
        assert PrincipleKind.INTERACTION_GRAMMAR.value == "interaction_grammar"
        assert PrincipleKind.NATIVE_SURFACE.value == "native_surface"
