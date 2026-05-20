# GitHub Live Mutation Runbook

**Schema version:** `rig.github.live_mutation_runbook.v1`
**Generated at:** `2026-05-20T19:42:22.326240+00:00`

## Purpose

Prepare and execute the first real rig-relay live pull request mutation for a code scanning alert fix.

## Prerequisites

- Phase 2 RC gates passed (ref: docs/json/release_gate/rc_readiness_gate.v1.json)
- Phase 3 RC gates passed (ref: docs/json/release_gate/rc_readiness_gate.v1.json)
- GitHub App installed on target repository with contents:write and pull_requests:write permissions
- Live mutation preflight completed successfully
- Operator checklist reviewed and all gates passed
- API token stored in ~/.rig/relay/.env
- Rate limit snapshot confirms headroom

## Environment Variables

| Name | Description | Required | Example |
|------|-------------|----------|---------|
| `RIG_LIVE_MUTATION` | Master gate flag; must be set to 1 to enable any remote mutation | Yes | `1` |
| `RIG_GITHUB_AUTH_TOKEN` | GitHub personal access token or installation token | Yes | `<from-token-store>` |
| `RIG_LIVE_AUTH_TESTS` | Enables live auth verification probes | Yes | `1` |
| `RIG_GITHUB_PERMISSION_MODE` | Permission mode (read_only, write, admin) | No | `write` |

## CLI Commands

### Dry-run

```bash
uv run python scripts/rig_github_security_packet_execution.py   --plan-json docs/json/governance/github_security_packet_runner_plan_v1.v1.json   --output-json docs/json/governance/github_security_packet_execution_v1.v1.json   --limit 1 --summary
```

### Simulate (fake boundary)

```bash
uv run python scripts/rig_github_security_packet_execution.py   --plan-json docs/json/governance/github_security_packet_runner_plan_v1.v1.json   --output-json docs/json/governance/github_security_packet_execution_v1.v1.json   --limit 1
```

### Live Execution

```bash
RIG_LIVE_MUTATION=1 RIG_LIVE_AUTH_TESTS=1 RIG_GITHUB_PERMISSION_MODE=write uv run python scripts/rig_github_security_packet_execution.py   --plan-json docs/json/governance/github_security_packet_runner_plan_v1.v1.json   --output-json docs/json/governance/github_security_packet_execution_v1.v1.json   --limit 1 --summary
```

### Verify

```bash
uv run python scripts/rig_github_security_lifecycle_replay.py --summary
```

## Gate Checklist

### RC Phase 2 gates passed
- **Command:** `uv run python scripts/rig_release_gate_validate.py`
- **Expected:** All Phase 2 gates PASSED

### RC Phase 3 gates passed
- **Command:** `uv run python scripts/rig_release_gate_validate.py`
- **Expected:** All Phase 3 gates PASSED

### Preflight ready
- **Command:** `cat docs/json/governance/github_live_mutation_preflight_v1.v1.json | uv run python -c "import json,sys; d=json.load(sys.stdin); print(d.get('status',''))"`
- **Expected:** ready_for_live_mutation_review

### Permissions verified
- **Command:** `cat docs/json/governance/github_live_mutation_phase3_permission_boundary_audit_v1.v1.json | uv run python -c "import json,sys; d=json.load(sys.stdin); print(d.get('gates_passed',''))"`
- **Expected:** True

### Rate limit headroom
- **Command:** `cat docs/json/governance/github_live_mutation_rate_limit_snapshot_v1.v1.json | uv run python -c "import json,sys; d=json.load(sys.stdin); print(d.get('rate_limited',''))"`
- **Expected:** False

### Operator checklist signed
- **Command:** `cat docs/json/governance/github_live_mutation_operator_checklist_v1.v1.json | uv run python -c "import json,sys; d=json.load(sys.stdin); acks=d.get('operator_acknowledgements',[]); print(len(acks)==8)"`
- **Expected:** True

### Dry-run candidate diff exists
- **Command:** `cat docs/json/governance/code_scanning_dry_run_candidate_diff_v1.v1.json | uv run python -c "import json,sys; d=json.load(sys.stdin); print(d.get('diff_sha256','')[:8])"`
- **Expected:** Non-empty hash prefix

## Expected Artifacts

