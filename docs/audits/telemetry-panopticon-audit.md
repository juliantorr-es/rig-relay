# Rig Relay Telemetry Audit: Governed Product Telemetry or Panopticon?

**Audit date**: 2026-05-17
**Auditor**: Lane B (telemetry/surveillance boundary audit)
**Repository**: `rig-relay`, branch `main`, commit `c92a220a`
**Status**: Clean working tree

---

## Executive Verdict

**Verdict: Governed telemetry — not a panopticon.**

Rig Relay's telemetry implementation is a legitimate first-party product telemetry system with clear architectural separation between local operational telemetry (required for product function) and remote beta-sharing telemetry (off by default). The content-light doctrine is genuinely implemented in code, not just documented. Defaults are safe: remote sharing is `False`, local observability is `True` with documented feature degradation when disabled. There are alpha-stage gaps in consent enforcement flow, dead OTEL dependencies, and a few open questions about the `session_id` as a stable pseudonymous identifier, but the architecture is sound and the implementation is honest.

---

## Architecture Summary

```
┌─────────────────────────────────────────────┐
│              Agent Loop / Tools              │
│        (emits events via mixin)              │
└──────────────────┬──────────────────────────┘
                   │ send_telemetry_event()
                   ▼
┌─────────────────────────────────────────────┐
│         TelemetryClient (send.py)            │
│                                              │
│  ┌─ Local Sink ──────────────────────────┐  │
│  │ enable_local_observability (default ON) │  │
│  │ → ~/.rig/relay/sessions/<id>/          │  │
│  │   observability.jsonl                  │  │
│  │ → hash-chained, canonical JSONL        │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  ┌─ Remote Sink ─────────────────────────┐  │
│  │ enable_remote_telemetry (default OFF)   │  │
│  │ → https://api.deepseek.com/v1/         │  │
│  │   datalake/events                      │  │
│  │ → fire-and-forget, exception-silent    │  │
│  └────────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
┌────────┐  ┌───────────┐  ┌──────────┐
│ Tracing │  │ Analytics │  │ Evidence │
│ (OTEL   │  │ (DuckDB   │  │ (Google  │
│  deps,  │  │  local)   │  │  Drive   │
│  unused)│  │           │  │  upload) │
└────────┘  └───────────┘  └──────────┘
```

---

## Complete Evidence Table

### 1. Event Emission (Agent Loop)

| Field               | Value                                                                                                                    |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **File**            | `rig_relay/core/_telemetry.py`                                                                                           |
| **Symbol**          | `TelemetryMixin` (mixin on `AgentLoop`)                                                                                  |
| **Data collected**  | Event name, session_id, tool name, status, tool output hash, file counts, model name, agent profile, timing, byte counts |
| **Destination**     | TelemetryClient → local JSONL + optional remote                                                                          |
| **Identifier risk** | Pseudonymous (stable `session_id` UUID, client-generated)                                                                |
| **Content risk**    | None — hashes and counts only. No raw prompts, outputs, paths, or file contents                                          |
| **User control**    | Local ON by default (required for governed mode). Remote OFF by default                                                  |
| **Disclosure**      | `beta-telemetry-onboarding.md`, `usage-data-doctrine.md`                                                                 |
| **Retention**       | Local: evidence-retained. Remote: alpha only, TTL unspecified                                                            |
| **Verdict**         | 🟢 Green                                                                                                                 |
| **Required fix**    | Specify remote TTL; add consent gate before emission                                                                     |

### 2. TelemetryClient — Local Sink

| Field               | Value                                                             |
| ------------------- | ----------------------------------------------------------------- |
| **File**            | `rig_relay/core/telemetry/send.py:150-162`                        |
| **Symbol**          | `TelemetryClient.send_telemetry_event()` local block              |
| **Data collected**  | Event name, properties dict, session_id, parent_session_id        |
| **Destination**     | `~/.rig/relay/sessions/<id>/observability.jsonl`                  |
| **Identifier risk** | Pseudonymous (session_id)                                         |
| **Content risk**    | None — properties are content-light per sending callers           |
| **User control**    | Controlled by `enable_local_observability` setting (default True) |
| **Disclosure**      | Documented in telemetry modes and onboarding                      |
| **Retention**       | Local disk, evidence-retained, user-deletable                     |
| **Verdict**         | 🟢 Green                                                          |
| **Required fix**    | None — this is the governed local store                           |

