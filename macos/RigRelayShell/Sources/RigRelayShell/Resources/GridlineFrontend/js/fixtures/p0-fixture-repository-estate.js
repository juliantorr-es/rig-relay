// Repository Estate surface fixture
// Matches J0 DeveloperGitHubWorkspaceService projection shapes
// Fixture-backed until O0 publishes

window.__P0_FIXTURES__ = window.__P0_FIXTURES__ || {};

window.__P0_FIXTURES__.repository_estate = {
  _fixture_backed: true,
  _fixture_disclaimer: "Fixture data — not live bridge projection. Replace when O0 publishes.",

  repositories: [
    {
      repo_id: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      display_name: "rig-relay",
      full_name: "juliantorr-es/rig-relay",
      clone_status: "cloned",        // "not_cloned" | "cloning" | "cloned" | "failed"
      workspace_path_hash: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      branch: "main",
      head_sha: "3451609e",
      dirty_files: 1,
      last_synced: "2026-05-26T00:00:00Z",
      publication_ready: false,
      publication_blockers: ["Publish Preview not yet released"]
    }
  ],

  intake_status: {
    status: "idle",              // "idle" | "in_progress" | "complete" | "failed"
    last_intake_at: null,
    repos_discovered: 1,
    repos_imported: 1,
    repos_failed: 0
  },

  sync_status: {
    status: "synced",            // "never" | "syncing" | "synced" | "stale" | "failed"
    last_sync_at: "2026-05-26T00:00:00Z",
    ahead_count: 0,
    behind_count: 0
  }
};
