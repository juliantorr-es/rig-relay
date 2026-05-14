# Schema Gaps

- Missing core fields detected: `0`
- Raw content keys seen: `content`

Recommended additions:
- explicit `tool_name`, `status`, `duration_ms`, `output_bytes`, `error_kind`, `receipt_id`, `schema_version`
- normalized outcome field for success/failure/skipped/refused
- stable tool invocation id and session id linkage
- redaction-safe hashes for any content-bearing fields

Forbidden fields in shared reports:
- raw prompts
- raw args
- raw stdout/stderr
- raw completions or transcripts
- raw private file contents
