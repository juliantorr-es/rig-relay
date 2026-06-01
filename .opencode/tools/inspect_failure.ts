import { tool } from "@opencode-ai/plugin";
import { resolveRepoRoot } from "./opencode_context_core.mjs";
import { inspectFailure } from "./opencode_failure_core.mjs";

export default tool({
	description:
		"Inspect a failing test or command result and turn it into a concise failure artifact with likely cause, paths, and next step.",
	args: {
		payload_json: tool.schema
			.string()
			.default("")
			.describe(
				"Structured JSON output from a native tool such as validate or test.",
			),
		log_path: tool.schema
			.string()
			.default("")
			.describe("Path to a raw log file or captured stderr/stdout transcript."),
		label: tool.schema
			.string()
			.default("")
			.describe("Short label for the inspection, such as pytest or ruff."),
		max_excerpt_lines: tool.schema
			.number()
			.default(80)
			.describe("Maximum number of log lines to include in the excerpt."),
	},
	async execute(args, context) {
		const repoRoot = resolveRepoRoot(context.worktree);
		let payload = null;
		if (args.payload_json.trim()) {
			try {
				payload = JSON.parse(args.payload_json);
			} catch {
				throw new Error("payload_json must contain valid JSON");
			}
		}
		const result = inspectFailure({
			repoRoot,
			payload,
			logPath: args.log_path,
			label: args.label,
			maxExcerptLines: args.max_excerpt_lines,
		});

		return {
			title: `inspect_failure: ${result.artifact.artifact_id}`,
			output: JSON.stringify(
				{
					artifact_path: result.filePath,
					artifact: result.artifact,
				},
				null,
				2,
			),
		};
	},
});