### 3. TelemetryClient — Remote Sink

| Field               | Value                                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **File**            | `rig_relay/core/telemetry/send.py:163-205`                                                                                           |
| **Symbol**          | `TelemetryClient.send_telemetry_event()` remote block                                                                                |
| **Data collected**  | Event name, properties + base_metadata (session_id, parent_session_id, agent_entrypoint, agent_version, client_name, client_version) |
| **Destination**     | `https://api.deepseek.com/v1/datalake/events` (or Mistral provider API base)                                                         |
| **Identifier risk** | Pseudonymous (stable session_id + client_name/version)                                                                               |
| **Content risk**    | None — hashes and counts, no raw content                                                                                             |
| **User control**    | **Default OFF** (`enable_remote_telemetry=False`, `enable_telemetry=False`)                                                          |
| **Disclosure**      | `beta-telemetry-onboarding.md`, `telemetry-contribution-policy.md`                                                                   |
| **Retention**       | Server-side TTL unknown (DeepSeek datalake)                                                                                          |
| **Verdict**         | 🟢 Green (when off by default) / 🟡 Yellow (when enabled, due to unknown server retention and missing consent gate in code)          |
| **Required fix**    | Document server-side TTL; wire consent enforcement before upload; add `--dry-run` receipt                                            |

### 4. Build Base Metadata

| Field               | Value                                                                                                                                  |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **File**            | `rig_relay/core/telemetry/build_metadata.py`                                                                                           |
| **Symbol**          | `build_base_metadata()`, `EntrypointMetadata`                                                                                          |
| **Data collected**  | `agent_entrypoint` (cli/acp/desktop/programmatic), `agent_version`, `client_name`, `client_version`, `session_id`, `parent_session_id` |
| **Destination**     | Included in every telemetry event (local + remote)                                                                                     |
| **Identifier risk** | Pseudonymous — product version + session UUID. No IP, no user-agent, no machine fingerprint                                            |
| **Content risk**    | None                                                                                                                                   |
| **User control**    | Inherent to telemetry toggle                                                                                                           |
| **Disclosure**      | Schema-visible in `TelemetryBaseMetadata`                                                                                              |
| **Retention**       | Follows event retention                                                                                                                |
| **Verdict**         | 🟢 Green                                                                                                                               |
| **Required fix**    | None — this is minimal product metadata                                                                                                |

### 5. User-Agent Header (HTTP)

| Field               | Value                                                                                         |
| ------------------- | --------------------------------------------------------------------------------------------- |
| **File**            | `rig_relay/core/utils/http.py:35`                                                             |
| **Symbol**          | `get_user_agent()`                                                                            |
| **Data collected**  | Static string: `"Mistral-Vibe/<version>"` or `"mistral-client-python/Mistral-Vibe/<version>"` |
| **Destination**     | HTTP header on remote telemetry POST                                                          |
| **Identifier risk** | None — identifies product version, not user or device                                         |
| **Content risk**    | None                                                                                          |
| **User control**    | N/A (not user-identifying)                                                                    |
| **Disclosure**      | Implicit in HTTP protocol                                                                     |
| **Retention**       | Server access log (not in our control)                                                        |
| **Verdict**         | 🟢 Green                                                                                      |
| **Required fix**    | None                                                                                          |

### 6. Tracing Subsystem (OTEL Unused)

| Field               | Value                                                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **File**            | `rig_relay/tracing/` (recorder, redaction, store, contract, context, models)                                              |
| **Symbol**          | `TraceRecorder`, `sanitize_trace_attributes()`, `TraceContractRegistry`                                                   |
| **Data collected**  | Trace events with redacted attributes (token/api_key/password/secret/credential/authorization/cookie/bearer keys dropped) |
| **Destination**     | Local JSONL only (`~/.rig/relay/traces/`)                                                                                 |
| **Identifier risk** | Pseudonymous (correlation_id, handshake_id)                                                                               |
| **Content risk**    | Low — redaction layer active; keys dropped, strings truncated at 1000 chars                                               |
| **User control**    | Local only, no remote export path wired                                                                                   |
| **Disclosure**      | `tracing-v0.md`, `correlated_visibility_matrix.v1.json`                                                                   |
| **Retention**       | Local disk                                                                                                                |
| **Verdict**         | 🟢 Green                                                                                                                  |
| **Required fix**    | Remove dead OpenTelemetry dependencies or wire them in with governance                                                    |

