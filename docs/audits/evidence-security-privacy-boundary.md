# Audit: Evidence Security and Privacy Boundary
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: e389b446706173ebc5950931994ba4cdb6a7d9f4
Scope: Read-only security audit
Owner area: security

## Executive Summary
This audit identifies sensitive data risks in Rig Relay's evidence storage. The primary risk is the leakage of absolute filesystem paths and environment secrets into project-local evidence files, which could be accidentally committed to version control.

## Evidence Privacy Inventory
- **Observability JSONL**: Contains full message history (potentially sensitive code/secrets).
- **Context Reports**: Contains tool schemas and system prompts.
- **Artifacts**: Contains raw tool outputs (e.g., `cat` of a config file).
- **Shadow Requests**: Contains the full payload sent to the LLM.

## Sensitive Field Map
| Field | Location | Risk |
| :--- | :--- | :--- |
| `artifact_path` | `observability.jsonl` | Leakage of absolute user home paths. |
| `content` | `artifacts/*.json` | Leakage of file contents/secrets read by tools. |
| `api_base` | `config.toml` | Leakage of private proxy/endpoint URLs. |
| `payload` | `shadow_request_*.json` | Leakage of full conversation state. |

## Redaction Gap List
- No current automatic redaction of `$HOME` in paths.
- No current "Secret Scrubber" for tool outputs before they hit the filesystem.

## Recommended Gitignore/Default Behavior
- **Action**: Rig Relay should automatically add `.rig/relay/` to the repo's `.gitignore` if it initializes repo-local evidence.
- **Action**: Add a "Privacy Mode" that hashes all paths and redacts message content, leaving only usage/token metrics.

## Test Recommendations
- `test_no_absolute_paths_in_evidence`
- `test_secrets_in_env_not_leaked_to_logs`

## Future Implementation Backlog
- [ ] Implement path normalization (relative to project root).
- [ ] Add a `--private` flag to suppress content logging.
- [ ] Create a `doctor` check for accidental credential leakage in evidence files.
