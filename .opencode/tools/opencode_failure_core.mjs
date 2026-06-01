import {
	existsSync,
	mkdirSync,
	readdirSync,
	readFileSync,
	unlinkSync,
} from "node:fs";
import { join } from "node:path";

import {
	createRecordId,
	readJson,
	resolveRepoRoot,
	stableDigest,
	stableObjectDigest,
	writeJson,
	writeJsonl,
} from "./opencode_context_core.mjs";

export const FAILURE_INSPECTION_SCHEMA_VERSION =
	"opencode.failure_inspection.v1";
export const ISSUE_REPORT_SCHEMA_VERSION = "opencode.issue_report.v1";

function opencodeRoot(repoRoot) {
	return join(repoRoot, "docs", "json", "opencode");
}

function failureInspectionsRoot(repoRoot) {
	return join(opencodeRoot(repoRoot), "failure_inspections");
}

function issueReportsRoot(repoRoot) {
	return join(opencodeRoot(repoRoot), "issue_reports");
}

function failureInspectionLedgerPath(repoRoot) {
	return join(failureInspectionsRoot(repoRoot), "ledger.jsonl");
}

function issueReportLedgerPath(repoRoot) {
	return join(issueReportsRoot(repoRoot), "ledger.jsonl");
}

function ensureIssueDirs(repoRoot) {
	mkdirSync(failureInspectionsRoot(repoRoot), { recursive: true });
	mkdirSync(issueReportsRoot(repoRoot), { recursive: true });
}

function writeArtifact(rootDir, artifact) {
	const filePath = join(rootDir, `${artifact.artifact_id}.json`);
	artifact.artifact_path = filePath;
	writeJson(filePath, artifact);
	return filePath;
}

function listJsonArtifacts(rootDir) {
	if (!existsSync(rootDir)) {
		return [];
	}
	return readdirSync(rootDir, { withFileTypes: true })
		.filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
		.map((entry) => join(rootDir, entry.name))
		.filter((path) => !path.endsWith("ledger.jsonl"));
}

function extractPathMentions(text) {
	const matches = String(text ?? "").matchAll(
		/([A-Za-z0-9_./-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|json|md|txt)):(\d+)(?::(\d+))?/g,
	);
	const locations = [];
	const seen = new Set();
	for (const match of matches) {
		const path = match[1];
		const line = Number.parseInt(match[2], 10);
		const column = match[3] ? Number.parseInt(match[3], 10) : null;
		const key = `${path}:${line}:${column ?? ""}`;
		if (seen.has(key)) {
			continue;
		}
		seen.add(key);
		locations.push({
			path,
			line,
			column,
		});
	}
	return locations;
}

function classifyFailure(payloadText, combinedText, sourceTool, sourceCommand) {
	const lowerText =
		`${payloadText}\n${combinedText}\n${sourceTool}\n${sourceCommand}`.toLowerCase();
	if (!combinedText.trim()) {
		return "unknown";
	}
	if (lowerText.includes("assertionerror") || lowerText.includes("failed")) {
		return "test_failure";
	}
	if (lowerText.includes("traceback")) {
		return "runtime_failure";
	}
	if (lowerText.includes("pyright") || lowerText.includes("type error")) {
		return "typecheck_failure";
	}
	if (lowerText.includes("ruff") || lowerText.includes("lint")) {
		return "lint_failure";
	}
	if (lowerText.includes("validation") || lowerText.includes("validate")) {
		return "validation_failure";
	}
	return "tool_failure";
}

function extractFirstSignal(lines) {
	const markers = [
		"AssertionError",
		"Traceback",
		"FAILED ",
		"E   ",
		"error:",
		"ERROR",
		"Type error",
		"Lint",
		"warning:",
	];
	for (const line of lines) {
		if (markers.some((marker) => line.includes(marker))) {
			return line.trim();
		}
	}
	return lines[0]?.trim() ?? "";
}

function buildExcerpt(lines, maxLines) {
	const trimmed = lines.map((line) => line.trimEnd()).filter(Boolean);
	if (!trimmed.length) {
		return "";
	}
	const signalIndex = trimmed.findIndex((line) =>
		["AssertionError", "Traceback", "FAILED ", "E   ", "error:", "ERROR"].some(
			(marker) => line.includes(marker),
		),
	);
	if (signalIndex === -1) {
		return trimmed.slice(0, maxLines).join("\n");
	}
	const start = Math.max(0, signalIndex - 4);
	const end = Math.min(trimmed.length, signalIndex + maxLines);
	return trimmed.slice(start, end).join("\n");
}

