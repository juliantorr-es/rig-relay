# Artifact Tracking Policy

## Status

**Draft.** Defines what generated artifacts may be tracked in Rig Relay.

## Core Rule

Tracked source should stay small, durable, and reviewable. Generated runtime
artifacts belong in `.build/` or another explicit runtime root unless a file is
deliberately curated as a fixture or proof.

## Do Not Track

- Session logs
- Coordination state
- Telemetry bundles
- Chat transcripts
- Desktop projections
- Validation outputs
- Derived evaluation dumps
- Upload payloads
- Temporary demo outputs
- Raw evidence snapshots

## Track Only When Curated

- Minimal fixtures needed for tests
- Hand-authored docs and policies
- Schemas
- Explicit demo assets
- Proof artifacts that are documented as part of the release workflow

## Alpha Policy

- Keep `.build/` out of source control unless a specific file is intentionally curated
- Do not expand tracked generated artifacts during alpha stabilization
- Prefer regeneration over versioning for runtime outputs
- Keep release commits focused on source, docs, schemas, and tests

## Validation

- Review `git status` before commit
- Confirm generated artifacts are not being staged unintentionally
- Keep public-facing docs content-light and free of raw evidence

