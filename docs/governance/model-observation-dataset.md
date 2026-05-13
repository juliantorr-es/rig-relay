# Model Observation Dataset

## Status

**Draft.** Defines the content-light observation dataset layer for ranking
cloud providers and local models across real Rig Relay workflows.

## Purpose

Rig Relay uses cleaned, aggregated usage data to answer:

> For this task, on this machine, with this budget/privacy preference,
> which cloud provider or local model should Rig Relay use?

The model observation dataset is the raw material for this recommendation
engine. It is content-light, consent-gated, and export-safe.

## Dataset Schema

Three schemas live in `docs/schemas/`:

| Schema | Purpose |
|--------|---------|
| `rig.relay.model_observation.v1.schema.json` | Per-invocation observation record |
| `rig.relay.provider_ranking_snapshot.v1.schema.json` | Aggregated provider/model scores |
| `rig.relay.local_model_comfort_score.v1.schema.json` | Local model fit assessment |

### ModelObservation Fields

All fields are content-light. No raw prompts, model outputs, source code,
diffs, stdout/stderr bodies, secrets, tokens, API keys, or raw private paths.

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | `rig.relay.model_observation.v1` |
| `observation_id` | string | Unique observation ID |
| `created_at` | string (ISO 8601) | Timestamp |
| `task_kind` | string | Kind of task (e.g. code_gen, chat) |
| `task_fingerprint` | string | SHA256 of task content (not raw) |
| `provider_kind` | enum | `cloud` or `local` |
| `provider_name` | string | Provider name (e.g. openai, ollama) |
| `model_id` | string | Model identifier |
| `backend` | enum | `api`, `mlx`, `llama_cpp` |
| `endpoint_kind` | string (optional) | chat, completion, embedding |
| `machine_profile_id` | string (optional) | For local model observations |
| `input_tokens` | integer (optional) | Prompt tokens |
| `output_tokens` | integer (optional) | Completion tokens |
| `context_tokens` | integer (optional) | Context window usage |
| `latency_ms` | number (optional) | End-to-end latency |
| `time_to_first_token_ms` | number (optional) | TTFT |
| `prompt_eval_tps` | number (optional) | Prompt eval throughput |
| `decode_tps` | number (optional) | Decode throughput |
| `peak_memory_gb` | number (optional) | Peak memory usage |
| `estimated_cost_usd` | number (optional) | Estimated cost |
| `tool_call_count` | integer | Total tool calls |
| `tool_success_count` | integer | Successful tool calls |
| `retry_count` | integer | Retry attempts |
| `refusal_count` | integer | Model refusals |
| `failure_count` | integer | Failed calls |
| `validation_status` | enum | `passed`, `failed`, `skipped`, `unknown` |
| `user_outcome` | enum | `accepted`, `revised`, `rejected`, `unknown` |
| `content_light_guarantee` | boolean | Always `true` |
| `artifact_refs` | array | References to related artifacts (sha256 only) |
| `warnings` | array | Human-readable warnings |

### ProviderRankingSnapshot Fields

| Field | Type | Description |
|-------|------|-------------|
| `ranking_id` | string | Unique ID |
| `created_at` | string (ISO 8601) | Timestamp |
| `task_kind` | string | Task kind this ranking applies to |
| `sample_count` | integer | Number of observations |
| `provider_scores[]` | array | Per-provider scores |
| `model_scores[]` | array | Per-model scores |
| `confidence_level` | enum | `low`, `medium`, `high` |
| `warnings` | array | Warnings (e.g. low sample count) |

Each score includes:
- `task_success_score` (0-1)
- `cost_efficiency_score` (0-1)
- `latency_score` (0-1)
- `tool_reliability_score` (0-1)
- `privacy_score` (0-1)
- `overall_score` (0-1)
- `local_comfort_score` (0-1, model_scores only, optional)

### LocalModelComfortScore Fields

