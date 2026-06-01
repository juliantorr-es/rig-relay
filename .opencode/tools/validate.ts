import { join } from "node:path";
import { tool } from "@opencode-ai/plugin";
import { runShellCommand } from "./bash_router_core.mjs";
import { resolveRepoRoot } from "./opencode_context_core.mjs";
import {
	garbageCollectResolvedFailureArtifacts,
	inspectFailure,
} from "./opencode_failure_core.mjs";

function buildCommand(paths, extraArgs, base) {
	const parts = [...base];
	parts.push(...extraArgs);
	parts.push(...paths);
	return parts.join(" ");
}

export default tool({
	description:
		"Run lint and/or typecheck validation natively for the current repo using ruff and pyright.",
	args: {
		paths: tool.schema
			.array(tool.schema.string())
			.default([])
			.describe("Optional file or directory paths to validate."),
		lint: tool.schema.boolean().default(true).describe("Run ruff check."),
		typecheck: tool.schema.boolean().default(true).describe("Run pyright."),
		ruff_args: tool.schema
			.array(tool.schema.string())
			.default([])
			.describe("Extra arguments to pass to ruff check."),
		pyright_args: tool.schema
			.array(tool.schema.string())
			.default([])
			.describe("Extra arguments to pass to pyright."),
		cwd: tool.schema
			.string()
			.default("")
			.describe("Working directory for validation."),
		timeout: tool.schema
			.number()
			.default(30)
			.describe("Timeout in seconds for each validation command."),
	},
	async execute(args, context) {
		const repoRoot = resolveRepoRoot(context.worktree);
		const cwd = args.cwd
			? args.cwd.startsWith("/")
				? args.cwd
				: join(repoRoot, args.cwd)
			: repoRoot;
		const commands: Array<{ name: string; command: string; result: object }> =
			[];

		if (args.lint) {
			const command = buildCommand(args.paths, args.ruff_args, [
				"uv",
				"run",
				"ruff",
				"check",
			]);
			commands.push({
				name: "ruff check",
				command,
				result: await runShellCommand(command, cwd, args.timeout, 1024 * 1024),
			});
		}

		if (args.typecheck) {
			const command = buildCommand(args.paths, args.pyright_args, [
				"uv",
				"run",
				"pyright",
			]);
			commands.push({
				name: "pyright",
				command,
				result: await runShellCommand(command, cwd, args.timeout, 1024 * 1024),
			});
		}

		const failed = commands.find((entry) => entry.result.status !== "success");
		const failureInspections = [];
		const resolvedFailureArtifacts = [];

		for (const entry of commands) {
			if (entry.result.status === "success") {
				const resolved = garbageCollectResolvedFailureArtifacts({
					repoRoot,
					sourceTool: "validate",
					sourceCommand: entry.command,
				});
				if (resolved.removed.length) {
					resolvedFailureArtifacts.push({
						command: entry.command,
						removed: resolved.removed,
					});
				}
				continue;
			}

			const inspection = inspectFailure({
				repoRoot,
				payload: {
					tool: "validate",
					command: entry.command,
					result: entry.result,
				},
				label: entry.name,
				maxExcerptLines: 80,
			});
			failureInspections.push({
				command: entry.command,
				artifact_path: inspection.filePath,
				artifact: inspection.artifact,
			});
		}

		return {
			title: failed ? `validate: ${failed.name}` : "validate: success",
			output: JSON.stringify(
				{
					tool: "validate",
					cwd,
					commands_run: commands,
					failure_inspections: failureInspections,
					resolved_failure_artifacts: resolvedFailureArtifacts,
					status: failed ? "failure" : "success",
				},
				null,
				2,
			),
		};
	},
});
