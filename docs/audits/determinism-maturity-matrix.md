# Audit: Determinism Maturity Matrix
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: 24c990e011375078a04cb4a5534d114f98c064ed
Scope: Read-only audit
Owner area: evidence

## Executive Summary
Rig Relay is currently at **Level 1 (Partially Controlled)** for most core components. While it has a deterministic serialization foundation (`dump_canonical_json`), it suffers from "Ambient Environment Dependency" (global home paths, unsorted filesystem traversal, random IDs).

## Findings Matrix
| ID | Area | Level | Priority | Owner | Files | Risk |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **DET-001** | Evidence root resolution | 1 | P0 | config | `_vibe_home.py` | Global home defaults mix প্রকল্পের state. |
| **DET-002** | Session/run identity | 1 | P2 | identity | `agent_loop.py` | Random UUIDs make sessions non-reproducible. |
| **DET-003** | Observability JSONL emission | 2 | P1 | logging | `local.py` | Timestamp-only ordering depends on wall-clock. |
| **DET-004** | Artifact file creation | 2 | P1 | artifact | `artifacts.py` | Filenames are non-deterministic (UUID). |
| **DET-005** | Context assembly | 1 | P0 | context | `assembler.py` | Assembly bypasses outside the _chat path. |
| **DET-006** | Serialization | 3 | P1 | serial | `local.py` | Key ordering is canonical but not enforced for all dicts. |

## Detailed Findings
### DET-001: Global Home Bias
Location: `vibe/core/paths/_vibe_home.py`
Risk: All evidence from all projects ends up in one folder, making per-run validation and cleanup difficult.
Recommendation: Implement local-first resolution (Git root discovery).

## Recommended Backlog
1.  **Mission: Monotonic Sequence Enforcer**: Add sequence numbers to all JSONL events.
2.  **Mission: Content-Addressed Evidence**: Use hashes for session and artifact IDs.
3.  **Mission: Canonical Traversal**: Enforce `sorted()` on all directory walks/glob results.