function normalizeStructuredInput(payload) {
	if (payload && typeof payload === "object") {
		return payload;
	}
	if (typeof payload !== "string" || !payload.trim()) {
		return null;
	}
	try {
		return JSON.parse(payload);
	} catch {
		return null;
	}
}

function unpackToolResult(payload) {
	const parsed = normalizeStructuredInput(payload);
	if (!parsed) {
		return {
			structured: null,
			rawText: String(payload ?? ""),
			sourceTool: "",
			sourceCommand: "",
			status: "unknown",
			exitCode: null,
			stdout: "",
			stderr: "",
			sourceArtifactPath: "",
			sourceLogPath: "",
		};
	}

	const result = parsed.result ?? parsed;
	const command = String(parsed.command ?? result.command ?? "").trim();
	const toolName = String(
		parsed.tool ??
			parsed.rerouted_tool ??
			parsed.tool_name ??
			result.tool ??
			"",
	).trim();
	const stdout = String(result.stdout ?? parsed.stdout ?? "").trim();
	const stderr = String(result.stderr ?? parsed.stderr ?? "").trim();
	const status =
		String(result.status ?? parsed.status ?? "").trim() || "unknown";
	const exitCode =
		typeof result.exit_code === "number"
			? result.exit_code
			: typeof parsed.exit_code === "number"
				? parsed.exit_code
				: null;
	const sourceArtifactPath = String(
		parsed.artifact_path ?? parsed.report_path ?? result.artifact_path ?? "",
	).trim();
	const sourceLogPath = String(parsed.log_path ?? result.log_path ?? "").trim();
	const rawText = [
		stdout,
		stderr,
		String(parsed.output ?? "").trim(),
		String(parsed.message ?? "").trim(),
	]
		.filter(Boolean)
		.join("\n")
		.trim();

	return {
		structured: parsed,
		rawText: rawText || JSON.stringify(parsed, null, 2),
		sourceTool: toolName,
		sourceCommand: command,
		status,
		exitCode,
		stdout,
		stderr,
		sourceArtifactPath,
		sourceLogPath,
	};
}

function matchesResolutionArtifact(artifact, criteria) {
	if (!artifact || typeof artifact !== "object") {
		return false;
	}
	if (
		criteria.sourceTool &&
		String(artifact.source_tool ?? "").trim() !== criteria.sourceTool
	) {
		return false;
	}
	if (
		criteria.sourceCommand &&
		String(artifact.source_command ?? "").trim() !== criteria.sourceCommand
	) {
		return false;
	}
	if (
		criteria.sourceArtifactPath &&
		String(artifact.source_artifact_path ?? "").trim() !==
			criteria.sourceArtifactPath
	) {
		return false;
	}
	if (
		criteria.sourceLogPath &&
		String(artifact.source_log_path ?? "").trim() !== criteria.sourceLogPath
	) {
		return false;
	}
	if (
		criteria.sourceKind &&
		String(artifact.source_kind ?? "").trim() !== criteria.sourceKind
	) {
		return false;
	}
	if (
		Object.hasOwn(artifact, "failure_type") &&
		criteria.failureTypes?.length &&
		!criteria.failureTypes.includes(String(artifact.failure_type ?? "").trim())
	) {
		return false;
	}
	if (
		Object.hasOwn(artifact, "kind") &&
		criteria.reportKinds?.length &&
		!criteria.reportKinds.includes(String(artifact.kind ?? "").trim())
	) {
		return false;
	}
	return true;
}

