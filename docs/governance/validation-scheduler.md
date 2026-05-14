# Validation Scheduler

## Overview

The Validation Scheduler is a Phase 0 control-plane system built into the Validate tool. It owns three responsibilities that parallel agents cannot reliably manage themselves: **caching**, **request coalescing**, and **bounded parallelism**.

Agents do not choose wrappers, remember to check for running validations, or coordinate xdist flags. The Validate tool owns this.

## Cache

### How it works

1. Before running a check, Validate computes an `input_fingerprint` from:
   - Normalized command fingerprint
   - `pyproject.toml` content hash (if present)
   - `uv.lock` content hash (if present)
   - `pytest.ini` / `setup.cfg` / `tox.ini` content hashes
   - `docs/schemas/*` file hashes (for `schema`-kind checks)
   - Python version
   - Tool versions (pytest, ruff, pyright) — hashed from `--version` output
   - Current working directory

2. A `cache_key` is derived from check identity + command fingerprint + input fingerprint + cwd.

3. The cache store is file-backed under `.build/rig/validation-cache/records/<prefix>/<key>.json`.

### Cache invalidation

A cache entry is invalidated when:
- The command fingerprint changes (different args)
- Any input file changes (pyproject.toml, uv.lock, pytest config, schemas)
- Python version changes
- Tool version changes
- The cache record is corrupt (JSON parse failure)
- `cache_policy=force_rerun` is set

### Reuse policy

- **Passed results**: reused by default (`cache_status="hit"`)
- **Failed results**: written to cache but NOT reused unless `allow_failed_cache_reuse=true`
- **Corrupt records**: treated as miss, rerun occurs
- **`cache_policy=disabled`**: bypasses cache entirely
- **`cache_policy=force_rerun`**: bypasses cache, forces re-execution

## Scheduler / Coalescing

### Running lock

Each cache key has a file-based running lock under `.build/rig/validation-scheduler/locks/`.

- If a check with the same cache key is already running (`lock_running_checks=true`), the duplicate gets `scheduler_status="blocked_duplicate"` and does NOT execute.
- Locks expire after 5 minutes without heartbeat (stale detection).
- Stale locks are cleaned up on next scheduler operation.

### Behavior

```
Check A starts → lock acquired for cache_key X
Check B requested same X → lock active → B gets blocked_duplicate
Check A finishes → lock released
Check C requested X → lock free → runs normally
```

### Phase 0 limitation

Following/waiting for in-flight checks is deferred. The requesting agent sees `blocked_duplicate` status and should retry later if needed.

## Bounded Parallelism

### Policy

Validate rewrites pytest commands to inject bounded xdist flags:

| Condition | Behavior |
|---|---|
| Cache hit | No injection (no run occurs) |
| Not pytest | Not applicable |
| Already has `-n` | Not applicable (respects existing) |
| Focused single file | Stays serial unless `parallel_policy=force` |
| Schema validation | Stays serial |
| ruff/pyright | Stays serial |
| xdist unavailable | Falls back to serial, warning emitted |
| Default | Injects `-n <workers> --dist <mode>` |

### Worker limits

- Default max workers: `min(4, os.cpu_count() or 1)`
- Configurable via `max_workers`
- Never `-n auto` by default — always bounded

### Why not `-n auto`

`-n auto` uses all CPU cores, which melts laptops during parallel agent activity. Bounded workers keep the machine usable.

## Validation Phases

| Phase | Behavior |
|---|---|
| `edit` | Full-suite validation emits `full_suite_during_edit_phase` warning. Cache still works normally. |
| `pre_report` | Normal validation. No phase warnings. |
| `cleanup` | Normal validation with cache. |
| `final` | Normal validation with cache. |

Phases emit **warnings only** — never hard failures.

## Content-Light Records

Cache records contain:
- `status`, `exit_code`, `duration_ms`
- `stdout_sha256`, `stderr_sha256`
- `stdout_bytes`, `stderr_bytes`
- `failure_kind`
- `cache_key`, `input_fingerprint`, `input_file_fingerprints`
- `validation_phase`, `worker_count`, `distribution`
- `warnings`

Cache records do NOT contain:
- Raw `stdout` / `stderr` content
- File diffs or patches
- Prompts or secrets
- Full raw `argv` (only fingerprint)

## Phase 0 Limitations

- No full coverage dependency graph
- No pytest-testmon integration
- No remote cache
- No wait/follow for in-flight checks (deferred)
- No cross-machine cache
- No `$HOME/.rig/relay` writes — cache is project-local under `.build/rig/`

## Configuration

Via `ValidateArgs`:

| Field | Default | Description |
|---|---|---|
| `cache_policy` | `"enabled"` | Cache: enabled, disabled, force_rerun |
| `allow_failed_cache_reuse` | `false` | Reuse failed cache records |
| `cache_root` | `None` | Override cache directory |
| `scheduler_policy` | `"enabled"` | Scheduler: enabled, disabled |
| `lock_running_checks` | `true` | Prevent duplicate execution |
| `validation_phase` | `"pre_report"` | Lifecycle phase |
| `parallel_policy` | `"auto"` | Parallel: auto, disabled, force |
| `max_workers` | `None` | Max parallel workers |
| `xdist_distribution` | `"loadfile"` | xdist distribution mode |
