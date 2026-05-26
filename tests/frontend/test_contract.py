from __future__ import annotations

from rig_relay.frontend.contract import (
    PortfolioSitePublicationProjection,
    ProjectPagePublicationProjection,
    SurfaceSpecificationContract,
    build_portfolio_site_sample_projection,
    build_project_page_sample_projection,
    build_surface_specification_contract,
    contract_surfaces_are_distinct,
    projection_is_content_light,
    publication_projections_are_distinct,
)
from rig_relay.frontend.surfaces import FrontendSurfaceKind


class TestSurfaceSpecificationContract:
    def test_builds_contract(self):
        contract = build_surface_specification_contract()
        assert isinstance(contract, SurfaceSpecificationContract)
        assert (
            contract.schema_version
            == "rig.relay.frontend_surface_specification_contract.v1"
        )

    def test_contract_has_three_surfaces(self):
        contract = build_surface_specification_contract()
        assert len(contract.surfaces) == 3
        assert FrontendSurfaceKind.GRIDLINE in contract.surfaces
        assert FrontendSurfaceKind.PROJECT_PAGE in contract.surfaces
        assert FrontendSurfaceKind.PORTFOLIO_SITE in contract.surfaces

    def test_distinct_projection_roots(self):
        contract = build_surface_specification_contract()
        pp_roots = set(
            contract.distinct_projection_roots[FrontendSurfaceKind.PROJECT_PAGE]
        )
        ps_roots = set(
            contract.distinct_projection_roots[FrontendSurfaceKind.PORTFOLIO_SITE]
        )
        gl_roots = set(contract.distinct_projection_roots[FrontendSurfaceKind.GRIDLINE])
        assert pp_roots != ps_roots
        assert pp_roots != gl_roots
        assert ps_roots != gl_roots
        assert len(pp_roots) > 0
        assert len(ps_roots) > 0
        assert len(gl_roots) > 0

    def test_distinct_reader_goals(self):
        contract = build_surface_specification_contract()
        pp_goals = set(contract.distinct_reader_goals[FrontendSurfaceKind.PROJECT_PAGE])
        ps_goals = set(
            contract.distinct_reader_goals[FrontendSurfaceKind.PORTFOLIO_SITE]
        )
        assert pp_goals != ps_goals
        assert len(pp_goals - ps_goals) > 0

    def test_has_publication_safety_rules(self):
        contract = build_surface_specification_contract()
        assert len(contract.publication_safety_rules) >= 5
        assert any("no_raw_secrets" in r for r in contract.publication_safety_rules)
        assert any(
            "all_claims_traceable" in r for r in contract.publication_safety_rules
        )

    def test_has_content_light_rules(self):
        contract = build_surface_specification_contract()
        assert len(contract.content_light_rules) >= 4
        assert any("sha256_hashes" in r for r in contract.content_light_rules)

    def test_deterministic_digest(self):
        c1 = build_surface_specification_contract()
        c2 = build_surface_specification_contract()
        assert c1.deterministic_digest == c2.deterministic_digest
        assert c1.deterministic_digest.startswith("sha256:")

    def test_contract_id_stable(self):
        c1 = build_surface_specification_contract()
        c2 = build_surface_specification_contract()
        assert c1.contract_id == c2.contract_id

    def test_contract_surfaces_are_distinct(self):
        contract = build_surface_specification_contract()
        assert contract_surfaces_are_distinct(contract)

    def test_shared_rendering_primitives(self):
        contract = build_surface_specification_contract()
        assert len(contract.shared_rendering_primitives) >= 5
        assert "design_tokens" in contract.shared_rendering_primitives
        assert "evidence_card" in contract.shared_rendering_primitives
        assert "timeline_primitive" in contract.shared_rendering_primitives


