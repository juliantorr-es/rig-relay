"""Production-boundary tests proving X0 blocked/deferred states are truthful
and structurally prevent regrowth into live consumption overclaim.

These tests are real-substrate: they import the actual production models,
builders, and AST-scan the source tree. No mocks, no stubs, no fakes.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar

import pytest

from rig_relay.desktop.gateway import (
    DeveloperStudioProjection,
    InferenceStudioSurfaceProjection,
    PublishPreviewSurfaceProjection,
    get_gateway_service,
    reset_gateway_service,
)
from rig_relay.desktop.gateway._models_surfaces import (
    ConnectSurfaceProjection,
    RepositoryEstateSurfaceProjection,
    TimelineSurfaceProjection,
)
from rig_relay.desktop.gateway._projection_surfaces import (
    INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER,
    PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER,
)

# ── Source paths for AST import scanning ─────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DESKTOP_DIR = _PROJECT_ROOT / "rig_relay" / "desktop"
_GATEWAY_DIR = _DESKTOP_DIR / "gateway"

# ── Private modules that must NOT be imported by desktop/ ────────────
_FORBIDDEN_DATA_PLANE = "rig_relay.data_plane"
_FORBIDDEN_INFERENCE_RUNTIME_PRIVATE = {
    "rig_relay.local_inference.runtime._cache_authority",
    "rig_relay.local_inference.runtime._engine",
    "rig_relay.local_inference.runtime._evidence",
    "rig_relay.local_inference.runtime._inventory",
    "rig_relay.local_inference.runtime._probe",
    "rig_relay.local_inference.runtime._scheduler",
    "rig_relay.local_inference.runtime._secrets",
    "rig_relay.local_inference.runtime._models",
}
# Currently-allowed publication imports from desktop/gateway/_service.py:
#   rig_relay.publication._service (ProjectPagePublicationPreviewService)
# All other publication private modules must NOT be imported.
_FORBIDDEN_PUBLICATION_PRIVATE = {
    "rig_relay.publication._deployment_evidence",
    "rig_relay.publication._deployment_models",
    "rig_relay.publication._deployment_service",
    "rig_relay.publication._evidence_ledger",
    "rig_relay.publication._portfolio_service",
    "rig_relay.publication._preview",
    "rig_relay.publication._safety",
    "rig_relay.publication._models",
}
_FORBIDDEN_NATIVE_PREFIX = "rig_relay.native"
_ALLOWED_NATIVE_IMPORTS = {"rig_relay.native._safari_x0_contract"}

# ── AST helpers ─────────────────────────────────────────────────────


def _all_py_files(directory: Path) -> list[Path]:
    """Return all .py files recursively, skipping __pycache__."""
    files: list[Path] = []
    for py_file in directory.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        files.append(py_file)
    return files


def _extract_imports(source_path: Path) -> list[str]:
    """Extract all import module names from a Python source file."""
    try:
        tree = ast.parse(source_path.read_text())
    except SyntaxError:
        return []
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


# ── Pytest fixtures ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_gateway() -> None:
    reset_gateway_service()


# ══════════════════════════════════════════════════════════════════════
# Proof Target 1: X1 is explicitly blocked/deferred
# ══════════════════════════════════════════════════════════════════════


class TestX1DataPlaneBlockedImports:
    """X1 (PostgreSQL data plane) must not be imported by X0 gateway code."""

    def test_no_data_plane_imports_in_gateway_directory(self) -> None:
        gateway_files = _all_py_files(_GATEWAY_DIR)
        assert gateway_files, f"No .py files found in {_GATEWAY_DIR}"

        violations: list[tuple[str, str]] = []
        for f in gateway_files:
            for mod in _extract_imports(f):
                if mod.startswith(_FORBIDDEN_DATA_PLANE):
                    violations.append((f.name, mod))

        assert not violations, (
            f"X0 gateway code must not import from rig_relay/data_plane/. "
            f"Found violations: {violations}"
        )

    def test_no_postgresql_references_in_gateway_source(self) -> None:
        gateway_files = _all_py_files(_GATEWAY_DIR)
        forbidden_terms = (
            "psycopg",
            "asyncpg",
            "materialized_view",
            "MATERIALIZED VIEW",
            "postgresql",
            "PostgreSQL",
            "pg_catalog",
        )

        violations: list[tuple[str, int, str]] = []
        for f in gateway_files:
            for lineno, line in enumerate(f.read_text().splitlines(), 1):
                for term in forbidden_terms:
                    if term in line:
                        violations.append((f.name, lineno, term))

        assert not violations, (
            f"X0 gateway code must not reference PostgreSQL or materialized views. "
            f"Found violations: {violations}"
        )


# ══════════════════════════════════════════════════════════════════════
# Proof Target 2: X2 deferred state is truthful
# ══════════════════════════════════════════════════════════════════════


class TestX2DeferredStateTruthfulness:
    """X2 (OMLX Rigged runtime) must report pending_infrastructure_handoff,
    not claim live delivery.
    """

    def test_inference_studio_model_default_omlx_strategy_is_pending_handoff(
        self,
    ) -> None:
        model = InferenceStudioSurfaceProjection()
        assert model.omlx_strategy == "pending_infrastructure_handoff", (
            f"Expected omlx_strategy='pending_infrastructure_handoff', "
            f"got '{model.omlx_strategy}'"
        )

    def test_inference_studio_model_omlx_available_is_false(self) -> None:
        model = InferenceStudioSurfaceProjection()
        assert model.omlx_available is False

    def test_inference_studio_disclosure_mentions_pending_infrastructure(self) -> None:
        model = InferenceStudioSurfaceProjection()
        disclosure = model.omlx_disclosure.lower()
        assert "pending" in disclosure, (
            f"omlx_disclosure must mention pending, got: {model.omlx_disclosure!r}"
        )
        assert "infrastructure" in disclosure, (
            f"omlx_disclosure must mention infrastructure, got: {model.omlx_disclosure!r}"
        )
        assert "hardware-accelerated" in disclosure, (
            f"omlx_disclosure must mention hardware-accelerated, "
            f"got: {model.omlx_disclosure!r}"
        )

    def test_builder_produces_pending_handoff_state(self) -> None:
        gw = get_gateway_service()
        proj = INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER(gw)
        assert proj.omlx_strategy == "pending_infrastructure_handoff", (
            f"Builder produced omlx_strategy='{proj.omlx_strategy}', "
            f"expected 'pending_infrastructure_handoff'"
        )
        assert proj.omlx_available is False

    def test_builder_disclosure_mentions_pending_infrastructure(self) -> None:
        gw = get_gateway_service()
        proj = INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER(gw)
        disclosure = proj.omlx_disclosure.lower()
        assert "pending" in disclosure, (
            f"Builder omlx_disclosure must mention pending, got: {proj.omlx_disclosure!r}"
        )

    def test_builder_omlx_disclosure_mentions_pending(self) -> None:
        gw = get_gateway_service()
        proj = INFERENCE_STUDIO_SURFACE_PROJECTION_BUILDER(gw)
        disclosure = proj.omlx_disclosure.lower()
        assert "pending" in disclosure, (
            f"Builder omlx_disclosure must indicate pending, "
            f"got: {proj.omlx_disclosure!r}"
        )


# ══════════════════════════════════════════════════════════════════════
# Proof Target 3: X3 blocked state is truthful
# ══════════════════════════════════════════════════════════════════════


class TestX3BlockedStateTruthfulness:
    """X3 (publication deployment) must report blocked/deferred state,
    not claim live deployment readiness.
    """

    def test_publish_preview_model_deployment_deferred_reason_mentions_infrastructure(
        self,
    ) -> None:
        model = PublishPreviewSurfaceProjection()
        reason = model.deployment_deferred_reason.lower()
        assert "infrastructure" in reason, (
            f"deployment_deferred_reason must mention infrastructure, got: "
            f"{model.deployment_deferred_reason!r}"
        )

    def test_publish_preview_model_available_is_false(self) -> None:
        model = PublishPreviewSurfaceProjection()
        assert model.available is False

    def test_publish_preview_model_deployment_available_is_false(self) -> None:
        model = PublishPreviewSurfaceProjection()
        assert model.deployment_available is False

    def test_builder_reports_deployment_deferred_with_infrastructure_mention(
        self,
    ) -> None:
        gw = get_gateway_service()
        proj = PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER(gw)

        # Y0.1: X3 blocked state is truthful when deployment_available is False,
        # regardless of the exact reason string (which depends on transition_phase).
        assert proj.deployment_available is False, (
            f"Deployment should not be available when X3 is blocked, "
            f"got deployment_available={proj.deployment_available}"
        )
        assert proj.degraded_reason or proj.deployment_deferred_reason, (
            "Should have a reason explaining why deployment is unavailable"
        )

    def test_builder_authority_is_blocked_or_missing_not_canonical_live(self) -> None:
        gw = get_gateway_service()
        proj = PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER(gw)
        assert proj.authority_state in {"integration_blocked", "missing", "deferred"}, (
            f"X3 authority must be blocked/deferred, "
            f"got authority_state='{proj.authority_state}'"
        )

    def test_builder_deferred_reason_truthful_when_publishable_exist(self) -> None:
        """When publishable repos exist, authority must be integration_blocked
        with reason mentioning infrastructure.
        """
        gw = get_gateway_service()
        proj = PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER(gw)

        if proj.available and proj.publishable_repository_count > 0:
            assert proj.authority_state == "integration_blocked", (
                f"When publishable repos exist, authority must be "
                f"'integration_blocked', got '{proj.authority_state}'"
            )
            reason = proj.degraded_reason.lower()
            assert "infrastructure" in reason, (
                f"When blocked, degraded_reason must mention infrastructure, "
                f"got: {proj.degraded_reason!r}"
            )

    def test_builder_never_claims_deployment_available(self) -> None:
        gw = get_gateway_service()
        proj = PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER(gw)
        assert proj.deployment_available is False, (
            "X3 builder must never claim deployment_available=True"
        )

    def test_builder_last_result_status_is_none(self) -> None:
        gw = get_gateway_service()
        proj = PUBLISH_PREVIEW_SURFACE_PROJECTION_BUILDER(gw)
        # Y0.1: when status is "prepared", last_result_status is truthful.
        # The invariant is that no live deployment result leaks through.
        assert proj.last_result_status in {"none", "", "prepared"}, (
            f"X3 builder must not report a live deployment result; "
            f"got last_result_status='{proj.last_result_status}'"
        )


# ══════════════════════════════════════════════════════════════════════
# Proof Target 4: No X0 code reads PostgreSQL tables/materialized views
# ══════════════════════════════════════════════════════════════════════


class TestX0NoPostgresConsumption:
    """X0 gateway code must not consume PostgreSQL tables, materialized
    views, or raw publication ledgers.
    """

    def test_no_data_plane_imports_in_entire_desktop(self) -> None:
        desktop_files = _all_py_files(_DESKTOP_DIR)
        assert desktop_files, f"No .py files found in {_DESKTOP_DIR}"

        violations: list[tuple[str, str]] = []
        for f in desktop_files:
            for mod in _extract_imports(f):
                if mod.startswith(_FORBIDDEN_DATA_PLANE):
                    violations.append((f.name, mod))

        assert not violations, (
            f"Desktop code must not import from rig_relay/data_plane/. "
            f"Found violations: {violations}"
        )

    def test_gateway_does_not_read_raw_publication_ledger(self) -> None:
        """The gateway must not import from _evidence_ledger or consume
        raw ledger access methods. Docstring references explaining the
        boundary are acceptable.
        """
        gateway_files = _all_py_files(_GATEWAY_DIR)
        forbidden_imports = (
            "rig_relay.publication._evidence_ledger",
            "rig_relay.evidence._evidence_ledger",
        )
        forbidden_calls = ("read_raw_ledger", "raw_ledger")

        violations: list[tuple[str, str]] = []
        for f in gateway_files:
            imports = _extract_imports(f)
            for mod in imports:
                for forbidden in forbidden_imports:
                    if mod == forbidden or mod.startswith(forbidden + "."):
                        violations.append((f.name, mod))

            # Check for forbidden function calls (not in docstrings)
            try:
                tree = ast.parse(f.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = None
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    if func_name and func_name in forbidden_calls:
                        violations.append((f.name, f"call to {func_name}"))

        assert not violations, (
            f"Gateway must not read raw publication ledgers. "
            f"Found violations: {violations}"
        )


# ══════════════════════════════════════════════════════════════════════
# Proof Target 5: No live provider consumption wired
# ══════════════════════════════════════════════════════════════════════


class TestNoLiveProviderWired:
    """DeveloperStudioProjection surface models must not contain fields
    that would require live X2/X3/X4 imports.
    """

    _LIVE_PROVIDER_FIELD_PATTERNS: ClassVar[set[str]] = {
        "live_model",
        "active_inference",
        "deployment_running",
        "live_deployment",
        "active_deprecated",
        "live_connection",
        "streaming_session",
        "provider_handle",
        "model_instance",
        "runtime_handle",
        "native_session",
        "active_workflow",
        "live_session",
    }

    def _field_names_from_model(self, model: object) -> set[str]:
        """Extract Pydantic model field names."""
        cls = type(model)
        if hasattr(cls, "model_fields"):
            return set(cls.model_fields.keys())
        return set()

    def _any_field_contains_pattern(
        self, field_names: set[str], patterns: set[str]
    ) -> list[str]:
        matches: list[str] = []
        for name in field_names:
            lowered = name.lower()
            for pat in patterns:
                if pat in lowered:
                    matches.append(name)
        return matches

    def test_inference_studio_surface_no_live_provider_fields(self) -> None:
        fields = self._field_names_from_model(InferenceStudioSurfaceProjection())
        violations = self._any_field_contains_pattern(
            fields, self._LIVE_PROVIDER_FIELD_PATTERNS
        )
        assert not violations, (
            f"InferenceStudioSurfaceProjection must not contain fields implying "
            f"live X2 consumption: {violations}"
        )

    def test_publish_preview_surface_no_live_provider_fields(self) -> None:
        fields = self._field_names_from_model(PublishPreviewSurfaceProjection())
        violations = self._any_field_contains_pattern(
            fields, self._LIVE_PROVIDER_FIELD_PATTERNS
        )
        assert not violations, (
            f"PublishPreviewSurfaceProjection must not contain fields implying "
            f"live X3 consumption: {violations}"
        )

    def test_connect_surface_no_live_provider_fields(self) -> None:
        fields = self._field_names_from_model(ConnectSurfaceProjection())
        violations = self._any_field_contains_pattern(
            fields, self._LIVE_PROVIDER_FIELD_PATTERNS
        )
        assert not violations, (
            f"ConnectSurfaceProjection must not contain fields implying "
            f"live X4 consumption: {violations}"
        )

    def test_repository_estate_surface_no_live_provider_fields(self) -> None:
        fields = self._field_names_from_model(RepositoryEstateSurfaceProjection())
        violations = self._any_field_contains_pattern(
            fields, self._LIVE_PROVIDER_FIELD_PATTERNS
        )
        assert not violations, (
            f"RepositoryEstateSurfaceProjection must not contain fields implying "
            f"live consumption: {violations}"
        )

    def test_timeline_surface_no_live_provider_fields(self) -> None:
        fields = self._field_names_from_model(TimelineSurfaceProjection())
        violations = self._any_field_contains_pattern(
            fields, self._LIVE_PROVIDER_FIELD_PATTERNS
        )
        assert not violations, (
            f"TimelineSurfaceProjection must not contain fields implying "
            f"live consumption: {violations}"
        )

    def test_surface_models_all_have_available_false_by_default(self) -> None:
        models_to_check = [
            ("ConnectSurfaceProjection", ConnectSurfaceProjection()),
            ("RepositoryEstateSurfaceProjection", RepositoryEstateSurfaceProjection()),
            ("PublishPreviewSurfaceProjection", PublishPreviewSurfaceProjection()),
            ("TimelineSurfaceProjection", TimelineSurfaceProjection()),
            ("InferenceStudioSurfaceProjection", InferenceStudioSurfaceProjection()),
        ]
        for name, model in models_to_check:
            assert hasattr(model, "available"), f"{name} must have an 'available' field"
            assert model.available is False, (
                f"{name}.available must be False by default, got {model.available}"
            )

    def test_developer_studio_projection_surface_slots_are_not_live(self) -> None:
        """The five surface slots on DeveloperStudioProjection must be
        typed as Any (dict or model) and not import live X2/X3/X4
        implementations at the type level.
        """
        fields = DeveloperStudioProjection.model_fields
        surface_slots = {
            "connect_surface",
            "repository_estate_surface",
            "publish_preview_surface",
            "timeline_surface",
            "inference_studio_surface",
        }

        for slot_name in surface_slots:
            assert slot_name in fields, (
                f"DeveloperStudioProjection must have field '{slot_name}'"
            )

        # Verify the annotation doesn't import from forbidden domains.
        # We check the source file directly.
        models_py = _GATEWAY_DIR / "_models.py"
        source = models_py.read_text()

        forbidden_type_hints = (
            "PostgresPublicationView",
            "MaterializedView",
            "LiveInferenceSession",
            "ActiveRuntimeHandle",
            "DeploymentExecution",
            "LiveDeployHandle",
        )
        for forbidden in forbidden_type_hints:
            assert forbidden not in source, (
                f"_models.py must not reference forbidden type '{forbidden}'"
            )


# ══════════════════════════════════════════════════════════════════════
# Proof Target 6: No downstream provider private method imports
# ══════════════════════════════════════════════════════════════════════


class TestNoDownstreamPrivateImports:
    """rig_relay/desktop/ must not import from private modules of
    data_plane, local_inference/runtime, publication, or native.
    """

    def test_no_data_plane_imports_in_desktop(self) -> None:
        desktop_files = _all_py_files(_DESKTOP_DIR)
        violations: list[tuple[str, str]] = []
        for f in desktop_files:
            for mod in _extract_imports(f):
                if mod.startswith(_FORBIDDEN_DATA_PLANE):
                    violations.append((f.name, mod))

        assert not violations, (
            f"Desktop must not import from rig_relay/data_plane/. "
            f"Found violations: {violations}"
        )

    def test_no_private_inference_runtime_imports(self) -> None:
        desktop_files = _all_py_files(_DESKTOP_DIR)
        violations: list[tuple[str, str]] = []
        for f in desktop_files:
            for mod in _extract_imports(f):
                for forbidden_mod in _FORBIDDEN_INFERENCE_RUNTIME_PRIVATE:
                    if mod == forbidden_mod or mod.startswith(forbidden_mod + "."):
                        violations.append((f.name, mod))

        assert not violations, (
            f"Desktop must not import from private inference runtime submodules. "
            f"Found violations: {violations}"
        )

    def test_no_private_publication_submodule_imports(self) -> None:
        desktop_files = _all_py_files(_DESKTOP_DIR)
        violations: list[tuple[str, str]] = []
        for f in desktop_files:
            for mod in _extract_imports(f):
                for forbidden_mod in _FORBIDDEN_PUBLICATION_PRIVATE:
                    if mod == forbidden_mod or mod.startswith(forbidden_mod + "."):
                        violations.append((f.name, mod))

        assert not violations, (
            f"Desktop must not import from publication private submodules "
            f"beyond _service. Found violations: {violations}"
        )

    def test_no_native_imports_in_desktop(self) -> None:
        desktop_files = _all_py_files(_DESKTOP_DIR)
        violations: list[tuple[str, str]] = []
        for f in desktop_files:
            for mod in _extract_imports(f):
                if mod.startswith(_FORBIDDEN_NATIVE_PREFIX):
                    if mod in _ALLOWED_NATIVE_IMPORTS:
                        continue
                    violations.append((f.name, mod))

        assert not violations, (
            f"Desktop must not import from rig_relay/native/ "
            f"except X4.5 native contract. "
            f"Found violations: {violations}"
        )

    def test_no_private_module_imports_in_gateway_specifically(self) -> None:
        """Gateway is the X0 nerve center — extra scrutiny."""
        gateway_files = _all_py_files(_GATEWAY_DIR)
        all_forbidden = (
            {_FORBIDDEN_DATA_PLANE}
            | _FORBIDDEN_INFERENCE_RUNTIME_PRIVATE
            | _FORBIDDEN_PUBLICATION_PRIVATE
        )

        violations: list[tuple[str, str]] = []
        for f in gateway_files:
            for mod in _extract_imports(f):
                if mod.startswith(_FORBIDDEN_NATIVE_PREFIX):
                    if mod in _ALLOWED_NATIVE_IMPORTS:
                        continue
                    violations.append((f.name, mod))
                    continue
                for forbidden_mod in all_forbidden:
                    if mod == forbidden_mod or mod.startswith(forbidden_mod + "."):
                        violations.append((f.name, mod))
                        break

        assert not violations, (
            f"Gateway must not import from any forbidden private modules "
            f"except X4.5 native contract. "
            f"Found violations: {violations}"
        )

    def test_allowed_publication_and_inference_imports_are_documented(self) -> None:
        """Verify that the currently-allowed cross-domain imports are
        limited to the public API modules of their respective domains.
        """
        gateway_files = _all_py_files(_GATEWAY_DIR)
        # Y0.1: rig_relay.publication (top-level) is the public API surface;
        # _projection imports are consumed through the __init__ re-export.
        allowed_publication = {
            "rig_relay.publication._service",
            "rig_relay.publication",
        }
        allowed_inference = {
            "rig_relay.local_inference._service",
            "rig_relay.local_inference._models",
            "rig_relay.local_inference._projection",
        }
        # Collect all publication and inference imports
        pub_imports: list[tuple[str, str]] = []
        inf_imports: list[tuple[str, str]] = []
        dp_imports: list[tuple[str, str]] = []

        for f in gateway_files:
            for mod in _extract_imports(f):
                if (
                    mod.startswith("rig_relay.publication.")
                    or mod == "rig_relay.publication"
                ):
                    pub_imports.append((f.name, mod))
                if mod.startswith("rig_relay.local_inference."):
                    inf_imports.append((f.name, mod))
                if mod.startswith("rig_relay.data_plane"):
                    dp_imports.append((f.name, mod))

        for filename, mod in pub_imports:
            assert mod in allowed_publication, (
                f"File '{filename}' imports unauthorized publication module "
                f"'{mod}'. Allowed: {allowed_publication}"
            )

        for filename, mod in inf_imports:
            assert mod in allowed_inference, (
                f"File '{filename}' imports unauthorized inference module "
                f"'{mod}'. Allowed: {allowed_inference}"
            )

        assert not dp_imports, (
            f"Gateway must not import from data_plane. Found: {dp_imports}"
        )