### 7. OpenTelemetry Dependencies (Dead Weight)

| Field               | Value                                                                                                                    |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **File**            | `pyproject.toml`, `uv.lock`                                                                                              |
| **Symbol**          | `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-semantic-conventions` |
| **Data collected**  | **Nothing** — these are installed dependencies with zero import or usage in the codebase                                 |
| **Destination**     | N/A                                                                                                                      |
| **Identifier risk** | None currently (unused)                                                                                                  |
| **Content risk**    | None currently (unused)                                                                                                  |
| **User control**    | N/A                                                                                                                      |
| **Disclosure**      | Not disclosed — these are not documented as used, but their presence in pyproject.toml is discoverable                   |
| **Retention**       | N/A                                                                                                                      |
| **Verdict**         | 🟡 Yellow — dead dependencies create supply-chain surface area and may imply planned functionality not yet disclosed     |
| **Required fix**    | Remove OTEL dependencies or document governance plan for them                                                            |

### 8. Google Drive Upload (Debug Bundle)

| Field               | Value                                                                                                    |
| ------------------- | -------------------------------------------------------------------------------------------------------- |
| **File**            | `rig_relay/evidence/google_drive_upload.py`, `rig_relay/evidence/telemetry_bundle.py`                    |
| **Symbol**          | `upload_bundle()`, `validate_bundle()`, `create_bundle()`                                                |
| **Data collected**  | Content-light telemetry bundles (validated for forbidden content)                                        |
| **Destination**     | Google Drive (`drive.file` scope, user-authenticated)                                                    |
| **Identifier risk** | Linked to user's Google account via OAuth                                                                |
| **Content risk**    | Low — bundle validator enforces content-light guarantee, rejects raw prompts/outputs/secrets             |
| **User control**    | **Explicit user action** — never automatic. Requires OAuth consent, `--confirm` flag, dry-run by default |
| **Disclosure**      | `debug-bundle-policy.md`, `telemetry-contribution-policy.md`                                             |
| **Retention**       | User's own Google Drive                                                                                  |
| **Verdict**         | 🟢 Green — explicit export, not surveillance                                                             |
| **Required fix**    | None                                                                                                     |

### 9. Consent Model

| Field               | Value                                                                                                                                                                                                                              |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **File**            | `rig_relay/identity/telemetry_consent.py`                                                                                                                                                                                          |
| **Symbol**          | `TelemetryConsentRecord`, `TelemetryConsentScope`, `grant_consent()`, `observation_allowed_by_consent()`                                                                                                                           |
| **Data collected**  | consent_id, subject_hash, provider, status, scopes, timestamps, policy_version                                                                                                                                                     |
| **Destination**     | Local consent store                                                                                                                                                                                                                |
| **Identifier risk** | Low — `subject_hash` is a hash, not raw identity                                                                                                                                                                                   |
| **Content risk**    | None — content-light by design                                                                                                                                                                                                     |
| **User control**    | `NOT_REQUESTED` by default, scoped to 5 basic categories for default grant                                                                                                                                                         |
| **Disclosure**      | Schema `rig.relay.telemetry_consent.v1.schema.json`                                                                                                                                                                                |
| **Retention**       | Local                                                                                                                                                                                                                              |
| **Verdict**         | 🟡 Yellow — model exists but consent enforcement hooks are not fully wired into the upload path. The `send_telemetry_event()` method checks `_is_remote_telemetry_enabled()` (a settings toggle) but does not check consent record |
| **Required fix**    | Wire `observation_allowed_by_consent()` into the remote upload gate                                                                                                                                                                |

### 10. Static Generated Website

| Field               | Value                                                                                          |
| ------------------- | ---------------------------------------------------------------------------------------------- |
| **File**            | `docs/assets/site.js`, `docs/index.html`, all `docs/pages/*.html`                              |
| **Symbol**          | Client-side search, disclosure controls, section linking                                       |
| **Data collected**  | **Nothing** — site.js explicitly states: "No framework. No remote CDNs. No tracking. No eval." |
| **Destination**     | N/A                                                                                            |
| **Identifier risk** | **None** — no localStorage, no cookies, no fingerprinting, no remote requests                  |
| **Content risk**    | None                                                                                           |
| **User control**    | All functionality works without JS (progressive enhancement)                                   |
| **Disclosure**      | Source code comment in site.js                                                                 |
| **Retention**       | N/A                                                                                            |
| **Verdict**         | 🟢 Green — exemplary                                                                           |
| **Required fix**    | None                                                                                           |

