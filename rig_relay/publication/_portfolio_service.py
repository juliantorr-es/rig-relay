"""Portfolio Synthesis Service — Lane X3.1 portfolio publication authority.

X3.1 repairs:
  7. Only verified approved records enter synthesis (not arbitrary dicts)
  8. Safe HTML escaping on all public values
  9. Deterministic output — operation identity separate from content digest
"""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import uuid as _uuid

from rig_relay.publication._deployment_models import (
    PortfolioProjectionRejection,
    PortfolioSynthesisInput,
    PortfolioSynthesisResult,
    VerifiedApprovedProjectPublicationRecord,
    _digest_sha256,
    _now_iso,
)

# ── HTML safety constants ──────────────────────────────────────────────

_FORBIDDEN_PORTFOLIO_PATTERNS: list[tuple[str, str]] = [
    ("script_tag", "<script"),
    ("on_event", "onerror="),
    ("on_event", "onload="),
    ("on_event", "onclick="),
    ("javascript_url", "javascript:"),
    ("iframe", "<iframe"),
    ("object_tag", "<object"),
    ("embed_tag", "<embed"),
]


def _scan_portfolio_html_for_safety(html_content: str) -> list[str]:
    """Scan generated portfolio HTML for injection or unsafe content."""
    findings: list[str] = []
    for label, pattern in _FORBIDDEN_PORTFOLIO_PATTERNS:
        if pattern.lower() in html_content.lower():
            findings.append(f"unsafe_pattern:{label}")
    return findings


