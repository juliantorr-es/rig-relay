from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import jinja2

from rig_relay.publication._models import (
    ProjectPageCompilerInput,
    ProjectPageCompilerResult,
    ProjectPagePreviewReport,
    ProjectPagePublicationProjection,
    _digest_sha256,
    _now_iso,
)
from rig_relay.publication._preview import build_preview_report
from rig_relay.publication._safety import (
    redact_unsafe_text,
    scan_project_page_output,
    validate_publication_policy,
)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_ASSETS_DIR = Path(__file__).parent / "assets"
_PUBLICATION_PROJECTION_SCHEMA = "rig.relay.publication_projection.v1"

_PUBLIC_SAFE_SECTION_KEYS = frozenset({
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
})


class ProjectPagePublicationCompiler:
    """Typed compiler that produces a public-safe per-repository project page.

    Accepts an L0-shaped PublishableProjectProfileCandidate plus J0-shaped
    publication readiness state. Produces a publication projection, static
    HTML preview bundle, and preview report.

    Does NOT deploy to GitHub Pages — that requires separate authority.
    """

    def __init__(self) -> None:
        self._jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def compile(
        self,
        compiler_input: ProjectPageCompilerInput,
        *,
        output_dir: Path | None = None,
        validate_schema: bool = False,
    ) -> ProjectPageCompilerResult:
        """Compile a public-safe project page from the given input.

        Args:
            compiler_input: Typed input with profile candidate, readiness, action, and policy.
            output_dir: Where to write the static preview bundle. If None, only
                        projection + report are produced (no static files written).
            validate_schema: Whether to validate against the publication projection schema
                            (requires jsonschema package).

        Returns:
            ProjectPageCompilerResult with projection, preview report, safety report,
            and optional static bundle path.
        """
        now = _now_iso()
        warnings: list[str] = []
        schema_validation_passed = True

        if not validate_publication_policy(compiler_input.publication_policy):
            warnings.append(
                f"Unrecognized publication policy: {compiler_input.publication_policy}"
            )

        projection = self._build_projection(compiler_input, now)

        if validate_schema:
            schema_validation_passed = self._validate_projection_schema(projection)
            if not schema_validation_passed:
                warnings.append("Projection failed schema validation")

        preview_report = build_preview_report(
            projection=projection.model_dump(),
            compiler_input=compiler_input.model_dump(),
            safety_passed=True,
            schema_validation_passed=schema_validation_passed,
        )

        static_bundle_path: str | None = None
        static_bundle_digest: str | None = None
        html_content = ""

        if output_dir is not None:
            static_bundle_path = str(output_dir.resolve())
            html_content = self._render_static_bundle(
                projection=projection,
                preview_report=preview_report,
                compiler_input=compiler_input,
                output_dir=output_dir,
            )
            static_bundle_digest = _digest_sha256(html_content)

        safety_report = scan_project_page_output(
            html_content=html_content,
            projection=projection.model_dump(),
            preview_report=preview_report.model_dump(),
        )

        if not safety_report.passed:
            warnings.append("Safety scan failed")

        compilation_successful = safety_report.passed
        deployment_ready = (
            compilation_successful
            and preview_report.ready_for_deployment
            and compiler_input.publication_policy != "preview_only"
        )

        result = ProjectPageCompilerResult(
            result_id=_digest_sha256(f"result:{now}")[:22],
            compiler_digest=_compile_digest(projection),
            generated_at=now,
            projection=projection,
            static_bundle_path=static_bundle_path,
            static_bundle_digest=static_bundle_digest,
            preview_report=preview_report,
            safety_report=safety_report,
            compilation_successful=compilation_successful,
            deployment_ready=deployment_ready,
            warnings=warnings,
        )

        return result

    def compile_projection_only(
        self, compiler_input: ProjectPageCompilerInput
    ) -> ProjectPagePublicationProjection:
        """Build only the publication projection, without rendering static output."""
        return self._build_projection(compiler_input, _now_iso())

    def _build_projection(
        self, compiler_input: ProjectPageCompilerInput, now: str
    ) -> ProjectPagePublicationProjection:
        profile = compiler_input.profile_candidate
        candidate_id = str(profile.get("candidate_id", "unknown"))
        project_name = str(profile.get("project_identity", {}).get("project_name", ""))
        projection_id = _digest_sha256(f"{candidate_id}:{project_name}")[:30]

        arch_overview: dict = {}
        raw_arch = profile.get("architecture_overview")
        if isinstance(raw_arch, dict):
            for k, v in raw_arch.items():
                arch_overview[str(k)] = redact_unsafe_text(str(v))

        generated_sections = _extract_generated_sections(
            profile, compiler_input.narrative_approvals
        )

        projection = ProjectPagePublicationProjection(
            projection_id=projection_id,
            projection_digest="",
            generated_at=now,
            project_identity=_extract_project_identity(profile),
            status_overview=_extract_status_overview(profile),
            accomplishments=_extract_accomplishments(profile),
            released_boundaries=_extract_released_boundaries(profile),
            mission_timeline=_extract_mission_timeline(profile),
            architecture_overview=arch_overview,
            capability_views=_build_capability_views(profile),
            audit_proofs=_extract_audit_proofs(profile),
            changelog=_extract_changelog(profile),
            screenshots_demos=_extract_screenshots(profile),
        )
        projection.projection_digest = projection.compute_digest()

        self._template_extras = {
            "redaction_log": profile.get("redaction_log", {}),
            "generated_narrative_sections": generated_sections,
            "structural_facts_public": profile.get("structural_facts_public", []),
            "technology_capabilities": profile.get("technology_capabilities", {}),
            "approval_status": profile.get(
                "approval_status", "pending_developer_review"
            ),
        }
        return projection

    def _render_static_bundle(
        self,
        projection: ProjectPagePublicationProjection,
        preview_report: ProjectPagePreviewReport,
        compiler_input: ProjectPageCompilerInput,
        output_dir: Path,
    ) -> str:
        output_dir.mkdir(parents=True, exist_ok=True)

        template = self._jinja_env.get_template("project_page.html.j2")

        extras = getattr(self, "_template_extras", {})
        projection_dict = projection.model_dump()
        projection_dict.update(extras)

        html = template.render(
            projection=projection_dict,
            preview_report=preview_report.model_dump(),
            publication_policy=compiler_input.publication_policy,
            is_preview=compiler_input.publication_policy == "preview_only",
            proposed_content_sections=preview_report.proposed_content.sections,
            publication_readiness=preview_report.publication_readiness,
            repo_owner=compiler_input.project_repo_owner,
            repo_name=compiler_input.project_repo_name,
        )

        index_path = output_dir / "index.html"
        index_path.write_text(html, encoding="utf-8")

        nojekyll_path = output_dir / ".nojekyll"
        nojekyll_path.write_text("")

        css_src = _ASSETS_DIR / "project_page.css"
        if css_src.exists():
            css_dest = output_dir / "project_page.css"
            shutil.copy2(css_src, css_dest)

        return html

    def _validate_projection_schema(
        self, projection: ProjectPagePublicationProjection
    ) -> bool:
        try:
            import jsonschema

            schema_path = (
                Path(__file__).parent.parent.parent
                / "docs"
                / "schemas"
                / "rig.relay.publication_projection.v1.schema.json"
            )
            if not schema_path.exists():
                return True
            schema_data = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(instance=projection.model_dump(), schema=schema_data)
            return True
        except Exception:
            return False