| Field | Type | Description |
|-------|------|-------------|
| `model_id` | string | Model identifier |
| `backend` | enum | `mlx`, `llama_cpp` |
| `quantization` | string (optional) | q4_0, q8_0, fp16 |
| `machine_profile_id` | string | Machine profile (e.g. m1-pro-16gb) |
| `memory_headroom_score` | number (0-1) | Memory fit |
| `speed_score` | number (0-1) | Inference speed |
| `context_score` | number (0-1) | Context window fit |
| `stability_score` | number (0-1) | Runtime stability |
| `comfort_category` | enum | `comfortable`, `maybe`, `not_recommended` |
| `evidence_count` | integer | Observation count supporting this score |
| `warnings` | array | Warnings (e.g. zero evidence) |

## Consent Gates

Every model observation collection is gated by active telemetry consent.
The `observation_allowed_by_consent()` helper checks:

| Observation Kind | Required Active Scope |
|-----------------|---------------------|
| `provider` | `provider_model_benchmarking` |
| `local_model` | `local_model_benchmarking` |
| `commercial_export` | `commercial_dataset_license` |
| `public_aggregate` | `aggregate_public_reporting` |

### Active Consent Semantics

A consent scope is considered **active** only when:
1. The consent record status is `GRANTED` (not `REVOKED`, `DENIED`, or `NOT_REQUESTED`)
2. The scope is present in the record's `scopes` list

If consent is revoked or denied, `active_consent_scopes()` returns an empty
list, even if scopes remain in the record. This means:
- A revoked record still shows which scopes were originally granted (audit)
- But no observation collection is allowed against a revoked record
- The `has_commercial_dataset_license()` helper checks raw scope presence
- The `has_active_commercial_dataset_license()` helper checks scope + status

## Content-Light Guarantee

All observation records carry `content_light_guarantee: true`. The
`validate_observation_content_light()` function verifies:

- No field keys named `raw_prompt`, `prompt`, `raw_model_output`,
  `model_output`, `source_code`, `diff`, `stdout`, `stderr`, `api_key`,
  `access_token`, `refresh_token`, or `private_path`
- No raw secrets in string values (API key patterns, private keys)
- The shared redaction module (`rig_relay.evidence.redaction`) classifies
  these same field keys as `FORBIDDEN`

## Confidence Labels

Early-alpha confidence levels for ranking snapshots:

| Sample Count | Confidence | Label |
|-------------|------------|-------|
| 0 | Low | No observations |
| 1-9 | Low | Insufficient data |
| 10-29 | Medium | Moderate confidence |
| 30+ | High | Reasonable confidence |

Local model comfort scores use three categories:

| Overall Score | Category |
|-------------|----------|
| 0.7+ | Comfortable — model runs well |
| 0.4-0.7 | Maybe — runs but may have constraints |
| <0.4 | Not recommended — unlikely to perform well |

When evidence_count is 0, a warning is emitted: "No observed evidence —
score is estimated, not measured."

## No Raw Content

This dataset layer explicitly prohibits:

- Raw prompts or user messages
- Raw model outputs or completions
- Source code, file contents, or diffs
- stdout/stderr output bodies
- API keys, tokens, secrets, or passwords
- Raw authorization receipt bodies
- Personal identifiable information
- Raw file paths or directory structures

## Commercial Export

Commercial/aggregate export of observation data requires:
1. The `commercial_dataset_license` scope to be **active** (granted + not revoked)
2. The `aggregate_public_reporting` scope for public reports
3. Content-light guarantee verified on all observations
4. See [Usage Data Commercial License](../legal/usage-data-license-alpha.md)

## Related

- [Usage Data Doctrine](./usage-data-doctrine.md)
- [Provider Onboarding Policy](./provider-onboarding-policy.md)
- [Local/Remote Boundary](./relay-local-remote-boundary.md)
- [Usage Data Commercial License](../legal/usage-data-license-alpha.md)
- [Privacy Notice](../legal/privacy-notice-alpha.md)
- [`rig_relay.evidence.model_observations`](../../rig_relay/evidence/model_observations.py)
- [`rig_relay.identity.telemetry_consent`](../../rig_relay/identity/telemetry_consent.py)
