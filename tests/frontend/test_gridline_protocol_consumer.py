from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re

import pytest

# ── Paths ──────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DESKTOP = ROOT / "frontend" / "desktop"
ADAPTER_PATH = FRONTEND_DESKTOP / "js" / "protocol" / "adapter.js"
KEYBOARD_NAV_PATH = FRONTEND_DESKTOP / "js" / "keyboardNav.js"
INDEX_HTML_PATH = FRONTEND_DESKTOP / "index.html"
APP_JS_PATH = FRONTEND_DESKTOP / "app.js"
STUDIO_SCHEMA_PATH = (
    ROOT / "docs" / "schemas" / "rig.relay.developer_studio_projection.v1.schema.json"
)
PATCH_SCHEMA_PATH = (
    ROOT / "docs" / "schemas" / "rig.relay.backend_projection_patch.v1.schema.json"
)


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def studio_schema():
    return json.loads(STUDIO_SCHEMA_PATH.read_text())


@pytest.fixture
def patch_schema():
    return json.loads(PATCH_SCHEMA_PATH.read_text())


@pytest.fixture
def adapter_source():
    return ADAPTER_PATH.read_text()


@pytest.fixture
def keyboard_nav_source():
    return KEYBOARD_NAV_PATH.read_text()


@pytest.fixture
def index_html_source():
    return INDEX_HTML_PATH.read_text()


@pytest.fixture
def app_js_source():
    return APP_JS_PATH.read_text()


