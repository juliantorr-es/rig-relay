# Test Suite Tiering Report

## Marker Definitions

| Marker | Description |
|---|---|
| `smoke` | Fastest health checks; must pass before demo/share |
| `contract` | Domain contract/unit tests |
| `integration` | Crosses multiple components/processes/filesystems |
| `e2e` | Broad-stack or full flow |
| `packaging` | Packaged app / installer / bundle checks |
| `slow` | Intentionally slow — excluded from default |
| `legacy` | Retained but not part of default suite |
| `quarantine` | Quarantined, runs only in dedicated job |
| `flaky` | Known nondeterministic — excluded from default |
| `network` | Requires external network |
| `provider` | Requires external model/provider/API |
| `destructive` | Mutates worktrees/branches/files beyond temp dirs |
| `migration` | Being relocated during test layout canonicalization |

## Canonical Commands

| Purpose | Command |
|---|---|
| Smoke | `uv run pytest -m smoke` |
| Default (dev/agent) | `uv run pytest -m "not slow and not legacy and not quarantine and not flaky and not network and not provider and not destructive"` |
| Full suite | `uv run pytest` |
| Collection check | `PYTHONDONTWRITEBYTECODE=1 uv run pytest --collect-only -q` |
| Legacy/quarantine review | `uv run pytest -m "legacy or quarantine or flaky"` |
| Packaging | `uv run pytest -m packaging` |
| Integration/e2e | `uv run pytest -m "integration or e2e"` |

## Current Suite Metrics

| Suite | Tests Collected | Passed | Time |
|---|---|---|---|
| Smoke | 24 | 24 | 48.7s |
| Default | 6104 | — | — |
| Full | 6108 | — | — |

## Smoke Tests (24 marks)

- Conftest hygiene (1): conftest source guard
- Layout guard (1): test layout audit
- Architecture quality doctrine (12): marker validation, conftest checks, naming rules
- Orchestrator (3): demo profiles, autonomous worker, local bindings
- Ralph (4): lifecycle projection, mission board, demo reports
- Desktop TLS (1): TLS material generation
- Desktop projection (1): build projection returns dict
- Runtime convergence (1): runner uses tool runtime

## Agent Guidance

Agents should run `validate focused` or the default marker expression unless explicitly asked for full suite validation. Full suite is an explicit confidence event, not an ordinary loop.
