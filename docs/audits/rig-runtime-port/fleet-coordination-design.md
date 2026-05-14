# Fleet Coordination Plane — Design Audit

**Date:** 2026-05-14
**Status:** Design Reviewed

## 1. Context

Rig Relay is evolving from a single-agent session model to a multi-agent fleet model. The current "Cross-Session Coordination" (local, file-backed) provides basic path and task isolation but does not scale to a fleet where many agents might need to mutate shared files.

## 2. Problem Statement

Parallel agents currently collide when editing shared files. While Git worktrees provide isolation, managing 20+ worktrees for a single mission is ergonomically and computationally expensive.

## 3. Design Principles

1. **Orchestrator Ownership**: The orchestrator is the only entity that mutates the canonical worktree.
2. **Patch-Based Workflow**: Agents submit `PatchProposals` for shared resources.
3. **Receipt-Backed Coordination**: Every coordination action (lease, message, patch) emits an event in a canonical JSONL stream.
4. **Content-Light Events**: Events contain hashes and metadata, never raw prompts, secrets, or large blobs.

## 4. Assessment of Proposed Entities

### AgentSession
- **Strengths**: Provides stable identity for audit and lease ownership.
- **Risks**: Stale sessions must be cleaned up to avoid holding leases indefinitely.

### WorkClaim & PathLease
- **Strengths**: Reuses successful concepts from existing cross-session coordination.
- **Risks**: Lease granularity (per-file vs. per-directory) needs to be balanced for performance vs. isolation. Salted hashes of paths are used for privacy.

### AgentMessage & PatchProposal
- **Strengths**: Enables the "agents propose; orchestrator disposes" model. Decouples thinking from mutation.
- **Risks**: Orchestrator review latency could become a bottleneck. Automated patch validation is required.

## 5. Storage and Indexing

- **Canonical JSONL**: Append-only log is robust and auditable.
- **DuckDB Boundary**: Using DuckDB as a read-only index is the correct posture. It avoids multi-process write contention and keeps the source of truth simple (files).
- **Local-First**: Staying under `.rig/fleet/` (within the project root) maintains the "no daemon" philosophy.

## 6. Failure Modes and Mitigation

| Failure | Mitigation |
|---------|------------|
| Agent Crash | Heartbeat monitor in orchestrator marks leases as `stale`. |
| Network/FS Partition | Atomic file replacement and `flock` as local guards. |
| Duplicate Event IDs | Idempotency checks at the store layer. |
| Stale Lease Conflict | Takeover protocol requiring fresh dirty snapshots. |

## 7. Migration Path

1. **Phase 1 (Current)**: Implement schemas and governance docs.
2. **Phase 2**: Implement `FleetCoordinationStore` with JSONL backing.
3. **Phase 3**: Implement `PatchProposal` artifact generation in agents.
4. **Phase 4**: Implement `MergeDecision` applier in orchestrator.

## 8. Conclusion

The proposed Fleet Coordination Plane design correctly centralizes mutation authority while decentralizing thought. It avoids the scaling limits of Git worktrees by moving to a structured patch-proposal mechanism. The use of salted hashes and content-light events preserves the project's privacy and observability standards.
