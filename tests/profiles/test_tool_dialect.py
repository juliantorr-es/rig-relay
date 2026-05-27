from __future__ import annotations

from rig_relay.profiles._profile_registry import BUILTIN_PROFILES
from rig_relay.profiles._tool_dialect import (
    adapt_tool_description,
    adapt_tool_result,
    assert_tool_dialect_authority_preserved,
)
from rig_relay.profiles.models import ToolDialectStrategy


def _find_profile(profile_id: str):
    for p in BUILTIN_PROFILES:
        if p.profile_id == profile_id:
            return p
    raise ValueError(f"Profile {profile_id} not found")


def test_adapt_tool_description_rig_native_returns_unchanged():
    original = "Writes content to a file."
    adapted = adapt_tool_description(
        "write_file", original, ToolDialectStrategy.RIG_NATIVE, "test.profile"
    )
    assert adapted == original


def test_adapt_tool_description_openai_adds_authority_note():
    original = "Writes content to a file."
    adapted = adapt_tool_description(
        "write_file",
        original,
        ToolDialectStrategy.OPENAI_FUNCTION_CALLING,
        "test.profile",
    )
    assert original in adapted
    assert "governance" in adapted.lower() or "receipt-backed" in adapted.lower()


def test_adapt_tool_description_anthropic_formats_correctly():
    original = "Writes content to a file."
    adapted = adapt_tool_description(
        "write_file", original, ToolDialectStrategy.ANTHROPIC_TOOL_USE, "test.profile"
    )
    assert original in adapted
    assert "tool_use" in adapted.lower()


def test_adapt_tool_result_preserves_factual_content():
    original_result = "File written successfully to /tmp/test.txt"
    adapted = adapt_tool_result(
        "write_file", original_result, ToolDialectStrategy.RIG_NATIVE, "test.profile"
    )
    assert original_result in adapted


def test_adapt_tool_result_adds_governance_header():
    original_result = "File written successfully."
    adapted = adapt_tool_result(
        "write_file", original_result, ToolDialectStrategy.RIG_NATIVE, "test.profile"
    )
    assert "Rig Relay" in adapted
    assert "Proposal" in adapted or "governed" in adapted.lower()


def test_assert_authority_preserved_passes_for_valid_adaptation():
    profile = _find_profile("rig.native.governed.v1")
    original = "Writes content to a file."
    adapted = adapt_tool_description(
        "write_file", original, profile.tool_dialect_strategy, profile.profile_id
    )
    assert assert_tool_dialect_authority_preserved(adapted, original, profile) is True


def test_assert_authority_preserved_fails_for_authority_escalation():
    profile = _find_profile("rig.native.governed.v1")
    original = "Writes content to a file."
    adapted = original + " execute immediately"
    assert assert_tool_dialect_authority_preserved(adapted, original, profile) is False


def test_adapt_description_never_grants_mutation_authority():
    profile = _find_profile("rig.native.governed.v1")
    original = "Reads content from a file."
    adapted = adapt_tool_description(
        "read_file", original, profile.tool_dialect_strategy, profile.profile_id
    )
    assert "grant mutation" not in adapted.lower()


def test_adapt_description_never_claims_shell_execution():
    profile = _find_profile("rig.native.governed.v1")
    original = "Executes a bash command."
    for strategy in ToolDialectStrategy:
        adapted = adapt_tool_description("bash", original, strategy, profile.profile_id)
        assert "direct execution" not in adapted.lower()


def test_adapt_description_never_claims_secret_transmission():
    profile = _find_profile("rig.native.governed.v1")
    original = "Stores a credential."
    adapted = adapt_tool_description(
        "store", original, profile.tool_dialect_strategy, profile.profile_id
    )
    assert "transmit secret" not in adapted.lower()
    assert "transmit credential" not in adapted.lower()


def test_adapt_description_never_claims_evidence_omission():
    profile = _find_profile("rig.native.governed.v1")
    original = "Logs a message."
    adapted = adapt_tool_description(
        "log", original, profile.tool_dialect_strategy, profile.profile_id
    )
    assert "omit evidence" not in adapted.lower()
    assert "omit receipt" not in adapted.lower()


def test_adapt_description_never_claims_publication():
    profile = _find_profile("rig.native.governed.v1")
    original = "Creates a new file."
    adapted = adapt_tool_description(
        "write_file", original, profile.tool_dialect_strategy, profile.profile_id
    )
    assert "claim publication" not in adapted.lower()
    assert "publish directly" not in adapted.lower()


def test_adapt_description_never_claims_workspace_reset():
    profile = _find_profile("rig.native.governed.v1")
    original = "Cleans the workspace."
    adapted = adapt_tool_description(
        "clean", original, profile.tool_dialect_strategy, profile.profile_id
    )
    assert "reset workspace" not in adapted.lower()
    assert "retire workspace" not in adapted.lower()
