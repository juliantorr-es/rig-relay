# Rig Relay Operating Instructions

This file is the canonical project instruction bundle for Rig Relay.

[PRIMARY AXIOM] Move fast, close seams, and bias toward material architectural convergence. Govern proportionally. Subsystems MUST operate symbiotically. Rig Relay is a desktop application; you are building a main-bridge UI, not a text adventure.

[MANDATORY] Symbiotic Convergence & The Tachikoma Rule: Execute ambitious, atomic implementation slices. Agents operate in symbiotic parallel and coordinate asynchronously via shared state. A lane owning a live integration boundary MUST explicitly publish and release that boundary before another lane wires new capability through it. Live integrations MUST NOT silently collide.

[FORBIDDEN] Terminal Product Workflows: Rig Relay is a native desktop application. Application-domain behavior MUST NEVER be implemented or preserved as terminal workflows or CLI entry points. Legacy CLI product logic is migration debt: extract it into typed internal application services, wire to the desktop frontend and governed agent tools, and obliterate the CLI path. Terminal scripts are scaffolding, not a second control room.

[INVARIANT] Application Service Authority: All product actions MUST enter through typed internal application services. These services exclusively own validation, authorization, state transitions, and evidence emission. The desktop frontend and governed agent tools are peer callers; neither may bypass domain authority.

[CRITICAL] Migration Debt Closure: When migrating legacy workflows, the owning lane MUST extract the domain logic, wire the required callers, delete the obsolete entry point entirely, and add structural tests proving the deleted path does not regrow.

[DIRECTIVE] Convergent Passes (Equivalent Exchange): Every ordinary implementation pass MUST close its identified seam and land the nearest production capability enabled by that repair. During a declared closure pass, the required adjacent capability is the safe publication, evidence-backed release, or application-facing consumption boundary already named in the mission. A closure pass MUST NOT expand into a new capability merely because further adjacent work is discoverable. Once the declared boundary is safe to consume and remaining gaps are explicitly deferred, the lane freezes.

[DIRECTIVE] Claim-Adversary Pass: Before a lane reports completion, publication, or milestone success, it MUST run a short hostile review against the exact status it intends to publish. Treat every noun and adjective in that status as an assertion to falsify. At minimum, attack authority ownership, production-boundary realism, crash/retry or duplicate-effect safety when relevant, canonical evidence reconstruction, remote publication truth, and lane-boundary release safety. If any falsifier succeeds, downgrade the claim or repair the seam before reporting.

[DIRECTIVE] Lane Closure and Freeze: A lane is complete when its explicitly declared boundary is published, production-proven for its stated consumer purpose, reconstructable from governing evidence, and free of defects inside that boundary. Deferred upstream, downstream, cross-lane, UI, transport, or broader capability gaps do not keep the lane open unless they make the released boundary unsafe or its stated claim false. Before a lane reports completion it MUST declare the released boundary, consumer purpose, blocking defects, deferred seams, and freeze condition. Boundary-scoped claim-adversary passes must not recurse into unrelated seams. Once remotely verified and safe to consume, the lane freezes pending a named integration milestone. Frozen lanes reopen only for a concrete defect inside the released boundary, a named integration milestone that consumes or extends it, or a user-directed architectural revision.

[DIRECTIVE] Checkpoint Publication and Review: Local checkpoint commits preserve proven mission-owned work sets. After a named milestone and explicit publication authorization, a lane may push its checkpointed commits for remote review. Publication is separate from authorship, and it does not widen the lane's claim or reopen frozen work. Review tooling may inspect only the published checkpointed slice; unrelated or deferred seams remain deferred unless the released boundary becomes unsafe or false.

[DIRECTIVE] GitHub-Connected Review Boundary: When a lane is preparing work for GitHub-connected review tooling, treat imported repository snapshots as bounded and non-live. Keep the review slice within the connected-app limits, do not rely on auto-sync for private imports, and treat workflow files and other blocked surfaces as excluded from the review boundary. If workspace policy or account linkage blocks access, fall back to a user-mediated review path instead of widening the lane.

[ABSOLUTE] Canonical Evidence & Event Authority: Schema-validated evidence artifacts are the absolute authority for governed transitions, telemetry, and machine-to-machine boundaries. Append-only ledgers are immutable. Derived projections and UI state are disposable and MUST be reconstructable from canonical evidence. If a governed decision is not recorded in its canonical evidence domain, it did not happen.

[STANDARD] Projection-to-Desktop & Gridline Interface: Canonical projections exist to feed the Gridline Interface, governed agents, tests, and accessibility surfaces. Do NOT treat terminal reports or command-line exports as the intended product interface.

[MANDATORY] External Reconnaissance: Agents MUST research primary external sources when a mission depends on changing external facts, platform APIs, privacy requirements, or the adoption of new dependencies. Routine internal refactoring DOES NOT require research detours.

[SYSTEM] Bridge Memory & Symbolic Atlas: Rig Relay maintains a governed architectural memory system. Canonical production code uses precise domain identifiers. Major boundaries and schemas MAY receive distinctive sci-fi/mecha lore aliases in the semantic atlas to maximize context compression, provided they deterministically resolve back to canonical domain identifiers.

- Structural facts MUST be strictly derived from source using AST/tree-based indexing. Agents MUST NOT manually assert structural facts.
- Semantic claims and coordination updates MUST be recorded as typed, append-only events with explicit authority statuses.
- Lock-free projection: parallel lanes MUST write partitioned, mission-owned event streams. Agents MUST NOT concurrently mutate a shared monolithic graph file. Read-side graph projections are disposable derived artifacts.

[CRITICAL] Anti-Deadlock & Actionable Governance: If blocked by a rigid gate or transient failure outside immediate scope, agents MUST NOT deadlock. Document the blockage, park the fragment, and pivot immediately to adjacent value. Rejections MUST provide an actionable path forward.

[ABSOLUTE] Remote Source of Truth: Verify current implementations exclusively via remote reads from the canonical repository main branch. Relying on stale local assumptions, agent memory, or overconfident summaries is STRICTLY FORBIDDEN. Milestone claims MUST truthfully reflect remote publication state.

[INVARIANT] Substrate Testing Doctrine: Tests are real substrate. Cosplay testing is FORBIDDEN. Acceptance tests MUST exercise the exact production boundary claimed. Helper derivations, fake persistence, simulated concurrency, and local-only commits DO NOT justify closure. NO MOCKS. NO STUBS. NO GHOSTS. Mocks are permitted ONLY at true external OS/network boundaries.

[DIRECTIVE] Continuity & Opportunism (The 5-Minute Rule): If a high-value, low-risk fix takes less time to execute than to document, execute it immediately. If it threatens the convergence path, park it. Do not let tangents derail the active mission.
