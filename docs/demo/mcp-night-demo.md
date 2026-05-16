# MCP Night Demo — Fresh-Clone Walkthrough

## Role Model

The desktop app shows a Role Model card explaining who does what:

| Role | Kind | Description |
|---|---|---|
| 🎯 Orchestrator | Manager | Assigns missions to subagents, reviews Ralph reports |
| 🔧 Subagents | Specialist workers | 5 configured profiles (runtime, frontend, docs, tests, analytics) |
| 🤖 Ralph | Autonomous background worker | Observes lane projections, fixes convergence issues in isolated worktrees, reports completed work |
| ⚡ Model Bindings | Capability config | Model/provider selection attached to profiles; local demo works without API keys |

Ralph is NOT a normal assignable subagent. Ralph works autonomously in Ralph-owned
worktrees and reports completed work to the orchestrator through RalphReports.
Model/provider selection is runtime capability configuration, not role identity.

## Quick start

```bash
git clone https://github.com/juliantorr-es/rig-relay
cd rig-relay
uv sync
uv run rig-relay demo-seed
uv run rig-relay demo-doctor
uv run rig-relay
```

## Pre-flight checks

```bash
# Verify all components are ready
uv run rig-relay demo-doctor
```

Expected output: all 17 checks green:

```
  ✅ pywebview import
  ✅ duckdb import
  ✅ frontend files exist
  ✅ desktop projection builds
  ✅ mission board projection builds
  ✅ ToolRuntime summary builds
  ✅ Ralph lifecycle projection builds
  ✅ review bundles exist
  ✅ adoption proposals exist
  ✅ report summary builds
  ✅ bash analytics data exists
  ✅ review_with_orchestrator explain-only
  ✅ docs render path
  ✅ local mode (no OAuth)
  ✅ merge/push disabled by default
  ✅ live_runtime_mutation always False
  ✅ frontend does not infer policy
  ✅ demo data has no secrets
```

## What demo-seed creates

| Artifact | Contents |
|---|---|
| `orchestrator_missions.json` | 3 synthetic missions (in progress, completed, pending) |
| `mission_board.json` | Full mission board projection (2 active, 8-step lifecycle, review entrypoint) |
| `ralph_lifecycle.json` | 2 completed lanes, 5 lifecycle gates, background policy state |
| `review_bundles.json` | 2 sealed review bundles with validation results and risk notes |
| `adoption_proposals.json` | 1 adoption proposal (pending review) |
| `report_summary.json` | 12 reports across 5 finding kinds |
| `bash_analytics.json` | 42 bash calls, 15 rerouted, 3 blocked |
| `projection.json` | Desktop cockpit projection snapshot |
| ToolRuntime ledger | 8 in-memory entries (completed, cached, refused, degraded) |

All data is clearly marked `"source": "demo-synthetic"`. No network, no secrets, no mutation.

## 3-minute walkthrough

### Step 1: Launch the desktop cockpit

```bash
uv run rig-relay
```

A pywebview window opens at 1200×800 with the Rig Relay desktop console.

### Step 2: See the Mission Board (Operator mode)

The Mission Board widget shows:
- **2 active missions**: "Extract ToolRuntime boundary from AgentLoop" and "Wire Ralph lifecycle into pywebview"
- **Lifecycle timeline**: 8 steps, the first 5 completed (Background enabled → Lane created → Execution completed → Commit recorded → Review bundle sealed), the last 3 locked (Adoption proposal → Merge → Push)
- **Review entrypoint**: "Review 2 completed lane(s) with orchestrator" button

### Step 3: See the Ralph Lifecycle widget

```
Background Lanes: ON
Lane execution: allowed
Runtime mutation: blocked
Merge: requires adoption approval
Push: requires preproduction approval

Active: 0 · Completed: 2 · Pending review: 2
Latest: ralph/bash-analytics-demo [completed] Commit: abc123def
```

The 5 lifecycle gates are shown as badges:
- Worktree creation: allowed
- Lane execution: allowed
- Ralph branch commits: allowed
- Adoption merge: requires adoption approval
- Push to preproduction: requires preproduction approval

### Step 4: Click "Review with Orchestrator"