export function inspectFailure({
	repoRoot,
	payload = null,
	logPath = "",
	label = "",
	maxExcerptLines = 80,
}) {
	const effectiveRepoRoot = repoRoot ?? resolveRepoRoot(process.cwd());
	ensureIssueDirs(effectiveRepoRoot);

	const fromPayload = unpackToolResult(payload);
	const logText = logPath ? readFileSync(logPath, "utf8") : "";
	const combinedText = [fromPayload.stdout, fromPayload.stderr, logText]
		.filter(Boolean)
		.join("\n")
		.trim();
	const lines = combinedText ? combinedText.split(/\r?\n/) : [];
	const failureType = classifyFailure(
		fromPayload.rawText,
		combinedText,
		fromPayload.sourceTool,
		fromPayload.sourceCommand,
	);
	const detectedLocations = extractPathMentions(combinedText);
	const failureSummary = extractFirstSignal(lines);
	const rawExcerpt = buildExcerpt(lines, maxExcerptLines);
	const reportKind =
		failureType === "lint_failure" ||
		failureType === "typecheck_failure" ||
		failureType === "validation_failure"
			? "validation_failure"
			: failureType === "test_failure"
				? "test_regression"
				: "tool_failure";
	const recommendedNextStep = detectedLocations.length
		? `Open ${detectedLocations[0].path}:${detectedLocations[0].line} and inspect the failing line.`
		: "Re-run with a tighter scope or inspect the raw stderr for the first concrete failure.";

	const artifact = {
		schema_version: FAILURE_INSPECTION_SCHEMA_VERSION,
		artifact_id: createRecordId("opencode-failure-inspection"),
		created_at: new Date().toISOString(),
		label: String(label ?? "").trim(),
		source_kind: fromPayload.structured
			? "tool_result"
			: logPath
				? "log_file"
				: "raw_text",
		source_tool: fromPayload.sourceTool || null,
		source_command: fromPayload.sourceCommand || null,
		source_artifact_path: fromPayload.sourceArtifactPath || null,
		source_log_path: logPath || fromPayload.sourceLogPath || null,
		status: fromPayload.status,
		exit_code: fromPayload.exitCode,
		failure_type: failureType,
		report_kind: reportKind,
		summary:
			failureSummary ||
			`Failure inspection for ${fromPayload.sourceTool || label || "unknown source"}.`,
		first_signal: failureSummary || null,
		detected_paths: [...new Set(detectedLocations.map((entry) => entry.path))],
		detected_locations: detectedLocations,
		log_excerpt: rawExcerpt,
		recommended_next_step: recommendedNextStep,
		source_digest: stableDigest(combinedText || fromPayload.rawText || ""),
		content_light: true,
	};
	const filePath = writeArtifact(
		failureInspectionsRoot(effectiveRepoRoot),
		artifact,
	);
	writeJsonl(failureInspectionLedgerPath(effectiveRepoRoot), [
		{
			artifact_id: artifact.artifact_id,
			created_at: artifact.created_at,
			label: artifact.label,
			failure_type: artifact.failure_type,
			report_kind: artifact.report_kind,
			source_tool: artifact.source_tool,
			source_command: artifact.source_command,
			source_artifact_path: artifact.source_artifact_path,
			source_log_path: artifact.source_log_path,
			summary: artifact.summary,
			artifact_path: artifact.artifact_path,
		},
	]);
	return { filePath, artifact };
}

export function buildIssueReport({
	repoRoot,
	kind,
	severity,
	summary,
	details = "",
	sourceTool = "",
	sourceCommand = "",
	sourceArtifactPath = "",
	inspectionArtifactPath = "",
	affectedPaths = [],
	labels = [],
	recommendedNextStep = "",
}) {
	const effectiveRepoRoot = repoRoot ?? resolveRepoRoot(process.cwd());
	ensureIssueDirs(effectiveRepoRoot);

	const artifact = {
		schema_version: ISSUE_REPORT_SCHEMA_VERSION,
		artifact_id: createRecordId("opencode-issue-report"),
		created_at: new Date().toISOString(),
		kind: String(kind ?? "").trim(),
		severity: String(severity ?? "major").trim(),
		summary: String(summary ?? "").trim(),
		details: String(details ?? "").trim(),
		source_tool: String(sourceTool ?? "").trim() || null,
		source_command: String(sourceCommand ?? "").trim() || null,
		source_artifact_path: String(sourceArtifactPath ?? "").trim() || null,
		inspection_artifact_path:
			String(inspectionArtifactPath ?? "").trim() || null,
		affected_paths: [
			...new Set(
				affectedPaths
					.map((value) => String(value ?? "").trim())
					.filter(Boolean),
			),
		],
		labels: [
			...new Set(
				labels.map((value) => String(value ?? "").trim()).filter(Boolean),
			),
		],
		recommended_next_step: String(recommendedNextStep ?? "").trim(),
		report_digest: stableObjectDigest({
			kind: String(kind ?? "").trim(),
			severity: String(severity ?? "major").trim(),
			summary: String(summary ?? "").trim(),
			details: String(details ?? "").trim(),
			sourceTool: String(sourceTool ?? "").trim() || null,
			sourceCommand: String(sourceCommand ?? "").trim() || null,
			sourceArtifactPath: String(sourceArtifactPath ?? "").trim() || null,
			inspectionArtifactPath:
				String(inspectionArtifactPath ?? "").trim() || null,
			affectedPaths: [
				...new Set(
					affectedPaths
						.map((value) => String(value ?? "").trim())
						.filter(Boolean),
				),
			],
			labels: [
				...new Set(
					labels.map((value) => String(value ?? "").trim()).filter(Boolean),
				),
			],
			recommendedNextStep: String(recommendedNextStep ?? "").trim(),
		}),
		content_light: true,
	};
	const filePath = writeArtifact(issueReportsRoot(effectiveRepoRoot), artifact);
	writeJsonl(issueReportLedgerPath(effectiveRepoRoot), [
		{
			artifact_id: artifact.artifact_id,
			created_at: artifact.created_at,
			kind: artifact.kind,
			severity: artifact.severity,
			summary: artifact.summary,
			source_tool: artifact.source_tool,
			source_command: artifact.source_command,
			source_artifact_path: artifact.source_artifact_path,
			inspection_artifact_path: artifact.inspection_artifact_path,
			artifact_path: artifact.artifact_path,
		},
	]);
	return { filePath, artifact };
}