class TestProjectPagePublicationProjection:
    def test_builds_sample_projection(self):
        proj = build_project_page_sample_projection("Test Project")
        assert proj.publication_surface == "project_page"
        assert proj.schema_version == "rig.relay.publication_projection.v1"
        assert proj.content_light_guarantee

    def test_project_identity_populated(self):
        proj = build_project_page_sample_projection("Rig Relay")
        assert proj.project_identity.project_name == "Rig Relay"
        assert proj.project_identity.tagline != ""
        assert proj.project_identity.current_milestone != ""

    def test_status_overview_positive_counts(self):
        proj = build_project_page_sample_projection()
        assert proj.status_overview.implemented_count > 0
        assert proj.status_overview.planned_count >= 0
        assert proj.status_overview.evidence_backed

    def test_accomplishments_have_receipts(self):
        proj = build_project_page_sample_projection()
        assert proj.accomplishments.total_receipts_referenced > 0
        assert len(proj.accomplishments.items) > 0

    def test_released_boundaries(self):
        proj = build_project_page_sample_projection()
        assert len(proj.released_boundaries.boundaries) > 0
        boundary_names = {b.boundary_name for b in proj.released_boundaries.boundaries}
        assert "disclosure_query_service" in boundary_names

    def test_mission_timeline(self):
        proj = build_project_page_sample_projection()
        assert len(proj.mission_timeline.entries) > 0
        statuses = {e.status.value for e in proj.mission_timeline.entries}
        assert "proven" in statuses

    def test_architecture_overview(self):
        proj = build_project_page_sample_projection()
        assert len(proj.architecture_overview) > 0

    def test_capability_views(self):
        proj = build_project_page_sample_projection()
        assert len(proj.capability_views) > 0

    def test_changelog(self):
        proj = build_project_page_sample_projection()
        assert len(proj.changelog) > 0

    def test_projection_digest(self):
        proj = build_project_page_sample_projection()
        assert proj.projection_digest.startswith("sha256:")

    def test_projection_is_content_light(self):
        proj = build_project_page_sample_projection()
        data = proj.model_dump()
        assert projection_is_content_light(data)

    def test_reserialization_preserves_content_light(self):
        proj = build_project_page_sample_projection()
        dump = proj.model_dump_json()
        import json

        reloaded = ProjectPagePublicationProjection.model_validate(json.loads(dump))
        data = reloaded.model_dump()
        assert projection_is_content_light(data)


class TestPortfolioSitePublicationProjection:
    def test_builds_sample_projection(self):
        proj = build_portfolio_site_sample_projection("Test Developer")
        assert proj.publication_surface == "portfolio_site"
        assert proj.schema_version == "rig.relay.publication_projection.v1"
        assert proj.content_light_guarantee

    def test_developer_identity(self):
        proj = build_portfolio_site_sample_projection("Jane Doe")
        assert proj.developer_identity.developer_name == "Jane Doe"
        assert proj.developer_identity.engineering_thesis != ""

    def test_project_catalogue(self):
        proj = build_portfolio_site_sample_projection()
        assert len(proj.project_catalogue.entries) > 0
        entry = proj.project_catalogue.entries[0]
        assert entry.project_name
        assert entry.project_url
        assert entry.status

    def test_case_studies(self):
        proj = build_portfolio_site_sample_projection()
        assert len(proj.case_studies.studies) > 0
        study = proj.case_studies.studies[0]
        assert study.study_id
        assert study.title
        assert study.source_project
        assert study.summary

    def test_technology_capability_map(self):
        proj = build_portfolio_site_sample_projection()
        assert len(proj.technology_capability_map) > 0

    def test_engineering_milestones(self):
        proj = build_portfolio_site_sample_projection()
        assert len(proj.engineering_milestones) > 0

    def test_projection_digest(self):
        proj = build_portfolio_site_sample_projection()
        assert proj.projection_digest.startswith("sha256:")

    def test_projection_is_content_light(self):
        proj = build_portfolio_site_sample_projection()
        data = proj.model_dump()
        assert projection_is_content_light(data)

    def test_reserialization_preserves_content_light(self):
        proj = build_portfolio_site_sample_projection()
        dump = proj.model_dump_json()
        import json

        reloaded = PortfolioSitePublicationProjection.model_validate(json.loads(dump))
        data = reloaded.model_dump()
        assert projection_is_content_light(data)


