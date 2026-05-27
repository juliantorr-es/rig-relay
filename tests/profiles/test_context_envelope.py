from __future__ import annotations

from pathlib import Path

from rig_relay.profiles._context_envelope import (
    build_context_envelope,
    compute_stable_prefix_digest,
)
from rig_relay.profiles._profile_registry import BUILTIN_PROFILES
from rig_relay.profiles.models import TaskRole


def _find_profile(profile_id: str):
    for p in BUILTIN_PROFILES:
        if p.profile_id == profile_id:
            return p
    raise ValueError(f"Profile {profile_id} not found")


def test_build_envelope_for_rig_governed():
    profile = _find_profile("rig.native.governed.v1")
    envelope = build_context_envelope(
        profile=profile,
        role=TaskRole.IMPLEMENTATION,
        workspace_root=Path.cwd(),
        session_id="test-session-1",
    )
    assert envelope.session_id == "test-session-1"
    assert envelope.section_count > 0
    assert envelope.rendered_prompt
    assert envelope.rendered_prompt


def test_build_envelope_for_codex_compatible():
    profile = _find_profile("openai.codex.compatible_engineering.v1")
    envelope = build_context_envelope(
        profile=profile,
        role=TaskRole.IMPLEMENTATION,
        workspace_root=Path.cwd(),
        session_id="test-session-2",
    )
    assert envelope.session_id == "test-session-2"
    assert envelope.section_count > 0
    assert (
        "AGENTS.md" in envelope.rendered_prompt or "Codex" in envelope.rendered_prompt
    )


def test_build_envelope_for_claude_compatible():
    profile = _find_profile("anthropic.claude_code.compatible_execution.v1")
    envelope = build_context_envelope(
        profile=profile,
        role=TaskRole.IMPLEMENTATION,
        workspace_root=Path.cwd(),
        session_id="test-session-3",
    )
    assert envelope.session_id == "test-session-3"
    assert envelope.section_count > 0
    assert (
        "CLAUDE.md" in envelope.rendered_prompt or "Claude" in envelope.rendered_prompt
    )


def test_build_envelope_for_copilot_compatible():
    profile = _find_profile("github.copilot.fleet.compatible_orchestration.v1")
    envelope = build_context_envelope(
        profile=profile,
        role=TaskRole.IMPLEMENTATION,
        workspace_root=Path.cwd(),
        session_id="test-session-4",
    )
    assert envelope.session_id == "test-session-4"
    assert envelope.section_count > 0
    assert (
        "Copilot" in envelope.rendered_prompt
        or "copilot" in envelope.rendered_prompt.lower()
    )


def test_envelope_has_valid_sha256():
    profile = _find_profile("rig.native.governed.v1")
    envelope = build_context_envelope(
        profile=profile,
        role=TaskRole.IMPLEMENTATION,
        workspace_root=Path.cwd(),
        session_id="test-session-5",
    )
    assert envelope.receipt_sha256.startswith("sha256:")


def test_envelope_section_count_positive():
    profile = _find_profile("rig.native.governed.v1")
    envelope = build_context_envelope(
        profile=profile,
        role=TaskRole.IMPLEMENTATION,
        workspace_root=Path.cwd(),
        session_id="test-session-6",
    )
    assert envelope.section_count > 0


def test_stable_prefix_digest_computed():
    profile = _find_profile("rig.native.governed.v1")
    envelope = build_context_envelope(
        profile=profile,
        role=TaskRole.IMPLEMENTATION,
        workspace_root=Path.cwd(),
        session_id="test-session-7",
    )
    digest = compute_stable_prefix_digest(envelope)
    assert digest.startswith("sha256:")


def test_envelope_handles_missing_workspace():
    profile = _find_profile("rig.native.governed.v1")
    nonexistent = Path("/tmp/nonexistent_workspace_12345_for_test")
    envelope = build_context_envelope(
        profile=profile,
        role=TaskRole.IMPLEMENTATION,
        workspace_root=nonexistent
        if nonexistent.exists()
        else Path("/nonexistent_xyz_workspace"),
        session_id="test-session-8",
    )
    assert envelope.session_id == "test-session-8"


def test_role_sensitive_envelope():
    profile = _find_profile("rig.native.governed.v1")
    impl_envelope = build_context_envelope(
        profile=profile,
        role=TaskRole.IMPLEMENTATION,
        workspace_root=Path.cwd(),
        session_id="test-session-9",
    )
    audit_envelope = build_context_envelope(
        profile=profile,
        role=TaskRole.AUDIT_REVIEW,
        workspace_root=Path.cwd(),
        session_id="test-session-10",
    )
    assert "implementation" in impl_envelope.rendered_prompt
    assert "audit_review" in audit_envelope.rendered_prompt
    assert impl_envelope.rendered_prompt != audit_envelope.rendered_prompt
