"""Council invoker — wires multi-provider consultation into AgentLoop turns.

Content-light: tool args and provider responses are SHA256-hashed,
never stored raw. No raw provider output is logged to telemetry.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from rig_relay.coordination.council import (
    Confidence,
    ConsultationReceipt,
    ConsultationRequest,
    Council,
    NormalizedConsultation,
    ProviderOpinion,
    ProviderSurface,
    RedactionMode,
)
from rig_relay.core.llm.backend.generic import GenericBackend
from rig_relay.core.logger import logger
from rig_relay.core.types import LLMMessage, Role


async def consult_council_before_mutation(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    context_summary: str,
    providers: list[str] | None = None,
    redaction: str = "standard",
) -> ConsultationReceipt:
    """Consult council providers before executing a mutation tool.

    Content-light: tool_args are SHA256-hashed before being stored.
    Returns a ConsultationReceipt summarizing all provider opinions.
    """
    args_sha256 = hashlib.sha256(
        json.dumps(tool_args, sort_keys=True, default=str).encode()
    ).hexdigest()

    redaction_mode = RedactionMode(redaction) if redaction else RedactionMode.STANDARD
    mission_id = f"mutation-{datetime.now(UTC).timestamp():.0f}"
    question = (
        f"Review proposed mutation tool call: {tool_name}\n"
        f"Args SHA256: {args_sha256}\n"
        f"Context: {context_summary}"
    )

    council = Council(provider_bridge=None)
    request = council.create_request(
        mission_id=mission_id,
        packet_sha256=args_sha256,
        question=question,
        providers=providers or [],
        redaction_mode=redaction_mode,
    )

    if not request.providers:
        return council._build_receipt(request, [])

    consultations: list[NormalizedConsultation] = []
    for provider_name in request.providers:
        nc = await _consult_one_provider(request, provider_name)
        consultations.append(nc)

    return council._build_receipt(request, consultations)


async def _consult_one_provider(
    request: ConsultationRequest, provider_name: str
) -> NormalizedConsultation:
    submitted_at = datetime.now(UTC).isoformat()
    prompt = Council._build_consult_prompt(request)

    provider_config = _find_provider_config(provider_name)
    if provider_config is None:
        return NormalizedConsultation(
            consultation_id=f"{request.request_id}-{provider_name}",
            request_id=request.request_id,
            provider=provider_name,
            provider_surface=ProviderSurface.API,
            submitted_at=submitted_at,
            returned_at=datetime.now(UTC).isoformat(),
            transcript_sha256=hashlib.sha256(b"provider_not_configured").hexdigest(),
        )

    model_config = _find_model_for_provider(provider_config)
    if model_config is None:
        logger.warning(
            "No model configured for provider %s, skipping council consult",
            provider_name,
        )
        return NormalizedConsultation(
            consultation_id=f"{request.request_id}-{provider_name}",
            request_id=request.request_id,
            provider=provider_name,
            provider_surface=ProviderSurface.API,
            submitted_at=submitted_at,
            returned_at=datetime.now(UTC).isoformat(),
            transcript_sha256=hashlib.sha256(b"no_model_configured").hexdigest(),
        )

    backend: GenericBackend | None = None
    try:
        backend = GenericBackend(provider=provider_config)
        await backend.__aenter__()

        messages: list[LLMMessage] = [LLMMessage(role=Role.user, content=prompt)]

        result = await backend.complete(
            model=model_config,
            messages=messages,
            temperature=0.3,
            tools=None,
            max_tokens=2000,
            tool_choice=None,
            extra_headers=None,
        )

        raw_response = result.message.content or ""
        transcript_sha256 = hashlib.sha256(raw_response.encode()).hexdigest()
        opinion = _parse_opinion(provider_name, request, raw_response)

        return NormalizedConsultation(
            consultation_id=f"{request.request_id}-{provider_name}",
            request_id=request.request_id,
            provider=provider_name,
            provider_surface=ProviderSurface.API,
            submitted_at=submitted_at,
            returned_at=datetime.now(UTC).isoformat(),
            transcript_sha256=transcript_sha256,
            opinion=opinion,
        )
    except Exception as exc:
        logger.warning(
            "Council consultation failed for provider=%s: %s", provider_name, exc
        )
        return NormalizedConsultation(
            consultation_id=f"{request.request_id}-{provider_name}",
            request_id=request.request_id,
            provider=provider_name,
            provider_surface=ProviderSurface.API,
            submitted_at=submitted_at,
            returned_at=datetime.now(UTC).isoformat(),
            transcript_sha256=hashlib.sha256(str(exc).encode()).hexdigest(),
        )
    finally:
        if backend is not None:
            with suppress(Exception):
                await backend.__aexit__(None, None, None)


def _find_provider_config(provider_name: str) -> Any | None:
    """Find provider config by name from loaded VibeConfig."""
    try:
        from rig_relay.core.config import VibeConfig

        config = VibeConfig.load()
        for p in config.providers:
            if p.name == provider_name:
                return p
    except Exception:
        pass
    return None


def _find_model_for_provider(provider_config: Any) -> Any | None:
    """Find the first model configured for a given provider."""
    try:
        from rig_relay.core.config import VibeConfig

        config = VibeConfig.load()
        for m in config.models:
            if m.provider == provider_config.name:
                return m
    except Exception:
        pass
    return None


def _parse_opinion(
    provider_name: str, request: ConsultationRequest, raw_response: str
) -> ProviderOpinion:
    """Parse structured provider response into a ProviderOpinion."""
    sections: dict[str, list[str]] = {
        "assumptions": [],
        "blockers": [],
        "risks": [],
        "recommended_next_slice": [],
        "files_or_symbols_to_inspect": [],
        "do_not_do": [],
    }
    confidence = "medium"
    current_section = ""

    for line in raw_response.split("\n"):
        stripped = line.strip()
        upper = stripped.upper()

        if upper.startswith("ASSUMPTIONS:"):
            current_section = "assumptions"
        elif upper.startswith("BLOCKERS:"):
            current_section = "blockers"
        elif upper.startswith("RISKS:"):
            current_section = "risks"
        elif upper.startswith("RECOMMENDED_NEXT_SLICE:"):
            current_section = "recommended_next_slice"
        elif upper.startswith("FILES_TO_INSPECT:"):
            current_section = "files_or_symbols_to_inspect"
        elif upper.startswith("CONFIDENCE:"):
            parts = stripped.split(":", 1)
            if len(parts) > 1:
                confidence = parts[1].strip().lower()
        elif upper.startswith("DO_NOT_DO:"):
            current_section = "do_not_do"
        elif current_section and stripped.startswith("- "):
            sections[current_section].append(stripped[2:].strip())

    try:
        conf = Confidence(confidence)
    except ValueError:
        conf = Confidence.MEDIUM

    return ProviderOpinion(
        provider=provider_name,
        model_label=provider_name,
        mission_id=request.mission_id,
        question=request.question,
        assumptions=sections["assumptions"],
        blockers=sections["blockers"],
        risks=sections["risks"],
        recommended_next_slice=sections["recommended_next_slice"],
        files_or_symbols_to_inspect=sections["files_or_symbols_to_inspect"],
        do_not_do=sections["do_not_do"],
        confidence=conf,
        raw_transcript_sha256=hashlib.sha256(raw_response.encode()).hexdigest(),
    )


def determine_council_recommendation(receipt: ConsultationReceipt) -> str:
    """Determine council recommendation from a receipt.

    Returns:
        "ALLOW" — no providers have blockers (consensus to proceed).
        "BLOCK" — all providers have blockers (consensus to block).
        "REVIEW" — mixed opinions, some providers have blockers.
    """
    if not receipt.consultations:
        return "ALLOW"

    block_count = sum(
        1 for nc in receipt.consultations if nc.opinion and nc.opinion.blockers
    )
    total = len(receipt.consultations)

    if block_count == total and total > 0:
        return "BLOCK"
    if block_count > 0:
        return "REVIEW"
    return "ALLOW"


__all__ = ["consult_council_before_mutation", "determine_council_recommendation"]
