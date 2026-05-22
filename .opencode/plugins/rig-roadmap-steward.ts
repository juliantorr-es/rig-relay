// rig-roadmap-steward.ts — OpenCode plugin for Rig Relay Idle Lane Steward
//
// Thin trigger only. Listens for session.idle, invokes the Python steward.
// All policy lives in the Python steward. This plugin is intentionally boring.
//
// Installation: place in .opencode/plugins/rig-roadmap-steward.ts

interface OpenCodePluginContext {
  dir: string;
  worktree?: string;
  client?: {
    app?: {
      log?: (...args: unknown[]) => void;
    };
  };
}

interface SessionIdleEvent {
  type: "session.idle";
}

declare function exec(command: string, options?: { cwd?: string }): Promise<{ stdout: string; stderr: string; exitCode: number }>;
declare function which(command: string): string | null;

export async function onEvent(
  event: SessionIdleEvent,
  ctx: OpenCodePluginContext,
): Promise<void> {
  if (event.type !== "session.idle") {
    return;
  }

  const projectRoot = ctx.dir;
  const worktree = ctx.worktree || projectRoot;
  const log = ctx.client?.app?.log;

  log?.("rig-roadmap-steward: session.idle received, invoking Python steward");

  const uvPath = which("uv");
  if (!uvPath) {
    log?.("rig-roadmap-steward: uv not found on PATH, skipping");
    return;
  }

  const stewardScript = "scripts/rig_opencode_idle_steward.py";

  try {
    const result = await exec(
      `uv run python ${stewardScript} --project-root "${projectRoot}" --worktree "${worktree}"`,
      { cwd: projectRoot },
    );

    if (result.exitCode !== 0) {
      log?.(`rig-roadmap-steward: steward exited ${result.exitCode}`, result.stderr);
    } else {
      log?.("rig-roadmap-steward: steward completed successfully");
    }
  } catch (err) {
    log?.("rig-roadmap-steward: steward invocation failed", err);
  }
}