### 11. Analytics Substrate (Local Only)

| Field               | Value                                                                               |
| ------------------- | ----------------------------------------------------------------------------------- |
| **File**            | `rig_relay/analytics/`, `rig_relay/core/telemetry/duckdb_projection.py`             |
| **Symbol**          | `bash_rows.py`, `model_rows.py`, DuckDB projections                                 |
| **Data collected**  | Aggregate bash invocation stats, model usage stats derived from local observability |
| **Destination**     | Local DuckDB database (`.rig/relay/analytics/`)                                     |
| **Identifier risk** | None — aggregate, local only                                                        |
| **Content risk**    | None — derived from content-light events                                            |
| **User control**    | Local only, never exported by default                                               |
| **Disclosure**      | `usage-data-doctrine.md`                                                            |
| **Retention**       | Local disk                                                                          |
| **Verdict**         | 🟢 Green                                                                            |
| **Required fix**    | None                                                                                |

### 12. Telemetry Validation & Receipts

| Field               | Value                                                                            |
| ------------------- | -------------------------------------------------------------------------------- |
| **File**            | `rig_relay/core/telemetry/validation.py`, `rig_relay/core/telemetry/receipts.py` |
| **Symbol**          | `EvidenceValidationResult`, `EvidenceReceipt`, `verify_receipt()`                |
| **Data collected**  | Receipt chain: event_index, evidence_sha256, evidence_relative_path, event_name  |
| **Destination**     | Local — validates observability.jsonl integrity                                  |
| **Identifier risk** | None — hash chain verification                                                   |
| **Content risk**    | None — hashes only                                                               |
| **User control**    | Automatic, part of local observability                                           |
| **Disclosure**      | `rig.relay.artifact.envelope.v1.schema.json`                                     |
| **Retention**       | Local                                                                            |
| **Verdict**         | 🟢 Green                                                                         |
| **Required fix**    | None                                                                             |

### 13. Telemetry Settings / Feature Gates

| Field               | Value                                                                                                                                                    |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **File**            | `rig_relay/core/config/telemetry_modes.py`, `rig_relay/core/config/_settings.py`                                                                         |
| **Symbol**          | `disabled_features_for_settings()`, `can_use_*()` guards                                                                                                 |
| **Data collected**  | Settings: `enable_local_observability` (default True), `enable_remote_telemetry` (default False), `mode` (basic_local/governed_local/beta_orchestration) |
| **Destination**     | Configuration — gates features, not data                                                                                                                 |
| **Identifier risk** | None                                                                                                                                                     |
| **Content risk**    | None                                                                                                                                                     |
| **User control**    | Full — three modes with documented feature degradation                                                                                                   |
| **Disclosure**      | `beta-telemetry-onboarding.md`, `telemetry_modes.py` docstring                                                                                           |
| **Retention**       | Settings file                                                                                                                                            |
| **Verdict**         | 🟢 Green                                                                                                                                                 |
| **Required fix**    | None — the degradation model is correct                                                                                                                  |

### 14. Session ID (Pseudonymous Identifier)

| Field               | Value                                                                                                                                                                                                                                         |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **File**            | Throughout (`TelemetryClient`, `AgentLoop`, local store)                                                                                                                                                                                      |
| **Symbol**          | `session_id` (UUID4 generated per session)                                                                                                                                                                                                    |
| **Data collected**  | Stable UUID that persists for the lifespan of a session                                                                                                                                                                                       |
| **Destination**     | Every event, local + remote                                                                                                                                                                                                                   |
| **Identifier risk** | **Pseudonymous** — stable across a session. If the same user runs multiple sessions, each gets a new UUID (not linkable across sessions without parent_session_id chain). The `parent_session_id` creates a session lineage.                  |
| **Content risk**    | Low — identifier, not content                                                                                                                                                                                                                 |
| **User control**    | Cannot be disabled (required for coordination)                                                                                                                                                                                                |
| **Disclosure**      | Not separately disclosed                                                                                                                                                                                                                      |
| **Retention**       | Follows event retention                                                                                                                                                                                                                       |
| **Verdict**         | 🟡 Yellow — `session_id` is a necessary operational identifier, but the lineage chain (`parent_session_id`) creates a persistent pseudonymous trail across sessions. This is not disguised or hidden, but it's not clearly explained to users |
| **Required fix**    | Document session_id lineage in privacy notice; consider session_id rotation for privacy-sensitive deployments                                                                                                                                 |

