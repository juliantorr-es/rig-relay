import { execFileSync } from "node:child_process";
import { tool, type ToolResult } from "@opencode-ai/plugin";

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
  git_summary?: Record<string, any> | null;
}

async function invokeBridge(
  toolName: string,
  args: Record<string, any>,
  sessionID: string,
  directory: string,
  worktree: string | undefined,
): Promise<BridgeResult> {
  const request = {
    tool_name: toolName,
    args,
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
  description: "Create a governed local checkpoint commit for session-owned files.",
  args: {
    message: tool.schema.string().describe("Commit message describing the checkpoint changes."),
    include_paths: tool.schema.array(tool.schema.string()).optional().default([]).describe("List of staged file paths to commit in this checkpoint."),
    validation_summary: tool.schema.array(tool.schema.string()).optional().default([]).describe("Optional list of validation steps executed prior to checkpoint."),
    allow_partial: tool.schema.boolean().optional().default(false).describe("If true, allow partial commits even if unrelated files are staged."),
    authorization_receipt: tool.schema.string().optional().describe("JSON string representing the signed authorization receipt required for the commit."),
  },
  async execute(args, context) {
    const directory = context.worktree || context.directory || process.cwd();
    const result = await invokeBridge(
      "checkpoint",
      {
        session_id: context.sessionID || "opencode-bridge",
        task_id: "opencode-task",
        message: args.message,
        include_paths: args.include_paths,
        validation_summary: args.validation_summary,
        allow_partial: args.allow_partial,
        authorization_receipt: args.authorization_receipt,
      },
      context.sessionID || "opencode-bridge",
      directory,
      context.worktree || undefined,
    );
    return {
      title: result.status === "completed" ? "rig_checkpoint completed" : "rig_checkpoint result",
      output: JSON.stringify(result),
      metadata: result,
    } satisfies ToolResult;
  },
});
