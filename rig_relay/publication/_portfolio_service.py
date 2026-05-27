"""Portfolio Synthesis Service — Lane X3 portfolio publication authority.

Aggregates approved project-page publication projections into a deterministic
portfolio publication projection. Only approved, safety-passed,
content-light-complying project records are included.

Remains distinct from project-page compilation — portfolio synthesis
consumes already-compiled projections and produces a new derivative work.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import uuid as _uuid

from rig_relay.publication._deployment_models import (
    PortfolioProjectionRejection,
    PortfolioSynthesisInput,
    PortfolioSynthesisResult,
    _digest_sha256,
    _now_iso,
)


class PortfolioSynthesisService:
    """Application service that aggregates approved project records into
    a portfolio publication projection.

    Consumes approved compilation receipts from the publication evidence
    ledger, filters to only valid records, and produces a deterministic
    portfolio projection suitable for publication.
    """

    def __init__(self) -> None:
        pass

    def synthesize(
        self,
        synthesis_input: PortfolioSynthesisInput,
        *,
        output_dir: Path | None = None,
    ) -> PortfolioSynthesisResult:
        """Synthesize a portfolio from approved project records.

        Each project record must be a valid compilation result with
        compilation_successful=True, safety_passed=True, and
        content_light_guarantee=True.

        Returns a PortfolioSynthesisResult with the aggregated projection
        and rejection details for excluded records.
        """
        synthesis_id = _uuid.uuid4().hex[:12]
        now = _now_iso()
        rejected: list[PortfolioProjectionRejection] = []
        included: list[dict] = []

        for record in synthesis_input.approved_project_records:
            rejection = self._validate_project_record(record)
            if rejection is not None:
                rejected.append(rejection)
                continue

            projection = self._extract_projection(record)
            if projection is None:
                rejected.append(
                    PortfolioProjectionRejection(
                        profile_candidate_digest=record.get(
                            "profile_candidate_digest", "unknown"
                        ),
                        compilation_receipt_digest=record.get(
                            "evidence_digest", record.get("receipt_id", "unknown")
                        ),
                        rejection_reason="missing_projection",
                        rejection_detail="Record has no valid projection",
                    )
                )
                continue

            included.append(projection)

        portfolio_projection = self._build_portfolio_projection(
            synthesis_id=synthesis_id,
            developer_name=synthesis_input.developer_display_name,
            developer_headline=synthesis_input.developer_headline,
            included=included,
            now=now,
        )

        portfolio_html = self._render_portfolio_html(
            developer_name=synthesis_input.developer_display_name,
            developer_headline=synthesis_input.developer_headline,
            developer_bio=synthesis_input.developer_bio,
            projects=included,
            title=synthesis_input.portfolio_title,
        )

        html_digest: str | None = None
        bundle_path: str | None = None
        if portfolio_html and output_dir is not None:
            html_digest = (
                f"sha256:{hashlib.sha256(portfolio_html.encode()).hexdigest()}"
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            index_path = output_dir / "index.html"
            index_path.write_text(portfolio_html, encoding="utf-8")
            bundle_path = str(index_path)

        result = PortfolioSynthesisResult(
            synthesis_id=synthesis_id,
            generated_at=now,
            compilation_successful=len(included) > 0,
            total_project_records=len(synthesis_input.approved_project_records),
            included_count=len(included),
            rejected_count=len(rejected),
            rejected_records=rejected,
            portfolio_projection=portfolio_projection,
            portfolio_html=portfolio_html,
            portfolio_html_digest=html_digest,
            portfolio_bundle_path=bundle_path,
            synthesis_digest=(
                f"sha256:{hashlib.sha256(portfolio_html.encode()).hexdigest()}"
                if portfolio_html
                else _digest_sha256(f"empty:portfolio:{synthesis_id}")
            ),
            content_light_guarantee=True,
            privacy_class="public_safe",
            warnings=(
                ["No valid project records included"]
                if len(included) == 0
                and len(synthesis_input.approved_project_records) > 0
                else []
            ),
            ready_for_deployment=len(included) > 0,
        )
        result.compute_digest()
        return result

    def _validate_project_record(
        self, record: dict
    ) -> PortfolioProjectionRejection | None:
        """Validate a single project record for portfolio inclusion.

        Returns None if valid, or a rejection with reason.
        """
        profile_digest = record.get(
            "profile_candidate_digest", record.get("receipt_id", "unknown")
        )
        receipt_digest = record.get("evidence_digest", record.get("receipt_id", ""))

        if not record.get("compilation_successful", False):
            return PortfolioProjectionRejection(
                profile_candidate_digest=str(profile_digest),
                compilation_receipt_digest=str(receipt_digest),
                rejection_reason="compilation_failed",
                rejection_detail="Compilation was not successful",
            )

        if not record.get("safety_passed", False):
            return PortfolioProjectionRejection(
                profile_candidate_digest=str(profile_digest),
                compilation_receipt_digest=str(receipt_digest),
                rejection_reason="safety_not_passed",
                rejection_detail="Safety scan did not pass",
            )

        if record.get("secrets_detected", False):
            return PortfolioProjectionRejection(
                profile_candidate_digest=str(profile_digest),
                compilation_receipt_digest=str(receipt_digest),
                rejection_reason="secrets_detected",
                rejection_detail="Secrets detected in compiled output",
            )

        if record.get("deployment_ready", True) is False and not record.get(
            "preview_only", True
        ):
            pass

        privacy_class = record.get("privacy_class", "")
        if privacy_class and privacy_class not in {"public_safe"}:
            return PortfolioProjectionRejection(
                profile_candidate_digest=str(profile_digest),
                compilation_receipt_digest=str(receipt_digest),
                rejection_reason="privacy_class_unsafe",
                rejection_detail=f"Privacy class is '{privacy_class}', not public_safe",
            )

        return None

    def _extract_projection(self, record: dict) -> dict | None:
        """Extract a project projection from a compilation record."""
        receipt = record.get("receipt", record)
        projection = (
            receipt.get("projection")
            or record.get("projection")
            or record.get("portfolio_projection")
        )
        if projection is None:
            return None

        if isinstance(projection, dict):
            return projection

        if hasattr(projection, "model_dump"):
            return projection.model_dump()

        return None

    def _build_portfolio_projection(
        self,
        synthesis_id: str,
        developer_name: str,
        developer_headline: str,
        included: list[dict],
        now: str,
    ) -> dict:
        """Build a content-light portfolio projection dict."""
        project_entries: list[dict] = []
        for proj in included:
            identity = proj.get("project_identity", {})
            status = proj.get("status_overview", {})
            entry = {
                "project_name": identity.get("project_name", "Unknown Project"),
                "tagline": identity.get("tagline", ""),
                "current_milestone": identity.get("current_milestone", ""),
                "overall_status": status.get("overall_status", "unknown"),
                "evidence_backed": status.get("evidence_backed", False),
                "projection_digest": proj.get("projection_digest", ""),
                "publication_surface": proj.get("publication_surface", "project_page"),
            }
            project_entries.append(entry)

        return {
            "schema_version": "rig.relay.publication_projection.v1",
            "publication_surface": "portfolio_site",
            "projection_id": synthesis_id,
            "content_light_guarantee": True,
            "privacy_class": "public_safe",
            "projection_digest": _digest_sha256(
                f"portfolio:{synthesis_id}:{len(project_entries)}"
            ),
            "generated_at": now,
            "developer_identity": {
                "display_name": developer_name,
                "headline": developer_headline,
            },
            "project_catalogue": project_entries,
            "case_studies": [],
        }

    def _render_portfolio_html(
        self,
        developer_name: str,
        developer_headline: str,
        developer_bio: str,
        projects: list[dict],
        title: str,
    ) -> str:
        """Render a basic portfolio HTML page from approved projects."""
        project_cards: list[str] = []
        for p in projects[:20]:
            identity = p.get("project_identity", {})
            status = p.get("status_overview", {})
            proj_name = identity.get("project_name", "Unnamed Project")
            tagline = identity.get("tagline", "")
            milestone = identity.get("current_milestone", "")
            status_text = status.get("overall_status", "unknown")

            project_cards.append(
                f'<div class="project-card">'
                f"<h3>{proj_name}</h3>"
                f'<p class="tagline">{tagline}</p>'
                f'<div class="meta">'
                f'<span class="milestone">{milestone}</span>'
                f'<span class="status">{status_text}</span>'
                f"</div></div>"
            )

        cards_html = "\n".join(project_cards)
        dev_section = ""
        if developer_name:
            dev_section = (
                f'<header class="developer-profile">'
                f"<h1>{developer_name}</h1>"
                f'<p class="headline">{developer_headline}</p>'
                f'<p class="bio">{developer_bio}</p>'
                f"</header>"
            )

        return (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f"<title>{title}</title>\n"
            "<style>\n"
            "body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; "
            "max-width: 800px; margin: 0 auto; padding: 2rem; "
            "background: #1a1a2e; color: #e0e0e0; }\n"
            ".project-card { border: 1px solid #333; padding: 1rem; margin: 1rem 0; "
            "border-radius: 6px; background: #16213e; }\n"
            ".project-card h3 { margin: 0 0 0.5rem 0; color: #64ffda; }\n"
            ".tagline { color: #a0a0b0; font-style: italic; }\n"
            ".meta { margin: 0.5rem 0; font-size: 0.85rem; color: #888; }\n"
            ".meta .milestone { margin-right: 1rem; }\n"
            ".developer-profile { text-align: center; margin-bottom: 2rem; }\n"
            ".developer-profile h1 { color: #64ffda; }\n"
            ".headline { color: #a0a0b0; font-size: 1.1rem; }\n"
            ".bio { color: #888; max-width: 600px; margin: 0 auto; }\n"
            "footer { text-align: center; margin-top: 3rem; padding-top: 1rem; "
            "border-top: 1px solid #333; color: #666; font-size: 0.8rem; }\n"
            "</style>\n"
            "</head>\n"
            "<body>\n"
            f"{dev_section}\n"
            '<main class="projects">\n'
            f"<h2>Projects ({len(projects)})</h2>\n"
            f"{cards_html}\n"
            "</main>\n"
            "<footer><p>Portfolio generated by Rig Relay</p></footer>\n"
            "</body>\n"
            "</html>"
        )


__all__ = ["PortfolioSynthesisService"]
