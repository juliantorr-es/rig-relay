# WriteFile Legacy Result Content Audit

## Purpose

Audit all callers of `WriteFileResult.content` to determine whether the
field can be removed, deprecated, or must be retained.

## Current State

`WriteFileResult` has a `content: str` field that carries the raw file
content on success. On refused/blocked paths, `content=""`.

`WriteFileReceipt` (the evidence/observability path) explicitly excludes
`content` — it is content-light by construction.

## Known Callers

### Production callers

1. **ACP bridge** — `vibe/acp/tools/builtins/write_file.py`
   - Reads `result.content` to construct the `new_text` field in diff update events
   - **Dependency**: uses raw content for diff rendering
   - **Migration**: could use `args.content` instead since the write was successful and content matches — but `result.content` is the authoritative written content
   - **Risk if removed**: ACP diff updates would lose the new file content

2. **UI widget** — `vibe/cli/textual_ui/widgets/tool_widgets.py`
   - `WriteFileResultWidget` reads `self.result.content` for display truncation
   - **Dependency**: displays written content in the tool result panel
   - **Migration**: could show path + bytes + hashes instead, or keep content for display-only
   - **Risk if removed**: UI would show empty result for successful writes

### Test callers

3. **ACP tests** — `tests/acp/test_write_file.py`
   - `assert result.content == "Hello, world!"` and similar
   - **Dependency**: verifies content round-trip through ACP
   - **Migration**: could verify via `after_sha256` + `bytes_written` + path

4. **Receipt emission tests** — `tests/tools/test_tool_receipt_emission.py`
   - Construct `WriteFileResult(content="...")` to test `build_receipt()`
   - **Dependency**: only uses content to prove receipt excludes it
   - **Migration**: already safe — receipt tests assert `content` is absent from receipt

5. **Mutation contract tests** — `tests/tools/test_mutation_tool_contracts.py`
   - Construct `WriteFileResult(content="...")` for schema/policy tests
   - **Dependency**: only uses content as fixture data for receipt construction
   - **Migration**: could use empty string or minimal fixture

6. **Hardened tools tests** — `tests/tools/test_hardened_tools.py`
   - Construct `WriteFileResult(content=args.content, ...)` for result verification
   - **Dependency**: some tests check that result.content equals written content
   - **Migration**: most could verify via `after_sha256` instead

### Doc/Config callers

7. **Audit docs** — various `.md` files reference `WriteFileResult.content` as a known legacy field
   - No code dependency

## Recommended Fate

**Keep `WriteFileResult.content` for now, mark as deprecated.**

Rationale:
- ACP bridge has a real production dependency on `result.content` for diff rendering
- UI widget displays it
- Removing it would require updating the ACP bridge to use `args.content` and updating the UI widget
- The evidence path (receipt) is already safe — `WriteFileReceipt` excludes content
- A deprecation period allows callers to migrate

### Deprecation plan
1. Add a `@property` or docstring noting deprecation (not in this mission — Python Pydantic fields can't be easily deprecated with runtime warnings)
2. Document in the release notes that content may be removed in a future breaking change
3. Update ACP bridge to fall back to `args.content` if `result.content` is empty
4. Update UI widget similarly
5. Remove content in a future breaking-change slice after callers are migrated

## Conclusion

| Caller | Current dependency | Can migrate? | Migration path |
|--------|-------------------|--------------|----------------|
| ACP bridge (production) | `result.content` for diff | Yes | Use `args.content` on success |
| UI widget (production) | `result.content` for display | Yes | Use path + bytes + hashes |
| ACP tests | `result.content` assertions | Yes | Use `after_sha256` + `bytes_written` |
| Receipt tests | Fixture construction only | Already safe | N/A |
| Contract tests | Fixture construction only | Already safe | N/A |
| Hardened tools tests | Result verification | Yes | Use `after_sha256` |
