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
  description: "Check the current branch name or list branches.",
  args: {
    show_current: tool.schema.boolean().optional().default(true).describe("Only print the name of the current branch."),
  },
  async execute(args, context) {
    const directory = context.worktree || context.directory || process.cwd();
    const result = await invokeBridge(
      "git_branch",
      {
        show_current: args.show_current,
      },
      context.sessionID || "opencode-bridge",
      directory,
      context.worktree || undefined,
    );
    return {
      title: result.status === "completed" ? "rig_git_branch completed" : "rig_git_branch result",
      output: JSON.stringify(result),
      metadata: result,
    } satisfies ToolResult;
  },
});