export function garbageCollectResolvedFailureArtifacts({
	repoRoot,
	sourceTool = "",
	sourceCommand = "",
	sourceArtifactPath = "",
	sourceLogPath = "",
	sourceKind = "",
	failureTypes = [
		"unknown",
		"tool_failure",
		"runtime_failure",
		"typecheck_failure",
		"lint_failure",
		"validation_failure",
		"test_failure",
	],
	reportKinds = ["tool_failure", "validation_failure", "test_regression"],
}) {
	const effectiveRepoRoot = repoRoot ?? resolveRepoRoot(process.cwd());
	const removed = [];
	const failureInspectionGcRows = [];
	const issueReportGcRows = [];
	let resolvedAt = null;
	const criteria = {
		sourceTool: String(sourceTool ?? "").trim(),
		sourceCommand: String(sourceCommand ?? "").trim(),
		sourceArtifactPath: String(sourceArtifactPath ?? "").trim(),
		sourceLogPath: String(sourceLogPath ?? "").trim(),
		sourceKind: String(sourceKind ?? "").trim(),
		failureTypes,
		reportKinds,
	};

	for (const path of listJsonArtifacts(
		failureInspectionsRoot(effectiveRepoRoot),
	)) {
		const artifact = readJson(path);
		if (!matchesResolutionArtifact(artifact, criteria)) {
			continue;
		}
		unlinkSync(path);
		const entry = {
			artifact_id: artifact.artifact_id,
			artifact_path: path,
			kind: "failure_inspection",
		};
		removed.push(entry);
		failureInspectionGcRows.push(entry);
	}

	for (const path of listJsonArtifacts(issueReportsRoot(effectiveRepoRoot))) {
		const artifact = readJson(path);
		if (!matchesResolutionArtifact(artifact, criteria)) {
			continue;
		}
		unlinkSync(path);
		const entry = {
			artifact_id: artifact.artifact_id,
			artifact_path: path,
			kind: "issue_report",
		};
		removed.push(entry);
		issueReportGcRows.push(entry);
	}

	if (removed.length) {
		resolvedAt = new Date().toISOString();
		if (failureInspectionGcRows.length) {
			writeJsonl(failureInspectionLedgerPath(effectiveRepoRoot), [
				...failureInspectionGcRows.map((entry) => ({
					event_kind: "gc",
					resolved_at: resolvedAt,
					artifact_id: entry.artifact_id,
					artifact_path: entry.artifact_path,
					source_tool: criteria.sourceTool || null,
					source_command: criteria.sourceCommand || null,
					source_artifact_path: criteria.sourceArtifactPath || null,
					source_log_path: criteria.sourceLogPath || null,
					kind: entry.kind,
				})),
			]);
		}
		if (issueReportGcRows.length) {
			writeJsonl(issueReportLedgerPath(effectiveRepoRoot), [
				...issueReportGcRows.map((entry) => ({
					event_kind: "gc",
					resolved_at: resolvedAt,
					artifact_id: entry.artifact_id,
					artifact_path: entry.artifact_path,
					source_tool: criteria.sourceTool || null,
					source_command: criteria.sourceCommand || null,
					source_artifact_path: criteria.sourceArtifactPath || null,
					source_log_path: criteria.sourceLogPath || null,
					kind: entry.kind,
				})),
			]);
		}
	}

	return {
		removed,
		resolved_at: resolvedAt,
	};
}

export function readInspectionArtifact(repoRoot, artifactPath) {
	const effectiveRepoRoot = repoRoot ?? resolveRepoRoot(process.cwd());
	const absolutePath = artifactPath.startsWith("/")
		? artifactPath
		: join(effectiveRepoRoot, artifactPath);
	if (!existsSync(absolutePath)) {
		throw new Error(`Inspection artifact not found: ${artifactPath}`);
	}
	return readJson(absolutePath);
}
