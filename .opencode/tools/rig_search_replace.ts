/**
 * OpenCode custom tool: rig_search_replace
 *
 * Stage A transport-only adapter that delegates search-replace mutations
 * to the Rig Relay RuntimeToolExecutionRunner via a Python subprocess bridge.
 *
 * Privacy boundary:
 *   Replacement content necessarily crosses the transport as transient tool
 *   input. This wrapper never persists, logs, or emits raw content outside the
 *   governed Rig invocation path. The returned result is content-light -
 *   receipt/envelope identifiers, status, and timing only.
 *
 * Governance:
 *   This wrapper owns zero policy. It does not determine mutation legality,
 *   construct receipts, implement redaction, classify paths, or evaluate
 *   dirty-guard policy. All governance is owned by Rig's RuntimeToolExecutionRunner
 *   and ToolRuntime.
 */

import { execFileSync } from "node:child_process";

import { tool, type ToolResult } from "@opencode-ai/plugin";

/** Content-light result returned to OpenCode. */
interface BridgeResult {
  status: string;
  outcome?: string;
  apply_receipt_id?: string;
  checkpoint_receipt_id?: string;
  actual_after_hash?: string;
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

async function invokeBridge(
  filePath: string,
  oldStr: string,
  newStr: string,
  expectedBeforeSha256: string | undefined,
  sessionID: string,
  directory: string,
  worktree: string | undefined,
): Promise<BridgeResult> {
  const request = {
    filePath,
    oldStr,
    newStr,
    expectedBeforeSha256,
    sessionId: sessionID,
    directory,
    worktree,
  };

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

  try {
    return JSON.parse(stdout) as BridgeResult;
  } catch {
    return {
      status: "failed",
      error_kind: "bridge_parse_error",
      refusal_reason: `Failed to parse bridge output: ${stdout.slice(0, 200)}`,
    };
  }
}

export default tool({
  description: "Replace text in a file using Rig's hardened SEARCH/REPLACE tool.",
  args: {
    filePath: tool.schema
      .string()
      .describe("Path to the file to modify, relative to the workspace root."),
    oldStr: tool.schema.string().describe("The exact text to find and replace."),
    newStr: tool.schema.string().describe("The replacement text."),
    expectedBeforeSha256: tool.schema
      .string()
      .optional()
      .describe(
        "Optional SHA-256 hex of the file bytes before the edit. If provided, the edit is refused if the current file hash does not match.",
      ),
  },
  async execute(args, context) {
    const directory = context.worktree || context.directory || process.cwd();
    const result = await invokeBridge(
      args.filePath,
      args.oldStr,
      args.newStr,
      args.expectedBeforeSha256,
      context.sessionID || "opencode-bridge",
      directory,
      context.worktree || undefined,
    );
    return {
      title: result.status === "completed" ? "rig_search_replace completed" : "rig_search_replace result",
      output: JSON.stringify(result),
      metadata: result,
    } satisfies ToolResult;
  },
});