- `docs/json/governance/github_live_mutation_operator_checklist_v1.v1.json` — Operator checklist — must be reviewed before execution (required)
- `docs/json/governance/github_live_mutation_preflight_v1.v1.json` — Preflight probe results — gates permission and rate limit status (required)
- `docs/json/governance/github_live_mutation_phase3_permission_boundary_audit_v1.v1.json` — Permission boundary audit — verifies required scopes are active (required)
- `docs/json/governance/code_scanning_dry_run_candidate_diff_v1.v1.json` — Dry-run candidate diff — the proposed change being promoted to live (required)
- `docs/json/governance/github_live_mutation_rate_limit_snapshot_v1.v1.json` — Rate limit snapshot — confirms headroom before mutation (required)
- `docs/json/governance/github_security_lifecycle_replay_v1.v1.json` — Lifecycle replay — end-to-end dry-run before live promotion (required)

## Expected GitHub Operations

- create_branch
- commit_file_change
- create_pull_request

## Blocked States

- **preflight_blocked**: One or more preflight gates failed (permissions, rate limit, branch collision) → Resolve the failing gate and re-run preflight before proceeding
- **rate_limit_exhaustion**: GitHub API rate limit near or at exhaustion → Wait for rate limit reset window. Re-run rate limit snapshot.
- **permission_denied**: Required GitHub App permissions not granted or token expired → Re-install GitHub App or refresh token. Re-run permission boundary audit.
- **branch_collision**: Proposed branch name already exists on remote → Choose a new branch name or delete the stale branch if safe.
- **idempotency_collision**: Operation idempotency key already recorded as executed → Review the previous execution receipt. If intentional re-execution, generate new idempotency key.

## Success Criteria

- Remote branch rig/security/code-scanning-fix-001 created on the target repository
- File change committed to the remote branch with correct diff contents
- Pull request opened with title referencing code scanning alert fix
- Operation receipt generated and persisted to docs/json/governance/
- No secrets, tokens, or raw vulnerable code present in any persisted artifact
- Rate limits not exhausted by the operation
- Alert state explicitly documented as deferred (not dismissed, not fixed)

## Rollback Steps

1. **Close the pull request without merging**
   ```bash
   gh pr close <PR_NUMBER> --comment "Rollback: per operator checklist rollback procedure."
   ```
2. **Delete the created remote branch**
   ```bash
   git push origin --delete rig/security/code-scanning-fix-001
   ```
3. **Preserve operation receipt as canonical evidence**
   ```bash
   Ensure operation receipt at docs/json/governance/github_code_scanning_pr_operation_receipt_v1.v1.json is preserved with rollback annotation
   ```

## Post-Review Steps

- Review the pull request diff for correctness and unintended changes
- Confirm the branch prefix matches rig/security/
- Verify no workflow files (.github/workflows/) were modified
- Verify no default branch write occurred
- Check that the operation receipt is content-light (no secrets, tokens, raw code)
- Document the alert state deferral reason in the PR body
- Schedule alert state update for post-merge validation lane

## Alert Deferred Explanation

Code scanning alert state update/dismissal requires separate security_events:write permission and is deferred to post-merge validation.

## Troubleshooting

- **RIG_LIVE_MUTATION=1 not recognized**: Environment variable not exported or shell session not refreshed → Re-export: export RIG_LIVE_MUTATION=1. Verify: echo $RIG_LIVE_MUTATION.
- **HTTP 401 or 403 on API calls**: Token expired, invalid, or missing required permissions → Refresh token. Re-run permission boundary audit. Check GitHub App installation.
- **HTTP 429 rate limit exceeded**: API rate limit exhausted → Check X-RateLimit-Reset header. Wait for reset window. Re-run rate limit snapshot.
- **Branch already exists (HTTP 422)**: Proposed branch name collision with existing remote branch → Verify branch safety. Delete stale branch if safe, or choose new branch name.
- **Diff does not apply cleanly**: Base branch has diverged from the expected SHA → Re-run dry-run candidate diff generation against current base branch HEAD.

## Rate Limit Handling

GitHub API rate limits are monitored via event fabric. Near-exhaustion triggers polling cadence reduction. Exhaustion triggers graceful degradation.

## Privacy Posture

No raw file contents, tokens, or secrets in operation receipts. Content-light evidence only.

## Stop Conditions

- Any readiness gate returns 'blocked'
- Rate limit snapshot shows rate_limited=True
- Permission boundary audit shows required permission not_granted
- Preflight status is not ready_for_live_mutation_review
- Operator checklist has not been fully acknowledged
- Idempotency key collision detected (operation already executed)
- Branch safety check fails (proposed branch exists on remote)
