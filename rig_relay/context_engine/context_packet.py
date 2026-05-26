"""Sanitized context packet builder for AgentLoop and local inference.

Produces bounded, provenance-rich, deterministic context packets from
a project understanding projection. Content-light: no raw repository
contents, secrets, or private paths. Digest-bound for reproducibility.
"""

from __future__ import annotations

from hashlib import sha256

from rig_relay.context_engine.models import (
    ConsumptionHints,
    ContextSummary,
    ProvenanceReference,
    RedactionLog as PacketRedactionLog,
    SanitizedContextPacket,
    TokenBudget,
)


def build_sanitized_context_packet(
    understanding_id: str,
    project_name: str,
    languages: list[str],
    frameworks: list[str],
    test_frameworks: list[str],
    build_systems: list[str],
    file_count: int = 0,
    subsystem_count: int = 0,
    has_documentation: bool = False,
    has_tests: bool = False,
    has_ci: bool = False,
    total_tokens: int = 4096,
) -> SanitizedContextPacket:
    """Build a deterministic, content-light context packet.

    Args:
        understanding_id: The projection ID this packet derives from.
        project_name: Project name for identity hash derivation.
        languages: Detected programming languages.
        frameworks: Detected frameworks.
        test_frameworks: Detected test frameworks.
        build_systems: Detected build systems.
        file_count: Approximate tracked file count.
        subsystem_count: Top-level subsystem count.
        has_documentation: Whether documentation was detected.
        has_tests: Whether test infrastructure was detected.
        has_ci: Whether CI/CD pipelines were detected.
        total_tokens: Token budget ceiling.

    Returns:
        A sanitized context packet ready for AgentLoop or local inference.
    """
    project_hash = sha256(project_name.encode()).hexdigest()

    summary = ContextSummary(
        languages=sorted(set(languages)),
        frameworks=sorted(set(frameworks)),
        test_frameworks=sorted(set(test_frameworks)),
        build_systems=sorted(set(build_systems)),
        project_type_hint=_infer_project_type(frameworks, languages),
        subsystem_count=subsystem_count,
        file_count=file_count,
        has_documentation=has_documentation,
        has_tests=has_tests,
        has_ci=has_ci,
    )

    provenance_refs: list[ProvenanceReference] = []
    for i, lang in enumerate(languages):
        provenance_refs.append(
            ProvenanceReference(
                ref_type="structural_fact",
                ref_id=f"lang_{i}",
                confidence="high",
                source_digest=f"sha256:{sha256(lang.encode()).hexdigest()[:16]}",
            )
        )

    consumed = _estimate_tokens(summary, provenance_refs)
    budget = TokenBudget(
        total_tokens_available=total_tokens,
        tokens_consumed=consumed,
        tokens_remaining=max(0, total_tokens - consumed),
    )
    if consumed > total_tokens:
        budget.budget_warnings.append(
            f"Token budget exceeded: {consumed} > {total_tokens}"
        )

    packet = SanitizedContextPacket(
        packet_id=f"ctx_packet_{project_hash[:12]}",
        project_identity_hash=f"sha256:{project_hash}",
        context_summary=summary,
        token_budget=budget,
        provenance_references=provenance_refs,
        redaction_summary=PacketRedactionLog(
            items_withheld=0, items_redacted=0, reasons=[]
        ),
        consumption_hints=ConsumptionHints(
            packet_kind="codebase_context", intended_consumer="agent_loop"
        ),
    )
    packet.packet_digest = packet.compute_digest()
    return packet


def _infer_project_type(frameworks: list[str], languages: list[str]) -> str:
    if "pywebview" in frameworks:
        return "desktop_application"
    if "fastapi" in frameworks or "flask" in frameworks or "django" in frameworks:
        return "web_application"
    if "textual" in frameworks:
        return "terminal_application"
    if "pydantic" in frameworks and not frameworks:
        return "library"
    lang_set = set(languages)
    if "python" in lang_set:
        return "python_project"
    if "rust" in lang_set:
        return "rust_project"
    return "unknown"


def _estimate_tokens(
    summary: ContextSummary, provenance_refs: list[ProvenanceReference]
) -> int:
    chars = 0
    chars += len(summary.project_type_hint)
    chars += sum(len(v) for v in summary.languages)
    chars += sum(len(v) for v in summary.frameworks)
    chars += sum(len(v) for v in summary.test_frameworks)
    chars += sum(len(v) for v in summary.build_systems)
    chars += 50
    chars += sum(
        len(r.ref_type) + len(r.ref_id) + len(r.source_digest) for r in provenance_refs
    )
    return chars // 4


__all__ = ["build_sanitized_context_packet"]
