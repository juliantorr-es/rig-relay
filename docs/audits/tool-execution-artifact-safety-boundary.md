# Audit: Tool Execution and Artifact Safety Boundary
Status: Draft
Date: 2026-05-13
Branch: main
HEAD: 24c990e011375078a04cb4a5534d114f98c064ed
Scope: Read-only audit
Owner area: tools

## Executive Summary
The boundary between tool execution and artifacting is centered on the `16KB` threshold in `AgentLoop._handle_tool_response`. While functional, the logic is highly coupled to the main agent loop and lacks explicit serialization/safety gates for binary or malformed data.

## Tool Output Lifecycle Map
1.  **Tool Invoke**: `AgentLoop` calls `tool.run()`.
2.  **Output Capture**: Raw string/data returned to `AgentLoop`.
3.  **Threshold Check**: If `len(output) > 16384` bytes, trigger artifacting.
4.  **Artifact Writing**: `ArtifactWriter` writes atomic JSON to `artifacts/tool-results/`.
5.  **Event Emission**: `ARTIFACT_WRITTEN` event sent to telemetry.
6.  **Prompt Inlining**: Truncated "excerpt" + "artifact reference" is placed in the `LLMMessage`.

## Artifacting Threshold Inventory
| Setting | Default | Location |
| :--- | :--- | :--- |
| `threshold_bytes` | 16384 | `vibe/core/telemetry/artifacts.py` |
| `auto_compact_threshold` | 200,000 (tokens) | `vibe/core/config/_settings.py` |

## Safety and Determinism Risks
- **Binary Data**: If a tool returns raw binary data, `json.dumps` (without `ensure_ascii=False`) or string encoding may fail non-deterministically based on the byte sequence.
- **Path Normalization**: Tool-produced paths in artifacts are not always absolute or normalized, which can cause breaks in evidence-reading tools if they depend on the session's CWD.
- **Failures**: Currently, tool failures (stderr/exceptions) are artifacted the same way as successes, but they may lack structured error metadata in the artifact itself.

## Missing Tests
- **Test: Binary Output**: Verify that binary tool output is handled without corrupting the JSONL.
- **Test: Path Resolution**: Verify that `artifact_path` in events is correctly resolvable from the repo root.
- **Test: Schema Parity**: Verify that every `ARTIFACT_WRITTEN` event has a corresponding valid file in the filesystem.

## Recommended Future Missions
1.  **Mission: Binary Safety Gate**: Implement a validation step in `ArtifactWriter` to safely encode or reject binary blobs.
2.  **Mission: Normalized Artifact Metadata**: Ensure all `artifact_path` references in events are relative to the project root, not the session directory.
