import * as fs from "node:fs";
import path from "node:path";

import type { BunShell, Plugin, PluginInput } from "@opencode-ai/plugin";

interface WriteCheckResult {
  allowed: boolean;
  action: string;
  reason: string;
}

const sessionQueues = new Map<string, Promise<void>>();

function queueWrite(sessionID: string, task: () => Promise<void>): void {
  const current = sessionQueues.get(sessionID) || Promise.resolve();
  const next = current.then(task).catch((err) => {
    console.error(`[rig-steward] Error in session ${sessionID} queue:`, err);
  });
  sessionQueues.set(sessionID, next);
}

function getProjectRoot(ctx: PluginInput): string {
  return ctx.worktree || ctx.directory || process.cwd();
}

async function emitLog(
  client: PluginInput["client"],
  level: "debug" | "info" | "warn" | "error",
  message: string,
  extra: Record<string, unknown> = {},
): Promise<void> {
  const logFn = (client as any)?.app?.log;
  if (typeof logFn !== "function") {
    return;
  }

  try {
    await logFn({
      body: {
        service: "rig-roadmap-steward",
        level,
        message,
        extra,
      },
    });
  } catch {
    // Logging is best-effort only.
  }
}

async function appendObservation(
  projectRoot: string,
  sessionID: string,
  eventType: string,
  payload: unknown,
): Promise<void> {
  const sessionDir = path.join(
    projectRoot,
    ".build",
    "rig-relay",
    "derived",
    "opencode-steward",
    "sessions",
    sessionID,
  );
  const flagPath = path.join(sessionDir, "evidence_incomplete.flag");

  try {
    await fs.promises.mkdir(sessionDir, { recursive: true });
    const obsPath = path.join(sessionDir, "observations.v1.jsonl");

    const event = {
      schema_version: "rig.relay.opencode_steward_observation.v1",
      session_id: sessionID,
      event_type: eventType,
      generated_at: new Date().toISOString(),
      payload,
    };
    await fs.promises.appendFile(obsPath, `${JSON.stringify(event)}\n`);
  } catch (err) {
    console.error(`[rig-steward] appendObservation failed for session ${sessionID}:`, err);
    try {
      await fs.promises.writeFile(flagPath, "true");
    } catch {
      // Ignored.
    }
    throw err;
  }
}

function extractPaths(args: unknown): string[] {
  if (!args || typeof args !== "object") {
    return [];
  }

  const paths: string[] = [];
  const record = args as Record<string, unknown>;
  const keys = ["filePath", "path", "target_directory", "dir", "file_path", "TargetFile"];

  for (const key of keys) {
    if (typeof record[key] === "string" && record[key]) {
      paths.push(record[key] as string);
    }
  }

  return paths;
}

async function checkWritePermission(
  shell: BunShell,
  projectRoot: string,
  filePath: string,
): Promise<WriteCheckResult> {
  const runCheck = shell`uv run rig-relay steward check-write ${filePath}`
    .cwd(projectRoot)
    .nothrow()
    .quiet();

  try {
    const result = await runCheck;
    const stdout = result.text().trim();
    const parsed = JSON.parse(stdout) as WriteCheckResult;
    return {
      allowed: parsed.allowed,
      action: parsed.action,
      reason: parsed.reason,
    };
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return {
      allowed: false,
      action: "deny",
      reason: `Steward check-write failed (denied for safety): ${errMsg} — path: ${filePath}`,
    };
  }
}

async function handleToolBefore(
  ctx: PluginInput,
  input: { tool: string; sessionID: string; callID: string },
  output: { args: unknown },
): Promise<void> {
  const projectRoot = getProjectRoot(ctx);
  const paths = extractPaths(output.args);

  for (const p of paths) {
    const result = await checkWritePermission(ctx.$, projectRoot, p);
    if (!result.allowed) {
      throw new Error(`Write blocked by Rig Steward: ${result.reason}`);
    }
    if (result.action === "advise" || result.action === "require_approval") {
      await emitLog(ctx.client, "warn", result.reason, {
        tool: input.tool,
        callID: input.callID,
        sessionID: input.sessionID,
        path: p,
        action: result.action,
      });
      queueWrite(input.sessionID, async () => {
        await appendObservation(projectRoot, input.sessionID, "warning_raised", {
          path: p,
          tool: input.tool,
          call_id: input.callID,
          action: result.action,
          reason: result.reason,
          timestamp: Date.now(),
        });
      });
    }
  }

  queueWrite(input.sessionID, async () => {
    await appendObservation(projectRoot, input.sessionID, "tool_call", {
      tool: input.tool,
      call_id: input.callID,
      phase: "before",
      paths,
      timestamp: Date.now(),
    });
  });
}

async function handleToolAfter(
  ctx: PluginInput,
  input: { tool: string; sessionID: string; callID: string; args: unknown },
  output: { title: string; output: string; metadata: Record<string, unknown> },
): Promise<void> {
  const projectRoot = getProjectRoot(ctx);

  queueWrite(input.sessionID, async () => {
    await appendObservation(projectRoot, input.sessionID, "tool_call", {
      tool: input.tool,
      call_id: input.callID,
      phase: "after",
      status: (output.metadata?.status as string | undefined) || "unknown",
      exitCode: (output.metadata?.exit as number | undefined) ?? null,
      timestamp: Date.now(),
    });
  });
}

export const RigRoadmapSteward: Plugin = async (ctx) => {
  const projectRoot = getProjectRoot(ctx);
  const shell = ctx.$;

  return {
    event: async ({ event }) => {
      if (event.type === "file.edited") {
        queueWrite("sessionless", async () => {
          await appendObservation(projectRoot, "sessionless", "file_edit", {
            path: event.properties.file,
            timestamp: Date.now(),
          });
        });
        return;
      }

      if (event.type === "session.diff") {
        queueWrite(event.properties.sessionID, async () => {
          await appendObservation(projectRoot, event.properties.sessionID, "session_diff", {
            diffCount: event.properties.diff.length,
            timestamp: Date.now(),
          });
        });
        return;
      }

      if (event.type === "session.idle") {
        const sessionID = event.properties.sessionID;
        const queue = sessionQueues.get(sessionID);
        if (queue) {
          await queue;
        }

        await appendObservation(projectRoot, sessionID, "session_idle", {
          timestamp: Date.now(),
        });

        void (async () => {
          try {
            const result = await shell`uv run rig-relay steward handoff --session-id ${sessionID}`
              .cwd(projectRoot)
              .nothrow()
              .quiet();

            if (result.exitCode === 0) {
              await emitLog(ctx.client, "info", "session.idle handoff packet generated successfully.", {
                sessionID,
              });
            } else {
              await emitLog(ctx.client, "warn", `session.idle handoff failed: ${result.stderr.toString("utf8")}`, {
                sessionID,
              });
            }
          } catch (err) {
            await emitLog(ctx.client, "warn", `session.idle handoff invocation error: ${String(err)}`, {
              sessionID,
            });
          }
        })();
      }
    },
    "tool.execute.before": async (input, output) => {
      await handleToolBefore(ctx, input, output);
    },
    "tool.execute.after": async (input, output) => {
      await handleToolAfter(ctx, input, output);
    },
  };
};
