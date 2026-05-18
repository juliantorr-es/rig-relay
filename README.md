# Rig Relay

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/release/python-3120/)
[![License](https://img.shields.io/github/license/juliantorr-es/rig-relay)](https://github.com/juliantorr-es/rig-relay/blob/main/LICENSE)

**Rig Relay — a governed local server/control-plane with a desktop cockpit.**

Rig Relay is a local control-plane for governed agentic development. The
desktop cockpit is the primary surface for operators and reviewers; the CLI
is a shim for launch, debug, and operator flows. The product provides
receipt-backed evidence, worktree isolation, multi-provider consultation
(Council), and fleet orchestration. It exposes MCP tools for Antigravity,
VS Code, and Zed, and speaks ACP for editor-integrated agent sessions.

## Quick Start

```bash
git clone https://github.com/juliantorr-es/rig-relay
cd rig-relay
uv sync
uv run rig-relay demo-seed      # create synthetic demo data
uv run rig-relay demo-doctor    # verify demo readiness
uv run rig-relay                # launch desktop cockpit
```

On first launch, Rig Relay will walk you through provider setup — pick a
provider, get an API key, and you're ready. No API key? Rig Relay still
starts in dry-run mode with full projection and WebSocket available.

```bash
uv tool install git+https://github.com/juliantorr-es/rig-relay.git --force
```

### Demo Walkthrough (3 minutes)

1. **Seed demo data**: `uv run rig-relay demo-seed` — creates 3 orchestrator missions, 8 ToolRuntime outcomes, 2 Ralph lifecycle lanes, review bundles, adoption proposals, reports, and bash analytics.
2. **Verify**: `uv run rig-relay demo-doctor` — 17 checks: imports, projections, review_with_orchestrator, merge/push gated, no secrets.
3. **Launch**: `uv run rig-relay` opens pywebview desktop cockpit.
4. **Mission Board**: 2 active missions, lifecycle timeline with 8 steps, review entrypoint.
5. **Ralph Lifecycle**: Background lanes ON, isolated lane execution allowed, live runtime mutation blocked, merge/push gated.
6. **Review with Orchestrator**: Explain-only review showing what Ralph did, when, why, validation results, risk notes, adoption recommendation. No merge or push authorized.
7. **Render docs site**: `uv run rig-relay demo-render-docs` produces `.build/rig-relay/docs-site/`.

See [docs/demo/mcp-night-demo.md](docs/demo/mcp-night-demo.md) for the full walkthrough.

## Current Path

Rig Relay is a standalone desktop application built with pywebview. The
primary surface is a chat-first console with widget panels for workspace
state, fleet status, provider health, and Council (multi-provider
adversarial review).

```
uv run rig-relay
```

### Desktop Cockpit

Operator, Review, System, and Technical layout modes. Widgets at three
disclosure levels: compact chips, standard cards, and full-page expanded
views. Chat sends to AgentLoop → LLM → tools → response. WebSocket
streams projections and chat state to the frontend. The server/control-plane
can also be launched headlessly for review, browser validation, and live
exercise of the cockpit path.

```bash
uv run rig-relay --dry-run       # projection dump, no window
uv run rig-relay --server-only   # WebSocket + URL, headless
```

## Protocol Surfaces

Rig Relay exposes four protocol surfaces for different integration patterns:

| Surface        | Role                 | Description                                                                                                                                                                            |
| -------------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ACP Agent**  | Editor ↔ Agent       | Rig presents as a governed coding agent to Zed, JetBrains, VS Code. Sessions, progress events, edit proposals, permission gating.                                                      |
| **MCP Client** | Rig ↔ External Tools | Rig consumes external MCP servers for additional tools and context.                                                                                                                    |
| **MCP Server** | Host ↔ Rig           | Rig exposes governed tools, resources, and prompts to Antigravity, Claude Desktop, Cursor, and other MCP hosts. Tiered: read-only → analysis → validation → patch proposal → mutation. |
| **WebSocket**  | Cockpit ↔ Backend    | Local projection stream for the desktop cockpit. Token-gated, localhost-only, content-light.                                                                                           |

See [docs/protocol-surfaces.md](docs/protocol-surfaces.md) for details.

## Legacy Path

Rig Relay is a derivative of mistralai/mistral-vibe. The `vibe` command
and legacy Textual TUI are retained for compatibility during migration
but are not the product identity.

```bash
rig-relay legacy          # legacy CLI
rig-relay legacy --agent plan
```

Legacy config paths (`.vibe/`, `~/.vibe/`) are read as compatibility
fallbacks. Set `RIG_RELAY_DISABLE_LEGACY_CONFIG=1` to require the new
paths.

## Agent Profiles

Rig Relay ships with built-in agent profiles. Select with `--agent`:

| Profile            | Type     | Tools                            | Use                                    |
| ------------------ | -------- | -------------------------------- | -------------------------------------- |
| `default`          | Agent    | Standard                         | Normal development with approval gates |
| `orchestrator`     | Agent    | Git, task dispatch, consult      | Fleet orchestration, roadmap planning  |
| `plan`             | Agent    | Read-only                        | Exploration and planning               |
| `explorer`         | Subagent | grep, read_file                  | Codebase exploration                   |
| `builder`          | Subagent | write_file, search_replace, task | Patch application in scratch worktrees |
| `cleaner`          | Subagent | validate, validation_suite       | Post-build validation and cleanup      |
| `bug-exterminator` | Subagent | cleaner tools + task             | Hard merge conflict resolution         |

## Safety Story

Rig Relay communicates **bounded autonomy**, not vague automation:

| Scope                   | Default                         | Meaning                                                                   |
| ----------------------- | ------------------------------- | ------------------------------------------------------------------------- |
| Isolated lane execution | Allowed (demo)                  | Ralph creates worktrees, scoped execution. No mutation of live workspace. |
| Live runtime mutation   | Always blocked                  | No agent can mutate the live runtime workspace.                           |
| Merge                   | Requires adoption approval      | Adoption must pass human approval + SHA match.                            |
| Push to preproduction   | Requires preproduction approval | Human approval + validation suite must pass.                              |

These gates align with OWASP agent security best practices: least-privilege
tools, per-tool permission scoping, separate tool sets by trust level, and
explicit authorization for sensitive operations.

**Frontend is a dumb renderer.** The backend owns all policy transitions.
The frontend receives projection fields like `isolated_lane_execution_enabled`
and `merge_enabled` and displays them as human labels ("Allowed" / "Blocked" /
"Requires adoption approval"). The frontend never infers or overrides policy.

## Features

- **Chat-first console** — Operator, Review, System, Technical layout modes with adaptive widget grids
- **Council** — Multi-provider adversarial review with structured opinions and receipt-backed findings
- **Fleet orchestration** — Roadmap planning, sprint scoping, mission dispatch to subagents on isolated worktrees
- **Receipt-backed evidence** — Every tool call, checkpoint, and consultation produces a receipt
- **Worktree isolation** — Agents operate in git worktrees under `.rig/relay/worktrees`
- **Slash commands** — `/init`, `/worktree`, `/fleet`, `/council`, `/orchestrator`, `/provider`, and more
- **Provider onboarding** — Interactive setup for DeepSeek, OpenAI, Anthropic, Google, Mistral, OpenRouter
- **MCP server** — 16 governed tools across 5 tiers, exposed for Antigravity/VS Code/Zed
- **ACP agent** — Editor-integrated session control with progress streaming and permission gating

## Configuration

Rig Relay looks for configuration at:

1. `./.rig/relay/config.toml` (project-specific)
2. `~/.rig/relay/config.toml` (user-global)

API keys are stored in `~/.rig/relay/.env`. On first launch with no key
configured, the onboarding wizard walks through provider selection and
key setup.

## Development

```bash
uv run pytest                  # full suite
uv run pyright                 # type check
uv run ruff check --fix .      # lint
uv run ruff format .           # format
```

## License

AGPL-3.0-or-later. Derivative of [mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe).
See [LICENSE](LICENSE) and [UPSTREAM.md](UPSTREAM.md).

## Release Candidate Status

Rig Relay is in alpha (v0.1.0a1). The release-candidate gate is **HOLD** —
installability smoke tests pass but dogfood operational readiness is not yet proven.

### Dogfood Golden Path

A structured reviewer checklist gates the PROMOTE decision:
[`docs/json/release_candidate/rc_reviewer_golden_path.v1.json`](docs/json/release_candidate/rc_reviewer_golden_path.v1.json)

To exercise the golden path:

1. Install: `git clone` + `uv sync`
2. Understand the product: read this README and the release gate phases
3. Launch server: `uv run rig-relay-acp`
4. Launch cockpit: `uv run rig-relay`
5. Run a real work lane and inspect structured evidence
6. Run the release gate validator: `uv run python scripts/rig_release_gate_validate.py`

### Structured Evidence

All evidence is JSON/JSONL/CSV — no Markdown-as-evidence.
Key evidence paths:

- `docs/json/release_gate/rc_blockers.v1.jsonl` — open RC blockers
- `docs/json/release_gate/rc_deferred_risks.v1.jsonl` — deferred risks with justifications
- `docs/json/release_gate/rc_candidate_verdict.v1.json` — current verdict
- `.rig/reports/reports.jsonl` — append-only structured reports
- `~/.rig/relay/sessions/<id>/observability.jsonl` — session telemetry

### Telemetry & Privacy

Telemetry is local-first and opt-in only. No raw file contents, secrets, or
private code are emitted. All content-derived data uses SHA256 hashes.
Telemetry-disabled mode must visibly degrade behavior (currently an open RC blocker).
See [`docs/governance/usage-data-doctrine.md`](docs/governance/usage-data-doctrine.md).
