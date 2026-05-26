from __future__ import annotations

from rig_relay.frontend.surfaces import (
    EvidenceStatus,
    FrontendSurfaceKind,
    PrivacyClass,
    build_gridline_specification,
    build_portfolio_site_specification,
    build_project_page_specification,
    build_shared_architecture_elements,
    build_three_surface_architecture,
    surface_specifications_are_distinct,
)


class TestSurfaceSpecifications:
    def test_gridline_is_live_internal_only(self):
        spec = build_gridline_specification()
        assert spec.surface_kind == FrontendSurfaceKind.GRIDLINE
        assert spec.privacy_class == PrivacyClass.INTERNAL_ONLY
        assert spec.static_or_live == "live"
        assert not spec.publication_safe
        assert spec.can_expose_canonical_evidence

    def test_gridline_reader_goals_include_operate_and_monitor(self):
        spec = build_gridline_specification()
        goals = {g.value for g in spec.reader_goals}
        assert "operate" in goals
        assert "monitor" in goals
        assert "review" in goals
        assert "verify" in goals
        assert "discover" not in goals

    def test_project_page_is_static_public_safe(self):
        spec = build_project_page_specification()
        assert spec.surface_kind == FrontendSurfaceKind.PROJECT_PAGE
        assert spec.privacy_class == PrivacyClass.PUBLIC_SAFE
        assert spec.static_or_live == "static"
        assert spec.publication_safe
        assert not spec.can_expose_canonical_evidence

    def test_project_page_reader_goals_include_evaluate_and_verify(self):
        spec = build_project_page_specification()
        goals = {g.value for g in spec.reader_goals}
        assert "evaluate" in goals
        assert "verify" in goals
        assert "review" in goals
        assert "operate" not in goals

    def test_portfolio_site_is_static_public_safe(self):
        spec = build_portfolio_site_specification()
        assert spec.surface_kind == FrontendSurfaceKind.PORTFOLIO_SITE
        assert spec.privacy_class == PrivacyClass.PUBLIC_SAFE
        assert spec.static_or_live == "static"
        assert spec.publication_safe

    def test_portfolio_site_reader_goals_include_discover(self):
        spec = build_portfolio_site_specification()
        goals = {g.value for g in spec.reader_goals}
        assert "discover" in goals
        assert "evaluate" in goals
        assert "navigate" in goals
        assert "operate" not in goals
        assert "monitor" not in goals

    def test_project_page_has_required_sections(self):
        spec = build_project_page_specification()
        section_ids = {s.section_id for s in spec.required_sections}
        assert "project_identity" in section_ids
        assert "status_overview" in section_ids
        assert "accomplishments" in section_ids
        assert "released_boundaries" in section_ids
        assert "mission_timeline" in section_ids
        assert "architecture_overview" in section_ids
        assert "capability_views" in section_ids
        assert "audit_proof_reader" in section_ids
        assert "changelog" in section_ids

    def test_portfolio_site_has_required_sections(self):
        spec = build_portfolio_site_specification()
        section_ids = {s.section_id for s in spec.required_sections}
        assert "developer_identity" in section_ids
        assert "project_catalogue" in section_ids
        assert "case_studies" in section_ids
        assert "technology_capability_map" in section_ids
        assert "engineering_milestones" in section_ids
        assert "project_links" in section_ids

    def test_optional_sections_marked_required_false(self):
        pp_spec = build_project_page_specification()
        ps_spec = build_portfolio_site_specification()
        pp_optional = [s for s in pp_spec.required_sections if not s.required]
        ps_optional = [s for s in ps_spec.required_sections if not s.required]
        assert len(pp_optional) >= 1
        assert len(ps_optional) >= 1
        assert any(s.section_id == "screenshots_demos" for s in pp_optional)
        assert any(s.section_id == "screenshots_demonstrations" for s in ps_optional)


