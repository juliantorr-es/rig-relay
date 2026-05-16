# RuntimeSupervisor Result Envelope v1

**Date**: 2026-05-16

## Summary

`RuntimeSupervisorResultEnvelope` is the canonical terminal evidence shape for
supervised subprocess execution. It is built at the invocation boundary by
`SupervisorCommandInvoker` from:

- terminal stream event classification
- command and cwd digests
- timing facts
- output digests and byte counts
- safe trace context
- state machine projection facts

The envelope is content-light and privacy-preserving. It does not carry raw
stdout, raw stderr, raw argv strings, or raw cwd values.

## Root Cause

Before this slice, `RuntimeSupervisor` produced terminal stream events and
`SupervisorCommandInvoker` converted those events into a flat result model.
Downstream layers could only infer subprocess meaning by reinterpreting raw
fields, which encouraged divergent vocabularies and duplicated result shapes.

## Cleanup / Normalization

This slice introduced a stable envelope model with a single terminal
classification vocabulary:

- `completed`
- `failed`
- `timed_out`
- `killed`
- `cancelled`
- `spawn_failed`
- `cleanup_failed`
- `errored`
- `refused`

The envelope also carries:

- command digest
- cwd digest
- output digest
- timing
- resource usage
- safe error details
- cleanup status
- trace/evidence identifiers
- state machine projection

## Semantics

Existing caller-facing subprocess output behavior remains unchanged. The flat
result still exposes stdout/stderr text to direct callers that expect it.
The envelope is additive evidence, not a replacement for the user-facing result.

## Tests

Covered by:

- `tests/runtime/test_runtime_supervisor_result_envelope.py`
- `tests/runtime/test_runtime_supervisor.py`
- `tests/runtime/test_runtime_supervisor_state_machine.py`
- `tests/runtime/test_runtime_supervisor_teardown.py`
- `tests/tracing/test_runtime_supervisor_tracing.py`

These tests prove:

- success, non-zero exit, timeout, spawn failure, and cancellation all produce
  envelopes
- privacy-sensitive fields are excluded from the envelope
- trace classification stays aligned with the envelope classification
- the state projection matches the terminal lifecycle
- the envelope builder is pure

## Remaining Gaps

The envelope is wired at the supervisor invocation boundary. Downstream
consumers still need to adopt it directly:

- `ToolRuntime`
- `validate`
- desktop diagnostics
- future `SubagentRuntime`

Those consumers currently still rely on the existing flat result contract.