class TestPublicationProjectionsAreDistinct:
    def test_projections_are_distinct(self):
        pp = build_project_page_sample_projection()
        ps = build_portfolio_site_sample_projection()
        assert publication_projections_are_distinct(pp, ps)

    def test_publication_surface_enum_different(self):
        pp = build_project_page_sample_projection()
        ps = build_portfolio_site_sample_projection()
        assert pp.publication_surface != ps.publication_surface

    def test_projection_ids_different(self):
        pp = build_project_page_sample_projection("A")
        ps = build_portfolio_site_sample_projection("B")
        assert pp.projection_id != ps.projection_id

    def test_no_portfolio_fields_in_project_projection(self):
        proj = build_project_page_sample_projection()
        data = proj.model_dump()
        assert "developer_identity" not in data
        assert "project_catalogue" not in data

    def test_no_project_fields_in_portfolio_projection(self):
        proj = build_portfolio_site_sample_projection()
        data = proj.model_dump()
        assert "project_identity" not in data
        assert "status_overview" not in data
        assert "accomplishments" not in data


class TestContentLightDetection:
    def test_rejects_raw_file_contents(self):
        assert not projection_is_content_light({"raw_file_contents": "secret code"})

    def test_rejects_raw_prompt_text(self):
        assert not projection_is_content_light({
            "raw_prompt_text": "system prompt here"
        })

    def test_rejects_model_output(self):
        assert not projection_is_content_light({"model_output_text": "generated text"})

    def test_rejects_secrets(self):
        assert not projection_is_content_light({"secrets": {"api_key": "sk-..."}})

    def test_accepts_clean_data(self):
        assert projection_is_content_light({
            "schema_version": "v1",
            "project_name": "Test",
            "count": 42,
            "items": [{"title": "A", "receipt_ref": "sha256:abc"}],
        })

    def test_accepts_sample_projections(self):
        pp = build_project_page_sample_projection()
        ps = build_portfolio_site_sample_projection()
        assert projection_is_content_light(pp.model_dump())
        assert projection_is_content_light(ps.model_dump())


class TestProjectionSerialization:
    def test_project_page_serialization_roundtrip(self):
        proj = build_project_page_sample_projection()
        dump = proj.model_dump_json()
        import json

        reloaded = ProjectPagePublicationProjection.model_validate(json.loads(dump))
        assert reloaded.projection_id == proj.projection_id
        assert reloaded.projection_digest == proj.projection_digest
        assert reloaded.publication_surface == proj.publication_surface

    def test_portfolio_site_serialization_roundtrip(self):
        proj = build_portfolio_site_sample_projection()
        dump = proj.model_dump_json()
        import json

        reloaded = PortfolioSitePublicationProjection.model_validate(json.loads(dump))
        assert reloaded.projection_id == proj.projection_id
        assert reloaded.projection_digest == proj.projection_digest

    def test_digest_deterministic_across_instances(self):
        p1 = build_project_page_sample_projection("Rig Relay")
        p2 = build_project_page_sample_projection("Rig Relay")
        assert p1.projection_digest == p2.projection_digest

    def test_digest_varies_by_project_name(self):
        p1 = build_project_page_sample_projection("Project A")
        p2 = build_project_page_sample_projection("Project B")
        assert p1.projection_digest != p2.projection_digest


class TestContractNonCollapse:
    def test_cannot_collapse_project_page_into_portfolio(self):
        pp = build_project_page_sample_projection()
        ps = build_portfolio_site_sample_projection()
        pp_keys = set(pp.model_dump().keys())
        ps_keys = set(ps.model_dump().keys())
        common = pp_keys & ps_keys
        structural = {
            "schema_version",
            "projection_id",
            "content_light_guarantee",
            "privacy_class",
            "generated_at",
            "projection_digest",
            "publication_surface",
        }
        domain_specific_common = common - structural
        assert len(domain_specific_common) == 0, (
            f"Unexpected shared domain fields between project_page and portfolio_site: "
            f"{domain_specific_common}"
        )

    def test_surface_specification_contract_distinct_roots(self):
        contract = build_surface_specification_contract()
        pp_roots = set(
            contract.distinct_projection_roots[FrontendSurfaceKind.PROJECT_PAGE]
        )
        ps_roots = set(
            contract.distinct_projection_roots[FrontendSurfaceKind.PORTFOLIO_SITE]
        )
        overlap = pp_roots & ps_roots
        assert len(overlap) == 0, (
            f"Project-page and portfolio-site share projection roots: {overlap}"
        )
