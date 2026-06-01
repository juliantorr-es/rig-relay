import { join } from "node:path";
import { tool } from "@opencode-ai/plugin";
import { runShellCommand } from "./bash_router_core.mjs";
import { resolveRepoRoot } from "./opencode_context_core.mjs";
import {
	garbageCollectResolvedFailureArtifacts,
	inspectFailure,
} from "./opencode_failure_core.mjs";

function buildPytestCommand(paths, extraArgs) {
	return ["uv", "run", "pytest", ...extraArgs, ...paths].join(" ");
}

export default tool({
	description:
		"Run pytest natively for the current repo and return a structured test result bundle.",
	args: {
		paths: tool.schema
			.array(tool.schema.string())
			.default([])
			.describe("Optional test file, path, or node id targets."),
		pytest_args: tool.schema
			.array(tool.schema.string())
			.default([])
			.describe("Extra arguments to pass to pytest."),
		cwd: tool.schema
			.string()
			.default("")
			.describe("Working directory for the test run."),
		timeout: tool.schema
			.number()
			.default(30)
			.describe("Timeout in seconds for the test run."),
	},
	async execute(args, context) {
		const repoRoot = resolveRepoRoot(context.worktree);
		const cwd = args.cwd
			? args.cwd.startsWith("/")
				? args.cwd
				: join(repoRoot, args.cwd)
			: repoRoot;
		const command = buildPytestCommand(args.paths, args.pytest_args);
		const result = await runShellCommand(
			command,
			cwd,
			args.timeout,
			1024 * 1024,
		);
		const failureInspections = [];
		const resolvedFailureArtifacts = [];
		if (result.status === "success") {
			const resolved = garbageCollectResolvedFailureArtifacts({
				repoRoot,
				sourceTool: "test",
				sourceCommand: command,
			});
			if (resolved.removed.length) {
				resolvedFailureArtifacts.push({
					command,
					removed: resolved.removed,
				});
			}
		} else {
			const inspection = inspectFailure({
				repoRoot,
				payload: {
					tool: "test",
					command,
					result,
				},
				label: "pytest",
				maxExcerptLines: 80,
			});
			failureInspections.push({
				command,
				artifact_path: inspection.filePath,
				artifact: inspection.artifact,
			});
		}

		return {
			title: result.status === "success" ? "test: success" : "test: failure",
			output: JSON.stringify(
				{
					tool: "test",
					cwd,
					command,
					result,
					failure_inspections: failureInspections,
					resolved_failure_artifacts: resolvedFailureArtifacts,
				},
				null,
				2,
			),
		};
	},
});
