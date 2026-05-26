"""Test malformed-call transducer — structural normalization, no fuzzy guessing."""

from __future__ import annotations

import hashlib
import json

from rig_relay.recovery.models import (
    AdmittedToolEntry,
    CanonicalToolSurfaceManifest,
    RawRecoveryInput,
    RecoveryRefusalCode,
)
from rig_relay.recovery.transducer import transduce


def _sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _entry(
    canonical_name: str,
    aliases: list[str] | None = None,
    mutation_class: str = "read_only",
    determinism_class: str = "deterministic_repo_state",
    args_schema_digest: str | None = None,
    arg_field_names: list[str] | None = None,
    recovery_admission_tier: str = "read_only_recoverable",
) -> AdmittedToolEntry:
    return AdmittedToolEntry(
        canonical_name=canonical_name,
        aliases=aliases or [],
        mutation_class=mutation_class,
        determinism_class=determinism_class,
        args_schema_digest=args_schema_digest or _sha256(canonical_name),
        arg_field_names=arg_field_names or [],
        recovery_admission_tier=recovery_admission_tier,  # type: ignore[arg-type]
    )


def _make_manifest() -> CanonicalToolSurfaceManifest:
    return CanonicalToolSurfaceManifest(
        manifest_id="test-manifest",
        generated_at="2026-01-01T00:00:00Z",
        manifest_digest=_sha256("test"),
        admitted_tools=[
            _entry("git_status", aliases=["git-status"], arg_field_names=["path"]),
            _entry(
                "read_file",
                aliases=["read-file"],
                arg_field_names=["file_path", "offset", "limit"],
            ),
            _entry(
                "write_file",
                aliases=["write-file"],
                mutation_class="writes_workspace",
                recovery_admission_tier="mutation_proposal_only",
                arg_field_names=["file_path", "content"],
            ),
            _entry(
                "bash",
                mutation_class="writes_workspace",
                determinism_class="nondeterministic_external_io",
                recovery_admission_tier="raw_shell_refuse",
                arg_field_names=["command", "workdir", "timeout"],
            ),
            _entry(
                "validate",
                recovery_admission_tier="validation_recoverable",
                arg_field_names=["command", "cwd", "env", "timeout"],
            ),
        ],
    )


_MANIFEST = _make_manifest()


def _raw(data: dict[str, object] | str, call_id: str = "c1") -> RawRecoveryInput:
    raw_str = data if isinstance(data, str) else json.dumps(data, sort_keys=True)
    return RawRecoveryInput(
        raw_emission=data, emission_sha256=_sha256(raw_str), call_id=call_id
    )


class TestCanonicalPassThrough:
    def test_canonical_dict_passes_through(self) -> None:
        result = transduce(
            _raw({"name": "git_status", "arguments": {"path": "."}}), _MANIFEST
        )
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "git_status"


class TestOpenAIWrapper:
    def test_function_wrapper_unwrapped(self) -> None:
        result = transduce(
            _raw({"function": {"name": "git_status", "arguments": {"path": "."}}}),
            _MANIFEST,
        )
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "git_status"
        assert "unwrap_function_object" in result.recovered_intent.rules_applied

    def test_nested_tool_wrapper(self) -> None:
        result = transduce(
            _raw({
                "function": {"name": "read_file", "arguments": {"file_path": "a.py"}}
            }),
            _MANIFEST,
        )
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "read_file"


class TestToolArgsWrapper:
    def test_tool_and_args_keys_unwrapped(self) -> None:
        result = transduce(
            _raw({"tool": "git_status", "args": {"path": "."}}), _MANIFEST
        )
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "git_status"

    def test_name_and_parameters_key_unwrapped(self) -> None:
        result = transduce(
            _raw({"name": "git_status", "parameters": {"path": "."}}), _MANIFEST
        )
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "git_status"


class TestDottedKeys:
    def test_dotted_function_keys_unpacked(self) -> None:
        result = transduce(
            _raw({"function.name": "git_status", "function.arguments": {"path": "."}}),
            _MANIFEST,
        )
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "git_status"


