import assert from "node:assert/strict";
import {
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
	buildMutationPreflight,
	readFileContext,
	writeFileWithContext,
} from "./../.opencode/tools/opencode_context_core.mjs";

test("write preflight warns before mutating a file with dependents", () => {
	const repoRoot = mkdtempSync(join(tmpdir(), "opencode-preflight-"));

	try {
		mkdirSync(join(repoRoot, "src"), { recursive: true });
		writeFileSync(join(repoRoot, "src", "dep.ts"), "export const dep = 1\n");
		writeFileSync(
			join(repoRoot, "src", "target.ts"),
			"import { dep } from './dep'\nexport const target = dep\n",
		);
		writeFileSync(
			join(repoRoot, "src", "consumer.ts"),
			"import { target } from './target'\nexport const consumer = target\n",
		);

		const beforeContent = readFileSync(
			join(repoRoot, "src", "target.ts"),
			"utf8",
		);
		const preflight = writeFileWithContext({
			repoRoot,
			path: "src/target.ts",
			content: "import { dep } from './dep'\nexport const target = dep + 1\n",
			reason: "increase target value",
			expectedBeforeSha256: null,
			allowOverwriteProtected: true,
			preflightOnly: true,
		});

		assert.equal(preflight.mutated, false);
		assert.equal(preflight.preflight.target_path, "src/target.ts");
		assert.ok(preflight.preflight.alerts.length >= 1);
		assert.equal(preflight.preflight.alerts[0].code, "linked-context-impact");
		assert.ok(Array.isArray(preflight.preflight.search_signals.grep_matches));
		assert.ok(
			Array.isArray(preflight.preflight.search_signals.ast_grep_matches),
		);
		assert.equal(
			readFileSync(join(repoRoot, "src", "target.ts"), "utf8"),
			beforeContent,
		);
	} finally {
		rmSync(repoRoot, { recursive: true, force: true });
	}
});

test("replace_symbol preflight stops when a symbol spans more than three contexts", () => {
	const repoRoot = mkdtempSync(join(tmpdir(), "opencode-preflight-symbol-"));

	try {
		mkdirSync(join(repoRoot, "src"), { recursive: true });
		writeFileSync(
			join(repoRoot, "src", "dep1.ts"),
			"export function target() { return 1 }\n",
		);
		writeFileSync(
			join(repoRoot, "src", "dep2.ts"),
			"export function target() { return 2 }\n",
		);
		writeFileSync(
			join(repoRoot, "src", "dep3.ts"),
			"export function target() { return 3 }\n",
		);
		writeFileSync(
			join(repoRoot, "src", "target.ts"),
			[
				"import { target as dep1 } from './dep1'",
				"import { target as dep2 } from './dep2'",
				"import { target as dep3 } from './dep3'",
				"export function target() { return dep1() + dep2() + dep3() }",
				"",
			].join("\n"),
		);

		const current = readFileContext({
			repoRoot,
			path: "src/target.ts",
			includeContent: true,
			includeHistory: true,
			depth: 2,
		});
		const symbolRecord = current.artifact.symbol_records.find(
			(record) => record.name === "target",
		);
		assert.ok(symbolRecord);

		const preflight = buildMutationPreflight({
			repoRoot,
			operation: "replace_symbol",
			targetPath: current.artifact.target_path,
			currentArtifact: current.artifact,
			symbolRecord,
			replacementText: "renamed_target",
		});

		assert.ok(
			preflight.search_signals.grep_matches.some(
				(signal) => signal.term === "target" && signal.file_count >= 3,
			),
		);
		assert.ok(
			preflight.search_signals.ast_grep_matches.some(
				(signal) => signal.term === "target" && signal.file_count >= 3,
			),
		);
		const stopAlert = preflight.alerts.find(
			(alert) => alert.code === "symbol-cross-context-stop",
		);
		assert.equal(preflight.risk_level, "critical");
		assert.equal(preflight.suggested_tool, "search_replace");
		assert.ok(stopAlert);
		assert.equal(stopAlert.severity, "critical");
		assert.equal(stopAlert.affected_contexts.length, 4);
		assert.ok(
			stopAlert.message.includes(
				"Stop and switch to a coordinated search_replace plan before mutating.",
			),
		);
	} finally {
		rmSync(repoRoot, { recursive: true, force: true });
	}
});