---

## Top 10 Risks (Ranked)

| #   | Risk                                                                                                                                                                                                                                                                                              | Severity | Category                      | Gap                                                                           |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ----------------------------- | ----------------------------------------------------------------------------- |
| 1   | **Consent enforcement not wired into upload path** — `send_telemetry_event()` checks settings toggle (`enable_remote_telemetry`) but never checks `TelemetryConsentRecord`. A user who enabled remote sharing in settings but later revoked consent would still have data uploaded                | HIGH     | Implementation gap            | Wire `observation_allowed_by_consent()` into remote gate                      |
| 2   | **Remote server-side retention unknown** — Uploads go to DeepSeek datalake with no documented TTL, deletion API, or data processing agreement                                                                                                                                                     | MEDIUM   | Disclosure gap                | Document or negotiate server-side retention policy                            |
| 3   | **Session lineage creates persistent pseudonymous trail** — `parent_session_id` chains sessions together indefinitely. Combined with `client_name`/`client_version`, this creates a reasonably linkable profile                                                                                   | MEDIUM   | Linkability risk              | Document lineage; add lineage-break option for privacy-sensitive users        |
| 4   | **Dead OTEL dependencies** — 4 OpenTelemetry packages installed but zero usage. Creates supply-chain surface area and implies planned export capabilities not yet governed                                                                                                                        | MEDIUM   | Supply chain / disclosure gap | Remove or govern with explicit policy                                         |
| 5   | **Consent scopes conflate product function with commercialization** — `TOOL_REFINEMENT_METRICS` is in the default grant set alongside `USAGE_METRICS`. Users cannot opt out of refinement telemetry without also losing governed mode                                                             | MEDIUM   | Granularity gap               | Split refinement metrics into a separate toggle or make the trade-off clearer |
| 6   | **`enable_telemetry` legacy alias** — The `VibeConfig` model has `enable_telemetry: bool = False` marked as "Legacy alias for enable_remote_telemetry". If a user sets `enable_telemetry = True` expecting a master switch, they get remote sharing enabled without understanding the distinction | LOW      | Naming risk                   | Remove legacy alias or emit deprecation warning                               |
| 7   | **Exception-silent upload failures** — Remote upload failures are silently swallowed (`except Exception: pass`). This means users might believe remote sharing is off when it's actually just failing                                                                                             | LOW      | Transparency risk             | Log upload failures locally at DEBUG level so they're auditable               |
| 8   | **No machine-readable privacy policy on generated site** — The static site has no `privacy.html` page, no `/rig-relay/.well-known/` privacy endpoint, and no machine-readable policy JSON linked from the home page                                                                               | LOW      | Disclosure gap                | Add privacy policy page to generated site; link from footer                   |
| 9   | **Observation consent model is provider-scoped but not repository-scoped** — A user who consents to provider observations for one repo implicitly consents for all repos on the same machine                                                                                                      | LOW      | Scope granularity gap         | Consider per-repo consent scoping                                             |
| 10  | **No automated test proving forbidden fields are excluded** — The redaction module has unit tests, but there's no end-to-end test that captures a real tool call, runs it through the telemetry pipeline, and asserts no raw prompts/paths/secrets appear in the output                           | LOW      | Test coverage gap             | Add E2E telemetry sanitization test                                           |

---

## Doctrine Compliance Matrix