The review session shows:
- **What Ralph did**: Summary of lane work (tool extraction, bash analytics hardening)
- **When**: Timestamps of lane creation and completion
- **Why**: Triggered by findings/reports
- **Source refs**: Evidence references (finding IDs, report IDs)
- **Branch/commit refs**: Head SHA, commit SHAs
- **Validation results**: ruff, pyright, pytest results
- **Risk notes**: Backward compatibility, API stabilization
- **Adoption recommendation**: Target kind, confidence level, reason

**No merge or push action is available.** The session is explain-only.

### Step 5: Switch layout modes

- **Operator**: Mission board, Ralph lifecycle, ToolRuntime summary, Provider health
- **Review**: Progress timeline, receipt timeline, refinement backlogs, dataset summary
- **System**: Identity, model providers, telemetry consent, update status
- **Technical**: Projection sources, storage diagnostics, connection status

### Step 6: Render the docs site

```bash
uv run rig-relay demo-render-docs
```

Produces `.build/rig-relay/docs-site/` with:
- `index.html` — styled index page with artifacts list and safety boundaries
- `docs/` — all project markdown docs
- `artifacts/` — all demo seed JSON artifacts
- Serve locally: `cd .build/rig-relay/docs-site && python3 -m http.server 8080`

## Key architecture visible in one screen

| Widget | What it proves |
|---|---|
| Mission Board | Orchestrator issues missions, lanes track work, lifecycle timeline |
| ToolRuntime Summary | Every tool call produces a typed, classified outcome (completed/cached/refused/degraded) |
| Ralph Lifecycle | Background lanes converge, seal review bundles, gates control adoption/merge/push |
| Ralph Scout | Scanning, ranking, approval decisions with content-addressed hashes |
| Reports | Findings are structured, countable, debuggable |
| Projection Sources | All data sources are content-light and auditable |
| Review with Orchestrator | Completed work is reviewable with evidence, validation, risk notes |

## Safety boundaries (all enforced by default)

- ✅ **Merge gated** — `RIG_RELAY_ENABLE_MERGE` must be explicitly set; demo policy has `allow_adoption_merge=False`
- ✅ **Push gated** — `RIG_RELAY_ENABLE_PUSH` must be explicitly set; demo policy has `allow_push_to_preproduction=False`
- ✅ **Live runtime mutation always blocked** — no policy enables this
- ✅ **No network required** — local mode works without OAuth
- ✅ **No secrets** — demo data is synthetic, no API keys, no private paths
- ✅ **No mutation** — canonical findings are never touched
- ✅ **Frontend does not infer policy** — backend owns all policy transitions
- ✅ **ToolRuntime governs all tool execution** — every tool call goes through permission/approval/patch-gate/invoke/receipt/cache/observation

## Dry-run / server-only modes

```bash
# Build and print projection, no window
uv run rig-relay --dry-run

# WebSocket + URL, no window (headless server)
uv run rig-relay --server-only
```

## Troubleshooting

**`uv run rig-relay` opens a blank window:**
Run `uv run rig-relay demo-seed` first if you want demo data. The cockpit works without demo data but shows empty widgets.

**Provider setup:**
On first launch without an API key, Rig Relay starts in onboarding mode. The projection system, WebSocket, and UI panels work without any LLM provider.

**Frontend not loading:**
Check `uv run rig-relay demo-doctor` — frontend files should be in `frontend/desktop/`.

**pywebview not launching (Linux):**
Install GTK or Qt WebKit: `sudo apt install python3-pyqt5.qtwebengine` or `python3-gi gir1.2-webkit2-4.0`.

**Module import errors:**
Run `uv sync` to install all dependencies. The `uv run` command ensures the correct venv is used.

**WebSocket connection refused:**
The WebSocket runs on `ws://127.0.0.1:9876`. Check port availability or use `--ws-port` to change it.

**pywebview not installed:**
```bash
uv add pywebview
```

## Local docs render

```bash
# Render all artifacts to static site
uv run rig-relay demo-render-docs

# Serve locally
cd .build/rig-relay/docs-site && python3 -m http.server 8080

# GitHub Pages: push docs-site/ to gh-pages branch
# Or: configure GitHub Actions to deploy from docs-site/
```

## GitHub Pages publish path

1. Run `uv run rig-relay demo-render-docs`
2. The output lives in `.build/rig-relay/docs-site/`
3. Push to `gh-pages` branch or configure GitHub Pages source to the `docs-site/` directory
4. Local render does not require OAuth or any provider keys
