# WriteFile Hardening State

## Current Status (Post-Closure)

WriteFile has reached near-parity with SearchReplace on evidence maturity.

## Current State

- structured invocation model: present
- structured result model: partial (carries `content` field for backwards compatibility)
- structured receipt model: **complete** (WriteFileReceipt, 16 fields, extra="forbid")
- `build_receipt()`: **complete** (content-light, sanitized refusal_reason)
- schema coverage: **added** (rig.relay.write_file_receipt.v1)
- receipt emission compatibility: **complete** (duck-typed into agent loop)
- receipt policy validation: **complete** (tested via test_tool_receipt_emission.py)
- receipt index compatibility: **complete** (write_file case in receipt_index.py)
- before/after hashes: present (success path only)
- before/after byte counts: complete (before_bytes from snapshot, after_bytes from file stat)
- created vs overwritten status: present
- path safety: present
- outside-workspace refusal: present
- atomicity: complete (tempfile + os.replace atomic pattern)

## Remaining Gaps

1. **content still in WriteFileResult** — Legacy callers may depend on it. See `docs/audits/tool-hardening/write-file-legacy-result-content-audit.md` — recommended to keep, mark as deprecated.
2. **Permission preservation** — Only mode bits preserved after atomic replace (ACLs/xattrs dropped).

## Gap Closure Reference

See `docs/audits/tool-hardening/write-file-receipt-gap-closure.md` for the detailed closure report.