| Doctrine Requirement                                  | Status                                             | Evidence                                                                                                                                               |
| ----------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| First-party telemetry by default                      | ✅ Compliant                                       | `enable_remote_telemetry=False` default. All telemetry is self-hosted (local JSONL) or first-party (DeepSeek/Mistral datalake)                         |
| Opt-out supported                                     | ✅ Compliant                                       | `enable_local_observability` and `enable_remote_telemetry` independently toggleable                                                                    |
| Disabling degrades features                           | ✅ Compliant                                       | `telemetry_modes.py` explicitly disables governed mode, fleet, checkpoint, coordination leases, replay/debug, autonomous spawn when local ops disabled |
| Degradation is disclosed                              | ✅ Compliant                                       | `beta-telemetry-onboarding.md` documents degraded feature tables                                                                                       |
| No sale of raw user content                           | ✅ Compliant                                       | Multiple "never" clauses in doctrine and code. Content-light enforcement in bundle validator                                                           |
| No raw prompts in telemetry                           | ✅ Compliant                                       | `send_tool_call_finished()` sends hashes only (`input_sha256`, `output_sha256`), never raw content                                                     |
| No raw file contents                                  | ✅ Compliant                                       | Event payloads never include file bodies — only hashes and byte counts                                                                                 |
| No credentials/secrets                                | ✅ Compliant                                       | `sanitize_trace_attributes()` drops keys matching token/api_key/password/secret/credential/authorization/cookie/bearer                                 |
| Commercialization limited to aggregated/de-identified | ✅ Compliant (by doctrine) / 🟡 Untested (in code) | Doctrine permits commercialization of derived insights. The export pipeline enforces content-light but doesn't verify aggregation level before export  |
| Inspectable telemetry                                 | ✅ Compliant                                       | Local `observability.jsonl` is human-readable. Schemas in `docs/schemas/`. Events are canonical JSON                                                   |
| Schema-governed                                       | ✅ Compliant                                       | Events registered in `EventName` enum. Schemas in `docs/schemas/` with versioned IDs                                                                   |
| Auditable receipts                                    | ✅ Compliant                                       | `EvidenceReceipt` with SHA256 chain. `verify_receipt()` validates integrity                                                                            |
| Privacy notice exists                                 | ✅ Compliant                                       | `privacy-notice-alpha.md` and JSON equivalent                                                                                                          |
| No third-party analytics on static site               | ✅ Compliant                                       | `site.js` explicitly: "No tracking." Static site is pure HTML/CSS/JS with zero remote requests                                                         |
| No silent commit trailers                             | ✅ Compliant                                       | `beta-telemetry-onboarding.md`: "Rig Relay does not add silent co-author trailers"                                                                     |
| Debug bundles explicit                                | ✅ Compliant                                       | `telemetry_bundle.py` dry-run by default; Google Drive upload requires `--confirm` flag                                                                |

---

## Opt-Out / Degradation Review

### Local Operational Telemetry (default ON)

| Feature             | When Enabled                                                      | When Disabled                               |
| ------------------- | ----------------------------------------------------------------- | ------------------------------------------- |
| Governed mode       | Full governance: tool permissions, mutation gating, session rules | **Disabled** — reverts to basic safety      |
| Fleet/delegate      | Multi-agent coordination, worktree isolation                      | **Disabled**                                |
| Checkpoint commits  | Git checkpoint tool available                                     | **Disabled**                                |
| Coordination leases | Path reservations, collision detection                            | **Disabled**                                |
| Replay/debug        | Session replay and debugging                                      | **Disabled**                                |
| Autonomous spawn    | Sub-agent execution                                               | **Disabled**                                |
| Ralph scanner       | Projection-based candidate ranking                                | **Disabled** — no projections to consume    |
| Basic agent loop    | Functional                                                        | **Still functional** — basic safety remains |

**Verdict**: The degradation is real, architectural, and intentional. Disabling local telemetry genuinely removes functionality because the functionality depends on the observability data. This is honest design, not deceptive dark-pattern degradation.

### Remote Beta Sharing (default OFF)

- `enable_remote_telemetry = False` by default
- `enable_telemetry = False` by default (legacy alias)
- When disabled: no HTTP requests leave the machine for telemetry
- When enabled: content-light bundles posted to DeepSeek datalake

**Verdict**: Default-off is the correct privacy posture. The remote path is gated behind a boolean toggle that is respected in code.

### Gap: Consent vs. Settings

The consent model (`TelemetryConsentRecord`) defines scopes and tracks consent status, but the upload gate checks only `enable_remote_telemetry` — a settings flag — not the consent record. A user who toggles remote sharing ON but later revokes consent would still have data uploaded. This is the top-ranked risk.

---

## Static-Site Review

