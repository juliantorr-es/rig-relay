# Read-Only Inspection Tool Gaps

## Inventory

Primary read-only inspection tools in the builtin registry:

- `read_file`
- `grep`

Secondary inspection-adjacent helpers:

- `webfetch`
- `websearch`
- directory / metadata inspection helpers where used through bash

## Current Behavior

### `read_file`

- structured args/result: present
- path safety: present
- byte cap: present
- truncation flag: present
- binary/content policy: partially implicit through safe decoding
- receipt model: missing
- content-light receipt: missing

### `grep`

- structured args/result: present
- path safety: present
- output cap / truncation: present
- parsed match model: present
- receipt model: missing
- content-light receipt: missing

## Observed Pressure

From the existing usage analysis:

- `read_file`: 3,970 calls, 14 failures
- `grep`: 1,243 calls, 4 failures

These are lower mutation-risk than bash or write tools, but they still carry the highest privacy and token-cost pressure because they return content directly.

## Desired Hardening

- deterministic caps
- explicit truncation flags
- structured statuses
- byte counts
- content hashes where the surface can do so safely
- content-light receipts
- clear path refusal behavior
- binary-safe handling

## Priority Order

1. `read_file`
2. `grep`
3. other directory / metadata inspection helpers

## Why They Matter

Read-only tools are the easiest way to leak too much data into prompts, receipts, or logs. Their hardening priority is lower than mutation tools, but their privacy risk is still high because they are used constantly.
