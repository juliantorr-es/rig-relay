# WriteFile Final Gaps

## Current Hardening Status

WriteFile remains behind SearchReplace on evidence maturity.

## Observed State

- structured invocation model: present
- structured result model: partial
- structured receipt model: missing
- `build_receipt()`: missing
- schema coverage: missing
- receipt emission compatibility: missing
- receipt policy validation: missing
- receipt index compatibility: missing
- before/after hashes: partial
- before/after byte counts: partial
- created vs overwritten status: present
- path safety: present
- outside-workspace refusal: present
- atomicity: partial

## Final Gaps

1. **No receipt model**
   - WriteFile still lacks a content-light receipt envelope.

2. **No schema / schema tests**
   - There is no write_file receipt schema to validate against.

3. **No receipt emission path**
   - The generic receipt capture seam cannot help until the tool exposes `build_receipt()`.

4. **Incomplete structured result**
   - The result still carries raw content and does not yet provide a fully structured status taxonomy comparable to SearchReplace.

5. **Evidence standard gap**
   - There is not yet a direct proof that receipts exclude raw file contents.

## Hardening Target

WriteFile should reach parity with or exceed SearchReplace on:

- structured statuses
- content-light receipts
- hash and byte accounting
- overwrite/refusal semantics
- atomic write evidence
