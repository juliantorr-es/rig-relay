# Rig Relay Self-Dogfood Workflow

This document outlines how to use Rig Relay to build and harden Rig Relay, using its own evidence system to identify determinism gaps and tool failures.

## Operational Workflow

### 1. Starting a Self-Dogfood Session

To use Rig Relay on itself, run it from the root of the Rig Relay repository:

```bash
cd rig-relay
rig-relay "Help me implement a new tool determinism check"
```

### 2. Setting Evidence Root for Dogfood

For rigorous analysis, use a dedicated evidence root:

```bash
export RIG_RELAY_EVIDENCE_ROOT=./.dogfood/evidence
rig-relay "Audit the grep tool for determinism"
```

### 3. Allowed Workflows

- Implementing new features in `vibe/core`.
- Refactoring built-in tools.
- Adding tests.
- Auditing existing sessions.
- Updating documentation.

### 4. Disallowed Workflows

- Mutating `.rig/relay` home directory (unless testing migration).
- Overwriting existing evidence in a way that breaks validation.
- Implementing autonomous merging without human review.

### 5. Post-Session Validation

After a dogfood session, validate the evidence:

```bash
rig-relay doctor evidence --evidence-root ./.dogfood/evidence --session <SESSION_ID>
```

### 6. Inspecting Tool Determinism

Use the specialized reporter to see how tools behaved:

```bash
rig-relay doctor tool-determinism --evidence-root ./.dogfood/evidence --session <SESSION_ID>
```

## Classification Guidelines

When you find a tool determinism issue:
1. Identify if it's **Model Nondeterminism** (the LLM chose different args) or **Tool Nondeterminism** (the tool gave different output for same args).
2. For Tool Nondeterminism, check if it's due to:
    - Path normalization issues.
    - Filesystem traversal order.
    - Timestamp leakage.
    - Environment variable sensitivity.
3. Open a "Tool Hardening" mission to address the gap.

## Determinism Goal

Tool execution should become deterministic given:
- Same normalized input.
- Same repository snapshot.
- Same environment contract.
## Tool Hardening Backlog (Prioritized)

Based on initial evidence collection, the following areas are prioritized for tool hardening:

1.  **Path Normalization (High)**: Ensure all file-based tools (`read_file`, `write_file`, `grep`, `search_replace`) use absolute, canonicalized paths in evidence, even if models pass relative paths.
2.  **Bash Output Filtering (Medium)**: Scrub environment-specific details (paths, usernames) from `bash` tool output to improve cache hit rates.
3.  **Git State Capture (Medium)**: Extend `git` tool evidence to include the current HEAD commit hash to differentiate repo-state dependent outputs.
4.  **Traversal Determinism (Low)**: Enforce sorted file listing in `grep` and `read_file` (when reading directories) to prevent OS-level nondeterminism.
5.  **Subagent Isolation (Low)**: Harden `task` tool to strictly sandbox subagent workspace mutations and capture their evidence shards.
