# Mission Envelope Spine Design

## Summary

Rig Relay does not need the full ADR/Sprint/Mission hierarchy wired into the executable path before it can have governed runtime context.

The smallest useful bridge is a mission envelope:

- one mission object
- one reproducible context packet
- one receipt path
- optional ADR/Sprint metadata

## Why Mission-First

The executable system currently has enough pieces to support a mission-shaped run:

- runtime context resolution
- dirty-file guardrails
- worktree management
- execution request and lease gating
- tool receipts and receipt indexing

What it does not need yet is a fantasy-level orchestration tree that must be perfect before anything can run.

## Minimal Envelope Contract

The mission envelope should support:

- `mission_id`
- `title`
- optional `adr_id`
- optional `sprint_id`
- `repo_root`
- `branch`
- `head`
- `dirty_status_fingerprint` or `dirty_file_summary`
- `allowed_paths`
- `protected_paths`
- `instruction_paths`
- `acceptance_checks`
- `handoff_required`
- `created_at`
- `schema_version`

## Context Packet Compilation

The context packet should be compiled from what exists today:

- `AGENTS.md`
- git branch/HEAD/status
- dirty file inventory
- task prompt
- allowed/protected paths
- validation commands
- explicitly listed docs
- prior handoff text, if provided

## Receipt First

The bridge should produce a receipt before it attempts any retrieval or higher-level orchestration.

That receipt should capture:

- `packet_id`
- `mission_id`
- `compiled_at`
- input paths and hashes
- branch
- head
- dirty fingerprint

## Relationship to Later Hierarchy

ADR and sprint metadata can be added later as optional references without changing the mission identity or the compiled packet contract.

That keeps the bridge stable while the higher-level orchestration matures.