def _compile_digest(projection: ProjectPagePublicationProjection) -> str:
    raw = f"{projection.projection_id}:{projection.projection_digest}"
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def _extract_project_identity(profile: dict) -> dict:
    identity = profile.get("project_identity", {})
    if not isinstance(identity, dict):
        identity = {}
    return {
        "project_name": str(identity.get("project_name", "")),
        "tagline": str(identity.get("tagline", "")),
        "current_milestone": str(identity.get("current_milestone", "")),
        "product_identity_blurb": str(identity.get("product_identity_blurb", "")),
    }


def _extract_status_overview(profile: dict) -> dict:
    status = profile.get("status_overview", {})
    if not isinstance(status, dict):
        status = {}
    return {
        "implemented_count": int(status.get("implemented_count", 0)),
        "planned_count": int(status.get("planned_count", 0)),
        "overall_status": str(status.get("overall_status", "unknown")),
        "evidence_backed": bool(status.get("evidence_backed", False)),
    }


def _extract_accomplishments(profile: dict) -> dict:
    acc = profile.get("accomplishments", {})
    if not isinstance(acc, dict):
        acc = {}
    raw_items = acc.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []
    safe_items: list[dict] = []
    for item in raw_items:
        if isinstance(item, dict):
            safe_items.append({
                "title": str(item.get("title", "")),
                "receipt_ref": str(item.get("receipt_ref", "")),
            })
    return {
        "get_item_list": safe_items,
        "get_total_receipts": int(acc.get("total_receipts_referenced", 0)),
    }


