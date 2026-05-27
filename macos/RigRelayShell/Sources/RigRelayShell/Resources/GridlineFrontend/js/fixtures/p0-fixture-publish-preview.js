// Publish Preview surface fixture
// Matches J0 publication readiness + L0 PublishableProjectProfileCandidate
// Fixture-backed until O0 publishes

window.__P0_FIXTURES__ = window.__P0_FIXTURES__ || {};

window.__P0_FIXTURES__.publish_preview = {
  _fixture_backed: true,
  _fixture_disclaimer: "Fixture data — not live bridge projection. Replace when O0 publishes.",

  // J0 — Publication Readiness
  publication_readiness: {
    status: "review_required",        // "not_prepared" | "preparing" | "review_required" | "ready" | "deferred" | "refused"
    prepared_pages_actions: 0,        // J0: Pages action count (0 = not prepared)
    can_publish: false,
    blockers: ["Live Pages deployment not yet released", "O0 bridge aggregation deferred"],
    content_light_check_passed: true,
    public_safety_check_passed: true
  },

  // L0 — Publishable Project Profile Candidate
  profile_candidate: {
    candidate_id: "candidate_ffff0001",
    status: "pending_review",          // L0: "proposed" | "pending_review" | "approved" | "rejected" | "superseded"
    project_name: "rig-relay",
    project_identity_sha256: "sha256:eeee1111111111111111111111111111111111111111111111111111111111",

    // Public-safe sections (no internal-only content)
    public_sections: [
      { section_id: "project_identity", title: "Project Identity", status: "proven", ready: true },
      { section_id: "status_overview", title: "Status Overview", status: "claimed", ready: true },
      { section_id: "accomplishments", title: "Accomplishments", status: "claimed", ready: false, reason: "Pending evidence assembly" },
      { section_id: "released_boundaries", title: "Released Boundaries", status: "proven", ready: true },
      { section_id: "mission_timeline", title: "Mission Timeline", status: "claimed", ready: true },
      { section_id: "architecture_overview", title: "Architecture Overview", status: "claimed", ready: false, reason: "Needs generated diagram" }
    ],

    // Withheld content (never exposed in public preview)
    withheld_sections: [
      { section_id: "internal_credentials", reason: "private credentials", privacy_class: "internal_only" },
      { section_id: "unpublished_lane_data", reason: "unpublished lane", privacy_class: "internal_only" }
    ],

    approval_required: true,
    approval_status: "pending_review",
    generated_at: "2026-05-26T00:00:00Z"
  }
};

// Export combined fixture accessor
window.__P0_FIXTURES__.all = function() {
  return {
    connect: window.__P0_FIXTURES__.connect,
    repository_estate: window.__P0_FIXTURES__.repository_estate,
    project_studio: window.__P0_FIXTURES__.project_studio,
    inference_studio: window.__P0_FIXTURES__.inference_studio,
    publish_preview: window.__P0_FIXTURES__.publish_preview
  };
};
