import { tool } from "@opencode-ai/plugin";
import {
	buildMutationPreflight,
	readFileContext,
	resolveRepoRoot,
	stableDigest,
	stableObjectDigest,
	writeFileWithContext,
} from "./opencode_context_core.mjs";

function findSymbolRecord(artifact, symbolId, symbolName) {
	const records = Array.isArray(artifact.symbol_records)
		? artifact.symbol_records
		: [];
	if (symbolId) {
		return records.find((record) => record.symbol_id === symbolId) ?? null;
	}
	if (symbolName) {
		return records.find((record) => record.name === symbolName) ?? null;
	}
	return null;
}

function buildReplacementPlan({
	targetPath,
	artifact,
	symbolRecord,
	replacement,
	scope,
}) {
	const occurrences =
		symbolRecord.references_out.length + symbolRecord.references_in.length + 1;
	const planId = stableDigest(
		`${targetPath}\n${symbolRecord.symbol_id}\n${replacement}\n${scope}\n${occurrences}`,
	);
	return {
		schema_version: "opencode.symbol_replacement_plan.v1",
		plan_id: planId,
		created_at: new Date().toISOString(),
		target_path: targetPath,
		scope,
		source_symbol: symbolRecord,
		replacement: {
			text: replacement,
			stable_digest: stableDigest(replacement),
		},
		occurrences,
		candidate_text: symbolRecord.name,
		affected_contexts: [
			{
				target_path: artifact.target_path,
				artifact_id: artifact.artifact_id,
				artifact_path: artifact.artifact_path ?? null,
			},
			...((artifact.linked_contexts ?? []).map((entry) => ({
				target_path: entry.target_path,
				artifact_id: entry.artifact_id,
				artifact_path: entry.artifact_path ?? null,
			})) ?? []),
		],
		content_light: true,
	};
}

export default tool({
	description:
		"Deterministically replace a symbol using the file context graph and emit a replacement plan plus updated context artifact.",
	args: {
		path: tool.schema
			.string()
			.describe(
				"Repository-relative or absolute path of the file containing the symbol.",
			),
		symbol_id: tool.schema
			.string()
			.default("")
			.describe(
				"Stable symbol id from the file context graph; preferred over symbol_name.",
			),
		symbol_name: tool.schema
			.string()
			.default("")
			.describe(
				"Fallback symbol name when a stable symbol id is not available.",
			),
		replacement: tool.schema
			.string()
			.describe("Replacement text for the symbol."),
		scope: tool.schema
			.string()
			.default("file")
			.describe("Replacement scope hint, such as file, module, or service."),
		reason: tool.schema
			.string()
			.default("")
			.describe("Reason for the mutation; stored in the change ledger."),
		expected_before_sha256: tool.schema
			.string()
			.default("")
			.describe(
				"Current file SHA256 when editing an existing file; leave empty for new files or protected-generated writes.",
			),
		allow_overwrite_protected: tool.schema
			.boolean()
			.default(false)
			.describe(
				"Bypass the expected hash guard for known-safe generated files.",
			),
		preflight_only: tool.schema
			.boolean()
			.default(false)
			.describe(
				"Return the impact warning and replacement plan without mutating the file.",
			),
	},
	async execute(args, context) {
		const repoRoot = resolveRepoRoot(context.worktree);
		const current = readFileContext({
			repoRoot,
			path: args.path,
			includeContent: true,
			includeHistory: true,
			depth: 2,
		});
		const symbolRecord = findSymbolRecord(
			current.artifact,
			args.symbol_id,
			args.symbol_name,
		);
		if (!symbolRecord) {
			throw new Error(
				`Symbol not found in ${current.artifact.target_path}: ${args.symbol_id || args.symbol_name || "<empty>"}`,
			);
		}

		const preflight = buildMutationPreflight({
			repoRoot,
			operation: "replace_symbol",
			targetPath: current.artifact.target_path,
			currentArtifact: current.artifact,
			symbolRecord,
			replacementText: args.replacement,
		});
		if (args.preflight_only) {
			const replacementPlan = buildReplacementPlan({
				targetPath: current.artifact.target_path,
				artifact: current.artifact,
				symbolRecord,
				replacement: args.replacement,
				scope: args.scope,
			});
			return {
				title: `preflight: ${current.artifact.target_path}`,
				output: JSON.stringify(
					{
						preflight,
						replacement_plan: {
							...replacementPlan,
							plan_digest: stableObjectDigest(replacementPlan),
						},
					},
					null,
					2,
				),
			};
		}

		const before = String(current.content ?? "");
		const searchText = symbolRecord.name;
		const occurrenceCount = before.split(searchText).length - 1;
		if (!occurrenceCount) {
			throw new Error(
				`Symbol text not found in ${current.artifact.target_path}: ${searchText}`,
			);
		}

		const replacementPlan = buildReplacementPlan({
			targetPath: current.artifact.target_path,
			artifact: current.artifact,
			symbolRecord,
			replacement: args.replacement,
			scope: args.scope,
		});
		const result = writeFileWithContext({
			repoRoot,
			path: args.path,
			content: before.split(searchText).join(args.replacement),
			operation: "replace_symbol",
			summary: `Replaced ${searchText} with ${args.replacement}`,
			reason: args.reason,
			searchText,
			replaceText: args.replacement,
			replaceAll: true,
			expectedBeforeSha256: args.expected_before_sha256 || stableDigest(before),
			allowOverwriteProtected: args.allow_overwrite_protected,
			preflightOnly: false,
		});

		const outputPlan = {
			...replacementPlan,
			preflight,
			post_change_context_artifact_id: result.context.artifact.artifact_id,
			post_change_context_artifact_path: result.context.artifactPath,
			change_event_id: result.event.event_id,
			content_light: true,
		};

		return {
			title: `replace_symbol: ${current.artifact.target_path}`,
			output: JSON.stringify(
				{
					preflight,
					replacement_plan: {
						...outputPlan,
						plan_digest: stableObjectDigest(outputPlan),
					},
					result: {
						file_path: result.filePath,
						artifact_path: result.context.artifactPath,
						ledger_path: result.ledgerPath,
						event: result.event,
						artifact: result.context.artifact,
						preview: result.context.preview,
					},
					mutated: result.mutated,
				},
				null,
				2,
			),
		};
	},
});
