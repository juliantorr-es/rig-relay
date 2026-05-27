// Connect surface — Carte Blanche state fixture
// Consumed by the Connect surface rendering. Fixture-backed until O0 publishes.
//
// Fixture status: FIXTURE_BACKED — not live service data.
// Projection shape: matches DeveloperGitHubWorkspaceService (J0) installation/connection concepts

window.__P0_FIXTURES__ = window.__P0_FIXTURES__ || {};

window.__P0_FIXTURES__.connect = {
  _fixture_backed: true,
  _fixture_disclaimer: "Fixture data — not live bridge projection. Replace when O0 publishes.",

  // Carte Blanche connection state
  carte_blanche: {
    status: "connected",        // "disconnected" | "connecting" | "connected" | "refused" | "error"
    installed_repos: 1,
    available_repos: 1,
    publication_approval_granted: false,
    publication_approval_deferred: true,
    installation_timestamp: "2026-05-26T00:00:00Z",
    installation_sha256: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
  },

  // Repository access
  repository_access: {
    status: "granted",          // "none" | "pending" | "granted" | "refused"
    token_present: true,
    token_fingerprint: "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
  },

  // Publication approval
  publication_approval: {
    status: "deferred",         // "none" | "pending" | "granted" | "deferred" | "refused"
    reason: "Live integration deferred to O0 bridge aggregation milestone",
    publication_ready: false
  }
};
