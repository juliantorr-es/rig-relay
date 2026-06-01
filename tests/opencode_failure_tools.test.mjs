import assert from "node:assert/strict";
import {
	existsSync,
	mkdirSync,
	mkdtempSync,
	readFileSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
	buildIssueReport,
	garbageCollectResolvedFailureArtifacts,
	inspectFailure,
	readInspectionArtifact,
} from "./../.opencode/tools/opencode_failure_core.mjs";

test("inspect_failure extracts the failure signal and affected file context", () => {
	const repoRoot = mkdtempSync(join(tmpdir(), "opencode-failure-"));

	try {
		mkdirSync(join(repoRoot, "tests"), { recursive: true });
		const logPath = join(repoRoot, "tests", "failure.log");
		writeFileSync(
			logPath,
			[
				"============================= test session starts =============================",
				"FAILED tests/test_example.py::test_failure",
				"tests/test_example.py:17:5 AssertionError: boom",
				"Traceback (most recent call last):",
				'  File "tests/test_example.py", line 17, in test_failure',
			].join("\n"),
			"utf8",
		);

		const result = inspectFailure({
			repoRoot,
			payload: {
				tool: "pytest",
				command: "uv run pytest tests/test_example.py -q",
				result: {
					status: "failed",
					exit_code: 1,
					stderr: readFileSync(logPath, "utf8"),
				},
			},
			logPath,
			label: "pytest",
			maxExcerptLines: 8,
		});

		assert.equal(result.artifact.failure_type, "test_failure");
		assert.equal(result.artifact.report_kind, "test_regression");
		assert.deepEqual(result.artifact.detected_paths, ["tests/test_example.py"]);
		assert.equal(result.artifact.detected_locations[0].line, 17);
		assert.match(result.artifact.log_excerpt, /AssertionError: boom/);
		assert.match(
			result.artifact.recommended_next_step,
			/tests\/test_example\.py:17/,
		);

		const reread = readInspectionArtifact(repoRoot, result.filePath);
		assert.equal(reread.artifact_id, result.artifact.artifact_id);
		assert.equal(reread.failure_type, "test_failure");
	} finally {
		rmSync(repoRoot, { recursive: true, force: true });
	}
});

test("report writes a canonical issue artifact with the requested kind", () => {
	const repoRoot = mkdtempSync(join(tmpdir(), "opencode-issue-"));

	try {
		const result = buildIssueReport({
			repoRoot,
			kind: "out_of_scope_finding",
			severity: "minor",
			summary: "Found a disconnected seam during inspection.",
			details: "The tool path is not wired through the prompt surface yet.",
			sourceTool: "inspect_failure",
			sourceCommand: "uv run pytest tests/test_example.py -q",
			sourceArtifactPath: "docs/json/opencode/failure_inspections/example.json",
			inspectionArtifactPath:
				"docs/json/opencode/failure_inspections/example.json",
			affectedPaths: ["tests/test_example.py", ".opencode/tools/report.ts"],
			labels: ["disconnected-seam", "reporting"],
			recommendedNextStep:
				"Wire the prompt to advertise report and inspect_failure.",
		});

		assert.equal(result.artifact.kind, "out_of_scope_finding");
		assert.equal(result.artifact.severity, "minor");
		assert.deepEqual(result.artifact.affected_paths, [
			"tests/test_example.py",
			".opencode/tools/report.ts",
		]);
		assert.match(result.artifact.report_digest, /^sha256:/);
		assert.match(result.filePath, /docs\/json\/opencode\/issue_reports\//);
	} finally {
		rmSync(repoRoot, { recursive: true, force: true });
	}
});

test("resolved failure artifacts are garbage-collected and ledgered", () => {
	const repoRoot = mkdtempSync(join(tmpdir(), "opencode-failure-gc-"));

	try {
		const command = "uv run pytest tests/test_example.py -q";
		const inspection = inspectFailure({
			repoRoot,
			payload: {
				tool: "test",
				command,
				result: {
					status: "failed",
					exit_code: 1,
					stderr: "FAILED tests/test_example.py::test_failure\n",
				},
			},
			label: "pytest",
			maxExcerptLines: 4,
		});
		const issue = buildIssueReport({
			repoRoot,
			kind: "validation_failure",
			severity: "major",
			summary: "Validation failed.",
			details: "The command still needs repair.",
			sourceTool: "test",
			sourceCommand: command,
			sourceArtifactPath: inspection.filePath,
			inspectionArtifactPath: inspection.filePath,
			affectedPaths: ["tests/test_example.py"],
			labels: ["test", "failure"],
			recommendedNextStep: "Fix the test and rerun the same command.",
		});

		const resolved = garbageCollectResolvedFailureArtifacts({
			repoRoot,
			sourceTool: "test",
			sourceCommand: command,
		});

		assert.equal(resolved.removed.length, 2);
		assert.equal(existsSync(inspection.filePath), false);
		assert.equal(existsSync(issue.filePath), false);
		assert.equal(
			readFileSync(
				join(repoRoot, "docs/json/opencode/failure_inspections/ledger.jsonl"),
				"utf8",
			).includes('"event_kind":"gc"'),
			true,
		);
		assert.equal(
			readFileSync(
				join(repoRoot, "docs/json/opencode/issue_reports/ledger.jsonl"),
				"utf8",
			).includes('"event_kind":"gc"'),
			true,
		);
	} finally {
		rmSync(repoRoot, { recursive: true, force: true });
	}
});