class TestExplicitAlias:
    def test_hyphen_variant_resolved(self) -> None:
        result = transduce(
            _raw({"name": "git-status", "arguments": {"path": "."}}), _MANIFEST
        )
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "git_status"
        assert "apply_explicit_alias" in result.recovered_intent.rules_applied


class TestInlineCallForm:
    def test_simple_inline_call(self) -> None:
        result = transduce(_raw("call:git_status{path:src}"), _MANIFEST)
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "git_status"
        assert result.recovered_intent.normalized_args == {"path": "src"}

    def test_inline_call_with_alias(self) -> None:
        result = transduce(_raw("call:git-status{path:.}"), _MANIFEST)
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "git_status"

    def test_inline_call_with_multiple_args(self) -> None:
        result = transduce(
            _raw("call:read_file{file_path:test.py,offset:10,limit:50}"), _MANIFEST
        )
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "read_file"
        assert result.recovered_intent.normalized_args["file_path"] == "test.py"

    def test_inline_call_with_integers(self) -> None:
        result = transduce(
            _raw("call:read_file{file_path:a.py,offset:10,limit:50}"), _MANIFEST
        )
        assert result.is_recovered
        assert result.recovered_intent.normalized_args["offset"] == 10

    def test_inline_call_with_booleans(self) -> None:
        result = transduce(_raw("call:validate{command:echo hi,timeout:30}"), _MANIFEST)
        assert result.is_recovered

    def test_inline_call_malformed_missing_brace(self) -> None:
        result = transduce(_raw("call:git_status{path:."), _MANIFEST)
        assert result.is_refused
        assert (
            result.refusal.refusal_code == RecoveryRefusalCode.MALFORMED_INLINE_SYNTAX
        )

    def test_inline_call_duplicate_keys_refused(self) -> None:
        result = transduce(_raw("call:git_status{path:a,path:b}"), _MANIFEST)
        assert result.is_refused


class TestRefusalCases:
    def test_unknown_tool_refused(self) -> None:
        result = transduce(
            _raw({"name": "nonexistent_tool", "arguments": {}}), _MANIFEST
        )
        assert result.is_refused

    def test_unlisted_alias_refused(self) -> None:
        result = transduce(_raw({"name": "getstatus", "arguments": {}}), _MANIFEST)
        assert result.is_refused
        assert result.refusal.refusal_code in (
            RecoveryRefusalCode.UNKNOWN_ALIAS,
            RecoveryRefusalCode.CANONICAL_TOOL_NOT_ADMITTED,
        )

    def test_bash_not_recoverable_in_manifest(self) -> None:
        result = transduce(
            _raw({"name": "bash", "arguments": {"command": "ls"}}), _MANIFEST
        )
        assert result.is_recovered
        assert result.recovered_intent.canonical_tool_name == "bash"

    def test_unsupported_wrapper_refused(self) -> None:
        result = transduce(_raw({"something": "weird"}), _MANIFEST)
        assert result.is_refused
        assert result.refusal.refusal_code == RecoveryRefusalCode.UNSUPPORTED_WRAPPER

    def test_shell_metacharacters_refused(self) -> None:
        result = transduce(_raw({"name": "ls; rm -rf /", "arguments": {}}), _MANIFEST)
        assert result.is_refused


class TestContentLight:
    def test_refusal_does_not_contain_raw_emission(self) -> None:
        result = transduce(_raw({"name": "unknown_x", "arguments": {}}), _MANIFEST)
        assert result.is_refused
        refusal_dict = json.loads(result.refusal.model_dump_json())
        assert "raw_emission" not in refusal_dict
        assert refusal_dict["original_emission_hash"].startswith("sha256:")

    def test_recovered_intent_contains_hashes_not_content(self) -> None:
        result = transduce(
            _raw({"name": "git_status", "arguments": {"path": "."}}), _MANIFEST
        )
        assert result.is_recovered
        intent_dict = json.loads(result.recovered_intent.model_dump_json())
        assert intent_dict["payload_digest"].startswith("sha256:")
        assert intent_dict["manifest_digest"].startswith("sha256:")
        # The intent carries arguments for the executor — that's by design
        assert result.recovered_intent.normalized_args is not None
