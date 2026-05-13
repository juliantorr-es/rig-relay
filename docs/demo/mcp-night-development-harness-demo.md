# MCP Night — Rig Relay Development Harness Demo

> **One-line thesis:** MCP connects agents to tools. Rig Relay makes that
> usable for real development: coordination, validation, receipts, progress,
> provider setup, consent, redaction, and local authority.

## Prerequisites

- Python 3.12+
- `uv` installed
- Rig Relay cloned

## Setup

```bash
cd rig-relay
uv sync --all-extras
```

No API keys required. No network setup. No local models to download.
The cockpit runs in demo mode with safe intents only.

## Launch

```bash
uv run python scripts/rig_relay_desktop_cockpit.py --dry-run
```

This launches the pywebview desktop cockpit. The `--dry-run` flag ensures
no protected state mutations occur.

**Fallback:** If pywebview is unavailable, use:
```bash
uv run python scripts/rig_relay_desktop_cockpit.py --dry-run --headless
```
This prints the projection JSON to stdout instead of opening a window.

## Five-Minute Talk Track

### 0:00 – Thesis (15s)

> "MCP gives agents a protocol to call tools. Rig Relay gives them a
> governed harness to do real development work — coordination, validation,
> progress, provider setup, consent, and content-light redaction."

Click **System** tab.

### 0:15 – Cockpit Layout (30s)

Three modes in the nav bar:

| Mode | What It Shows |
|------|---------------|
| **Operate** | Live state: provider health, validation counts, storage budget, Next Action |
| **Review** | Progress Timeline, validation results, storage audit, bundle status |
| **System** | Identity, provider keys, telemetry consent, authorization receipts, bundles |

### 0:45 – Operate: Live State (45s)

Click **Operate**.

Six widgets:
- **Operator** — version, mode, session
- **Safety State** — dirty count, lease count, stale leases
- **Validation** — passed/failed counts
- **Storage Budget** — size, budget status, prune candidates
- **Next Action** — recommended next step (computed from projection state)
- **Provider Health** — provider status summary

> "This is the live instrument panel. No guesswork — every number comes
> from real artifact data."

### 1:30 – Run Safe Intents (90s)

Click the following buttons in **Operate** (or run from terminal):

1. **Generate Refinement Report**
   - `runIntent('generate_refinement_report')`
   - Produces a content-light report from derived datasets
   - Result card shows report summary

2. **Create Refinement Packets**
   - `runIntent('create_refinement_packets', { limit: 3 })`
   - Produces mission packet artifacts

3. **Run Validation Suite**
   - `runIntent('run_validation_suite')`
   - Runs all registered validators
   - Result shows passed/failed counts

4. **Refresh Projection**
   - `runIntent('refresh_projection')`
   - Rebuilds Operate widgets from latest artifacts

**Fallback:** If buttons are unresponsive, run from terminal:
```bash
# These commands work headless:
uv run python -c "
from scripts.rig_relay_desktop_cockpit import execute_intent
result = execute_intent({'intent_name': 'generate_refinement_report'})
print(result['status'], result.get('summary', ''))
"
```

### 3:00 – Review: Progress Timeline (60s)

Click **Review**.

Left column:
- **Progress Timeline** — shows every operation as a card with type, phase,
  status, and message. Each card has a colored left border
  (green=ok, yellow=warn, red=error).
- **Receipt Timeline** — authorization receipts (if any)
- **Refinement Backlog** — generated packets

Right column:
- **Validation Results** — per-validator outcomes
- **Storage Audit** — budget details
- **Telemetry Bundle** — bundle status (if created)

> "The Progress Timeline is a live event stream. Every intent, validation
> step, and operation logs here. No second transport — it reuses the
> existing WebSocket."

### 4:00 – System: Trust Infrastructure (60s)

Click **System**.

Five cards:
1. **Identity Providers** — Sign in with GitHub or Google (or skip)
2. **Model Providers** — Manage API keys locally. Keys are:
   - Stored in file or keychain — never in telemetry/audit
   - Hashed to fingerprint — never raw in results
   - Input fields use `type="password"` — cleared after save
