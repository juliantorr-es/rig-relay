"""Council — structured multi-provider consultation with receipts.

Council lets the user send a bounded mission packet to one or more
external AI providers, collect their critiques, and convert those
critiques into receipt-backed findings before any agent mutates the
worktree.

Architecture:
  MissionContextPacket -> ConsultationRequest -> ProviderSession
  -> ProviderTranscript -> NormalizedConsultation -> ConsultationReceipt
  -> AdjudicationNote

Content-light: packets, transcripts, and findings are hashed. Raw
provider output is never logged to telemetry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ═══ Schemas ═══════════════════════════════════════════════════════════

_SCHEMA_CONSULTATION_REQUEST = "rig.relay.council.consultation_request.v1"
_SCHEMA_NORMALIZED_CONSULTATION = "rig.relay.council.normalized_consultation.v1"
_SCHEMA_CONSULTATION_RECEIPT = "rig.relay.council.consultation_receipt.v1"
_SCHEMA_ADJUDICATION_NOTE = "rig.relay.council.adjudication_note.v1"
_SCHEMA_PROVIDER_OPINION = "rig.relay.council.provider_opinion.v1"


class RedactionMode(StrEnum):
    """How much context to include in a consultation packet."""

    MINIMAL = "minimal"    # task, error, path hashes only
    STANDARD = "standard"  # mission brief, relevant files, receipts
    FULL = "full"          # complete context packet
    PARANOID = "paranoid"  # symbols + summaries only, no source bodies


class ProviderSurface(StrEnum):
    """How the consultation was conducted."""

    BROWSER = "browser"        # pywebview companion window via JS bridge
    API = "api"                # provider API
    MANUAL_PASTE = "manual_paste"  # user copy-pasted


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingKind(StrEnum):
    RISK = "risk"
    BLOCKER = "blocker"
    ASSUMPTION = "assumption"
    RECOMMENDATION = "recommendation"
    DO_NOT_DO = "do_not_do"
    FILE_TO_INSPECT = "file_or_symbol_to_inspect"


# ═══ Models ════════════════════════════════════════════════════════════


class ConsultationRequest(BaseModel):
    """A request to consult one or more providers about a mission packet.

    Content-light: mission context is referenced by SHA256, not embedded.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_CONSULTATION_REQUEST
    request_id: str
    mission_id: str
    packet_sha256: str
    question: str
    providers: list[str]  # chatgpt, claude, gemini, etc.
    redaction_mode: RedactionMode = RedactionMode.STANDARD
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    user_initiated: bool = True
    direct_repo_write_allowed: bool = False


class ProviderOpinion(BaseModel):
    """Normalized structured opinion from a single provider.

    Every provider is asked the same disciplined questions. This lets
    Rig compare answers and render a Consensus / Disagreement view.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_PROVIDER_OPINION
    provider: str
    model_label: str = ""  # user-visible model name from the provider's UI
    mission_id: str
    question: str
    assumptions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommended_next_slice: list[str] = Field(default_factory=list)
    files_or_symbols_to_inspect: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.MEDIUM
    do_not_do: list[str] = Field(default_factory=list)
    raw_transcript_sha256: str = ""


class NormalizedConsultation(BaseModel):
    """A single provider's consultation, normalized for comparison.

    Contains both the structured opinion and the raw transcript hash.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_NORMALIZED_CONSULTATION
    consultation_id: str
    request_id: str
    provider: str
    provider_surface: ProviderSurface = ProviderSurface.BROWSER
    submitted_at: str = ""
    returned_at: str = ""
    transcript_sha256: str = ""
    attachments_sha256: list[str] = Field(default_factory=list)
    normalized_findings_sha256: str = ""
    opinion: ProviderOpinion | None = None
    user_initiated: bool = True
    direct_repo_write_allowed: bool = False


class ConsultationReceipt(BaseModel):
    """Receipt-backed artifact recording a completed consultation.

    Content-light: contains hashes and summaries, not raw transcripts.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_CONSULTATION_RECEIPT
    receipt_id: str
    request_id: str
    consultations: list[NormalizedConsultation] = Field(default_factory=list)
    provider_count: int = 0
    consensus_findings: list[str] = Field(default_factory=list)
    disagreement_findings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class AdjudicationNote(BaseModel):
    """The orchestrator's decision after reviewing council findings.

    Converts provider opinions into actionable work items or refusals.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_ADJUDICATION_NOTE
    adjudication_id: str
    receipt_id: str
    decision: Literal["proceed", "revise", "block", "delegate"]
    rationale: str
    action_items: list[str] = Field(default_factory=list)
    deferred_findings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


