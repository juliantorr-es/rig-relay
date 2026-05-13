# Rig Relay Self-Dogfood Workflow

This document outlines how to use Rig Relay to build and harden Rig Relay, using its own evidence system to identify determinism gaps and tool failures. Rig Relay is the product; providers are interchangeable backends.

## Operational Workflow

### 1. Starting a Self-Dogfood Session

To use Rig Relay on itself, run it from the root of the Rig Relay repository. By default, evidence will be stored in your global Relay home (`~/.rig/relay`):

```bash
cd rig-relay
rig-relay "Help me implement a new tool determinism check"
```

### 2. Setting Evidence Root for Dogfood

Normal dogfood sessions should use the global Relay home. However, to isolate a test or experiment (e.g., to keep dogfood evidence separate from your main history), use `RIG_RELAY_HOME`:

```bash
RIG_RELAY_HOME=./.dogfood rig-relay "Audit the grep tool for determinism"
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
- Creating unstructured artifacts that do not adhere to [Artifact Schema Doctrine](../audits/artifact-schema-doctrine.md).

### 5. Post-Session Validation

After a dogfood session, validate the evidence. If you used the default global home, you don't need to pass `--evidence-root`. If you used an isolated root (e.g., via `RIG_RELAY_HOME=./.dogfood`), point the doctor there:

```bash
rig-relay doctor evidence --evidence-root ./.dogfood --session <SESSION_ID>
```

> [!NOTE]
> When using `RIG_RELAY_HOME=./.dogfood`, the evidence root passed to the doctor is `./.dogfood`.

### 6. Inspecting Tool Determinism

Use the specialized reporter to see how tools behaved:

```bash
rig-relay doctor tool-determinism --evidence-root ./.dogfood --session <SESSION_ID>
```

### 7. Inspecting Tool Reasoning and Latency

Rig Relay records structured reasoning traces for every tool call — latency, byte sizes, determinism class, and observable rationale — without capturing hidden chain-of-thought.

Report with the reasoning tracer:

```bash
rig-relay doctor tool-reasoning --evidence-root ./.dogfood --session <SESSION_ID>
```

JSON output is supported:

```bash
rig-relay doctor tool-reasoning --evidence-root ./.dogfood --session <SESSION_ID> --json
```

The report shows:
- Slowest tool calls (latency candidates)
- Largest inline outputs (token-pressure candidates)
- Largest artifacted outputs
- Calls missing observable rationale
- Retry/error patterns
- Aggregate latency and byte metrics

## Latency-First Design Principle

Tool-output latency takes priority over model magic. The fastest latency wins come from making tools produce compact, typed, reusable artifacts so the model sees handles + summaries instead of huge raw outputs. Tool content should stay in the dynamic suffix (later in the prompt) so stable prefixes remain cacheable.

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

1.  **Mutation Evidence Hashes (Completed 2025-05-17)**: `write_file` and `search_replace` now emit before/after SHA256 content hashes, creation/overwrite flags, block counts, and changed file lists. See `WriteFileResult` and `SearchReplaceResult`.
2.  **Typed File Write/Diff Artifacts (Next)**: Add structured `file_write` artifact envelopes and diff/patch evidence for `write_file` and `search_replace` to enable autonomous promotion gates and rollback.
3.  **Path Normalization (High)**: Ensure all file-based tools (`read_file`, `write_file`, `grep`, `search_replace`) use absolute, canonicalized paths in evidence, even if models pass relative paths.
4.  **Bash Output Filtering (Medium)**: Scrub environment-specific details (paths, usernames) from `bash` tool output to improve cache hit rates.
5.  **Git State Capture (Medium)**: Extend `git` tool evidence to include the current HEAD commit hash to differentiate repo-state dependent outputs.
6.  **Traversal Determinism (Low)**: Enforce sorted file listing in `grep` and `read_file` (when reading directories) to prevent OS-level nondeterminism.
7.  **Subagent Isolation (Low)**: Harden `task` tool to strictly sandbox subagent workspace mutations and capture their evidence shards.

## Future Hardening Tracks

1.  **Mutation Evidence Hashing (Completed)**: `write_file` and `search_replace` now emit before/after SHA256 hashes. See [current built-in tools audit](../audits/current-built-in-tools.md).
2.  **Typed File Write/Diff Evidence (Next)**: Add structured `file_write` artifact envelopes and diff/patch evidence for write tools to enable autonomous promotion gates.
3.  **Fuzzy Search Hardening (Deferred)**: Audit fuzzy matching behavior in `search_replace` to reduce wrong-edit risk at the matching threshold boundary.
4.  **Semantic Placement (Deferred)**: Audit `semantic_placement` artifacts to ensure edits land in the correct symbols.
5.  **Token Optimization**: Analyze artifact kind density to identify candidates for summarization or deduplication based on [Artifact Schema Doctrine](../audits/artifact-schema-doctrine.md).