class PortfolioSynthesisService:
    """Application service that synthesizes a portfolio from verified approved
    project publication records.

    X3.1 repair #7: only VerifiedApprovedProjectPublicationRecord instances
    may enter synthesis. Arbitrary dicts are rejected.

    X3.1 repair #8: all public values are HTML-escaped before rendering.

    X3.1 repair #9: content_digest is deterministic from inputs only;
    synthesis_id and generated_at are separate operation identity fields.
    """

    def __init__(self) -> None:
        pass

    def synthesize(
        self,
        synthesis_input: PortfolioSynthesisInput,
        *,
        output_dir: Path | None = None,
    ) -> PortfolioSynthesisResult:
        """Synthesize portfolio from verified approved records."""
        synthesis_id = _uuid.uuid4().hex[:12]
        now = _now_iso()
        rejected: list[PortfolioProjectionRejection] = []
        included: list[VerifiedApprovedProjectPublicationRecord] = []

        for record in synthesis_input.verified_records:
            if isinstance(record, VerifiedApprovedProjectPublicationRecord):
                inc, rejection = self._validate_for_portfolio(record)
                if inc:
                    included.append(record)
                elif rejection is not None:
                    rejected.append(rejection)
            elif isinstance(record, dict):
                rejection = self._reject_unverified_dict(record)
                rejected.append(rejection)
            else:
                rejected.append(
                    PortfolioProjectionRejection(
                        profile_candidate_digest="unknown",
                        compilation_receipt_digest="unknown",
                        rejection_reason="unrecognized_record_type",
                        rejection_detail=f"Record type {type(record).__name__} is not VerifiedApprovedProjectPublicationRecord",
                    )
                )

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
            records=included,
            title=synthesis_input.portfolio_title,
        )

        safety_warnings = _scan_portfolio_html_for_safety(portfolio_html)
        safety_passed = len(safety_warnings) == 0

        html_digest: str | None = None
        bundle_path: str | None = None
        if output_dir is not None:
            html_digest = (
                f"sha256:{hashlib.sha256(portfolio_html.encode()).hexdigest()}"
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            index_path = output_dir / "index.html"
            index_path.write_text(portfolio_html, encoding="utf-8")
            bundle_path = str(index_path)

        content_digest = self._compute_content_digest(included)
        compilation_successful = len(included) > 0 and safety_passed

        result = PortfolioSynthesisResult(
            synthesis_id=synthesis_id,
            generated_at=now,
            compilation_successful=compilation_successful,
            total_project_records=len(synthesis_input.verified_records),
            included_count=len(included),
            rejected_count=len(rejected),
            rejected_records=rejected,
            portfolio_projection=portfolio_projection,
            portfolio_html=portfolio_html,
            portfolio_html_digest=html_digest,
            portfolio_bundle_path=bundle_path,
            content_digest=content_digest,
            synthesis_digest=(_digest_sha256(f"synth:{synthesis_id}:{now}")),
            content_light_guarantee=True,
            privacy_class="public_safe",
            safety_passed=safety_passed,
            safety_warnings=safety_warnings,
            warnings=(
                ["No valid project records included"]
                if len(included) == 0 and len(synthesis_input.verified_records) > 0
                else safety_warnings
            ),
            ready_for_deployment=compilation_successful,
        )
        return result

    def _validate_for_portfolio(
        self, record: VerifiedApprovedProjectPublicationRecord
    ) -> tuple[bool, PortfolioProjectionRejection | None]:
        """Validate a verified record for portfolio inclusion.

        Returns (include, rejection_or_None).
        """
        if not record.verified:
            return False, PortfolioProjectionRejection(
                profile_candidate_digest=record.profile_candidate_digest,
                compilation_receipt_digest=record.verification_digest,
                rejection_reason="not_verified",
                rejection_detail="Record is not verified",
            )
        if not record.safety_passed:
            return False, PortfolioProjectionRejection(
                profile_candidate_digest=record.profile_candidate_digest,
                compilation_receipt_digest=record.verification_digest,
                rejection_reason="safety_not_passed",
                rejection_detail="Safety scan did not pass",
            )
        if record.privacy_class not in {"public_safe", "public"}:
            return False, PortfolioProjectionRejection(
                profile_candidate_digest=record.profile_candidate_digest,
                compilation_receipt_digest=record.verification_digest,
                rejection_reason="privacy_class_unsafe",
                rejection_detail=(
                    f"Privacy class is '{record.privacy_class}', not public_safe"
                ),
            )
        if not record.content_light_guarantee:
            return False, PortfolioProjectionRejection(
                profile_candidate_digest=record.profile_candidate_digest,
                compilation_receipt_digest=record.verification_digest,
                rejection_reason="content_light_guarantee_missing",
                rejection_detail="Record does not guarantee content-light compliance",
            )
        return True, None

    def _reject_unverified_dict(self, record: dict) -> PortfolioProjectionRejection:
        profile_digest = record.get("profile_candidate_digest", "unknown")
        receipt_digest = record.get(
            "evidence_digest", record.get("receipt_id", "unknown")
        )
        return PortfolioProjectionRejection(
            profile_candidate_digest=str(profile_digest),
            compilation_receipt_digest=str(receipt_digest),
            rejection_reason="not_verified_record",
            rejection_detail=(
                "Record is a raw dict, not a VerifiedApprovedProjectPublicationRecord. "
                "Portfolio synthesis requires verified records."
            ),
        )

    def _build_portfolio_projection(
        self,
        synthesis_id: str,
        developer_name: str,
        developer_headline: str,
        included: list[VerifiedApprovedProjectPublicationRecord],
        now: str,
    ) -> dict:
        project_entries: list[dict] = []
        for rec in included:
            proj = rec.projection
            identity = proj.get("project_identity", {})
            status = proj.get("status_overview", {})
            entry = {
                "project_name": identity.get("project_name", "Unknown Project"),
                "tagline": identity.get("tagline", ""),
                "current_milestone": identity.get("current_milestone", ""),
                "overall_status": status.get("overall_status", "unknown"),
                "evidence_backed": status.get("evidence_backed", False),
                "projection_digest": rec.projection_digest,
                "publication_surface": proj.get("publication_surface", "project_page"),
                "preview_evidence_digest": rec.preview_evidence_digest,
                "approval_evidence_digest": rec.approval_evidence_digest,
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
                "display_name": html.escape(developer_name),
                "headline": html.escape(developer_headline),
            },
            "project_catalogue": project_entries,
            "case_studies": [],
        }

    def _render_portfolio_html(
        self,
        developer_name: str,
        developer_headline: str,
        developer_bio: str,
        records: list[VerifiedApprovedProjectPublicationRecord],
        title: str,
    ) -> str:
        """X3.1 repair #8: all user-provided values are HTML-escaped."""
        project_cards: list[str] = []
        for rec in records[:20]:
            proj = rec.projection
            identity = proj.get("project_identity", {})
            status = proj.get("status_overview", {})
            proj_name = html.escape(identity.get("project_name", "Unnamed Project"))
            tagline = html.escape(identity.get("tagline", ""))
            milestone = html.escape(identity.get("current_milestone", ""))
            status_text = html.escape(status.get("overall_status", "unknown"))

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
                '<header class="developer-profile">'
                f"<h1>{html.escape(developer_name)}</h1>"
                f'<p class="headline">{html.escape(developer_headline)}</p>'
                f'<p class="bio">{html.escape(developer_bio)}</p>'
                "</header>"
            )

        escaped_title = html.escape(title)

        return (
            "<!DOCTYPE html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f"<title>{escaped_title}</title>\n"
            "<style>\n"
            "body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; "
            "max-width: 800px; margin: 0 auto; padding: 2rem; "
            "background: #1a1a2e; color: #e0e0e0; }\n"
            ".project-card { border: 1px solid #333; padding: 1rem; margin: 1rem 0; "
            "border-radius: 6px; background: #16213e; }\n"
            ".project-card h3 { margin: 0 0 0.5rem 0; color: #64ffda; }\n"
            ".tagline { color: #a0a0b0; font-style: italic; }\n"
            ".meta { margin: 0.5rem 0; font-size: 0.85rem; color: #888; }\n"
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
            f"<h2>Projects ({len(records)})</h2>\n"
            f"{cards_html}\n"
            "</main>\n"
            "<footer><p>Portfolio generated by Rig Relay</p></footer>\n"
            "</body>\n"
            "</html>"
        )

    def _compute_content_digest(
        self, records: list[VerifiedApprovedProjectPublicationRecord]
    ) -> str:
        """X3.1 repair #9: deterministic content digest from inputs only."""
        parts = sorted(
            r.projection_digest or r.profile_candidate_digest for r in records
        )
        raw = json.dumps(parts, sort_keys=True)
        return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


__all__ = ["PortfolioSynthesisService"]
