import * as fs from 'fs';
import * as path from 'path';

interface OpenCodePluginContext {
  dir: string;
  worktree?: string;
  client?: {
    app?: {
      log?: (...args: unknown[]) => void;
    };
  };
}

declare function exec(command: string, options?: { cwd?: string }): Promise<{ stdout: string; stderr: string; exitCode: number }>;
declare function which(command: string): string | null;

const sessionQueues = new Map<string, Promise<void>>();

function queueWrite(sessionID: string, task: () => Promise<void>): void {
  const current = sessionQueues.get(sessionID) || Promise.resolve();
  const next = current.then(task).catch(err => {
    console.error(`[rig-steward] Error in session ${sessionID} queue:`, err);
  });
  sessionQueues.set(sessionID, next);
}

async function appendObservation(projectRoot: string, sessionID: string, eventType: string, payload: any): Promise<void> {
  const sessionDir = path.join(projectRoot, '.build', 'rig-relay', 'derived', 'opencode-steward', 'sessions', sessionID);
  const flagPath = path.join(sessionDir, 'evidence_incomplete.flag');
  try {
    await fs.promises.mkdir(sessionDir, { recursive: true });
    const obsPath = path.join(sessionDir, 'observations.v1.jsonl');
    
    const event = {
      schema_version: "rig.relay.opencode_steward_observation.v1",
      session_id: sessionID,
      event_type: eventType,
      generated_at: new Date().toISOString(),
      payload: payload
    };
    await fs.promises.appendFile(obsPath, JSON.stringify(event) + '\n');
  } catch (err) {
    console.error(`[rig-steward] appendObservation failed for session ${sessionID}:`, err);
    try {
      await fs.promises.writeFile(flagPath, 'true');
    } catch (e) {
      // Ignored
    }
    throw err;
  }
}

function extractPaths(args: any): string[] {
  if (!args || typeof args !== 'object') return [];
  const paths: string[] = [];
  const keys = ["filePath", "path", "target_directory", "dir", "file_path", "TargetFile"];
  for (const key of keys) {
    if (typeof args[key] === 'string' && args[key]) {
      paths.push(args[key]);
    }
  }
  return paths;
}

async function checkWritePermission(uvPath: string, projectRoot: string, filePath: string): Promise<{ allowed: boolean; action: string; reason: string }> {
  const checkCmd = `"${uvPath}" run rig-relay steward check-write "${filePath}"`;
  
  const runCheck = exec(checkCmd, { cwd: projectRoot });
  const timeoutPromise = new Promise<{ stdout: string; stderr: string; exitCode: number }>((_, reject) =>
    setTimeout(() => reject(new Error("Timeout")), 2000)
  );
  
  try {
    const result = await Promise.race([runCheck, timeoutPromise]);
    const parsed = JSON.parse(result.stdout);
    return {
      allowed: parsed.allowed,
      action: parsed.action,
      reason: parsed.reason
    };
  } catch (err) {
    const isSecret = filePath.endsWith(".env") || filePath.includes("credentials") || filePath.includes("secrets");
    if (isSecret) {
      return {
        allowed: false,
        action: "deny",
        reason: `Steward check-write failed/timed out on protected path: ${filePath}`
      };
    }
    return {
      allowed: true,
      action: "advise",
      reason: `Steward check-write fallback allowance for governed path: ${filePath}`
    };
  }
}

export async function onEvent(
  event: any,
  ctx: OpenCodePluginContext,
): Promise<void> {
  const sessionID = event.sessionID || event.session_id || event.metadata?.sessionID;
  const projectRoot = ctx.dir;
  const log = ctx.client?.app?.log;
  const uvPath = which("uv") || "uv";

  if (!sessionID) {
    // If we cannot attribute sessionID, we cannot record observations to session log
    if (event.type === "tool.execute.before") {
      const paths = extractPaths(event.arguments);
      for (const p of paths) {
        const result = await checkWritePermission(uvPath, projectRoot, p);
        if (!result.allowed) {
          throw new Error("Write blocked by Rig Steward: " + result.reason);
        }
        if (result.action === "advise" || result.action === "require_approval") {
          log?.(`rig-roadmap-steward: [Unattributed Session Warning] ${result.reason}`);
        }
      }
    }
    return;
  }

  if (event.type === "tool.execute.before") {
    const paths = extractPaths(event.arguments);
    for (const p of paths) {
      const result = await checkWritePermission(uvPath, projectRoot, p);
      if (!result.allowed) {
        throw new Error("Write blocked by Rig Steward: " + result.reason);
      }
      if (result.action === "advise" || result.action === "require_approval") {
        log?.(`rig-roadmap-steward: ${result.reason}`);
        queueWrite(sessionID, async () => {
          await appendObservation(projectRoot, sessionID, "warning_raised", {
            path: p,
            action: result.action,
            reason: result.reason,
            timestamp: Date.now()
          });
        });
      }
    }

    queueWrite(sessionID, async () => {
      await appendObservation(projectRoot, sessionID, "tool_call", {
        tool: event.tool,
        phase: "before",
        paths: paths,
        timestamp: Date.now()
      });
    });
  }

  else if (event.type === "tool.execute.after") {
    queueWrite(sessionID, async () => {
      await appendObservation(projectRoot, sessionID, "tool_call", {
        tool: event.tool,
        phase: "after",
        status: event.result?.status || "unknown",
        exitCode: event.result?.metadata?.exit,
        timestamp: Date.now()
      });
    });
  }

  else if (event.type === "file.edited") {
    queueWrite(sessionID, async () => {
      await appendObservation(projectRoot, sessionID, "file_edit", {
        path: event.path,
        timestamp: Date.now()
      });
    });
  }

  else if (event.type === "session.diff") {
    queueWrite(sessionID, async () => {
      await appendObservation(projectRoot, sessionID, "session_diff", {
        diffLength: event.diff?.length || 0,
        timestamp: Date.now()
      });
    });
  }

  else if (event.type === "session.idle") {
    const queue = sessionQueues.get(sessionID);
    if (queue) {
      await queue;
    }

    await appendObservation(projectRoot, sessionID, "session_idle", {
      timestamp: Date.now()
    });

    try {
      const handoffCmd = `"${uvPath}" run rig-relay steward handoff --session-id "${sessionID}"`;
      const result = await exec(handoffCmd, { cwd: projectRoot });
      if (result.exitCode === 0) {
        log?.("rig-roadmap-steward: session.idle - handoff packet generated successfully.");
      } else {
        log?.("rig-roadmap-steward: session.idle - handoff generation failed: " + result.stderr);
      }
    } catch (err) {
      log?.("rig-roadmap-steward: session.idle - handoff invocation error: " + err);
    }
  }
}
