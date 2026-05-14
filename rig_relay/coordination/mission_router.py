"""Rig Fleet Mission Router — Phase 0.

Plans and routes mission batches into governed fleet primitives.
Provides deterministic heuristic classification, dependency planning,
and queue item compilation.

Content-light: never includes raw mission text in generic projection output.
Raw text is summary-only unless explicitly requested via payload_ref.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination.fleet_queue import FleetQueueItemKind

# ── Enums ────────────────────────────────────────────────────────────────


class MissionRoute(StrEnum):
    """Routing destinations for mission nodes."""

    LOCAL_RUNTIME = "local_runtime"
    DELEGATED_AGENT = "delegated_agent"
    FLEET = "fleet"
    PATCH_PROPOSAL = "patch_proposal"
    HUMAN_REVIEW = "human_review"
    BLOCKED = "blocked"


class MissionNodeStatus(StrEnum):
    """Lifecycle status of a mission node during planning."""

    PENDING = "pending"
    ROUTED = "routed"
    FAILED = "failed"


# ── Models ───────────────────────────────────────────────────────────────


class MissionBatch(BaseModel):
    """Input bundle of mission texts to be routed."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.mission_batch.v1"
    batch_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    user_request_summary: str
    mission_texts: list[str]
    requested_by: str
    default_policy: dict[str, Any] = Field(default_factory=dict)
    mission_id: str | None = None
    sprint_id: str | None = None
    adr_id: str | None = None


class MissionNode(BaseModel):
    """A single normalized mission node.

    Content-light: payload carries summary/metadata, never raw mission text.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str
    title: str
    summary: str
    payload_ref: str | None = None  # Reference to raw mission text
    sanitized_text_summary: str | None = None
    inferred_domains: list[str] = Field(default_factory=list)
    candidate_paths: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high", "critical"] = "low"
    estimated_size: Literal["small", "medium", "large", "massive"] = "small"
    status: MissionNodeStatus = MissionNodeStatus.PENDING
    route: MissionRoute | None = None
    refusal_reason: str | None = None


class MissionDependency(BaseModel):
    """Dependency link between mission nodes."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    depends_on: str  # node_id
    kind: Literal["must_complete", "affects_paths"] = "must_complete"


class MissionConflict(BaseModel):
    """Conflict record for overlapping mission nodes."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    other_node_id: str
    kind: Literal["path_overlap", "domain_overlap"]
    paths: list[str] = Field(default_factory=list)


class MissionAssignment(BaseModel):
    """Final routing assignment for a node."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    route: MissionRoute
    agent_id: str | None = None
    priority: int = 0


class MissionPlan(BaseModel):
    """The compiled plan for a mission batch.

    Content-light: provides summary of nodes and their routing, not raw text.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.fleet.mission_plan.v1"
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    batch_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    nodes: list[MissionNode] = Field(default_factory=list)
    dependencies: list[MissionDependency] = Field(default_factory=list)
    conflicts: list[MissionConflict] = Field(default_factory=list)
    runnable_groups: list[list[str]] = Field(default_factory=list)  # node_ids
    assignments: list[MissionAssignment] = Field(default_factory=list)


class MissionPlanSummary(BaseModel):
    """Content-light summary of a mission plan."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    batch_id: str
    node_count: int
    route_counts: dict[str, int]
    conflict_count: int
    created_at: str


# ── Router ────────────────────────────────────────────────────────────────


