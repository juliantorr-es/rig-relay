# Rig Relay Dependency Policy

## Philosophy

Rig Relay is a cohesive product, not a tiny library. Product-critical capabilities
use explicit core runtime dependencies. We do not maintain fragile ImportError
fallback paths for capabilities that are part of the product.

## Three-Bucket Model

| Bucket | Purpose | Declared In | Used By |
|---|---|---|---|
| **Core runtime** | Features installed for everyone | `[project.dependencies]` | Any runtime module |
| **Workbench/dev group** | Contributor tooling, notebooks, interactive analytics | `[dependency-groups]` | Notebooks, scripts |
| **Optional extras** | Genuinely non-product integrations | `[project.optional-dependencies]` | Experimental features only |

## Rules

1. **Explicit declaration required.** If Rig Relay imports a package directly
   in any runtime module, that package must be declared explicitly in
   `[project.dependencies]` or `[project.optional-dependencies]`.

2. **No accidental transitive dependency reliance.** If package A brings in
   package B, and Rig Relay code imports B directly, B must be listed as a
   dependency. An upstream update can otherwise remove B and break the build.

3. **Product-critical deps are core.** If a capability is part of the default
   product install (dataset analysis, desktop shell, schema validation,
   telemetry upload), its dependencies belong in `[project.dependencies]`,
   not in optional extras.

4. **Use dependencies intentionally.** Import a core dependency where it
   improves correctness, maintainability, or product quality. Do not add
   duplicate stdlib-only reimplementations to pretend the dependency is
   optional. Do not import a dependency just because it happens to be
   installed.

5. **Avoid dependency soup.** A dependency is worth the cost if it:
   - Removes significant boilerplate or bug-prone logic
   - Provides correctness guarantees the stdlib cannot
   - Is the standard backend for the domain (DuckDB for analytics,
     pywebview for desktop, jsonschema for validation)

6. **Workbench dependencies.** Libraries used only by the marimo notebook
   and interactive analysis tools (pandas, altair, marimo) belong in the
   `workbench` dependency group, not in optional extras. These are
   contributor/development tools, not product features.

7. **Optional extras are for non-product integrations.** Examples:
   third-party API bindings not part of the core product, experimental
   local workflows, or platform-specific shims. Optional extras must NOT
   be used to gate product features.

## Current Classification (2026-05-13)

### Core runtime dependencies (product features)

| Package | Role |
|---|---|
| `duckdb` | Dataset analytics, current_state aggregation, reports, snippets |
| `jsonschema` | Schema validation boundary (bundles, receipts, projections) |
| `pywebview` | Desktop cockpit shell |
| `google-api-python-client` | Google Drive upload |
| `google-auth` | Google OAuth flow |
| `google-auth-oauthlib` | Google OAuth flow (app-side) |
| `google-auth-httplib2` | Google OAuth HTTP transport |

### Workbench dependency group (not product)

| Package | Role |
|---|---|
| `pandas` | Inspector tables (marimo notebook) |
| `altair` | Inspector charts (marimo notebook) |
| `marimo` | Interactive dataset workbench |

### Optional extras

| Extra | Contents | Reason |
|---|---|---|
| `desktop` | `pywebview` | Listed for discoverability; actually pulled in as core |

## Enforcement

- CI (ruff + pyright) must pass after every dependency change.
- Tests verify that every directly imported runtime dependency is declared.
- Adding a new optional extra that gates a product feature requires policy
  review.

## Cross-References

- [Python Packaging Guide — Optional Dependencies](https://packaging.python.org/en/latest/specifications/dependency-specifiers/#optional-dependencies)
- [uv — Dependency Management](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- [Install Channels](../install.md)
- [Usage Data Doctrine](usage-data-doctrine.md)
- [Desktop Cockpit UI Doctrine](desktop-cockpit-ui.md)