def _extract_released_boundaries(profile: dict) -> dict:
    boundaries = profile.get("released_boundaries", [])
    if not isinstance(boundaries, list):
        boundaries = []
    safe: list[dict] = []
    for b in boundaries:
        if isinstance(b, dict):
            safe.append({
                "boundary_name": str(b.get("boundary_name", "")),
                "release_status": str(b.get("release_status", "planned")),
                "consuming_surfaces": (
                    list(b.get("consuming_surfaces", []))
                    if isinstance(b.get("consuming_surfaces"), list)
                    else []
                ),
            })
    return {"get_boundary_list": safe}


def _extract_mission_timeline(profile: dict) -> dict:
    entries = profile.get("mission_timeline", [])
    if not isinstance(entries, list):
        entries = []
    safe: list[dict] = []
    for e in entries:
        if isinstance(e, dict):
            completed = e.get("completed_at")
            safe.append({
                "mission_id": str(e.get("mission_id", "")),
                "title": str(e.get("title", "")),
                "status": str(e.get("status", "planned")),
                "completed_at": str(completed) if completed else None,
            })
    return {"get_entry_list": safe}


def _extract_audit_proofs(profile: dict) -> list[str]:
    proofs: list[str] = []
    for key in ("audit_proofs", "candidate_id"):
        val = profile.get(key)
        if isinstance(val, str) and val:
            proofs.append(val)
    return proofs[:20]


def _extract_changelog(profile: dict) -> list[dict]:
    return []


def _extract_screenshots(profile: dict) -> list[str]:
    assets = profile.get("publication_assets", {})
    if not isinstance(assets, dict):
        assets = {}
    refs: list[str] = []
    for key in ("screenshot_count", "demo_count"):
        val = assets.get(key)
        if isinstance(val, int) and val > 0:
            refs.append(f"{key}:{val}")
    return refs


def _extract_generated_sections(
    profile: dict, narrative_approvals: dict[str, str]
) -> dict[str, dict]:
    sections = profile.get("generated_narrative_sections", {})
    if not isinstance(sections, dict):
        sections = {}
    safe: dict[str, dict] = {}
    for key, data in sections.items():
        if not isinstance(data, dict):
            continue
        narrative = str(data.get("narrative", ""))
        approval = narrative_approvals.get(key, "proposed")
        safe[key] = {
            "narrative": redact_unsafe_text(narrative),
            "approval_status": approval,
            "basis_fact_ids": (
                list(data.get("basis_fact_ids", []))
                if isinstance(data.get("basis_fact_ids"), list)
                else []
            ),
        }
    return safe


def _build_capability_views(profile: dict) -> dict:
    tech = profile.get("technology_capabilities", {})
    if not isinstance(tech, dict):
        tech = {}
    return {
        "languages": tech.get("languages", []),
        "frameworks": tech.get("frameworks", []),
        "test_frameworks": tech.get("test_frameworks", []),
        "build_systems": tech.get("build_systems", []),
        "protocols": tech.get("protocols", []),
    }