# ═══ Council Engine ════════════════════════════════════════════════════


class Council:
    """Governed multi-provider consultation engine.

    The Council sends bounded mission packets to external providers,
    collects structured opinions, normalizes them for comparison, and
    produces receipt-backed findings. No provider ever gets direct
    repo mutation authority.

    Usage:
        council = Council(provider_bridge)
        request = council.create_request(mission_id, packet_hash, question, providers)
        receipt = await council.consult(request)
        note = council.adjudicate(receipt, decision="proceed", rationale="...")
    """

    def __init__(self, provider_bridge: Any) -> None:
        self._bridge = provider_bridge

    def create_request(
        self,
        mission_id: str,
        packet_sha256: str,
        question: str,
        providers: list[str],
        redaction_mode: RedactionMode = RedactionMode.STANDARD,
    ) -> ConsultationRequest:
        return ConsultationRequest(
            request_id=f"council-{datetime.now(UTC).timestamp():.0f}",
            mission_id=mission_id,
            packet_sha256=packet_sha256,
            question=question,
            providers=providers,
            redaction_mode=redaction_mode,
        )

    async def consult(
        self, request: ConsultationRequest
    ) -> ConsultationReceipt:
        consultations: list[NormalizedConsultation] = []
        for provider in request.providers:
            nc = await self._consult_one(request, provider)
            consultations.append(nc)

        return self._build_receipt(request, consultations)

    async def _consult_one(
        self, request: ConsultationRequest, provider: str
    ) -> NormalizedConsultation:
        submitted_at = datetime.now(UTC).isoformat()

        prompt = self._build_consult_prompt(request)
        result = await self._bridge.send_and_read(provider, prompt)

        returned_at = datetime.now(UTC).isoformat()

        return NormalizedConsultation(
            consultation_id=f"{request.request_id}-{provider}",
            request_id=request.request_id,
            provider=provider,
            provider_surface=ProviderSurface.BROWSER,
            submitted_at=submitted_at,
            returned_at=returned_at,
            transcript_sha256=result.get("transcript_sha256", ""),
        )

    @staticmethod
    def _build_consult_prompt(request: ConsultationRequest) -> str:
        lines = [
            "You are an external reviewer for a coding agent mission.",
            "Your output will be compared against other providers.",
            "Answer each section concisely. Do not write code.",
            "",
            f"Mission ID: {request.mission_id}",
            f"Question: {request.question}",
            "",
            "Respond in this exact format:",
            "ASSUMPTIONS:",
            "- (list assumptions you are making)",
            "BLOCKERS:",
            "- (list blockers that would prevent this mission from succeeding)",
            "RISKS:",
            "- (list architectural, security, or process risks)",
            "RECOMMENDED_NEXT_SLICE:",
            "- (list the next concrete step)",
            "FILES_TO_INSPECT:",
            "- (list files or symbols worth inspecting)",
            "CONFIDENCE: low|medium|high",
            "DO_NOT_DO:",
            "- (list things that should absolutely NOT be done)",
        ]
        return "\n".join(lines)

    @staticmethod
    def _build_receipt(
        request: ConsultationRequest, consultations: list[NormalizedConsultation]
    ) -> ConsultationReceipt:
        return ConsultationReceipt(
            receipt_id=f"receipt-{request.request_id}",
            request_id=request.request_id,
            consultations=consultations,
            provider_count=len(consultations),
        )

    @staticmethod
    def adjudicate(
        receipt: ConsultationReceipt,
        *,
        decision: Literal["proceed", "revise", "block", "delegate"],
        rationale: str,
        action_items: list[str] | None = None,
    ) -> AdjudicationNote:
        return AdjudicationNote(
            adjudication_id=f"adj-{receipt.receipt_id}",
            receipt_id=receipt.receipt_id,
            decision=decision,
            rationale=rationale,
            action_items=action_items or [],
        )


__all__ = [
    "AdjudicationNote",
    "Confidence",
    "ConsultationReceipt",
    "ConsultationRequest",
    "Council",
    "FindingKind",
    "NormalizedConsultation",
    "ProviderOpinion",
    "ProviderSurface",
    "RedactionMode",
]