3. **Telemetry Consent** — Granular scope checkboxes. Commercial scopes
   are never default. Must be explicitly checked.
4. **Authorization Receipts** — Mint and inspect receipts for step-up auth
5. **Bundles** — Dev bundle dry-run, telemetry bundle dry-run

**Protected controls are absent.** There are no buttons for:
- `bash`, `shell`, `write_file`, `search_replace`
- `spawn.execute`, `fleet.execute`, `delegate.execute`
- `remote_upload.confirm`
- `lease_cleanup.remove`

> "The System tab is the trust panel. Identity, keys, consent, receipts —
> everything that makes agent tool use safe for real development."

### 4:45 – Dataset Close (15s)

Open `docs/demo/fixtures/model-observation-demo.json`:

```json
{
  "schema_version": "rig.relay.model_observation.v1",
  "task_kind": "code_gen",
  "provider_kind": "cloud",
  "provider_name": "openai",
  "model_id": "gpt-4o",
  "latency_ms": 2340.5,
  "tool_call_count": 4,
  "tool_success_count": 3,
  "content_light_guarantee": true
}
```

And `docs/demo/fixtures/provider-ranking-demo.json`:

```json
{
  "ranking_id": "rank_demo_mcp_night_001",
  "provider_scores": [
    { "provider_name": "openai", "overall_score": 0.72 },
    { "provider_name": "anthropic", "overall_score": 0.74 }
  ],
  "confidence_level": "low",
  "warnings": ["Low sample count (3): consider collecting more observations..."]
}
```

> "This is the dataset story: content-light observations, structured
> rankings, consent-gated, early-alpha confidence labels. No raw prompts,
> no raw outputs, no source code, no diffs, no secrets — just the signal.
> Aggregation over time turns low-confidence rankings into
> high-confidence recommendations."

### 5:00 – Closing Value Proposition

> **Rig Relay today:**
> - Governed local harness with three-mode cockpit
> - Safe intent execution (no protected mutation)
> - Content-light telemetry with granular consent
> - Provider onboarding with local key store
> - Progress event streaming with Review timeline
> - Validation artifacts with dashboard
> - Model observation dataset for provider/local model ranking
>
> **Next (not today):**
> - Full observation ingestion from all tool calls
> - Dashboard visualization of ranking snapshots
> - Automatic local model benchmarking
> - Commercial/aggregate dataset export with consent

## What Not to Show

- Do not click any button labeled "Bash", "Shell", "Write File",
  "Search/Replace", "Spawn", "Fleet", "Delegate".
- Do not enter real API keys on a projector screen.
- Do not click "Upload to Google Drive" — it requires real credentials.
- Do not claim production readiness. This is alpha.
- Do not show raw prompts, raw model outputs, source code diffs, or
  stdout/stderr bodies on screen.
- Do not run `git commit`, `git push`, or any git mutation during demo.

## Trust/Data Use Line

> **Rig Relay collects no raw prompts, no raw model outputs, no source code,
> no diffs, no stdout/stderr bodies, and no secrets.** All telemetry is
> content-light: hashes, counts, timestamps, and statuses. Consent is
> explicit, granular, and revocable. The redaction boundary is enforced
> by a shared module that every bundle writer, audit builder, and export
> helper must route through.

## Artifact References

- Demo observation: `docs/demo/fixtures/model-observation-demo.json`
- Demo ranking: `docs/demo/fixtures/provider-ranking-demo.json`
- Observation schema: `docs/schemas/rig.relay.model_observation.v1.schema.json`
- Ranking schema: `docs/schemas/rig.relay.provider_ranking_snapshot.v1.schema.json`
- Model code: `rig_relay/evidence/model_observations.py`
- Consent helpers: `rig_relay/identity/telemetry_consent.py`
- Redaction: `rig_relay/evidence/redaction.py`
- Dataset governance: `docs/governance/model-observation-dataset.md`
- Commercial license: `docs/legal/usage-data-license-alpha.md`
- Privacy notice: `docs/legal/privacy-notice-alpha.md`
