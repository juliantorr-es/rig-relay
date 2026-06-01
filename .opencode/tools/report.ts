import { tool } from "@opencode-ai/plugin";
import { resolveRepoRoot } from "./opencode_context_core.mjs";
import { buildIssueReport } from "./opencode_failure_core.mjs";

export default tool({
	description:
		"Append a structured issue report for a tool failure, disconnected seam, or out-of-scope finding.",
	args: {
		kind: tool.schema
			.enum([
				"tool_failure",
				"out_of_scope_finding",
				"disconnected_seam",
				"test_regression",
				"validation_failure",
			])
			.describe("Class of issue being reported."),
		severity: tool.schema
			.enum(["info", "minor", "major", "critical"])
			.default("major")
			.describe("Severity of the issue."),
		summary: tool.schema.string().describe("Short issue summary."),
		details: tool.schema
			.string()
			.default("")
			.describe("Longer context or explanation for the issue."),
		source_tool: tool.schema
			.string()
			.default("")
			.describe("Tool or command that produced the issue."),
		source_command: tool.schema
			.string()
			.default("")
			.describe("Original command or invocation that produced the issue."),
		source_artifact_path: tool.schema
			.string()
			.default("")
			.describe("Path to the source artifact, if one exists."),
		inspection_artifact_path: tool.schema
			.string()
			.default("")
			.describe("Path to a failure inspection artifact, if one exists."),
		affected_paths: tool.schema
			.array(tool.schema.string())
			.default([])
			.describe("Repository paths touched or implicated by the issue."),
		labels: tool.schema
			.array(tool.schema.string())
			.default([])
			.describe("Additional search labels such as dead-code or schema-gap."),
		recommended_next_step: tool.schema
			.string()
			.default("")
			.describe("One-line recommendation for the next action."),
	},
	async execute(args, context) {
		const repoRoot = resolveRepoRoot(context.worktree);
		const result = buildIssueReport({
			repoRoot,
			kind: args.kind,
			severity: args.severity,
			summary: args.summary,
			details: args.details,
			sourceTool: args.source_tool,
			sourceCommand: args.source_command,
			sourceArtifactPath: args.source_artifact_path,
			inspectionArtifactPath: args.inspection_artifact_path,
			affectedPaths: args.affected_paths,
			labels: args.labels,
			recommendedNextStep: args.recommended_next_step,
		});

		return {
			title: `report: ${result.artifact.artifact_id}`,
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
