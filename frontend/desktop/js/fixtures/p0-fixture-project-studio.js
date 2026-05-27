// Project Studio surface fixture
// Combines K0 (RepositoryOperatorSessionService) and L0 (ProjectContextAssemblyService) projections
// Fixture-backed until O0 publishes

window.__P0_FIXTURES__ = window.__P0_FIXTURES__ || {};

window.__P0_FIXTURES__.project_studio = {
  _fixture_backed: true,
  _fixture_disclaimer: "Fixture data — not live bridge projection. Replace when O0 publishes.",

  // K0 — Operator Session
  operator_session: {
    session_id: "session_20260526_000000",
    repository_label: "rig-relay",
    purpose: "Repository investigation",
    status: "active",                // "idle" | "active" | "completed" | "refused" | "failed"
    phase: "investigation",          // "idle" | "investigation" | "proposal_review" | "completed"
    tool_summary: [
      { tool_name: "grep", calls: 4, successes: 4, failures: 0, refusals: 0 },
      { tool_name: "read_file", calls: 12, successes: 12, failures: 0, refusals: 0 },
      { tool_name: "git_status", calls: 2, successes: 2, failures: 0, refusals: 0 }
    ],
    proposal_count: 2,
    proposal_dispositions: { "needs_review": 1, "approved": 0, "refused": 1 },
    refusal_count: 1,
    pending_decisions: ["Proposal #2: Add evidence rail CSS"],
    blocked_capabilities: ["write_file: requires approval"],
    deferred_integrations: ["Live J0 workspace integration"],
    recovery_materialization_available: false,
    evidence_integrity: "ok",
    error_message: null
  },

  // L0 — Project Understanding
  project_understanding: {
    projection_id: "proj_ffff0001",
    project_name: "rig-relay",
    study_status: "study_complete",          // L0 enum: "not_started" | "studying" | "study_complete" | "publication_proposed" | "publication_approved" | "failed"
    head_sha: "3451609e",
    branch: "main",
    facts_discovered: 47,
    facts_with_provenance: 42,
    languages_detected: ["Python", "TypeScript", "JavaScript", "HTML", "Swift"],
    frameworks_detected: ["pytest", "pywebview", "WebSocket", "Pydantic"],
    test_frameworks_detected: ["pytest", "pytest-asyncio", "pytest-xdist"],
    public_ready_assets: [
      "docs/json/frontend/lane_e0_frontend_systems_atlas.v1.json",
      "docs/json/audits/desktop/lane_n0_gridline_developer_studio_shell_initial_slice.v1.json"
    ],
    public_ready_asset_count: 12,
    withheld_material_count: 3,
    withheld_reasons: ["private credentials", "internal architecture notes", "unpublished lane"],
    draft_narrative_count: 5,
    draft_narrative_awaiting_approval: 3,
    bootstrap_gaps: ["O0 bridge aggregation not yet published", "Portfolio compiler deferred"],
    context_packet_ready: true,
    context_packet_digest: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    portfolio_eligibility: "eligible",      // L0 enum: "eligible" | "not_eligible" | "needs_review"
    approval_status: "pending_review",      // L0 enum: "proposed" | "pending_review" | "approved" | "rejected" | "superseded"
    recommendation: "Proceed to Publish Preview after draft narratives reviewed",
    content_light_guarantee: true
  }
};