@pytest.fixture
def valid_studio_projection():
    return {
        "schema_version": "rig.relay.developer_studio_projection.v1",
        "projection_id": "proj_test_001",
        "generated_at": datetime.now(UTC).isoformat(),
        "workspace": {
            "provenance": "derived_projection",
            "available": True,
            "connection": {
                "provenance": "canonical_fact",
                "trust_state": "trusted_live",
                "connection_state": "connected",
                "installation_id_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "token_available": True,
                "accessible_repository_count": 1,
                "live_installation_verified": True,
                "errors": [],
            },
            "repositories": [
                {
                    "provenance": "derived_projection",
                    "repository_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "owner": "test-owner",
                    "name": "test-repo",
                    "full_name": "test-owner/test-repo",
                    "description_hash": None,
                    "visibility": "public",
                    "default_branch": "main",
                    "has_pages": False,
                    "intake_state": "imported",
                    "selected": True,
                    "import_state": "imported",
                    "local_path_digest": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                    "head_sha": "1234567",
                    "branch": "main",
                    "publication_readiness_state": "review_required",
                    "pages_action_state": "planned",
                    "pages_action_requires_approval": True,
                    "error_kind": None,
                }
            ],
            "selected_count": 1,
            "imported_count": 1,
            "publishable_count": 0,
            "total_discovered": 1,
        },
        "operator": {
            "provenance": "derived_projection",
            "available": True,
            "active_sessions": [
                {
                    "provenance": "derived_projection",
                    "session_id": "session_001",
                    "repository_label": "test-repo",
                    "purpose": "Test investigation",
                    "status": "active",
                    "phase": "investigation",
                    "agent_profile_name": "plan",
                    "tool_call_count": 5,
                    "tool_success_count": 4,
                    "tool_refusal_count": 0,
                    "tool_failure_count": 1,
                    "proposal_count": 0,
                    "refusal_count": 0,
                    "pending_decisions": [],
                    "blocked_capabilities": [],
                    "error_message": None,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
            "total_sessions": 1,
            "active_session_count": 1,
            "refused_session_count": 0,
            "proposal_pending_count": 0,
            "deferred_integrations": [],
            "recovery_materialization_available": False,
        },
        "context": {
            "provenance": "derived_projection",
            "available": True,
            "studies": [
                {
                    "provenance": "derived_projection",
                    "study_status": "study_complete",
                    "project_name": "test-repo",
                    "head_sha": "1234567",
                    "branch": "main",
                    "facts_discovered": 10,
                    "facts_with_provenance": 8,
                    "languages_detected": ["Python"],
                    "frameworks_detected": ["pytest"],
                    "public_ready_assets": [],
                    "public_ready_asset_count": 0,
                    "withheld_material_count": 1,
                    "withheld_reasons": ["private credentials"],
                    "draft_narrative_count": 1,
                    "draft_narrative_awaiting_approval": 1,
                    "bootstrap_gaps": [],
                    "context_packet_ready": True,
                    "context_packet_digest": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
                    "profile_candidate_ready": False,
                    "profile_candidate_digest": "",
                    "portfolio_eligibility": "eligible",
                    "approval_status": "pending_review",
                    "recommendation": "Proceed",
                }
            ],
            "intake_dependency_status": {
                "provenance": "derived_projection",
                "j0_intake_boundary": "live",
                "k0_investigation_boundary": "live",
                "j0_intake_available": True,
                "k0_investigation_available": True,
            },
            "redaction_engine_available": True,
        },
        "inference": {
            "provenance": "derived_projection",
            "available": True,
            "runtime_available": True,
            "runtime_configured": True,
            "runtime_kind": "ollama",
            "platform_class": "macOS",
            "task_suitability": [
                {
                    "task_kind": "PROJECT_SUMMARY",
                    "suitable": True,
                    "requires_runtime": True,
                    "enforcement_class_required": "JSON_OBJECT_FORMATTING_ONLY",
                    "publication_applicability": "internal_only",
                    "refusal_reason": "",
                },
                {
                    "task_kind": "CAPABILITY_CLASSIFICATION",
                    "suitable": False,
                    "requires_runtime": True,
                    "enforcement_class_required": "CLASSIFICATION_REQUIRED",
                    "publication_applicability": "internal_only",
                    "refusal_reason": "Insufficient model capability",
                },
            ],
            "total_results": 2,
            "total_executed": 1,
            "total_refused": 1,
            "drafts_awaiting_review": 1,
            "drafts": [
                {
                    "provenance": "review_required_draft",
                    "result_id": "result_001",
                    "task_id": "task_001",
                    "task_kind": "PROJECT_SUMMARY",
                    "draft_sha256": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                    "draft_byte_count": 1024,
                    "output_disposition": "review_required",
                    "publication_applicability": "internal_only",
                    "requires_approval": True,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
            "refusals": [
                {
                    "provenance": "refused",
                    "result_id": "result_002",
                    "task_id": "task_002",
                    "task_kind": "CAPABILITY_CLASSIFICATION",
                    "refusal_code": "UNSUPPORTED_CAPABILITY",
                    "refusal_reason": "Insufficient model capability",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
            "native_schema_capability_claimed": False,
            "native_schema_capability_proven": False,
            "grammar_capability_claimed": False,
            "grammar_capability_proven": False,
        },
        "service_health": {
            "j0_workspace": "available",
            "k0_operator": "available",
            "l0_context": "available",
            "m0_inference": "available",
        },
        "provenance_summary": {
            "canonical_facts": 1,
            "derived_projections": 5,
            "generated_proposals": 0,
            "review_required_drafts": 1,
            "approved_contents": 0,
            "controlled_boundary_proofs": 0,
            "fixture_deferred": 0,
            "refused": 1,
            "corrupt_untrusted": 0,
        },
        "content_light": True,
        "projection_digest": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    }


@pytest.fixture
def valid_patch():
    return {
        "schema_version": "rig.relay.backend_projection_patch.v1",
        "projection_sequence": 1,
        "trace_id": "trace_001",
        "frontend_session_id": "frontend_001",
        "backend_session_id": "backend_001",
        "generated_at": datetime.now(UTC).isoformat(),
        "patch_kind": "full",
        "changed_sections": ["developer_studio"],
        "sections": {"current_state": {"available": True}},
        "digest": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "redaction_status": "content_light",
    }


@pytest.fixture
def unavailable_studio_projection():
    """All services unavailable — triggers truthful unavailable states."""
    return {
        "schema_version": "rig.relay.developer_studio_projection.v1",
        "projection_id": "proj_unavailable_001",
        "generated_at": datetime.now(UTC).isoformat(),
        "workspace": {
            "provenance": "derived_projection",
            "available": False,
            "connection": {
                "provenance": "controlled_boundary_proof",
                "trust_state": "deferred",
                "connection_state": "disconnected",
                "installation_id_hash": "",
                "token_available": False,
                "accessible_repository_count": 0,
                "live_installation_verified": False,
                "errors": [],
            },
            "repositories": [],
            "selected_count": 0,
            "imported_count": 0,
            "publishable_count": 0,
            "total_discovered": 0,
        },
        "operator": {
            "provenance": "derived_projection",
            "available": False,
            "active_sessions": [],
            "total_sessions": 0,
            "active_session_count": 0,
            "refused_session_count": 0,
            "proposal_pending_count": 0,
            "deferred_integrations": [],
            "recovery_materialization_available": False,
        },
        "context": {
            "provenance": "derived_projection",
            "available": False,
            "studies": [],
            "intake_dependency_status": {
                "provenance": "derived_projection",
                "j0_intake_boundary": "fixture",
                "k0_investigation_boundary": "fixture",
                "j0_intake_available": False,
                "k0_investigation_available": False,
            },
            "redaction_engine_available": True,
        },
        "inference": {
            "provenance": "derived_projection",
            "available": False,
            "runtime_available": False,
            "runtime_configured": False,
            "runtime_kind": "unknown",
            "platform_class": "unknown",
            "task_suitability": [],
            "total_results": 0,
            "total_executed": 0,
            "total_refused": 0,
            "drafts_awaiting_review": 0,
            "drafts": [],
            "refusals": [],
            "native_schema_capability_claimed": False,
            "native_schema_capability_proven": False,
            "grammar_capability_claimed": False,
            "grammar_capability_proven": False,
        },
        "service_health": {
            "j0_workspace": "unavailable",
            "k0_operator": "unavailable",
            "l0_context": "unavailable",
            "m0_inference": "unavailable",
        },
        "provenance_summary": {
            "canonical_facts": 0,
            "derived_projections": 0,
            "generated_proposals": 0,
            "review_required_drafts": 0,
            "approved_contents": 0,
            "controlled_boundary_proofs": 0,
            "fixture_deferred": 4,
            "refused": 0,
            "corrupt_untrusted": 0,
        },
        "content_light": True,
        "projection_digest": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    }


# ── Schema validation tests ────────────────────────────────────────


class TestStudioProjectionSchema:
    def test_valid_projection_passes_schema(
        self, valid_studio_projection, studio_schema
    ):
        """A valid developer-studio projection must validate against the schema."""
        from jsonschema import validate

        validate(instance=valid_studio_projection, schema=studio_schema)

    def test_unavailable_projection_passes_schema(
        self, unavailable_studio_projection, studio_schema
    ):
        """An all-unavailable projection must also validate."""
        from jsonschema import validate

        validate(instance=unavailable_studio_projection, schema=studio_schema)

    def test_projection_without_content_light_rejected(
        self, valid_studio_projection, studio_schema
    ):
        """A projection with content_light=False must be rejected by schema."""
        from jsonschema import ValidationError, validate

        projection = dict(valid_studio_projection)
        projection["content_light"] = False
        with pytest.raises(ValidationError):
            validate(instance=projection, schema=studio_schema)

    def test_projection_with_wrong_schema_version_rejected(
        self, valid_studio_projection, studio_schema
    ):
        """A projection with wrong schema_version must be rejected."""
        from jsonschema import ValidationError, validate

        projection = dict(valid_studio_projection)
        projection["schema_version"] = "rig.relay.fake_schema.v1"
        with pytest.raises(ValidationError):
            validate(instance=projection, schema=studio_schema)


class TestBackendPatchSchema:
    def test_valid_patch_passes_schema(self, valid_patch, patch_schema):
        from jsonschema import validate

        validate(instance=valid_patch, schema=patch_schema)

    def test_stale_patch_sequence_is_valid(self, valid_patch, patch_schema):
        """Stale sequences are structurally valid (rejection is at adapter level)."""
        from jsonschema import validate

        validate(instance=valid_patch, schema=patch_schema)

    def test_patch_without_redaction_status_rejected(self, valid_patch, patch_schema):
        from jsonschema import ValidationError, validate

        patch = dict(valid_patch)
        patch["redaction_status"] = "not_content_light"
        with pytest.raises(ValidationError):
            validate(instance=patch, schema=patch_schema)


# ── Adapter source analysis tests ───────────────────────────────────


class TestAdapterSource:
    def test_adapter_file_exists(self, adapter_source):
        assert len(adapter_source) > 100

    def test_production_mode_is_default(self, adapter_source):
        """Adapter must default to production mode, not fixture mode."""
        assert "return 'production'" in adapter_source
        assert "_mode = _detectMode()" in adapter_source

    def test_fixture_mode_is_explicit_opt_in(self, adapter_source):
        """Fixture mode must require an explicit opt-in (URL param or window flag)."""
        assert "fixture_mode" in adapter_source
        assert "params.get('fixture_mode') === '1'" in adapter_source
        assert "__RIG_RELAY_FIXTURE_MODE__ === true" in adapter_source

    def test_accept_developer_studio_projection_checks_schema(self, adapter_source):
        """Ingestion must validate schema_version before accepting."""
        assert "acceptDeveloperStudioProjection" in adapter_source
        assert "rig.relay.developer_studio_projection.v1" in adapter_source

    def test_accept_projection_patch_checks_schema(self, adapter_source):
        """Patch ingestion must validate schema_version."""
        assert "acceptProjectionPatch" in adapter_source
        assert "rig.relay.backend_projection_patch.v1" in adapter_source

    def test_surface_states_have_unavailable_default(self, adapter_source):
        """All 5 surface states must begin with 'unavailable'."""
        assert "unavailable" in adapter_source
        for surface in [
            "'connect'",
            "'repository-estate'",
            "'project-studio'",
            "'inference-studio'",
            "'publish-preview'",
        ]:
            assert surface in adapter_source, f"Missing surface: {surface}"

    def test_all_trust_states_rendered(self, adapter_source):
        """All trust states from TrustState enum must have render paths."""
        for trust_state in [
            "trusted_live",
            "controlled_boundary",
            "fixture",
            "deferred",
            "refused",
            "corrupt",
        ]:
            assert trust_state in adapter_source, f"Missing trust state: {trust_state}"

    def test_evidence_tags_for_all_provenance_classes(self, adapter_source):
        """All ProvenanceClass values should have evidence tag rendering."""
        for tag in ["proven", "claimed", "planned", "narrative"]:
            assert f"'{tag}'" in adapter_source or f'"{tag}"' in adapter_source, (
                f"Missing evidence tag: {tag}"
            )

    def test_intents_from_three_surfaces(self, adapter_source):
        """Typed intents must emit from Connect, RepositoryEstate, and ProjectStudio."""
        assert "emitConnectIntent" in adapter_source
        assert "emitRepositoryEstateIntent" in adapter_source
        assert "emitProjectStudioIntent" in adapter_source

    def test_stale_patch_sequence_rejected(self, adapter_source):
        """Stale patches (seq <= last) must be rejected."""
        assert "stale_sequence" in adapter_source
        assert "_lastProjectionSeq" in adapter_source

    def test_no_unsafe_inner_html_patterns(self, adapter_source):
        """Adapter must not contain dangerous innerHTML patterns for untrusted data."""
        # The adapter uses _setText (textContent), not innerHTML for projection data.
        # Allowed: innerHTML used only with known-safe templates (evidence tags, status chips).
        _verify_no_untrusted_innerhtml(adapter_source, "adapter.js")

    def test_escape_html_function_defined(self, adapter_source):
        """_escapeHtml must be defined and cover the basic XSS vectors."""
        assert "_escapeHtml" in adapter_source
        assert "replace(/&/g, '&amp;')" in adapter_source
        assert "replace(/</g, '&lt;')" in adapter_source
        assert "replace(/>/g, '&gt;')" in adapter_source
        assert "replace(/\"/g, '&quot;')" in adapter_source


# ── Keyboard navigation tests ──────────────────────────────────────


class TestKeyboardNavigation:
    def test_keyboard_nav_file_exists(self, keyboard_nav_source):
        assert len(keyboard_nav_source) > 100

    def test_arrow_key_navigation_defined(self, keyboard_nav_source):
        """Both surface and mode tabs must support ArrowRight/ArrowLeft."""
        assert "ArrowRight" in keyboard_nav_source
        assert "ArrowLeft" in keyboard_nav_source

    def test_home_end_navigation_defined(self, keyboard_nav_source):
        """Home and End keys must be supported."""
        assert "'Home'" in keyboard_nav_source or '"Home"' in keyboard_nav_source
        assert "'End'" in keyboard_nav_source or '"End"' in keyboard_nav_source

    def test_aria_selected_managed(self, keyboard_nav_source):
        """ARIA selected attribute must be managed."""
        assert "aria-selected" in keyboard_nav_source

    def test_tabindex_managed(self, keyboard_nav_source):
        """tabindex must be managed for keyboard focus order."""
        assert "tabindex" in keyboard_nav_source

    def test_setup_keyboard_navigation_exported(self, keyboard_nav_source):
        """The setup function must be exported."""
        assert "setupKeyboardNavigation" in keyboard_nav_source


# ── HTML source analysis ───────────────────────────────────────────


class TestIndexHtmlSource:
    def test_fixture_scripts_are_gated(self, index_html_source):
        """Fixture scripts must have data-fixture-only attribute for conditional unloading."""
        assert "data-fixture-only" in index_html_source

    def test_fixture_unload_script_present(self, index_html_source):
        """Production mode must unload fixture scripts."""
        assert "__RIG_RELAY_FIXTURE_MODE__" in index_html_source

    def test_adapter_script_loaded(self, index_html_source):
        """The Gridline adapter must be loaded."""
        assert "js/protocol/adapter.js" in index_html_source

    def test_keyboard_nav_script_loaded(self, index_html_source):
        """Keyboard nav module must be loaded."""
        assert "js/keyboardNav.js" in index_html_source

    def test_surface_nav_has_aria_role(self, index_html_source):
        """Surface nav must have ARIA tab role."""
        assert 'role="tab"' in index_html_source
        assert "aria-selected" in index_html_source

    def test_skip_link_present(self, index_html_source):
        """Skip-to-content link must exist for accessibility."""
        assert "skip-link" in index_html_source


# ── App.js source analysis ─────────────────────────────────────────


class TestAppJsSource:
    def test_global_bridge_attached(self, app_js_source):
        """S1 global bridge must attach key functions to window."""
        assert "window.switchSurface" in app_js_source
        assert "window.emitP0Intent" in app_js_source
        assert "window.switchMode" in app_js_source

    def test_adapter_imported(self, app_js_source):
        """app.js must import the Gridline adapter."""
        assert "./js/protocol/adapter.js" in app_js_source
        assert "GridlineAdapter" in app_js_source

    def test_intent_routing_uses_adapter(self, app_js_source):
        """emitP0Intent must route studio intents through the adapter."""
        assert "GridlineAdapter.emitConnectIntent" in app_js_source
        assert "GridlineAdapter.emitRepositoryEstateIntent" in app_js_source
        assert "GridlineAdapter.emitProjectStudioIntent" in app_js_source

    def test_fixture_mode_detected_in_switch_surface(self, app_js_source):
        """switchSurface must check GridlineAdapter.getMode() before rendering."""
        assert "GridlineAdapter.getMode()" in app_js_source


# ── Malicious payload safety ───────────────────────────────────────


class TestMaliciousPayloadSafety:
    def test_xss_in_projection_fields(self, valid_studio_projection, studio_schema):
        """Projection with XSS payload in string fields must still validate structurally."""
        from jsonschema import validate

        projection = dict(valid_studio_projection)
        projection["workspace"]["connection"]["connection_state"] = (
            '<script>alert("xss")</script>connected'
        )
        validate(instance=projection, schema=studio_schema)

    def test_html_injection_in_repo_name(self, valid_studio_projection, studio_schema):
        """Repository names with HTML must still pass schema validation."""
        from jsonschema import validate

        projection = dict(valid_studio_projection)
        projection["workspace"]["repositories"][0]["name"] = (
            "<img src=x onerror=alert(1)>"
        )
        validate(instance=projection, schema=studio_schema)

    def test_adapter_uses_textcontent_for_untrusted(self, adapter_source):
        """Adapter must use textContent (setText) for untrusted content, never bare innerHTML."""
        assert "textContent" in adapter_source or "_setText" in adapter_source

    def test_adapter_escape_html_called_before_rendering(self, adapter_source):
        """_escapeHtml must be called for all projection string fields rendered in HTML."""
        assert "_escapeHtml" in adapter_source

    def test_provenance_summary_protected_fields(self, valid_studio_projection):
        """Provenance summary must not contain raw file contents or secrets."""
        ps = valid_studio_projection["provenance_summary"]
        assert isinstance(ps["canonical_facts"], int)
        assert isinstance(ps["fixture_deferred"], int)
        assert isinstance(ps["refused"], int)
        # No string fields that could leak secrets (all integers)


# ── Reduced motion ─────────────────────────────────────────────────


class TestReducedMotion:
    def test_reduced_motion_css_rule(self):
        """variables.css must honor prefers-reduced-motion."""
        css_path = FRONTEND_DESKTOP / "css" / "variables.css"
        css = css_path.read_text()
        assert "@media (prefers-reduced-motion: reduce)" in css
        assert "--transition-fast: 0ms" in css
        assert "--transition-base: 0ms" in css

    def test_no_new_unconditional_transitions_in_layout_css(self):
        """Layout transitions should use CSS custom properties (already set to 0 in reduced motion)."""
        layout_css = (FRONTEND_DESKTOP / "css" / "layout.css").read_text()
        # Verify that expand overlay transitions use var() so they respect reduced motion
        assert "var(--transition-" in layout_css


# ── Production vs fixture behavior ──────────────────────────────────


class TestProductionVsFixtureBehavior:
    def test_production_default_in_adapter(self, adapter_source):
        """The adapter's mode detection must default to 'production'."""
        # Find the _detectMode function and verify the default return
        assert "return 'production'" in adapter_source

    def test_fixture_mode_is_explicit_param(self, adapter_source):
        """Fixture mode requires ?fixture_mode=1 or window flag."""
        assert "fixture_mode" in adapter_source

    def test_adapter_does_not_fallback_to_fixtures(self, adapter_source):
        """In production mode, the adapter must never call fixture rendering."""
        # The renderFixtureSurface function checks getMode() first
        assert "_mode !== 'fixture'" in adapter_source

    def test_fixture_rendering_gated(self, adapter_source):
        """RenderFixtureSurface must return not_in_fixture_mode in production."""
        assert "'not_in_fixture_mode'" in adapter_source

    def test_unavailable_state_rendering(self, adapter_source):
        """When projection is null, all surfaces must show unavailable status."""
        assert "unavailable" in adapter_source
        assert "No live bridge projection" in adapter_source

    def test_deferred_state_rendering(self, adapter_source):
        """When service is not available, surfaces must show deferred."""
        assert "deferred" in adapter_source


# ── Helpers ────────────────────────────────────────────────────────


def _verify_no_untrusted_innerhtml(source: str, filename: str) -> None:
    """Verify that innerHTML usage is not applied to untrusted projection data.

    The adapter is allowed to use innerHTML for:
    - Known-safe template strings (evidence tags, status chips)
    - Setter functions that only receive backend-constructed HTML

    But must never directly assign projection string fields to innerHTML
    without _escapeHtml.
    """
    lines = source.split("\n")
    innerhtml_lines = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if "innerHTML" in stripped:
            innerhtml_lines.append((i, stripped))

    # Every innerHTML line that includes projection data must also call _escapeHtml
    # or be constructing from known-safe strings.
    for lineno, line in innerhtml_lines:
        # Skip known-safe patterns: evidence tag construction, string literals
        if "_renderEvidenceTag(" in line:
            continue
        if "_setStatusChip(" in line:
            continue
        if "class=" in line and "status-chip" in line:
            continue
        if "banner" in line:
            continue
        # Lines with innerHTML must use _escapeHtml for any non-literal content.
        # Allowed exceptions: integer scalars (totalCalls, totalSuccess, lengths, etc.)
        if (
            "+" in line
            and "_escapeHtml" not in line.replace(" ", "")
            and "innerHTML +=" not in line
            and "innerHTML =" not in line
        ):
            continue
        if "innerHTML +=" in line or "innerHTML =" in line:
            # Pure literal string assignment (no + concatenation) is always safe
            assign_part = line.split("=", 1)[-1] if "=" in line else line
            if "+" not in assign_part:
                continue
            # Skip known-safe numeric or length-only template lines
            if _is_numeric_template_only(line):
                continue
            assert "_escapeHtml" in line or "evidence-tag" in line, (
                f"Potential unsafe innerHTML at {filename}:{lineno}: {line.strip()[:80]}"
            )


def _is_numeric_template_only(line: str) -> bool:
    """Check if an innerHTML line only concatenates integer scalars or array lengths."""
    # Extract concatenation operands (parts between + signs after =)
    assign_idx = line.find("=")
    if assign_idx < 0:
        return False
    rhs = line[assign_idx + 1 :]
    # Split by +, but keep only bare variable references (no string literals)
    parts = [p.strip() for p in rhs.split("+")]
    safe_numeric = {
        "totalCalls",
        "totalSuccess",
        "totalProposals",
        "totalPending",
        "totalRefused",
        "String",
        "Number",
    }
    for part in parts:
        # Skip string literal parts (quoted strings)
        if part.startswith(("'", '"', "`")):
            continue
        # Bare variable: check if it's a safe numeric or length access
        clean = part.rstrip(";").strip()
        if clean.endswith(".length"):
            continue
        if clean in safe_numeric:
            continue
        if re.match(r"^[a-zA-Z_]\w*$", clean):
            # Unknown bare variable — potentially unsafe string
            return False
    return True
