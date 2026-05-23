/**
 * OpenCode custom tool: rig_search_replace
 *
 * Stage A transport-only adapter that delegates search-replace mutations
 * to the Rig Relay RuntimeToolExecutionRunner via a Python subprocess bridge.
 *
 * Privacy boundary:
 *   Replacement content necessarily crosses the transport as transient tool
 *   input. This wrapper never persists, logs, or emits raw content outside the
 *   governed Rig invocation path. The returned result is content-light —
 *   receipt/envelope identifiers, status, and timing only.
 *
 * Governance:
 *   This wrapper owns zero policy. It does not determine mutation legality,
 *   construct receipts, implement redaction, classify paths, or evaluate
 *   dirty-guard policy. All governance is owned by Rig's RuntimeToolExecutionRunner
 *   and ToolRuntime.
 */

import { execFileSync } from "node:child_process";

/** Arguments accepted by the rig_search_replace tool. */
export const tool = {
  name: "rig_search_replace",
  description: "Replace text in a file using Rig's hardened SEARCH/REPLACE tool.",
  parameters: {
    type: "object" as const,
    properties: {
      filePath: {
        type: "string" as const,
        description: "Path to the file to modify, relative to the workspace root.",
      },
      oldStr: {
        type: "string" as const,
        description: "The exact text to find and replace.",
      },
      newStr: {
        type: "string" as const,
        description: "The replacement text.",
      },
      expectedBeforeSha256: {
        type: "string" as const,
        description:
          "Optional SHA-256 hex of the file bytes before the edit. " +
          "If provided, the edit is refused if the current file hash does not match.",
      },
    },
    required: ["filePath", "oldStr", "newStr"],
  },
};

/** OpenCode tool execution context provided to custom tools. */
interface ToolContext {
  sessionID?: string;
  directory?: string;
  worktree?: string;
}

/** Content-light result returned to OpenCode. */
interface BridgeResult {
  status: string;
  intent_id?: string;
  tool_name?: string;
  receipt_sha256?: string | null;
  receipt_envelope_id?: string | null;
  audit_event_id?: string | null;
  supervisor_result_envelope_id?: string | null;
  supervisor_result_envelope_sha256?: string | null;
  changed_paths?: string[];
  duration_ms?: number | null;
  error_kind?: string;
  refusal_reason?: string;
  warnings?: string[];
}

export async function execute(
  params: Record<string, unknown>,
  context: ToolContext,
): Promise<BridgeResult> {
  const request = {
    filePath: params.filePath as string,
    oldStr: params.oldStr as string,
    newStr: params.newStr as string,
    expectedBeforeSha256: params.expectedBeforeSha256 as string | undefined,
    sessionId: context.sessionID || "opencode-bridge",
    directory: context.directory || process.cwd(),
    worktree: context.worktree || undefined,
  };

  // Resolve the uv binary for subprocess execution.
  const uvBin = process.env.UV_BIN || "uv";
  const bridgeModule = "rig_relay.cli.opencode_tool_bridge";

  let stdout: string;
  try {
    stdout = execFileSync(uvBin, ["run", "python", "-m", bridgeModule], {
      input: JSON.stringify(request),
      encoding: "utf-8",
      timeout: 60_000,
      maxBuffer: 256 * 1024,
    }).trim();
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      status: "failed",
      error_kind: "bridge_subprocess_error",
      refusal_reason: `Python bridge subprocess failed: ${message}`,
    };
  }

  if (!stdout) {
    return {
      status: "failed",
      error_kind: "bridge_empty_output",
      refusal_reason: "Python bridge produced no output",
    };
  }

  let result: BridgeResult;
  try {
    result = JSON.parse(stdout) as BridgeResult;
  } catch {
    return {
      status: "failed",
      error_kind: "bridge_parse_error",
      refusal_reason: `Failed to parse bridge output: ${stdout.slice(0, 200)}`,
    };
  }

  return result;
}
