"""Context envelope assembler for harness compatibility profiles.

Builds a ContextEnvelopeReceipt from a resolved profile, role, and workspace.
Each strategy assembles the stable prefix and dynamic suffix differently.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from rig_relay.context.models import ContextEnvelopeReceipt
from rig_relay.profiles.models import (
    ContextEnvelopeStrategy,
    HarnessCompatibilityProfile,
    InstructionRenderingStrategy,
    TaskRole,
)


def build_context_envelope(
    profile: HarnessCompatibilityProfile,
    role: TaskRole,
    workspace_root: Path,
    session_id: str,
    extra_context: dict[str, str] | None = None,
) -> ContextEnvelopeReceipt:
    strategy = profile.context_envelope_strategy

    match strategy:
        case ContextEnvelopeStrategy.RIG_GOVERNED:
            return _build_rig_governed(
                profile, role, workspace_root, session_id, extra_context
            )
        case ContextEnvelopeStrategy.CODEX_COMPATIBLE:
            return _build_codex_compatible(
                profile, role, workspace_root, session_id, extra_context
            )
        case ContextEnvelopeStrategy.CLAUDE_COMPATIBLE:
            return _build_claude_compatible(
                profile, role, workspace_root, session_id, extra_context
            )
        case ContextEnvelopeStrategy.COPILOT_COMPATIBLE:
            return _build_copilot_compatible(
                profile, role, workspace_root, session_id, extra_context
            )


def compute_stable_prefix_digest(envelope: ContextEnvelopeReceipt) -> str:
    prefix_hash = hashlib.sha256(envelope.rendered_prompt.encode()).hexdigest()
    return f"sha256:{prefix_hash}"


def _find_file_upwards(
    filename: str, start_dir: Path, max_depth: int = 20
) -> Path | None:
    current = start_dir.resolve()
    for _ in range(max_depth + 1):
        candidate = current / filename
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def _read_file_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _instruction_block(
    strategy: InstructionRenderingStrategy, section_count: int
) -> tuple[list[str], int]:
    lines: list[str] = []
    lines.append(f"\n**Instruction Rendering Strategy**: {strategy.value}\n")
    section_count += 1

    match strategy:
        case InstructionRenderingStrategy.RIG_DEFAULT:
            lines.append(
                "AGENTS.md + PROJECT.md delivered as system message. "
                "Standard Rig Relay governed context envelope.\n"
            )
        case InstructionRenderingStrategy.CODEX:
            lines.append(
                "Scope: AGENTS.md files govern the directory tree rooted at the "
                "folder containing them. More-deeply-nested AGENTS.md take precedence.\n"
                "Use citation format: 【F:file_path†Lstart(-Lend)】\n"
            )
        case InstructionRenderingStrategy.CLAUDE:
            lines.append(
                "CLAUDE.md loading order (broadest to most specific): "
                "managed → user (~/.claude/CLAUDE.md) → project (./CLAUDE.md) → "
                "local (./CLAUDE.local.md). Delivered as user message after system prompt.\n"
            )
        case InstructionRenderingStrategy.COPILOT:
            lines.append(
                "Custom instructions combine from: "
                ".github/copilot-instructions.md, "
                ".github/instructions/*.instructions.md (path-specific with glob frontmatter), "
                "AGENTS.md. Custom agents are defined as Markdown+YAML files in "
                ".github/agents/.\n"
            )

    return lines, section_count


def _build_rig_governed(
    profile: HarnessCompatibilityProfile,
    role: TaskRole,
    workspace_root: Path,
    session_id: str,
    extra_context: dict[str, str] | None,
) -> ContextEnvelopeReceipt:
    sections: list[str] = []
    section_count = 0

    agents_md = _find_file_upwards("AGENTS.md", workspace_root)
    project_md = _find_file_upwards("PROJECT.md", workspace_root)

    sections.append("# Rig Relay Governed Context Envelope\n")
    sections.append(f"Profile: {profile.profile_id}\n")
    sections.append(f"Role: {role.value}\n")
    sections.append(f"Session: {session_id}\n")
    section_count += 1

    if agents_md:
        content = _read_file_safe(agents_md)
        sections.append(f"\n## AGENTS.md\n{content}")
        section_count += 1

    if project_md:
        content = _read_file_safe(project_md)
        sections.append(f"\n## PROJECT.md\n{content}")
        section_count += 1

    try:
        head_path = workspace_root / ".git" / "HEAD"
        if head_path.exists():
            head_content = head_path.read_text().strip()
            if head_content.startswith("ref: refs/heads/"):
                branch = head_content.removeprefix("ref: refs/heads/")
                git_status = f"branch: {branch}"
            else:
                git_status = f"detached HEAD: {head_content[:12]}"
            sections.append(f"\n## Git Status\n```\n{git_status}```")
            section_count += 1
    except OSError:
        pass

    instr_lines, section_count = _instruction_block(
        profile.instruction_rendering_strategy, section_count
    )
    sections.extend(instr_lines)

    if extra_context:
        sections.append("\n## Extra Context\n")
        for key, val in extra_context.items():
            sections.append(f"**{key}**: {val}\n")
        section_count += 1

    rendered = "\n".join(sections)
    receipt_sha = hashlib.sha256(rendered.encode()).hexdigest()

    return ContextEnvelopeReceipt(
        envelope_id=str(uuid4()),
        session_id=session_id,
        rendered_prompt=rendered,
        section_count=section_count,
        estimated_tokens=max(1, len(rendered) // 4),
        receipt_sha256=f"sha256:{receipt_sha}",
    )


def _build_codex_compatible(
    profile: HarnessCompatibilityProfile,
    role: TaskRole,
    workspace_root: Path,
    session_id: str,
    extra_context: dict[str, str] | None,
) -> ContextEnvelopeReceipt:
    sections: list[str] = []
    section_count = 0

    sections.append("# Codex-Compatible Context Envelope\n")
    section_count += 1

    agents_md = _find_file_upwards("AGENTS.md", workspace_root)
    if agents_md:
        content = _read_file_safe(agents_md)
        sections.append(f"## AGENTS.md Chain\n{content}")
        section_count += 1

    sections.append(
        "\n## Git Rules\n"
        "- Never create new branches without explicit instruction.\n"
        "- Commit changes when asked. Do not commit when not asked.\n"
        "- Fix pre-commit failures before asking for review.\n"
        "- Keep the worktree clean; do not leave unstaged changes.\n"
    )
    section_count += 1

    sections.append(
        "\n## Citation Format\n"
        "Use citation format: 【F:path†L1-L2】 when referencing file locations.\n"
        "This is advisory for Rig Relay governance but aids traceability.\n"
    )
    section_count += 1

    instr_lines, section_count = _instruction_block(
        profile.instruction_rendering_strategy, section_count
    )
    sections.extend(instr_lines)

    sections.append(f"\n## Task Role\n{role.value}\n")
    sections.append(f"\n## Profile\n{profile.profile_id} — {profile.display_name}\n")
    section_count += 1

    if extra_context:
        sections.append("\n## Extra Context\n")
        for key, val in extra_context.items():
            sections.append(f"**{key}**: {val}\n")
        section_count += 1

    rendered = "\n".join(sections)
    receipt_sha = hashlib.sha256(rendered.encode()).hexdigest()

    return ContextEnvelopeReceipt(
        envelope_id=str(uuid4()),
        session_id=session_id,
        rendered_prompt=rendered,
        section_count=section_count,
        estimated_tokens=max(1, len(rendered) // 4),
        receipt_sha256=f"sha256:{receipt_sha}",
    )


def _build_claude_compatible(
    profile: HarnessCompatibilityProfile,
    role: TaskRole,
    workspace_root: Path,
    session_id: str,
    extra_context: dict[str, str] | None,
) -> ContextEnvelopeReceipt:
    sections: list[str] = []
    section_count = 0

    sections.append("# Claude-Compatible Context Envelope\n")
    section_count += 1

    sections.append(
        "## CLAUDE.md Load Order\n"
        "CLAUDE.md is loaded in 4 layers:\n"
        "1. Managed — system-level policy (not overridable).\n"
        "2. User — user home directory (~/.claude/CLAUDE.md).\n"
        "3. Project — repository root (CLAUDE.md).\n"
        "4. Local — nearest ancestor directory (CLAUDE.local.md).\n"
        "All layers are concatenated and delivered as a user message, "
        "not system message.\n"
    )
    section_count += 1

    claude_md = _find_file_upwards("CLAUDE.md", workspace_root)
    if claude_md:
        content = _read_file_safe(claude_md)
        sections.append(f"## CLAUDE.md (Project Layer)\n{content}")
        section_count += 1

    instr_lines, section_count = _instruction_block(
        profile.instruction_rendering_strategy, section_count
    )
    sections.extend(instr_lines)

    sections.append(f"\n## Task Role\n{role.value}\n")
    sections.append(f"\n## Profile\n{profile.profile_id} — {profile.display_name}\n")
    section_count += 1

    if profile.workspace_subagent_posture.supports_subagents:
        sections.append(
            "\n## Subagent Support\n"
            "This profile supports subagents with isolated contexts. "
            "Subagent model selection may differ from parent.\n"
        )
        section_count += 1

    if extra_context:
        sections.append("\n## Extra Context\n")
        for key, val in extra_context.items():
            sections.append(f"**{key}**: {val}\n")
        section_count += 1

    rendered = "\n".join(sections)
    receipt_sha = hashlib.sha256(rendered.encode()).hexdigest()

    return ContextEnvelopeReceipt(
        envelope_id=str(uuid4()),
        session_id=session_id,
        rendered_prompt=rendered,
        section_count=section_count,
        estimated_tokens=max(1, len(rendered) // 4),
        receipt_sha256=f"sha256:{receipt_sha}",
    )


def _build_copilot_compatible(
    profile: HarnessCompatibilityProfile,
    role: TaskRole,
    workspace_root: Path,
    session_id: str,
    extra_context: dict[str, str] | None,
) -> ContextEnvelopeReceipt:
    sections: list[str] = []
    section_count = 0

    sections.append("# Copilot-Compatible Context Envelope\n")
    section_count += 1

    sections.append(
        "## Multi-Layer Instruction Discovery\n"
        "Instructions are loaded from:\n"
        "- Repository: AGENTS.md or .github/copilot-instructions.md\n"
        "- Path-specific: .instructions.md files with glob frontmatter\n"
        "- User home: ~/.config/github-copilot/instructions.md\n"
        "- Fallback: CLAUDE.md if no AGENTS.md found\n"
    )
    section_count += 1

    agents_md = _find_file_upwards("AGENTS.md", workspace_root)
    if agents_md:
        content = _read_file_safe(agents_md)
        sections.append(f"## AGENTS.md\n{content}")
        section_count += 1

    copilot_md = _find_file_upwards(".github/copilot-instructions.md", workspace_root)
    if copilot_md:
        content = _read_file_safe(copilot_md)
        sections.append(f"## .github/copilot-instructions.md\n{content}")
        section_count += 1

    sections.append(
        "\n## Built-in Agent Profiles\n"
        "- explore — read-only exploration\n"
        "- task — bounded implementation task\n"
        "- general-purpose — all tools\n"
        "- code-review — adversarial code review\n"
        "- research — deep research with Markdown reports\n"
        "- rubber-duck — cross-model critique\n"
    )
    section_count += 1

    sections.append(
        "\n## Compaction Policy\n"
        "Context compaction is recommended at 80% utilization. "
        "Rig Relay manages this through its own governed lifecycle.\n"
    )
    section_count += 1

    instr_lines, section_count = _instruction_block(
        profile.instruction_rendering_strategy, section_count
    )
    sections.extend(instr_lines)

    sections.append(f"\n## Task Role\n{role.value}\n")
    sections.append(f"\n## Profile\n{profile.profile_id} — {profile.display_name}\n")
    section_count += 1

    if extra_context:
        sections.append("\n## Extra Context\n")
        for key, val in extra_context.items():
            sections.append(f"**{key}**: {val}\n")
        section_count += 1

    rendered = "\n".join(sections)
    receipt_sha = hashlib.sha256(rendered.encode()).hexdigest()

    return ContextEnvelopeReceipt(
        envelope_id=str(uuid4()),
        session_id=session_id,
        rendered_prompt=rendered,
        section_count=section_count,
        estimated_tokens=max(1, len(rendered) // 4),
        receipt_sha256=f"sha256:{receipt_sha}",
    )
