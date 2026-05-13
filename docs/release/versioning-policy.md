# Rig Relay Versioning Policy

## Independent Version Line

Rig Relay has an **independent version line** derived from Mistral Vibe CLI
lineage but versioned independently. Upstream Vibe CLI version numbers are
**provenance only** — they do not determine Rig Relay's version.

| Context | Version |
|---|---|
| Human/product version | **v0.1.0-alpha.1** |
| Python package version (PEP 440) | **0.1.0a1** |

## Version Format

- **Human**: SemVer-style wording: `vMAJOR.MINOR.PATCH-<pre-release>`
  Example: `v0.1.0-alpha.1`
- **Python**: PEP 440-compatible: `<major>.<minor>.<patch><pre>`
  Example: `0.1.0a1`

## Pre-release Convention

| Suffix | Meaning |
|---|---|
| `a1`, `a2`, `a3` | Alpha releases — unstable API, schema, CLI changes allowed |
| `b1`, `b2` | Beta releases — API/schema freeze preparation |
| (none) | Stable release — public API/CLI/schema contracts stable |

## What Version Bumps Mean

| Bump | Meaning |
|---|---|
| Patch (0.1.0 → 0.1.1) | Bug fixes, tests, docs, safety fixes |
| Minor (0.1.0 → 0.2.0) | New orchestration capability, feature additions |
| Major (0.y.z → 1.0.0) | Stable CLI/data contracts for external users |

## Current Release

**Rig Relay v0.1.0-alpha.1** (Python package `0.1.0a1`)

This is the first alpha release. It includes:
- Local guarded runtime with dirty-file preservation
- Coordination store and tool
- Checkpoint commits
- Normalized event streams
- Dataset exporter, report, and inspector
- Reviewer cockpit, spawn planner, current_state pulse
- Queue planner
- Telemetry/data-sharing doctrine
- Semantic change snippet anonymizer

## Alpha Stability Guarantee

During the 0.y.z phase:
- CLI flags may change.
- JSON Schema fields may be added, removed, or renamed.
- Runtime behavior may change.
- Data formats may change.
- No backward compatibility guarantees.

## Provenance

Rig Relay began as a Vibe-derived fork but now uses an independent version
line. Upstream compatibility is not guaranteed. The `vibe` module namespace
is retained for internal organizational purposes during alpha. The legacy migration to `rig_relay.*` follows a Strangler Fig pattern. See `docs/governance/vibe-legacy-deprecation.md` for the migration doctrine. Existing `vibe.*` imports remain supported during alpha. New product code targets `rig_relay.*`.
future release.

## Version Source of Truth

The canonical version is defined in two places that MUST match:

1. `pyproject.toml`: `version = "0.1.0a1"` — Python packaging source
2. `vibe/__init__.py`: `__version__ = "0.1.0a1"` — runtime access

Both must be updated together on every release.