| Check                         | Result                                                                  |
| ----------------------------- | ----------------------------------------------------------------------- |
| Third-party analytics scripts | **None found**                                                          |
| Tracking pixels / beacons     | **None found**                                                          |
| localStorage / cookies        | **None set** (verified in site.js)                                      |
| Remote CDN requests           | **None** — all assets self-hosted                                       |
| Fingerprinting                | **None** — no canvas, no font enumeration, no WebGL                     |
| Raw IP collection             | **None** — static site, no server-side collection                       |
| Raw referrer collection       | **None**                                                                |
| Search query collection       | **Client-side only** — search-index.json loaded and searched in-browser |
| Privacy notice on site        | **Missing** — no privacy page linked from generated site                |
| Machine-readable policy       | **Missing** — no `.well-known/` or structured policy artifact           |

**Verdict**: The static site is exemplary in its privacy posture — zero tracking, zero remote requests, progressive enhancement. The only gap is the absence of a visible privacy notice on the generated site itself.

---

## Monetization Boundary Review

### What the Doctrine Says

From `usage-data-doctrine.md` and `telemetry-contribution-policy.md`:

**Permitted commercialization**:

- Aggregated, de-identified, or derived insights
- Benchmarks
- Models
- Reports
- Product intelligence generated from telemetry

**Prohibited**:

- Sale of raw user content
- Sale of prompts
- Sale of credentials or secrets
- Sale of private files or repository contents

### What the Code Enforces

- **Content-light bundle validator** (`telemetry_bundle.py`): rejects bundles containing raw prompts, model outputs, file contents, stdout/stderr, diffs, or secrets
- **Redaction pipeline** (`redaction.py`): drops token/key/secret/credential fields
- **Export pipeline** (`dataset_export.py`): content-light enforcement with manifest `content_light_guarantee: true`
- **Consent scopes**: Commercial/data license scopes (`COMMERCIAL_DATASET_LICENSE`, `AGGREGATE_PUBLIC_REPORTING`) are **never in the default grant set** — they require explicit opt-in

### Gap Identified

The doctrine says Rig "may commercialize aggregated, de-identified, or derived insights" but the code currently doesn't verify **aggregation level** before export — it only enforces content-light. Individual tool-call events are technically "content-light" but not "aggregated." There should be a gate that either:

1. Requires a minimum k-anonymity threshold before export, or
2. Requires explicit `COMMERCIAL_DATASET_LICENSE` consent before any export that isn't aggregated

**Verdict**: The raw-content boundary is hard (code-enforced). The aggregation boundary is soft (doctrine-stated, not code-enforced). This is acceptable for alpha but should be hardened.

---

## Required Fixes — Convergent Slices

### Slice A: Consent Enforcement Wire-Up (BLOCKER)

**Problem**: Consent record exists but doesn't gate the upload path.

**Changes**:

- Code: `rig_relay/core/telemetry/send.py` — add `consent_record` parameter to `send_telemetry_event()` or check consent store before remote upload
- Code: `rig_relay/core/_telemetry.py` — pass consent state through the TelemetryMixin
- Tests: `tests/core/test_telemetry_send.py` — add test proving upload is refused when consent is REVOKED even if settings toggle is ON
- Tests: `tests/identity/test_telemetry_consent.py` — add integration test wiring consent to telemetry client
- Docs: update `telemetry-contribution-policy.md` with consent enforcement flow diagram

### Slice B: Redaction and Linkability Firewall

**Problem**: Session lineage is unbroken; session_id is a stable pseudonymous identifier.

**Changes**:

- Code: Add `lineage_break` option to session fork that generates a new root session_id with no parent
- Code: Add session_id rotation on consent revocation
- Docs: Document session_id lifecycle in privacy notice, including lineage implications
- Docs: Add data flow diagram showing what identifiers persist where
- Tests: Test that lineage break prevents correlation across sessions

### Slice C: Opt-Out and Degraded-Mode Enforcement

**Problem**: Legacy `enable_telemetry` alias creates confusion; no automated test proves all exporters respect opt-out.

**Changes**:

- Code: Deprecate or remove `enable_telemetry` legacy alias in `_settings.py`
- Code: Add `_verify_opt_out_respected()` check that runs on startup
- Tests: E2E test proving zero remote HTTP requests when remote telemetry is disabled
- Tests: Test proving all feature gates degrade correctly
- Docs: Clarify the three-mode model in onboarding

### Slice D: Static-Site Privacy Presence

**Problem**: Generated site has no privacy notice or machine-readable policy.

**Changes**:

- Docs: Add `docs/json/legal/site-privacy.v1.json` (privacy notice for site visitors)
- Renderer: Render privacy page from JSON artifact
- Code: Add privacy link to site footer/nav
- Docs: Add `Content-Security-Policy` validation to release gate

