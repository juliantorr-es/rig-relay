import { join } from "node:path";
import { tool } from "@opencode-ai/plugin";
import { routeBashCommand, runShellCommand } from "./bash_router_core.mjs";
import {
	readFileContext,
	resolveRepoRoot,
	searchReplaceFileWithContext,
	writeFileWithContext,
} from "./opencode_context_core.mjs";

function buildReadOutput(command, route, result) {
	const content = String(result.content ?? "");
	const lines = content.split("\n");
	const limit = route.limit ?? lines.length;
	const offset = route.offset ?? 0;
	const preview =
		offset < 0
			? lines.slice(Math.max(0, lines.length - limit), lines.length).join("\n")
			: lines.slice(offset, offset + limit).join("\n");
	return {
		command,
		rerouted: true,
		rerouted_tool: "read",
		file_path: result.filePath,
		artifact_path: result.artifactPath,
		ledger_path: result.ledgerPath,
		artifact: result.artifact,
		preview,
		content,
		mutated: false,
	};
}

function buildValidationCommand(route) {
	const base =
		route.mode === "lint"
			? ["uv", "run", "ruff", "check"]
			: ["uv", "run", "pyright"];
	return [...base, ...(route.extra_args ?? []), ...(route.paths ?? [])].join(
		" ",
	);
}

function buildTestCommand(route) {
	return [
		"uv",
		"run",
		"pytest",
		...(route.extra_args ?? []),
		...(route.paths ?? []),
	].join(" ");
}

export default tool({
	description:
		"Run a shell command, transparently rerouting simple file reads, writes, substitutions, validation, and tests to native OpenCode tools when possible.",
	args: {
		command: tool.schema
			.string()
			.describe("Shell command to execute or reroute."),
		cwd: tool.schema
			.string()
			.default("")
			.describe("Working directory for shell fallback execution."),
		timeout: tool.schema
			.number()
			.default(30)
			.describe("Timeout in seconds for shell fallback execution."),
		max_output_bytes: tool.schema
			.number()
			.default(65536)
			.describe("Maximum stdout/stderr bytes for shell fallback execution."),
	},
	async execute(args, context) {
		const repoRoot = resolveRepoRoot(context.worktree);
		const cwd = args.cwd
			? args.cwd.startsWith("/")
				? args.cwd
				: join(repoRoot, args.cwd)
			: repoRoot;
		const route = routeBashCommand(args.command);

		if (route?.kind === "read_file") {
			const result = readFileContext({
				repoRoot,
				path: route.path,
				includeContent: true,
				includeHistory: true,
				depth: 1,
			});

			return {
				title: `bash→read: ${result.artifact.target_path}`,
				output: JSON.stringify(
					buildReadOutput(args.command, route, result),
					null,
					2,
				),
			};
		}

		if (route?.kind === "write_file") {
			const result = writeFileWithContext({
				repoRoot,
				path: route.path,
				content: route.content,
				operation: "write_file",
				summary: `bash write to ${route.path}`,
				reason: `bash reroute: ${args.command}`,
				expectedBeforeSha256: null,
				allowOverwriteProtected: false,
				preflightOnly: false,
			});

			return {
				title: `bash→write_file: ${result.filePath}`,
				output: JSON.stringify(
					{
						command: args.command,
						rerouted: true,
						rerouted_tool: "write_file",
						file_path: result.filePath,
						artifact_path: result.context.artifactPath,
						ledger_path: result.ledgerPath,
						preflight: result.preflight,
						event: result.event,
						artifact: result.context.artifact,
						preview: result.context.preview,
						mutated: result.mutated,
					},
					null,
					2,
				),
			};
		}

		if (route?.kind === "search_replace") {
			const result = searchReplaceFileWithContext({
				repoRoot,
				path: route.path,
				search: route.search,
				replace: route.replace,
				all: route.all,
				reason: `bash reroute: ${args.command}`,
				expectedBeforeSha256: null,
				allowOverwriteProtected: false,
				preflightOnly: false,
			});

			return {
				title: `bash→search_replace: ${result.filePath}`,
				output: JSON.stringify(
					{
						command: args.command,
						rerouted: true,
						rerouted_tool: "search_replace",
						file_path: result.filePath,
						artifact_path: result.context.artifactPath,
						ledger_path: result.ledgerPath,
						preflight: result.preflight,
						event: result.event,
						artifact: result.context.artifact,
						preview: result.context.preview,
						mutated: result.mutated,
					},
					null,
					2,
				),
			};
		}

		if (route?.kind === "validate") {
			const command = buildValidationCommand(route);
			const result = await runShellCommand(
				command,
				cwd,
				args.timeout,
				args.max_output_bytes,
			);

			return {
				title: `bash→validate: ${route.mode}`,
				output: JSON.stringify(
					{
						command: args.command,
						rerouted: true,
						rerouted_tool: "validate",
						mode: route.mode,
						paths: route.paths ?? [],
						extra_args: route.extra_args ?? [],
						result,
					},
					null,
					2,
				),
			};
		}

		if (route?.kind === "test") {
			const command = buildTestCommand(route);
			const result = await runShellCommand(
				command,
				cwd,
				args.timeout,
				args.max_output_bytes,
			);

			return {
				title: "bash→test",
				output: JSON.stringify(
					{
						command: args.command,
						rerouted: true,
						rerouted_tool: "test",
						paths: route.paths ?? [],
						extra_args: route.extra_args ?? [],
						result,
					},
					null,
					2,
				),
			};
		}

		const shellResult = await runShellCommand(
			args.command,
			cwd,
			args.timeout,
			args.max_output_bytes,
		);

		return {
			title: `bash: ${args.command}`,
			output: JSON.stringify(
				{
					command: args.command,
					rerouted: false,
					rerouted_tool: null,
					...shellResult,
				},
				null,
				2,
			),
		};
	},
});
