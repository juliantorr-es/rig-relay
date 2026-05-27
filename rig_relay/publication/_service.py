from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import uuid as _uuid

from rig_relay.publication._evidence_ledger import PublicationEvidenceLedger
from rig_relay.publication._models import (
    PreviewEvidenceReceipt,
    PreviewRefusalCode,
    ProjectPageCompilerResult,
    ProjectPagePreviewReport,
    ProjectPagePublicationProjection,
    PublicationPreviewRefusal,
    PublicationPreviewResult,
    PublicationSafetyReport,
    _digest_sha256,
    _now_iso,
)
from rig_relay.publication.project_page_compiler import ProjectPagePublicationCompiler

if TYPE_CHECKING:
    pass

_VALID_PUBLICATION_POLICIES: frozenset[str] = frozenset({
    "preview_only",
    "developer_approved",
    "public_release",
})

_VALID_APPROVAL_STATUSES: frozenset[str] = frozenset({
    "proposed",
    "pending_review",
    "approved",
    "rejected",
    "superseded",
})

_SAFE_PRIVACY_CLASSES: frozenset[str] = frozenset({"public_safe"})

_UNSAFE_APPROVAL_STATUSES: frozenset[str] = frozenset({"rejected"})


class ProjectPagePublicationPreviewService:
    """Application-service boundary for project-page publication preview.

    Consumes live L0 PublishableProjectProfileCandidate and J0
    PublicationReadiness/PagesActionPreparation typed model instances.
    Validates inputs, compiles a public-safe preview, and returns a
    structured result with canonical evidence.

    Does NOT deploy to GitHub Pages. Does NOT mutate GitHub state.
    Does NOT bypass developer approval. Strictly preview-only.
    """

    def __init__(self, ledger: PublicationEvidenceLedger | None = None) -> None:
        self._compiler = ProjectPagePublicationCompiler()
        self._ledger = ledger or PublicationEvidenceLedger()

    def compile_preview(
        self,
        profile: object,
        *,
        readiness: object | None = None,
        pages_action: object | None = None,
        narrative_approvals: dict[str, str] | None = None,
        publication_policy: str = "preview_only",
        repo_owner: str = "",
        repo_name: str = "",
        output_dir: Path | None = None,
        validate_schema: bool = False,
        operation_id: str | None = None,
    ) -> PublicationPreviewResult:
        """Compile a publication preview from live producer-compatible input.

        Args:
            profile: L0 PublishableProjectProfileCandidate instance.
            readiness: J0 PublicationReadiness instance (optional).
            pages_action: J0 PagesActionPreparation instance (optional).
            narrative_approvals: Map of narrative section key → approval status.
            publication_policy: preview_only, developer_approved, or public_release.
            repo_owner: Repository owner for URL construction.
            repo_name: Repository name for URL construction.
            output_dir: Where to write static preview bundle.
            validate_schema: Whether to validate against publication schema.
            operation_id: Caller-supplied operation identity for exactly-once
                semantics. A retry of a prior request uses the same operation_id.
                A distinct user action uses a new operation_id. If not provided,
                a fresh UUID v4 is generated.

        Returns:
            PublicationPreviewResult with compiler output and evidence,
            or a refusal if input validation fails.
        """
        op_id = operation_id or _uuid.uuid4().hex
        refusal = self._validate_inputs(
            profile=profile,
            readiness=readiness,
            pages_action=pages_action,
            narrative_approvals=narrative_approvals or {},
            publication_policy=publication_policy,
        )
        if refusal is not None:
            receipt = refusal.receipt or PreviewEvidenceReceipt(
                receipt_id=_digest_sha256(f"refusal:{_now_iso()}")[:22],
                compiled_at=_now_iso(),
                compilation_successful=False,
                profile_candidate_digest=_profile_digest(profile),
                refusal_code=refusal.refusal_code.value,
                refusal_reasons=refusal.reasons,
            )
            receipt.evidence_digest = receipt.compute_digest()
            self._ledger.append_event(op_id, receipt.model_dump())
            return PublicationPreviewResult(
                compiler_result=self._empty_result(),
                receipt=receipt,
                refused=refusal.refusal_code,
            )

        from rig_relay.publication._models import ProjectPageCompilerInput

        approvals = narrative_approvals or {}
        for k, v in approvals.items():
            if v not in _VALID_APPROVAL_STATUSES:
                approvals[k] = "proposed"

        profile_dict = getattr(profile, "model_dump", lambda: {})()
        readiness_dict = (
            getattr(readiness, "model_dump", lambda: {})() if readiness else None
        )
        pages_action_dict = (
            getattr(pages_action, "model_dump", lambda: {})() if pages_action else None
        )

        compiler_input = ProjectPageCompilerInput(
            profile_candidate=profile_dict,
            publication_readiness=readiness_dict,
            pages_action=pages_action_dict,
            narrative_approvals=approvals,
            publication_policy=publication_policy,
            project_repo_owner=repo_owner,
            project_repo_name=repo_name,
        )

        compiler_result = self._compiler.compile(
            compiler_input, output_dir=output_dir, validate_schema=validate_schema
        )

        receipt = PreviewEvidenceReceipt(
            receipt_id=_digest_sha256(f"preview:{compiler_result.result_id}")[:22],
            compiled_at=compiler_result.generated_at,
            compilation_successful=compiler_result.compilation_successful,
            profile_candidate_digest=_profile_digest(profile),
            result_digest=compiler_result.compute_result_digest(),
            safety_passed=compiler_result.safety_report.passed,
            deployment_ready=False,
            preview_only=True,
        )
        receipt.evidence_digest = receipt.compute_digest()

        refused = None
        if not compiler_result.compilation_successful:
            refused = PreviewRefusalCode.SAFETY_SCAN_FAILED
            receipt.refusal_code = refused.value
            receipt.refusal_reasons = compiler_result.warnings
            receipt.evidence_digest = receipt.compute_digest()

        self._ledger.append_event(op_id, receipt.model_dump())

        return PublicationPreviewResult(
            compiler_result=compiler_result, receipt=receipt, refused=refused
        )

    def _validate_inputs(
        self,
        profile: object,
        readiness: object | None,
        pages_action: object | None,
        narrative_approvals: dict[str, str],
        publication_policy: str,
    ) -> PublicationPreviewRefusal | None:
        """Validate all inputs. Returns None if valid, refusal if invalid."""
        if profile is None:
            return PublicationPreviewRefusal(
                refusal_code=PreviewRefusalCode.PROFILE_ABSENT,
                reasons=["No PublishableProjectProfileCandidate provided"],
            )

        schema_version = getattr(profile, "schema_version", "")
        if (
            not isinstance(schema_version, str)
            or "publishable_project_profile" not in schema_version
        ):
            return PublicationPreviewRefusal(
                refusal_code=PreviewRefusalCode.SCHEMA_MISMATCH,
                reasons=[
                    f"Expected publishable_project_profile_candidate schema, got: {schema_version}"
                ],
            )

        privacy_class = getattr(profile, "privacy_class", "")
        privacy_value = getattr(privacy_class, "value", str(privacy_class))
        if privacy_value not in _SAFE_PRIVACY_CLASSES:
            return PublicationPreviewRefusal(
                refusal_code=PreviewRefusalCode.PRIVACY_CLASS_UNSAFE,
                reasons=[
                    f"Profile privacy_class must be 'public_safe', got: {privacy_value}"
                ],
            )

        content_light = getattr(profile, "content_light_guarantee", False)
        if not content_light:
            return PublicationPreviewRefusal(
                refusal_code=PreviewRefusalCode.CONTENT_LIGHT_GUARANTEE_MISSING,
                reasons=["Profile must guarantee content-light compliance"],
            )

        approval_status = getattr(profile, "approval_status", "")
        approval_value = getattr(approval_status, "value", str(approval_status))
        if approval_value in _UNSAFE_APPROVAL_STATUSES:
            return PublicationPreviewRefusal(
                refusal_code=PreviewRefusalCode.APPROVAL_NOT_GRANTED,
                reasons=[
                    f"Profile approval status is '{approval_value}'. "
                    "Only proposed, pending_review, or approved profiles may be previewed."
                ],
            )

        candidate_id = getattr(profile, "candidate_id", "")
        if not candidate_id:
            return PublicationPreviewRefusal(
                refusal_code=PreviewRefusalCode.PROFILE_INVALID,
                reasons=["Profile missing required candidate_id"],
            )

        project_identity = getattr(profile, "project_identity", None)
        if project_identity is None:
            return PublicationPreviewRefusal(
                refusal_code=PreviewRefusalCode.PROFILE_INVALID,
                reasons=["Profile missing required project_identity"],
            )

        project_name = getattr(project_identity, "project_name", "")
        if not project_name:
            return PublicationPreviewRefusal(
                refusal_code=PreviewRefusalCode.PROFILE_INVALID,
                reasons=["Profile project_identity missing required project_name"],
            )

        if publication_policy not in _VALID_PUBLICATION_POLICIES:
            return PublicationPreviewRefusal(
                refusal_code=PreviewRefusalCode.POLICY_UNRECOGNIZED,
                reasons=[
                    f"Unrecognized publication policy: {publication_policy}. "
                    f"Must be one of: {', '.join(sorted(_VALID_PUBLICATION_POLICIES))}"
                ],
            )

        for key, val in narrative_approvals.items():
            if val not in _VALID_APPROVAL_STATUSES:
                return PublicationPreviewRefusal(
                    refusal_code=PreviewRefusalCode.PROFILE_INVALID,
                    reasons=[
                        f"Narrative approval for '{key}' has invalid status: {val}. "
                        f"Must be one of: {', '.join(sorted(_VALID_APPROVAL_STATUSES))}"
                    ],
                )

        return None

    def _empty_result(self) -> ProjectPageCompilerResult:
        now = _now_iso()
        return ProjectPageCompilerResult(
            result_id=_digest_sha256(f"empty:{now}")[:22],
            compiler_digest=_digest_sha256(f"empty_compiler:{now}"),
            generated_at=now,
            projection=ProjectPagePublicationProjection(
                projection_id="refused",
                projection_digest="sha256:empty",
                generated_at=now,
                project_identity={"project_name": ""},
                status_overview={
                    "implemented_count": 0,
                    "planned_count": 0,
                    "overall_status": "refused",
                },
                accomplishments={},
                released_boundaries={},
                mission_timeline={},
            ),
            preview_report=ProjectPagePreviewReport(
                report_id="refused", projection_id="refused", generated_at=now
            ),
            safety_report=PublicationSafetyReport(
                passed=False,
                scan_id=_digest_sha256(f"empty_scan:{now}")[:22],
                scanned_at=now,
            ),
            compilation_successful=False,
            warnings=["Compilation refused: input validation failed"],
        )


def _profile_digest(profile: object) -> str:
    digest = getattr(profile, "candidate_digest", "")
    if digest:
        return str(digest)
    compute = getattr(profile, "compute_digest", None)
    if callable(compute):
        result = compute()
        if result:
            return str(result)
    candidate_id = getattr(profile, "candidate_id", "unknown")
    return _digest_sha256(f"profile:{candidate_id}")