class MissionRouter:
    """Plans and routes mission batches into governed fleet primitives.

    Phase 0: Deterministic heuristic classification and planning.
    """

    def route_batch(self, batch: MissionBatch) -> MissionPlan:
        """Route a batch of missions into a unified plan."""
        nodes: list[MissionNode] = []
        raw_map: dict[str, str] = {}

        for i, text in enumerate(batch.mission_texts):
            node_id = f"node_{batch.batch_id}_{i:03d}"
            raw_map[node_id] = text
            node = self._normalize_node(node_id, text)
            nodes.append(node)

        # 1. Classify each node
        for node in nodes:
            raw_text = raw_map[node.node_id]
            node.route = self._classify_node(node, raw_text)
            node.status = MissionNodeStatus.ROUTED

        # 2. Build dependency/conflict plan
        conflicts = self._detect_conflicts(nodes)
        dependencies = self._inferred_dependencies(nodes, conflicts)

        # 3. Build assignments
        assignments = [
            MissionAssignment(node_id=n.node_id, route=n.route or MissionRoute.BLOCKED)
            for n in nodes
        ]

        # 4. Build runnable groups
        runnable_groups = self._build_runnable_groups(nodes, dependencies)

        return MissionPlan(
            batch_id=batch.batch_id,
            nodes=nodes,
            dependencies=dependencies,
            conflicts=conflicts,
            runnable_groups=runnable_groups,
            assignments=assignments,
        )

    def _normalize_node(self, node_id: str, text: str) -> MissionNode:
        """Heuristic normalization of raw text into a node."""
        # Extract title from first line or "Mission:" marker
        lines = text.strip().splitlines()
        first_line = lines[0] if lines else "Untitled Mission"
        title_match = re.search(r"Mission:\s*(.*)", text)
        title = title_match.group(1).strip() if title_match else first_line[:50]

        # Simple domain inference
        domains = []
        if any(w in text.lower() for w in ["docs/", "documentation", "markdown"]):
            domains.append("documentation")
        if any(w in text.lower() for w in ["tests/", "pytest", "unit test"]):
            domains.append("testing")
        if "rig_relay/runtime" in text.lower():
            domains.append("runtime_core")
        if "vibe/cli" in text.lower() or "tui" in text.lower():
            domains.append("tui")
        if ".json" in text.lower() or "schema" in text.lower():
            domains.append("schema")

        # Simple path extraction (looks for things that look like paths)
        paths = re.findall(r"([a-zA-Z0-9_\-/]+\.[a-zA-Z0-9]+)", text)
        candidate_paths = sorted(list(set(paths)))

        _SUMMARY_LEN = 100
        _SANITIZED_LEN = 200
        _MASSIVE_DOMAIN_COUNT = 3
        _MASSIVE_TEXT_LEN = 1000

        # Simple secret redaction (Phase 0)
        sanitized_text = re.sub(
            r"(key|secret|password|token|auth|pwd)=([^\s&]+)",
            r"\1=[REDACTED]",
            text,
            flags=re.IGNORECASE,
        )

        return MissionNode(
            node_id=node_id,
            title=title,
            summary=sanitized_text[:_SUMMARY_LEN]
            + ("..." if len(sanitized_text) > _SUMMARY_LEN else ""),
            sanitized_text_summary=sanitized_text[:_SANITIZED_LEN],
            inferred_domains=domains,
            candidate_paths=candidate_paths,
            required_capabilities=[],
            risk_level="high" if "runtime_core" in domains else "low",
            estimated_size="massive"
            if len(domains) >= _MASSIVE_DOMAIN_COUNT or len(text) > _MASSIVE_TEXT_LEN
            else "small",
        )

    def _classify_node(self, node: MissionNode, raw_text: str) -> MissionRoute:
        """Deterministic heuristic classifier."""
        text = raw_text.lower()

        # Destructive git language -> blocked or human_review
        destructive = [
            "git delete",
            "git reset",
            "git clean",
            "git stash",
            "git restore",
            "delete file",
            "remove directory",
        ]
        if any(w in text for w in destructive):
            return MissionRoute.HUMAN_REVIEW

        # Mentions approval/apply/merge -> human_review or patch_proposal
        if any(w in text for w in ["approve", "apply", "merge", "pull request"]):
            return MissionRoute.PATCH_PROPOSAL

        # Ambiguous broad mission -> fleet (high priority)
        if node.estimated_size == "massive":
            return MissionRoute.FLEET

        # Shared runtime core mutation -> patch_proposal
        if "runtime_core" in node.inferred_domains:
            return MissionRoute.PATCH_PROPOSAL

        # Schema/model/test isolated -> delegated_agent
        if node.inferred_domains and all(
            d in {"testing", "schema", "documentation"} for d in node.inferred_domains
        ):
            return MissionRoute.DELEGATED_AGENT

        # Default to local_runtime for small targeted missions
        return MissionRoute.LOCAL_RUNTIME

    def _detect_conflicts(self, nodes: list[MissionNode]) -> list[MissionConflict]:
        """Detect overlapping candidate paths and shared domains."""
        conflicts: list[MissionConflict] = []
        for i, n1 in enumerate(nodes):
            for n2 in nodes[i + 1 :]:
                # Path overlap
                overlap = set(n1.candidate_paths) & set(n2.candidate_paths)
                if overlap:
                    conflicts.append(
                        MissionConflict(
                            node_id=n1.node_id,
                            other_node_id=n2.node_id,
                            kind="path_overlap",
                            paths=sorted(list(overlap)),
                        )
                    )
                # Domain overlap (critical domains)
                critical_domains = {"runtime_core", "tui", "schema"}
                domain_overlap = (
                    set(n1.inferred_domains) & set(n2.inferred_domains)
                ) & critical_domains
                if domain_overlap:
                    conflicts.append(
                        MissionConflict(
                            node_id=n1.node_id,
                            other_node_id=n2.node_id,
                            kind="domain_overlap",
                        )
                    )
        return conflicts

    def _inferred_dependencies(
        self, nodes: list[MissionNode], conflicts: list[MissionConflict]
    ) -> list[MissionDependency]:
        """Infers dependencies between nodes, including conflict serialization."""
        deps: list[MissionDependency] = []
        # Phase 0: turn conflicts into sequential dependencies to be safe
        for c in conflicts:
            # Ensure deterministic order: lower node_id runs first
            n1, n2 = sorted([c.node_id, c.other_node_id])
            deps.append(
                MissionDependency(node_id=n2, depends_on=n1, kind="affects_paths")
            )
        return deps

    def _build_runnable_groups(
        self, nodes: list[MissionNode], deps: list[MissionDependency]
    ) -> list[list[str]]:
        """Group nodes into parallelizable batches based on dependencies."""
        if not deps:
            return [[n.node_id for n in nodes]]

        ordered_groups = []
        remaining = set(n.node_id for n in nodes)

        while remaining:
            # Find nodes in 'remaining' that have no dependencies also in 'remaining'
            ready = []
            for node_id in sorted(list(remaining)):
                is_ready = True
                for d in deps:
                    if d.node_id == node_id and d.depends_on in remaining:
                        is_ready = False
                        break
                if is_ready:
                    ready.append(node_id)

            if not ready:
                # Cycle or missing nodes — serialize the rest as a fallback
                ordered_groups.append(sorted(list(remaining)))
                break

            ordered_groups.append(ready)
            for r in ready:
                remaining.remove(r)

        return ordered_groups

    def compile_to_queue_items(self, plan: MissionPlan) -> list[dict[str, Any]]:
        """Compile a plan into FleetQueueItem templates.

        Does not enqueue or execute.
        """
        templates = []
        for n in plan.nodes:
            route = n.route or MissionRoute.BLOCKED

            # Select queue item kind based on route
            if route == MissionRoute.LOCAL_RUNTIME:
                kind = FleetQueueItemKind.RUNTIME_EXEC
            elif route == MissionRoute.DELEGATED_AGENT:
                kind = (
                    FleetQueueItemKind.RUNTIME_EXEC
                )  # Use runtime_exec for agents too
            elif route == MissionRoute.FLEET:
                kind = FleetQueueItemKind.MESSAGE  # Phase 0: fleet missions as messages
            elif route == MissionRoute.PATCH_PROPOSAL:
                kind = FleetQueueItemKind.MESSAGE
            elif route in {MissionRoute.HUMAN_REVIEW, MissionRoute.BLOCKED}:
                kind = FleetQueueItemKind.PAUSE
            else:
                kind = FleetQueueItemKind.MESSAGE

            # Find dependencies for this node
            depends_on = [
                d.depends_on for d in plan.dependencies if d.node_id == n.node_id
            ]

            template = {
                "kind": str(kind),
                "priority": 50,
                "depends_on": sorted(depends_on),
                "mission_id": plan.batch_id,
                "payload": {
                    "node_id": n.node_id,
                    "title": n.title,
                    "summary": n.summary,
                    "route": str(route),
                    "sanitized_text_summary": n.sanitized_text_summary,
                },
            }
            templates.append(template)
        return templates