class TestSurfaceDistinction:
    def test_surface_specifications_are_distinct(self):
        assert surface_specifications_are_distinct()

    def test_project_page_and_portfolio_have_different_reader_goals(self):
        pp = build_project_page_specification()
        ps = build_portfolio_site_specification()
        pp_goals = {g.value for g in pp.reader_goals}
        ps_goals = {g.value for g in ps.reader_goals}
        assert pp_goals != ps_goals
        assert pp_goals - ps_goals
        assert ps_goals - pp_goals

    def test_project_page_and_portfolio_have_different_projection_roots(self):
        pp = build_project_page_specification()
        ps = build_portfolio_site_specification()
        assert set(pp.projection_source_roots) != set(ps.projection_source_roots)

    def test_project_page_and_portfolio_have_different_section_ids(self):
        pp = build_project_page_specification()
        ps = build_portfolio_site_specification()
        pp_sections = {s.section_id for s in pp.required_sections}
        ps_sections = {s.section_id for s in ps.required_sections}
        assert pp_sections != ps_sections
        assert pp_sections - ps_sections
        assert ps_sections - pp_sections


class TestThreeSurfaceArchitecture:
    def test_builds_all_three_surfaces(self):
        arch = build_three_surface_architecture()
        assert len(arch.surfaces) == 3
        assert FrontendSurfaceKind.GRIDLINE in arch.surfaces
        assert FrontendSurfaceKind.PROJECT_PAGE in arch.surfaces
        assert FrontendSurfaceKind.PORTFOLIO_SITE in arch.surfaces

    def test_has_distinct_elements(self):
        arch = build_three_surface_architecture()
        assert len(arch.distinct_elements) > 0
        assert "reader_goals" in arch.distinct_elements

    def test_has_shared_elements(self):
        arch = build_three_surface_architecture()
        assert len(arch.shared_elements) > 0
        element_names = {e.element_name for e in arch.shared_elements}
        assert "design_tokens" in element_names
        assert "content_light_evidence_card" in element_names
        assert "capability_badge" in element_names

    def test_shared_elements_span_surfaces(self):
        arch = build_three_surface_architecture()
        tokens = next(
            e for e in arch.shared_elements if e.element_name == "design_tokens"
        )
        assert len(tokens.surfaces_using) == 3

    def test_some_shared_elements_are_static_only(self):
        arch = build_three_surface_architecture()
        typography = next(
            e
            for e in arch.shared_elements
            if e.element_name == "typography_rhythm_scale"
        )
        assert FrontendSurfaceKind.GRIDLINE not in typography.surfaces_using
        assert FrontendSurfaceKind.PROJECT_PAGE in typography.surfaces_using

    def test_architecture_digest_is_deterministic(self):
        arch1 = build_three_surface_architecture()
        arch2 = build_three_surface_architecture()
        assert (
            arch1.compute_architecture_digest() == arch2.compute_architecture_digest()
        )

    def test_architecture_schema_version(self):
        arch = build_three_surface_architecture()
        assert arch.schema_version == "rig.relay.frontend_three_surface_architecture.v1"
        assert arch.content_light


class TestEvidenceStatus:
    def test_evidence_status_values(self):
        assert EvidenceStatus.PROVEN.value == "proven"
        assert EvidenceStatus.CLAIMED.value == "claimed"
        assert EvidenceStatus.PLANNED.value == "planned"
        assert EvidenceStatus.NARRATIVE.value == "narrative"
        assert EvidenceStatus.REDACTED.value == "redacted"


class TestPrivacyClass:
    def test_privacy_class_values(self):
        assert PrivacyClass.PUBLIC_SAFE.value == "public_safe"
        assert PrivacyClass.CONTENT_LIGHT.value == "content_light"
        assert PrivacyClass.INTERNAL_ONLY.value == "internal_only"


class TestSharedArchitectureElements:
    def test_all_elements_have_names(self):
        elements = build_shared_architecture_elements()
        assert len(elements) >= 6
        for e in elements:
            assert e.element_name
            assert e.element_kind
            assert len(e.surfaces_using) >= 1
