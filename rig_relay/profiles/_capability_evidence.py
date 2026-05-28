"""Capability evidence models, enums, and built-in static evidence.

Content-light: no raw prompts, secrets, credentials, file contents, or diffs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto
import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field


class CapabilityEvidenceSourceClass(StrEnum):
    VERIFIED_LIVE_PROVIDER_RESPONSE = auto()
    OFFICIAL_DOCUMENTED_STATIC_CAPABILITY = auto()
    LOCAL_RUNTIME_PUBLIC_PROJECTION = auto()
    USER_DECLARED_CONFIGURATION = auto()
    UNKNOWN = auto()
    CONFLICTING = auto()
    UNAVAILABLE_WITHOUT_CREDENTIALS = auto()


class CapabilityPosture(StrEnum):
    SUPPORTED = auto()
    UNSUPPORTED = auto()
    UNKNOWN = auto()
    REQUIRES_CONFIGURATION = auto()
    REQUIRES_CREDENTIALS = auto()
    EXPERIMENTAL = auto()
    DEGRADED = auto()
    CONFLICTING = auto()
    UNAVAILABLE = auto()


class CapabilityName(StrEnum):
    TOOL_USE = auto()
    STREAMING = auto()
    STRUCTURED_OUTPUT = auto()
    THINKING = auto()
    VISION = auto()
    EMBEDDINGS = auto()
    PROMPT_CACHING = auto()
    EXTENDED_CONTEXT = auto()
    SUBAGENTS = auto()
    REASONING_EFFORT_CONTROL = auto()
    ADAPTIVE_REASONING = auto()


class CapabilityEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    provider: str
    model_pattern: str
    capability: CapabilityName
    posture: CapabilityPosture
    source_class: CapabilityEvidenceSourceClass
    source_reference: str
    source_digest: str = ""
    observed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    freshness_ttl_hours: int = 0
    confidence: str = "medium"
    conflict_state: str = "none"
    unsupported_claims: list[str] = Field(default_factory=list)
    evidence_digest: str = ""

    def compute_digest(self) -> str:
        data = self.model_dump(exclude={"evidence_digest"})
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _make_builtin_evidence() -> tuple[CapabilityEvidenceItem, ...]:
    raw: list[CapabilityEvidenceItem] = [
        # === OpenAI models (from openai.com docs) ===
        CapabilityEvidenceItem(
            evidence_id="y3-ce-openai-gpt-tool-use",
            provider="openai",
            model_pattern="gpt-.*",
            capability=CapabilityName.TOOL_USE,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://platform.openai.com/docs/guides/function-calling",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-openai-gpt-structured-output",
            provider="openai",
            model_pattern="gpt-.*",
            capability=CapabilityName.STRUCTURED_OUTPUT,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://platform.openai.com/docs/guides/structured-outputs",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-openai-gpt-streaming",
            provider="openai",
            model_pattern="gpt-.*",
            capability=CapabilityName.STREAMING,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://platform.openai.com/docs/api-reference/streaming",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-openai-reasoning-thinking",
            provider="openai",
            model_pattern=r"(o1|o3|o4|codex).*",
            capability=CapabilityName.THINKING,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://platform.openai.com/docs/guides/reasoning",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-openai-reasoning-effort",
            provider="openai",
            model_pattern=r"(o1|o3|o4).*",
            capability=CapabilityName.REASONING_EFFORT_CONTROL,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://platform.openai.com/docs/guides/reasoning",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-openai-prompt-caching",
            provider="openai",
            model_pattern=".*",
            capability=CapabilityName.PROMPT_CACHING,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://platform.openai.com/docs/guides/prompt-caching",
            confidence="medium",
        ),
        # === Anthropic models (from docs.anthropic.com) ===
        CapabilityEvidenceItem(
            evidence_id="y3-ce-anthropic-claude-tool-use",
            provider="anthropic",
            model_pattern="claude-.*",
            capability=CapabilityName.TOOL_USE,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://docs.anthropic.com/en/docs/build-with-claude/tool-use",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-anthropic-claude-streaming",
            provider="anthropic",
            model_pattern="claude-.*",
            capability=CapabilityName.STREAMING,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://docs.anthropic.com/en/docs/build-with-claude/streaming",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-anthropic-claude-thinking",
            provider="anthropic",
            model_pattern="claude-.*",
            capability=CapabilityName.THINKING,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-anthropic-claude-effort-control",
            provider="anthropic",
            model_pattern="claude-.*",
            capability=CapabilityName.REASONING_EFFORT_CONTROL,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://docs.anthropic.com/en/docs/claude-code/effort",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-anthropic-claude-adaptive-reasoning",
            provider="anthropic",
            model_pattern="claude-opus.*",
            capability=CapabilityName.ADAPTIVE_REASONING,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://docs.anthropic.com/en/docs/claude-code/effort#adaptive-reasoning",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-anthropic-claude-prompt-caching",
            provider="anthropic",
            model_pattern="claude-.*",
            capability=CapabilityName.PROMPT_CACHING,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching",
            confidence="high",
        ),
        CapabilityEvidenceItem(
            evidence_id="y3-ce-anthropic-claude-subagents",
            provider="anthropic",
            model_pattern="claude-.*",
            capability=CapabilityName.SUBAGENTS,
            posture=CapabilityPosture.SUPPORTED,
            source_class=CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY,
            source_reference="https://docs.anthropic.com/en/docs/claude-code/sub-agents",
            confidence="high",
        ),
    ]

    return tuple(
        item.model_copy(update={"evidence_digest": item.compute_digest()})
        for item in raw
    )


BUILTIN_CAPABILITY_EVIDENCE: tuple[CapabilityEvidenceItem, ...] = (
    _make_builtin_evidence()
)


_CAPABILITY_TO_PROFILE_REQUIREMENT: dict[CapabilityName, str] = {
    CapabilityName.TOOL_USE: "requires_tool_use",
    CapabilityName.STREAMING: "requires_streaming",
    CapabilityName.STRUCTURED_OUTPUT: "requires_structured_output",
    CapabilityName.THINKING: "requires_thinking",
    CapabilityName.VISION: "requires_vision",
    CapabilityName.EMBEDDINGS: "requires_embeddings",
}

_SOURCE_CLASS_CONFIDENCE: dict[CapabilityEvidenceSourceClass, int] = {
    CapabilityEvidenceSourceClass.VERIFIED_LIVE_PROVIDER_RESPONSE: 0,
    CapabilityEvidenceSourceClass.OFFICIAL_DOCUMENTED_STATIC_CAPABILITY: 1,
    CapabilityEvidenceSourceClass.LOCAL_RUNTIME_PUBLIC_PROJECTION: 2,
    CapabilityEvidenceSourceClass.USER_DECLARED_CONFIGURATION: 3,
    CapabilityEvidenceSourceClass.UNKNOWN: 4,
    CapabilityEvidenceSourceClass.CONFLICTING: 5,
    CapabilityEvidenceSourceClass.UNAVAILABLE_WITHOUT_CREDENTIALS: 6,
}


def resolve_capability_evidence(
    provider: str,
    model_id: str,
    capability: CapabilityName | str,
    sources: tuple[CapabilityEvidenceItem, ...] | None = None,
) -> CapabilityEvidenceItem | None:
    if sources is None:
        sources = BUILTIN_CAPABILITY_EVIDENCE

    cap_value = capability if isinstance(capability, str) else capability.value

    matches = [
        e
        for e in sources
        if e.provider == provider
        and re.fullmatch(e.model_pattern, model_id)
        and e.capability.value == cap_value
    ]
    if not matches:
        return None

    confidence_order: dict[str, int] = {"high": 0, "medium": 1, "low": 2}
    matches.sort(
        key=lambda e: (
            confidence_order.get(e.confidence, 3),
            1 if e.model_pattern == ".*" else 0,
        )
    )
    return matches[0]


def merge_capability_evidence(
    items: list[CapabilityEvidenceItem],
) -> dict[str, CapabilityEvidenceItem | None]:
    by_cap: dict[str, list[CapabilityEvidenceItem]] = {}
    for item in items:
        by_cap.setdefault(item.capability.value, []).append(item)

    merged: dict[str, CapabilityEvidenceItem | None] = {}
    for cap_name, evidence_list in by_cap.items():
        if len(evidence_list) == 1:
            merged[cap_name] = evidence_list[0]
            continue

        sources = {e.source_class for e in evidence_list}
        if CapabilityEvidenceSourceClass.CONFLICTING in sources:
            merged[cap_name] = None
            continue

        postures = {e.posture for e in evidence_list}
        if (
            CapabilityPosture.UNSUPPORTED in postures
            and CapabilityPosture.SUPPORTED in postures
        ):
            merged[cap_name] = None
            continue

        merged[cap_name] = min(
            evidence_list,
            key=lambda e: _SOURCE_CLASS_CONFIDENCE.get(
                CapabilityEvidenceSourceClass(e.source_class.value), 99
            ),
        )

    return merged


def validate_profile_requirements_against_evidence(
    profile: object,  # HarnessCompatibilityProfile (lazy import to avoid cycles)
    provider: str,
    model_id: str,
    sources: tuple[CapabilityEvidenceItem, ...] | None = None,
) -> tuple[bool, dict[str, CapabilityEvidenceItem | None], list[str]]:
    from rig_relay.profiles.models import HarnessCompatibilityProfile

    if not isinstance(profile, HarnessCompatibilityProfile):
        raise TypeError(f"Expected HarnessCompatibilityProfile, got {type(profile)}")

    req = profile.required_capabilities
    if sources is None:
        sources = BUILTIN_CAPABILITY_EVIDENCE

    evidence_map: dict[str, CapabilityEvidenceItem | None] = {}
    warnings: list[str] = []
    satisfied = True

    capability_checks: list[tuple[bool, str, CapabilityName]] = [
        (req.requires_tool_use, "tool_use", CapabilityName.TOOL_USE),
        (req.requires_streaming, "streaming", CapabilityName.STREAMING),
        (
            req.requires_structured_output,
            "structured_output",
            CapabilityName.STRUCTURED_OUTPUT,
        ),
        (req.requires_thinking, "thinking", CapabilityName.THINKING),
        (req.requires_vision, "vision", CapabilityName.VISION),
        (req.requires_embeddings, "embeddings", CapabilityName.EMBEDDINGS),
    ]

    for required, label, cap_enum in capability_checks:
        if not required:
            continue

        evidence = resolve_capability_evidence(provider, model_id, cap_enum, sources)
        evidence_map[label] = evidence

        if evidence is None:
            satisfied = False
            warnings.append(
                f"Required capability '{label}' has no evidence for "
                f"{provider}/{model_id}"
            )
            continue

        match evidence.source_class:
            case CapabilityEvidenceSourceClass.USER_DECLARED_CONFIGURATION:
                warnings.append(
                    f"Required capability '{label}' has only user-declared evidence "
                    f"for {provider}/{model_id}"
                )
            case _:
                pass

        if evidence.posture in {
            CapabilityPosture.UNSUPPORTED,
            CapabilityPosture.UNAVAILABLE,
        }:
            satisfied = False
            warnings.append(
                f"Required capability '{label}' is {evidence.posture.value} "
                f"for {provider}/{model_id}"
            )

        if evidence.conflict_state != "none":
            satisfied = False
            warnings.append(
                f"Required capability '{label}' has conflicting evidence "
                f"for {provider}/{model_id}"
            )

    return satisfied, evidence_map, warnings


def build_capability_projection(
    provider: str,
    model_id: str,
    sources: tuple[CapabilityEvidenceItem, ...] | None = None,
) -> dict[str, object]:
    if sources is None:
        sources = BUILTIN_CAPABILITY_EVIDENCE

    projection: dict[str, object] = {
        "provider": provider,
        "model_id": model_id,
        "capabilities": {},
    }

    caps: dict[str, dict[str, object]] = {}
    for cap_name in CapabilityName:
        evidence = resolve_capability_evidence(provider, model_id, cap_name, sources)
        cap_key = cap_name.value
        if evidence is None:
            caps[cap_key] = {
                "posture": CapabilityPosture.UNKNOWN.value,
                "source_class": CapabilityEvidenceSourceClass.UNKNOWN.value,
                "confidence": "low",
            }
        else:
            caps[cap_key] = {
                "posture": evidence.posture.value,
                "source_class": evidence.source_class.value,
                "source_reference": evidence.source_reference,
                "confidence": evidence.confidence,
                "evidence_digest": evidence.evidence_digest,
            }

    projection["capabilities"] = caps
    return projection
