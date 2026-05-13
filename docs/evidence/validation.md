# Evidence Validation

## Evidence Model

Rig Relay stores evidence under a selected evidence root. A session is one
directory under that root, and the session directory contains:

- `observability.jsonl`: append-only JSON Lines telemetry for the session
- `context/`: context assembly, layout, and shadow-request reports when present
- `artifacts/tool-results/`: tool-output artifact JSON files when present
- `manifest.json`: a minimal session index when the session has been finalized

The validator checks the current session only. It does not repair, rewrite, or
generate missing evidence.

## Evidence Root Modes

The selected evidence root is classified as one of:

- `repo_local`
- `explicit_home`
- `user_global`
- `legacy_vibe_home`
- `test_temp`

Current precedence remains unchanged:

1. `RIG_RELAY_HOME`
2. default user-global Relay home
3. legacy fallback only when canonical home is absent and legacy config is allowed

Repo-local evidence is observable and supported for validation, but it is not
the default root policy.

## Doctor CLI

Validate one selected session:

```bash
rig-relay doctor evidence --evidence-root <path> --session <session-id>
rig-relay doctor evidence --evidence-root <path> --session <session-id> --json
```

Exit behavior:

- `0` for `pass` and `warn`
- `1` for `fail`

Human output includes:

- status
- evidence root
- session id
- root mode/source when available
- event count
- referenced file count
- unreferenced evidence file count
- malformed event count
- warnings
- failures

JSON output uses the same structured result fields.

`doctor evidence` is read-only:

- it reads existing evidence
- it does not mutate sessions
- it does not create manifests
- it does not repair missing files
- it does not change root resolution
- it does not scan global sessions unless the caller explicitly points it there

## Smoke Workflow

The canonical evidence smoke is provider-independent:

1. run the repo-local evidence smoke
2. identify the session root
3. validate that selected session with `doctor evidence`
4. expect manifest, observability, context, and artifact evidence when the smoke
   exercises those paths

Do not treat the CLI inspection smoke as evidence coverage. CLI inspection proves
command viability; the repo-local smoke proves the evidence-producing internals.

## Manifest Semantics

`manifest.json` lives at:

```text
<evidence_root>/sessions/<session_id>/manifest.json
```

It is a minimal canonical JSON index. Current entries include:

- `observability.jsonl`
- tool-output artifacts
- context assembly reports
- context layout reports
- shadow-request reports

Each entry records:

- `evidence_kind`
- relative path only
- file-byte SHA-256
- size in bytes
- event name when known

The validator prefers the manifest when present and falls back to scan-based
validation for legacy sessions without a manifest.

## Artifact Hash Semantics

Tool-output artifacts have two relevant hashes:

- `payload_sha256`: SHA-256 of the canonical payload object
- `artifact_record_sha256`: SHA-256 of the canonical artifact envelope without
  the self-referential hash field

`evidence_sha256` in observability events references the evidence contract used
by the current writer. For tool-output artifacts, the validator checks the
artifact record hash contract rather than blindly assuming the raw file bytes are
the event hash target.

## Partial Evidence Behavior

Expected behavior for incomplete sessions:

- missing evidence root: fail
- missing session directory: fail
- missing `observability.jsonl`: fail
- malformed JSONL: fail
- missing `rig.relay.session.started`: fail
- missing root metadata on an old session: warn
- missing manifest: warn, then scan fallback
- missing `rig.relay.session.closed`: warn
- missing referenced evidence file: fail
- hash mismatch: fail
- unsafe path or absolute path: fail
- unreferenced governed evidence file: fail
- optional context reports absent with no matching event: warn or ignore

## Next Layer

The current validator and manifest give us a local integrity gate: selected
session, file presence, relative-path safety, hash checks, and event/file parity.
The next layer is a receipt-chain or Merkle-backed design that adds chained
integrity across events and finalization receipts. That layer should build on the
validator and manifest instead of replacing them.

