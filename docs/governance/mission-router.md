# Rig Mission Router — Phase 0

**Status: Phase 0 — Deterministic Planning & Routing (Complete).**

## 1. Vision

The Rig Mission Router is the "brain" of the fleet orchestrator. It accepts unstructured or semi-structured mission requests from users, normalizes them into a graph of mission nodes, classifies them according to risk and capability, and produces a deterministic execution plan.

The router moves Rig from "one mission at a time" to "batch mission orchestration".

## 2. Core Workflow

1.  **Intake**: Accept a `MissionBatch` (a bundle of raw mission texts).
2.  **Normalization**: Parse raw text into `MissionNode` metadata (titles, domains, paths, size).
3.  **Classification**: Determine the `MissionRoute` for each node based on heuristics.
4.  **Dependency Planning**: Detect path and domain overlaps; serialize conflicting missions.
5.  **Grouping**: Organize nodes into `runnable_groups` that can be dispatched sequentially or in parallel.
6.  **Compilation**: Compile the plan into `FleetQueueItem` templates for the fleet queue.

## 3. Mission Route Types

| Route | Destination | Description |
|---|---|---|
| `local_runtime` | Local orchestrator | High-trust, low-risk missions requiring direct tool access. |
| `delegated_agent` | Remote agent | Isolated missions (e.g., docs, tests) that can run in a separate process. |
| `fleet` | Fleet decomposition | Massive missions that need to be broken down into sub-missions. |
| `patch_proposal` | Patch submission | Missions mutating shared core components; requires orchestrator review. |
| `human_review` | Human operator | High-risk or destructive missions requiring explicit user approval. |
| `blocked` | None | Invalid or impossible missions. |

## 4. Routing Heuristics

The Phase 0 router uses a deterministic heuristic classifier:

*   **Destructive language**: Mentions of `git reset`, `git clean`, `git delete`, etc., route to `human_review`.
*   **Approval/Merge language**: Mentions of `approve`, `apply`, `merge`, or `PR` route to `patch_proposal`.
*   **Domain Isolation**: Missions restricted to `documentation`, `testing`, or `schema` domains route to `delegated_agent`.
*   **Runtime Core**: Missions touching `rig_relay/runtime` route to `patch_proposal` to ensure shared-state integrity.
*   **Scale**: Missions involving >= 3 domains or > 1000 chars of prompt route to `fleet` for further decomposition.
*   **Conflict Serialization**: If two missions in a batch overlap on candidate paths, the router adds a dependency to ensure they run sequentially.

## 5. Content-Light Boundary

The Mission Router adheres to the strict content-light principle:

*   **No raw prompts** in `MissionPlan` or `MissionNode` output.
*   **Summaries only**: `MissionNode` contains a `sanitized_text_summary` (first 200 chars) for UI/observability.
*   **Payload Ref**: The raw mission text is retained only behind a `payload_ref` or in the original `MissionBatch` artifact.
*   **No Blobs**: Projections never include file contents, diffs, secrets, or tool outputs.

## 6. Relationship to Fleet Queue

The `MissionPlan` is a static blueprint. To execute, it must be compiled into `FleetQueueItem` templates.

*   `local_runtime` and `delegated_agent` nodes become `runtime_exec` queue items.
*   `patch_proposal` and `fleet` nodes become `message` queue items in Phase 0 (signaling intent).
*   `human_review` and `blocked` nodes become `pause` queue items, blocking downstream progress until resolved.

## 7. Deferred Features (Post-Phase 0)

*   **LLM Decomposition**: Phase 0 uses simple regex/keyword heuristics. Future phases will use LLMs for deeper semantic planning.
*   **Dynamic Re-routing**: The plan is currently static at intake. Future versions will support mid-mission plan revision.
*   **Agent Spawning**: Real process/container management for `delegated_agent` is deferred.
*   **Patch Application**: Automatic application of patches from `patch_proposal` routes is deferred.
