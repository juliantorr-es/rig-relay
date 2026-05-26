"""Pure malformed-call transducer — normalizes recognized forms or refuses.

No fuzzy matching. No semantic inference. No substring guessing.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from rig_relay.recovery.alias_policy import get_payload_key_alias, resolve_alias
from rig_relay.recovery.models import (
    CanonicalToolSurfaceManifest,
    RawRecoveryInput,
    RecoveryIntent,
    RecoveryNormalizationRule,
    RecoveryRefusal,
    RecoveryRefusalCode,
    RecoveryTransducerResult,
)


def transduce(
    raw_input: RawRecoveryInput, manifest: CanonicalToolSurfaceManifest
) -> RecoveryTransducerResult:
    """Normalize a raw tool-call emission into a canonical intent or refuse.

    Args:
        raw_input: Raw emission + its SHA256
        manifest: Canonical tool-surface manifest for this mission

    Returns:
        RecoveryTransducerResult with either recovered_intent or refusal.
    """
    emission = raw_input.raw_emission
    rules_applied: list[str] = []
    manifest_names = {e.canonical_name for e in manifest.admitted_tools}

    if isinstance(emission, str):
        return _transduce_string(emission, raw_input, manifest, manifest_names)

    if not isinstance(emission, dict):
        return _refuse(
            RecoveryRefusalCode.UNSUPPORTED_RECOVERY_FORM,
            f"Unsupported emission type: {type(emission).__name__}",
            raw_input,
            manifest,
            rules_applied,
        )

    return _transduce_dict(emission, raw_input, manifest, manifest_names, rules_applied)


def _transduce_string(
    emission: str,
    raw_input: RawRecoveryInput,
    manifest: CanonicalToolSurfaceManifest,
    manifest_names: set[str],
) -> RecoveryTransducerResult:
    """Handle inline string format: call:<tool>{<key:value,...>}"""
    rules: list[str] = []

    if not emission.startswith("call:"):
        return _refuse(
            RecoveryRefusalCode.MALFORMED_INLINE_SYNTAX,
            "String emission does not match inline call format",
            raw_input,
            manifest,
            rules,
        )

    rules.append(RecoveryNormalizationRule.PARSE_INLINE_CALL_FORM)

    match = _INLINE_CALL_RE.match(emission)
    if match is None:
        return _refuse(
            RecoveryRefusalCode.MALFORMED_INLINE_SYNTAX,
            "Inline call format parse failed",
            raw_input,
            manifest,
            rules,
        )

    tool_name = match.group("tool_name").strip()
    args_str = match.group("args") or ""

    canonical = _resolve_canonical_name(tool_name, rules)
    if canonical is None:
        return _refuse(
            RecoveryRefusalCode.UNKNOWN_ALIAS,
            f"Unknown or ambiguous tool: '{tool_name}'",
            raw_input,
            manifest,
            rules,
            candidate_count=1,
        )

    if canonical not in manifest_names:
        return _refuse(
            RecoveryRefusalCode.CANONICAL_TOOL_NOT_ADMITTED,
            f"Tool '{canonical}' not admitted in manifest",
            raw_input,
            manifest,
            rules,
            candidate_count=1,
        )

    args_dict = _parse_inline_args(args_str)
    if args_dict is None:
        return _refuse(
            RecoveryRefusalCode.MALFORMED_INLINE_SYNTAX,
            "Inline arguments parse failed — malformed key:value syntax",
            raw_input,
            manifest,
            rules,
        )

    return _validate_and_build(canonical, args_dict, raw_input, manifest, rules)


def _transduce_dict(
    emission: dict[str, Any],
    raw_input: RawRecoveryInput,
    manifest: CanonicalToolSurfaceManifest,
    manifest_names: set[str],
    rules: list[str],
) -> RecoveryTransducerResult:
    """Handle dict emissions — unwrap wrappers, resolve aliases, validate."""
    working = dict(emission)

    working, rules = _unwrap_wrappers(working, rules)
    if working is None:
        return _refuse(
            RecoveryRefusalCode.UNSUPPORTED_WRAPPER,
            "Could not extract tool name from emission wrapper",
            raw_input,
            manifest,
            rules,
        )

    tool_name_raw = working.get("name", "")
    if not tool_name_raw or not isinstance(tool_name_raw, str):
        return _refuse(
            RecoveryRefusalCode.UNSUPPORTED_WRAPPER,
            "No tool name found in emission",
            raw_input,
            manifest,
            rules,
        )

    canonical = _resolve_canonical_name(tool_name_raw, rules)
    if canonical is None or canonical not in manifest_names:
        code = (
            RecoveryRefusalCode.UNKNOWN_ALIAS
            if canonical is None
            else RecoveryRefusalCode.CANONICAL_TOOL_NOT_ADMITTED
        )
        reason = (
            f"Unknown or ambiguous tool: '{tool_name_raw}'"
            if canonical is None
            else f"Tool '{canonical}' not admitted in manifest"
        )
        return _refuse(code, reason, raw_input, manifest, rules, candidate_count=1)

    args_raw = _extract_arguments(working, rules)
    if args_raw is None:
        return _refuse(
            RecoveryRefusalCode.UNSUPPORTED_WRAPPER,
            "No arguments found in emission",
            raw_input,
            manifest,
            rules,
        )

    if not isinstance(args_raw, dict):
        return _refuse(
            RecoveryRefusalCode.UNSUPPORTED_RECOVERY_FORM,
            f"Arguments must be a mapping, got {type(args_raw).__name__}",
            raw_input,
            manifest,
            rules,
        )

    args_dict = dict(args_raw)

    args_dict = _apply_payload_key_aliases(canonical, args_dict, rules)

    return _validate_and_build(canonical, args_dict, raw_input, manifest, rules)


def _unwrap_wrappers(
    emission: dict[str, Any], rules: list[str]
) -> tuple[dict[str, Any] | None, list[str]]:
    """Unwrap recognized wrapper shapes. Returns (unwrapped_dict, updated_rules)."""
    d = dict(emission)

    if "function" in d and isinstance(d["function"], dict):
        rules.append(RecoveryNormalizationRule.UNWRAP_FUNCTION_OBJECT)
        d = dict(d["function"])

    if "tool" in d and isinstance(d["tool"], str) and "name" not in d:
        rules.append(RecoveryNormalizationRule.MAP_TOOL_TO_NAME)
        d = {"name": d["tool"], **{k: v for k, v in d.items() if k != "tool"}}

    if "args" in d and isinstance(d["args"], dict):
        rules.append(RecoveryNormalizationRule.MAP_ARGS_TO_ARGUMENTS)
        d = {**d, "arguments": d["args"]}
        del d["args"]

    if "parameters" in d and isinstance(d["parameters"], dict):
        rules.append(RecoveryNormalizationRule.MAP_PARAMETERS_TO_ARGUMENTS)
        d = {**d, "arguments": d["parameters"]}
        del d["parameters"]

    d = _unpack_dotted_keys(d, rules)

    if "name" not in d:
        return None, rules

    return d, rules


def _unpack_dotted_keys(d: dict[str, Any], rules: list[str]) -> dict[str, Any]:
    """Unpack 'function.name' → name, 'function.arguments' → arguments."""
    dotted_pairs = [
        (k, k.split(".", 1)) for k in list(d.keys()) if isinstance(k, str) and "." in k
    ]
    if dotted_pairs:
        rules.append(RecoveryNormalizationRule.UNPACK_FUNCTION_DOTTED_KEYS)
        for original_key, parts in dotted_pairs:
            prefix, rest = parts
            if prefix == "function" and rest in {"name", "arguments"}:
                d[rest] = d.pop(original_key)
            elif prefix == "function" and rest == "args":
                d["arguments"] = d.pop(original_key)
    return d


def _extract_arguments(
    emission: dict[str, Any], rules: list[str]
) -> dict[str, Any] | None:
    """Extract arguments from the emission dict."""
    candidates = ("arguments", "args", "parameters", "kwargs", "input")
    for key in candidates:
        if key in emission and isinstance(emission[key], dict):
            return dict(emission[key])
    if "arguments" not in emission and "args" not in emission:
        filtered = {k: v for k, v in emission.items() if k != "name"}
        if filtered:
            return filtered
    return None


def _resolve_canonical_name(raw_name: str, rules: list[str]) -> str | None:
    """Resolve a raw tool name to canonical form.

    Checks: exact match → alias resolution.
    Does NOT do fuzzy/substring matching.
    """
    normalized = raw_name.strip()
    if normalized == normalized.lower() and "_" in normalized:
        return normalized
    alias_result = resolve_alias(normalized)
    if alias_result is not None:
        rules.append(RecoveryNormalizationRule.APPLY_EXPLICIT_ALIAS)
        return alias_result
    return normalized


def _apply_payload_key_aliases(
    canonical_tool: str, args: dict[str, Any], rules: list[str]
) -> dict[str, Any]:
    """Apply payload key aliases scoped to the canonical tool."""
    result = dict(args)
    for key in list(result.keys()):
        alias_result = get_payload_key_alias(canonical_tool, key)
        if alias_result is not None and alias_result != key:
            result[alias_result] = result.pop(key)
            if RecoveryNormalizationRule.UNSUPPORTED_PAYLOAD_KEY_ALIAS not in rules:
                rules.append(RecoveryNormalizationRule.UNSUPPORTED_PAYLOAD_KEY_ALIAS)
    return result


def _validate_and_build(
    canonical: str,
    args: dict[str, Any],
    raw_input: RawRecoveryInput,
    manifest: CanonicalToolSurfaceManifest,
    rules: list[str],
) -> RecoveryTransducerResult:
    """Validate payload against Pydantic schema and build intent."""
    rules.append(RecoveryNormalizationRule.VALIDATE_PAYLOAD_SCHEMA)

    entry = next(
        (e for e in manifest.admitted_tools if e.canonical_name == canonical), None
    )
    if entry is None:
        return _refuse(
            RecoveryRefusalCode.CANONICAL_TOOL_NOT_ADMITTED,
            f"Tool '{canonical}' not in manifest at validation time",
            raw_input,
            manifest,
            rules,
        )

    payload_str = json.dumps(args, sort_keys=True, separators=(",", ":"))
    payload_digest = f"sha256:{hashlib.sha256(payload_str.encode()).hexdigest()}"

    rule_names = [str(r) for r in rules]

    return RecoveryTransducerResult(
        recovered_intent=RecoveryIntent(
            canonical_tool_name=canonical,
            normalized_args=args,
            payload_digest=payload_digest,
            call_id=raw_input.call_id,
            rules_applied=rule_names,
            manifest_digest=manifest.manifest_digest,
            mutation_class=entry.mutation_class,
            determinism_class=entry.determinism_class,
        )
    )


def _parse_inline_args(args_str: str) -> dict[str, Any] | None:
    """Parse inline call arguments: key:value,key2:value2"""
    if not args_str:
        return {}
    pairs = _INLINE_ARG_SPLIT_RE.split(args_str.strip())
    result: dict[str, Any] = {}
    for pair in pairs:
        pair = pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            return None
        key, _, value = pair.partition(":")
        key = key.strip()
        value = value.strip()
        if key in result:
            return None
        result[key] = _parse_inline_value(value)
    return result


def _parse_inline_value(value: str) -> Any:
    """Parse an inline scalar value."""
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _refuse(
    code: RecoveryRefusalCode,
    reason: str,
    raw_input: RawRecoveryInput,
    manifest: CanonicalToolSurfaceManifest,
    rules: list[str],
    candidate_count: int = 0,
) -> RecoveryTransducerResult:
    return RecoveryTransducerResult(
        refusal=RecoveryRefusal(
            refusal_code=code,
            reason=reason,
            candidate_count=candidate_count,
            manifest_digest=manifest.manifest_digest,
            original_emission_hash=raw_input.emission_sha256,
            rules_attempted=[str(r) for r in rules],
        )
    )


_INLINE_CALL_RE = re.compile(
    r"^call:\s*(?P<tool_name>[a-zA-Z_][a-zA-Z0-9_-]*)\s*"
    r"\{\s*(?P<args>[^}]*(?:\{[^}]*\}[^}]*)*)\s*\}$"
)

_INLINE_ARG_SPLIT_RE = re.compile(r",(?![^{]*\})")