### Slice E: Telemetry Receipts, Retention, and Audit UI

**Problem**: Remote retention TTL unknown; no automated test for forbidden-field exclusion.

**Changes**:

- Code: Add retention TTL field to remote upload payload (or negotiate with endpoint)
- Tests: E2E telemetry sanitization test — capture real tool call, run through pipeline, assert no raw prompts/paths/secrets in output
- Tests: Receipt chain integrity test for multi-event sessions
- Docs: Document destruction/deletion process for remote data
- Code: Add content-light audit report generator that users can run locally

---

## Test Plan

| Test                                               | File                                                   | Status                                                     |
| -------------------------------------------------- | ------------------------------------------------------ | ---------------------------------------------------------- |
| Opt-out enforcement (remote OFF → zero HTTP)       | `tests/core/test_telemetry_send.py`                    | ❌ Missing                                                 |
| Redaction — forbidden fields excluded              | `tests/evidence/test_redaction.py`                     | ✅ Exists (unit tests)                                     |
| Redaction — E2E with real tool call                | `tests/telemetry/test_observability_e2e.py`            | ⚠️ Partial — checks event structure, not content exclusion |
| Schema governance — event validates against schema | `tests/scripts/test_telemetry_contribution_schemas.py` | ✅ Exists                                                  |
| Static-site — no third-party trackers              | Release gate `static.renderer.no_secret_leakage`       | ✅ Exists (Lane B)                                         |
| Receipt generation — hash chain valid              | `tests/core/test_telemetry_send.py`                    | ⚠️ Needs verification                                      |
| Retention — TTL respected                          | N/A                                                    | ❌ Not applicable (remote TTL unknown)                     |
| Disclosure — onboarding matches implementation     | N/A                                                    | ⚠️ Manual verification needed                              |
| No hidden channels — all upload paths covered      | `tests/scripts/test_rig_relay_telemetry_bundle.py`     | ✅ Exists (bundle validation)                              |
| Consent wire-up — revoked consent blocks upload    | `tests/identity/test_telemetry_consent.py`             | ❌ Missing                                                 |

---

## Open Questions

1. **What is the server-side retention policy for DeepSeek's datalake endpoint?** The code uploads to `https://api.deepseek.com/v1/datalake/events` but there's no documented TTL, deletion API, or data processing agreement. If the datalake retains events indefinitely, this changes the risk calculus for remote sharing.

2. **Are OpenTelemetry dependencies planned for future use or are they dead weight?** Four OTEL packages in `pyproject.toml` with zero usage. If they're planned, the governance plan should be documented before wiring them in. If they're dead weight, they should be removed.

3. **Is the `subject_hash` in TelemetryConsentRecord derived from identity data, or is it a random identifier?** The consent model has a `subject_hash` field with no documentation on how it's generated. If it's a hash of an email, GitHub username, or other PII, it flips from pseudonymous to personal data.

4. **What is the data processing relationship with Mistral/DeepSeek?** The telemetry upload endpoint is on their API infrastructure. Are they a data processor or a joint controller? Is there a DPA? This matters for GDPR compliance if European users adopt Rig Relay.

5. **Can users delete their remote telemetry data?** The doctrine says remote data is deletable, but there's no code path implementing a deletion request.

---

## Final Assessment

Rig Relay's telemetry implementation is **governed first-party product telemetry**, not surveillance or a panopticon. The architecture separates local operational telemetry from remote sharing cleanly. Defaults are safe. Content-light guarantees are implemented in code, not just stated in docs. The static site is tracking-free. The degradation model when telemetry is disabled is honest and architectural, not a dark pattern.

The gaps — consent enforcement wire-up, session lineage documentation, dead OTEL dependencies, and missing E2E content-exclusion tests — are alpha-stage implementation issues, not architectural design flaws. They should be addressed before general availability, particularly the consent enforcement gap (Slice A), which is the only finding that could cause a user's revoked consent to be ignored.

If the alternative were a panopticon, it would be capturing raw prompts, raw file contents, raw paths, IP addresses, user agents, and session replays, uploading them silently to a third-party analytics service with no opt-out. Rig Relay does none of these things. It is not that. It is a governed telemetry system that needs its last few consent bolts tightened.

**Bottom line: Not a panopticon. Governed telemetry. Ship with Slice A fixed.**
