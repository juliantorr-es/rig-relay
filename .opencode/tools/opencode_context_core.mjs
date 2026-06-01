import { spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import {
	basename,
	dirname,
	join as pathJoin,
	relative,
	resolve,
} from "node:path";

import {
	readSmartFile,
	resolveToolPath as resolveSmartToolPath,
} from "./smart_read_file_core.mjs";

export const FILE_CONTEXT_SCHEMA_VERSION = "opencode.file_context.v1";
export const FILE_CHANGE_EVENT_SCHEMA_VERSION = "opencode.file_change_event.v1";
export const RECENT_EVENT_LIMIT = 5;

export function resolveRepoRoot(worktree) {
	return resolve(worktree || process.cwd());
}

export function contextRoot(repoRoot) {
	return pathJoin(repoRoot, "docs", "json", "opencode", "context");
}

export function contextFilesRoot(repoRoot) {
	return pathJoin(contextRoot(repoRoot), "files");
}

export function contextLedgersRoot(repoRoot) {
	return pathJoin(contextRoot(repoRoot), "ledgers");
}

export function ensureContextDirs(repoRoot) {
	mkdirSync(contextFilesRoot(repoRoot), { recursive: true });
	mkdirSync(contextLedgersRoot(repoRoot), { recursive: true });
}

export function repoRelative(repoRoot, filePath) {
	return relative(repoRoot, filePath).split("\\").join("/");
}

export function stableDigest(payload) {
	return `sha256:${createHash("sha256").update(payload, "utf8").digest("hex")}`;
}

export function stableObjectDigest(payload) {
	return stableDigest(`${JSON.stringify(payload, null, 2)}\n`);
}

export function stablePathId(targetPath) {
	const stem =
		basename(String(targetPath ?? "").trim())
			.replace(/\.[^.]+$/, "")
			.replace(/[^a-zA-Z0-9]+/g, "-")
			.replace(/^-+|-+$/g, "")
			.slice(0, 32) || "file";
	return `${stem}-${createHash("sha256")
		.update(String(targetPath ?? "").trim(), "utf8")
		.digest("hex")
		.slice(0, 12)}`;
}

export function contextArtifactPath(repoRoot, artifactId) {
	return pathJoin(contextFilesRoot(repoRoot), `${artifactId}.json`);
}

export function contextLedgerPath(repoRoot, targetPath) {
	return pathJoin(
		contextLedgersRoot(repoRoot),
		`${stablePathId(targetPath)}.jsonl`,
	);
}

export function readJson(filePath) {
	return JSON.parse(readFileSync(filePath, "utf8"));
}

export function writeJson(filePath, payload) {
	mkdirSync(dirname(filePath), { recursive: true });
	writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

export function readJsonl(filePath) {
	if (!existsSync(filePath)) {
		return [];
	}
	return readFileSync(filePath, "utf8")
		.split(/\r?\n/)
		.map((line) => line.trim())
		.filter(Boolean)
		.map((line) => JSON.parse(line));
}

export function writeJsonl(filePath, entries) {
	mkdirSync(dirname(filePath), { recursive: true });
	writeFileSync(
		filePath,
		`${entries.map((entry) => JSON.stringify(entry)).join("\n")}${entries.length ? "\n" : ""}`,
		"utf8",
	);
}

export function appendRecentEvent(repoRoot, targetPath, event) {
	const ledgerPath = contextLedgerPath(repoRoot, targetPath);
	const recentEvents = [...readJsonl(ledgerPath), event].slice(
		-RECENT_EVENT_LIMIT,
	);
	writeJsonl(ledgerPath, recentEvents);
	return { ledgerPath, recentEvents };
}

export function readRecentEvents(repoRoot, targetPath) {
	return readJsonl(contextLedgerPath(repoRoot, targetPath)).slice(
		-RECENT_EVENT_LIMIT,
	);
}

export function inferPathKind(targetPath) {
	const name = basename(String(targetPath ?? "").trim()).toLowerCase();
	if (name === "index" || name.startsWith("index.")) return "module";
	if (name.includes("service")) return "service";
	return "file";
}

export function createRecordId(prefix) {
	const stamp = new Date()
		.toISOString()
		.replace(/[-:]/g, "")
		.replace(/\.\d{3}Z$/, "Z");
	return `${prefix}-${stamp}-${randomUUID().slice(0, 8)}`;
}

function runRg(repoRoot, args) {
	const result = spawnSync("rg", args, {
		cwd: repoRoot,
		encoding: "utf8",
		maxBuffer: 1024 * 1024,
	});
	if (result.error?.code === "ENOENT") {
		return "";
	}
	if (result.status !== 0 && result.status !== 1) {
		return "";
	}
	return String(result.stdout ?? "").trim();
}

function runAstGrep(repoRoot, language, pattern) {
	const result = spawnSync(
		"sg",
		[
			"run",
			"-p",
			pattern,
			"--lang",
			language,
			"--files-with-matches",
			"--globs",
			"!docs/json/**",
			"--globs",
			"!.git/**",
			"--globs",
			"!graphify-out/**",
			".",
		],
		{
			cwd: repoRoot,
			encoding: "utf8",
			maxBuffer: 1024 * 1024,
		},
	);
	if (result.error?.code === "ENOENT") {
		return "";
	}
	if (result.status !== 0 && result.status !== 1) {
		return "";
	}
	return String(result.stdout ?? "").trim();
}

function parseMatchedFiles(output, repoRoot) {
	return output
		.split(/\r?\n/)
		.map((value) => value.trim())
		.filter(Boolean)
		.map((value) => (value.startsWith("./") ? value.slice(2) : value))
		.map((value) =>
			value.startsWith(repoRoot) ? repoRelative(repoRoot, value) : value,
		)
		.filter((value) => value && value !== ".");
}

function isIdentifierLike(value) {
	return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(value);
}

function collectPreflightSearchSignals({
	repoRoot,
	language,
	targetPath,
	currentArtifact,
	searchText = "",
	symbolRecord = null,
}) {
	const searchTerms = [];
	const addTerm = (value) => {
		const term = String(value ?? "").trim();
		if (!term || term.length > 120 || searchTerms.includes(term)) {
			return;
		}
		searchTerms.push(term);
	};

	addTerm(searchText);
	addTerm(symbolRecord?.name);
	for (const record of Array.isArray(currentArtifact?.symbol_records)
		? currentArtifact.symbol_records.slice(0, 5)
		: []) {
		addTerm(record?.name);
	}

	const textMatches = [];
	const astMatches = [];

	for (const term of searchTerms) {
		const grepOutput = runRg(repoRoot, [
			"-l",
			"-F",
			term,
			"--glob",
			"!docs/json/**",
			"--glob",
			"!.git/**",
			"--glob",
			"!graphify-out/**",
			".",
		]);
		const grepFiles = parseMatchedFiles(grepOutput, repoRoot).filter(
			(file) => file !== targetPath,
		);
		if (grepFiles.length) {
			textMatches.push({
				term,
				file_count: grepFiles.length,
				files: grepFiles,
				mode: "grep",
			});
		}

		if (language && isIdentifierLike(term)) {
			const astOutput = runAstGrep(repoRoot, language, term);
			const astFiles = parseMatchedFiles(astOutput, repoRoot).filter(
				(file) => file !== targetPath,
			);
			if (astFiles.length) {
				astMatches.push({
					term,
					language,
					file_count: astFiles.length,
					files: astFiles,
					mode: "ast_grep",
				});
			}
		}
	}

	return {
		search_terms: searchTerms,
		grep_matches: textMatches,
		ast_grep_matches: astMatches,
	};
}

function normalizeSpecifier(specifier, filePath, repoRoot) {
	if (!specifier) return null;
	if (!specifier.startsWith(".")) {
		return {
			specifier,
			resolved_path: null,
			kind: "external",
		};
	}

	const dir = dirname(filePath);
	const candidateRoots = [
		resolve(dir, specifier),
		resolve(dir, `${specifier}.ts`),
		resolve(dir, `${specifier}.tsx`),
		resolve(dir, `${specifier}.js`),
		resolve(dir, `${specifier}.jsx`),
		resolve(dir, `${specifier}.mjs`),
		resolve(dir, `${specifier}.py`),
		resolve(dir, specifier, "index.ts"),
		resolve(dir, specifier, "index.tsx"),
		resolve(dir, specifier, "index.js"),
		resolve(dir, specifier, "index.py"),
	];
	const resolved =
		candidateRoots.find((candidate) => existsSync(candidate)) ??
		candidateRoots[0];
	const rel = repoRelative(repoRoot, resolved);
	return {
		specifier,
		resolved_path: rel.startsWith("..") ? null : rel,
		kind: "internal",
	};
}

function collectImports(filePath, content, language, repoRoot) {
	const imports = [];
	const lines = content.split(/\r?\n/);

	for (const line of lines) {
		const text = line.trim();
		if (!text) continue;

		if (language === "python") {
			const fromMatch = text.match(/^from\s+([A-Za-z0-9_.]+)\s+import\s+/);
			const importMatch = text.match(
				/^import\s+([A-Za-z0-9_.]+(?:\s*,\s*[A-Za-z0-9_.]+)*)/,
			);
			if (fromMatch) {
				imports.push({
					specifier: fromMatch[1],
					resolved_path: null,
					kind: "python",
				});
			}
			if (importMatch) {
				for (const specifier of importMatch[1]
					.split(",")
					.map((value) => value.trim())
					.filter(Boolean)) {
					imports.push({
						specifier,
						resolved_path: null,
						kind: "python",
					});
				}
			}
			continue;
		}

		const fromMatch = text.match(/^import\s+.+?\s+from\s+['"]([^'"]+)['"]/);
		const bareMatch = text.match(/^import\s+['"]([^'"]+)['"]/);
		const requireMatch = text.match(/require\(\s*['"]([^'"]+)['"]\s*\)/);
		const exportFromMatch = text.match(
			/^export\s+.+?\s+from\s+['"]([^'"]+)['"]/,
		);
		const specifiers = [
			fromMatch?.[1],
			bareMatch?.[1],
			requireMatch?.[1],
			exportFromMatch?.[1],
		].filter(Boolean);
		for (const specifier of specifiers) {
			const normalized = normalizeSpecifier(specifier, filePath, repoRoot);
			if (normalized) {
				imports.push(normalized);
			}
		}
	}

	return [
		...new Map(
			imports.map((entry) => [`${entry.kind}:${entry.specifier}`, entry]),
		).values(),
	];
}

function collectExports(content, language) {
	const exports = [];
	const lines = content.split(/\r?\n/);

	for (const line of lines) {
		const text = line.trim();
		if (!text) continue;

		if (language === "python") {
			const funcMatch = text.match(/^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/);
			const classMatch = text.match(/^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:(]/);
			if (funcMatch) exports.push(funcMatch[1]);
			if (classMatch) exports.push(classMatch[1]);
			continue;
		}

		const patterns = [
			/^export\s+default\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/,
			/^export\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/,
			/^export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=/,
			/^export\s+class\s+([A-Za-z_][A-Za-z0-9_]*)\s+/,
			/^export\s+interface\s+([A-Za-z_][A-Za-z0-9_]*)\s+/,
			/^export\s+type\s+([A-Za-z_][A-Za-z0-9_]*)\s+/,
			/^export\s+enum\s+([A-Za-z_][A-Za-z0-9_]*)\s+/,
			/^export\s+default\s+([A-Za-z_][A-Za-z0-9_]*)/,
		];
		for (const pattern of patterns) {
			const match = text.match(pattern);
			if (match) {
				exports.push(match[1]);
			}
		}
	}

	return [...new Set(exports)];
}

function collectDependents(repoRoot, filePath, symbols) {
	const targetName = basename(filePath);
	const targetStem = targetName.replace(/\.[^.]+$/, "");
	const searchTokens = new Set(
		[targetName, targetStem, ...symbols].filter(Boolean),
	);
	const dependents = new Set();
	for (const token of searchTokens) {
		const output = runRg(repoRoot, [
			"-l",
			"-F",
			token,
			"--glob",
			"!docs/json/**",
			"--glob",
			"!.git/**",
			"--glob",
			"!graphify-out/**",
			".",
		]);
		for (const line of output
			.split(/\r?\n/)
			.map((value) => value.trim())
			.filter(Boolean)) {
			const rel = line.startsWith("./") ? line.slice(2) : line;
			if (rel !== repoRelative(repoRoot, filePath)) {
				dependents.add(rel);
			}
		}
	}
	return [...dependents].sort((left, right) => left.localeCompare(right));
}

function collectEntryPoints(filePath, exports) {
	const name = basename(filePath).toLowerCase();
	const entrypoints = [];
	if (name.startsWith("index.")) entrypoints.push("index");
	if (name.startsWith("main.")) entrypoints.push("main");
	if (name.includes("cli")) entrypoints.push("cli");
	if (exports.includes("default")) entrypoints.push("default export");
	return [...new Set(entrypoints)];
}

function collectEditSurfaces(outline, imports, dependents) {
	const surfaces = [];
	for (const entry of outline.slice(0, 6)) {
		if (entry.name) {
			surfaces.push(entry.name);
		} else if (entry.label) {
			surfaces.push(entry.label);
		}
	}
	for (const dependency of imports.slice(0, 6)) {
		if (dependency.resolved_path) {
			surfaces.push(dependency.resolved_path);
		}
	}
	for (const dependent of dependents.slice(0, 6)) {
		surfaces.push(dependent);
	}
	return [...new Set(surfaces)];
}

function buildContextSummary(language, outline, imports, _exports, dependents) {
	const unknowns = [];
	if (!outline.length) unknowns.push("no structural outline extracted");
	if (!imports.length) unknowns.push("no imports detected");
	if (!dependents.length) unknowns.push("no dependents found in repo scan");
	if (!language) unknowns.push("language could not be inferred");
	return unknowns;
}

function normalizeSymbolName(entry) {
	return String(entry.name ?? "").trim() || String(entry.label ?? "").trim();
}

function collectSymbolRecords(targetPath, outline, imports, dependents) {
	const records = [];
	const seen = new Map();
	const referencesOut = [
		...new Set(
			imports
				.map((item) => item.resolved_path ?? item.specifier)
				.filter(Boolean),
		),
	];
	const referencesIn = [...dependents];

	outline.forEach((entry) => {
		const name = normalizeSymbolName(entry);
		if (!name) {
			return;
		}
		const kind = String(entry.label ?? "symbol").trim();
		const ordinal = (seen.get(name) ?? 0) + 1;
		seen.set(name, ordinal);
		const symbolId = stableDigest(
			`${targetPath}\n${kind}\n${name}\n${ordinal}\n${entry.startLine}\n${entry.endLine}`,
		);
		records.push({
			symbol_id: symbolId,
			ordinal,
			name,
			kind,
			start_line: entry.startLine + 1,
			end_line: entry.endLine + 1,
			snippet: String(entry.snippet ?? "").trim(),
			references_out: referencesOut,
			references_in: referencesIn,
			replacement_key: `${name}#${ordinal}`,
		});
	});

	return records;
}

function collectLinkedContextTargets(linkedContexts, visited = new Set()) {
	const targets = [];
	for (const entry of linkedContexts ?? []) {
		if (!entry || typeof entry !== "object") {
			continue;
		}
		const targetPath = String(entry.target_path ?? "").trim();
		if (targetPath && !visited.has(targetPath)) {
			visited.add(targetPath);
			targets.push(targetPath);
		}
		const children = Array.isArray(entry.linked_contexts)
			? entry.linked_contexts
			: [];
		targets.push(...collectLinkedContextTargets(children, visited));
	}
	return targets;
}

function collectImpactedContexts(currentArtifact, visited = new Set()) {
	const contexts = [];
	if (!currentArtifact || typeof currentArtifact !== "object") {
		return contexts;
	}

	const artifactPath =
		String(currentArtifact.artifact_path ?? "").trim() || null;
	const artifactId = String(currentArtifact.artifact_id ?? "").trim() || null;
	const targetPath = String(currentArtifact.target_path ?? "").trim() || null;
	const currentKey = artifactId ?? targetPath ?? artifactPath ?? "";
	if (currentKey && !visited.has(currentKey)) {
		visited.add(currentKey);
		contexts.push({
			relation: "current",
			target_path: targetPath,
			artifact_id: artifactId,
			artifact_path: artifactPath,
			kind: currentArtifact.kind ?? null,
			depth: 0,
		});
	}

	const walk = (entries, depth) => {
		for (const entry of entries ?? []) {
			if (!entry || typeof entry !== "object") {
				continue;
			}
			const key = String(
				entry.artifact_id ?? entry.target_path ?? entry.artifact_path ?? "",
			).trim();
			if (key && visited.has(key)) {
				continue;
			}
			if (key) {
				visited.add(key);
			}
			contexts.push({
				relation: String(entry.relation ?? "linked"),
				target_path: String(entry.target_path ?? "").trim() || null,
				artifact_id: String(entry.artifact_id ?? "").trim() || null,
				artifact_path: String(entry.artifact_path ?? "").trim() || null,
				kind: entry.kind ?? null,
				depth,
			});
			walk(
				Array.isArray(entry.linked_contexts) ? entry.linked_contexts : [],
				depth + 1,
			);
		}
	};

	walk(
		Array.isArray(currentArtifact.linked_contexts)
			? currentArtifact.linked_contexts
			: [],
		1,
	);
	const deduped = [];
	const seen = new Set();
	for (const entry of contexts) {
		const key = String(
			entry.target_path ?? entry.artifact_path ?? entry.artifact_id ?? "",
		).trim();
		if (!key || seen.has(key)) {
			continue;
		}
		seen.add(key);
		deduped.push(entry);
	}
	return deduped;
}

function collectSymbolContextMatches(
	currentArtifact,
	symbolName,
	visited = new Set(),
) {
	const contexts = [];
	if (!currentArtifact || typeof currentArtifact !== "object" || !symbolName) {
		return contexts;
	}

	const inspectNode = (node, relation, depth) => {
		if (!node || typeof node !== "object") {
			return null;
		}
		const artifactPath = String(node.artifact_path ?? "").trim() || null;
		const artifactId = String(node.artifact_id ?? "").trim() || null;
		const targetPath = String(node.target_path ?? "").trim() || null;
		const currentKey = artifactId ?? targetPath ?? artifactPath ?? "";
		if (currentKey && visited.has(currentKey)) {
			return null;
		}
		if (currentKey) {
			visited.add(currentKey);
		}

		const matchingRecords = (
			Array.isArray(node.symbol_records) ? node.symbol_records : []
		).filter((record) => record?.name === symbolName);
		if (matchingRecords.length) {
			contexts.push({
				relation,
				target_path: targetPath,
				artifact_id: artifactId,
				artifact_path: artifactPath,
				kind: node.kind ?? null,
				depth,
				symbol_count: matchingRecords.length,
				symbol_names: matchingRecords.map((record) => record.name),
			});
		}
		return node;
	};

	inspectNode(currentArtifact, "current", 0);

	const walk = (entries, depth) => {
		for (const entry of entries ?? []) {
			if (!entry || typeof entry !== "object") {
				continue;
			}
			const key = String(
				entry.artifact_id ?? entry.target_path ?? entry.artifact_path ?? "",
			).trim();
			if (key && visited.has(key)) {
				continue;
			}
			const hydratedEntry =
				Array.isArray(entry.symbol_records) && entry.symbol_records.length
					? entry
					: entry.artifact_path
						? (() => {
								try {
									return readJson(entry.artifact_path);
								} catch {
									return entry;
								}
							})()
						: entry;
			const inspected = inspectNode(
				hydratedEntry,
				String(entry.relation ?? "linked"),
				depth,
			);
			if (!inspected) {
				continue;
			}
			walk(
				Array.isArray(inspected.linked_contexts)
					? inspected.linked_contexts
					: [],
				depth + 1,
			);
		}
	};

	walk(
		Array.isArray(currentArtifact.linked_contexts)
			? currentArtifact.linked_contexts
			: [],
		1,
	);
	const deduped = [];
	const seen = new Set();
	for (const entry of contexts) {
		const key = String(
			entry.target_path ?? entry.artifact_path ?? entry.artifact_id ?? "",
		).trim();
		if (!key || seen.has(key)) {
			continue;
		}
		seen.add(key);
		deduped.push(entry);
	}
	return deduped;
}

export function buildMutationPreflight({
	repoRoot = process.cwd(),
	operation,
	targetPath,
	currentArtifact,
	symbolRecord = null,
	searchText = "",
	replaceText = "",
	replacementText = "",
}) {
	const dependentTargets = Array.isArray(currentArtifact?.dependents)
		? currentArtifact.dependents
		: [];
	const linkedTargets = collectLinkedContextTargets(
		currentArtifact?.linked_contexts ?? [],
	);
	const impactedContexts = collectImpactedContexts(currentArtifact);
	const symbolTargets = Array.isArray(currentArtifact?.symbol_records)
		? currentArtifact.symbol_records.map((record) => record.name)
		: [];
	const impactSymbolName =
		symbolRecord?.name ??
		(searchText && symbolTargets.includes(searchText) ? searchText : null);
	const symbolContextMatches = impactSymbolName
		? collectSymbolContextMatches(currentArtifact, impactSymbolName)
		: [];
	const searchSignals = collectPreflightSearchSignals({
		repoRoot,
		language: currentArtifact?.language ?? null,
		targetPath,
		currentArtifact,
		searchText,
		symbolRecord,
	});
	const crossFileSignals = [
		...searchSignals.grep_matches,
		...searchSignals.ast_grep_matches,
	].filter((signal) => signal.file_count > 1);
	const impactedPaths = [
		...new Set([...dependentTargets, ...linkedTargets].filter(Boolean)),
	];
	const alerts = [];

	if (impactedPaths.length) {
		alerts.push({
			severity: "major",
			code: "linked-context-impact",
			message: `This change touches ${impactedPaths.length} linked or dependent context(s).`,
			affected_paths: impactedPaths,
			affected_contexts: impactedContexts,
		});
	}

	if (operation === "replace_symbol" && symbolRecord) {
		alerts.push({
			severity: impactedPaths.length ? "critical" : "major",
			code: "symbol-replacement-propagation",
			message: `Replacing symbol ${symbolRecord.name} may propagate through ${symbolRecord.references_in.length} inbound reference(s).`,
			affected_paths: [
				...new Set([...impactedPaths, ...symbolRecord.references_in]),
			],
			affected_contexts: symbolContextMatches,
		});
	}

	if (
		operation === "search_replace" &&
		searchText &&
		symbolTargets.includes(searchText)
	) {
		alerts.push({
			severity: "major",
			code: "search-target-matches-symbol",
			message: `Search text matches a known symbol in the current context graph: ${searchText}.`,
			affected_paths: impactedPaths,
			affected_contexts: symbolContextMatches,
		});
	}

	if (operation === "write_file" && currentArtifact?.symbol_records?.length) {
		alerts.push({
			severity: "minor",
			code: "symbol-context-refresh",
			message: `This file already has ${currentArtifact.symbol_records.length} symbol record(s); the write will refresh the context graph.`,
			affected_paths: impactedPaths,
			affected_contexts: impactedContexts,
		});
	}

	if (!alerts.length && !currentArtifact) {
		alerts.push({
			severity: "info",
			code: "new-file",
			message: `This path has no existing context; the mutation will seed a new context artifact.`,
			affected_paths: [],
			affected_contexts: [],
		});
	}

	if (symbolContextMatches.length > 1) {
		alerts.push({
			severity: symbolContextMatches.length > 3 ? "critical" : "major",
			code:
				symbolContextMatches.length > 3
					? "symbol-cross-context-stop"
					: "symbol-cross-context-warning",
			message:
				symbolContextMatches.length > 3
					? `Symbol ${impactSymbolName} appears in ${symbolContextMatches.length} file contexts. Stop and switch to a coordinated search_replace plan before mutating.`
					: operation === "search_replace"
						? `Symbol ${impactSymbolName} appears in ${symbolContextMatches.length} file contexts. Re-read the affected contexts before the next mutation.`
						: `Symbol ${impactSymbolName} appears in ${symbolContextMatches.length} file contexts. Use search_replace to coordinate the cross-file edit.`,
			affected_paths: [
				...new Set(
					symbolContextMatches
						.map((entry) => entry.target_path)
						.filter(Boolean),
				),
			],
			affected_contexts: symbolContextMatches,
		});
	}

	for (const signal of crossFileSignals) {
		alerts.push({
			severity: signal.file_count > 3 ? "critical" : "major",
			code:
				signal.mode === "ast_grep"
					? "ast-grep-cross-context"
					: "grep-cross-context",
			message:
				signal.file_count > 3
					? `${signal.mode} found ${signal.file_count} file contexts for ${signal.term}. Stop and coordinate the change before mutating.`
					: `${signal.mode} found ${signal.file_count} file contexts for ${signal.term}. Re-read the affected files before mutating.`,
			affected_paths: signal.files,
			affected_contexts: signal.files.map((file) => ({
				relation: signal.mode,
				target_path: file,
				artifact_id: null,
				artifact_path: null,
				kind: currentArtifact?.kind ?? null,
				depth: 0,
			})),
		});
	}

	const riskLevel = alerts.some((alert) => alert.severity === "critical")
		? "critical"
		: alerts.some((alert) => alert.severity === "major")
			? "high"
			: alerts.some((alert) => alert.severity === "minor")
				? "medium"
				: "low";

	const suggestedTool =
		symbolContextMatches.length > 1 && operation !== "search_replace"
			? "search_replace"
			: crossFileSignals.length && operation !== "search_replace"
				? crossFileSignals.some((signal) => signal.mode === "ast_grep")
					? "replace_symbol"
					: "search_replace"
				: crossFileSignals.length &&
						operation === "search_replace" &&
						symbolRecord
					? "replace_symbol"
					: operation === "write_file" &&
							currentArtifact?.symbol_records?.length &&
							impactedPaths.length > 0
						? "search_replace"
						: operation === "search_replace" &&
								symbolRecord &&
								impactedPaths.length > 1
							? "replace_symbol"
							: null;

	const suggestedReason =
		suggestedTool === "search_replace"
			? symbolContextMatches.length > 1
				? `Symbol ${impactSymbolName ?? "change"} appears in ${symbolContextMatches.length} contexts; use search_replace to coordinate the cross-file change and then re-read the affected contexts.`
				: "This change spans multiple related contexts; use search_replace in the current file, then re-read the linked contexts before further mutation."
			: suggestedTool === "replace_symbol"
				? "The search text matches a stable symbol; use replace_symbol so the symbol graph and replacement plan stay deterministic."
				: null;

	return {
		operation,
		target_path: targetPath,
		risk_level: riskLevel,
		alert_count: alerts.length,
		alerts,
		impacted_paths: impactedPaths,
		impacted_contexts: impactedContexts,
		symbol_context_matches: symbolContextMatches,
		suggested_tool: suggestedTool,
		suggested_reason: suggestedReason,
		symbol_name: symbolRecord?.name ?? null,
		symbol_id: symbolRecord?.symbol_id ?? null,
		replacement_text: replacementText || null,
		search_text: searchText || null,
		replace_text: replaceText || null,
		search_signals: searchSignals,
		content_light: true,
	};
}

function contextLinkKey(relation, targetPath) {
	return `${relation}:${targetPath}`;
}

function collectDirectContextLinks({ imports, dependents }) {
	const links = [];
	const seen = new Set();
	for (const item of imports) {
		if (!item.resolved_path) continue;
		const key = contextLinkKey("dependency", item.resolved_path);
		if (seen.has(key)) continue;
		seen.add(key);
		links.push({
			relation: "dependency",
			target_path: item.resolved_path,
		});
	}
	for (const dependent of dependents) {
		const key = contextLinkKey("dependent", dependent);
		if (seen.has(key)) continue;
		seen.add(key);
		links.push({
			relation: "dependent",
			target_path: dependent,
		});
	}
	return links;
}

function summarizeLinkedContext(link, artifact, depth, children = []) {
	return {
		relation: link.relation,
		target_path: artifact.target_path,
		artifact_id: artifact.artifact_id,
		artifact_path: artifact.artifact_path,
		kind: artifact.kind,
		target_hash: artifact.target_hash,
		depth,
		linked_contexts: children,
	};
}

function buildLinkedContexts({ repoRoot, links, depth, visited }) {
	if (depth <= 0) {
		return [];
	}

	const linkedContexts = [];
	for (const link of links) {
		const targetPath = link.target_path;
		const visitKey = repoRelative(
			repoRoot,
			resolveSmartToolPath(repoRoot, targetPath),
		);
		if (visited.has(visitKey)) {
			continue;
		}
		visited.add(visitKey);

		const linked = readFileContext({
			repoRoot,
			path: targetPath,
			includeContent: false,
			includeHistory: true,
			depth: depth - 1,
			visited,
			writeArtifact: true,
		});

		linkedContexts.push(
			summarizeLinkedContext(
				link,
				linked.artifact,
				depth,
				linked.artifact.linked_contexts ?? [],
			),
		);
	}

	return linkedContexts;
}

export function readFileContext({
	repoRoot,
	path,
	kind = "file",
	includeContent = true,
	includeHistory = true,
	depth = 1,
	visited = new Set(),
	writeArtifact = true,
}) {
	ensureContextDirs(repoRoot);
	const filePath = resolveSmartToolPath(repoRoot, path);
	if (!existsSync(filePath)) {
		throw new Error(`File not found: ${repoRelative(repoRoot, filePath)}`);
	}

	const targetPath = repoRelative(repoRoot, filePath);
	const content = readFileSync(filePath, "utf8");
	const language = readSmartFile({
		worktree: repoRoot,
		path: targetPath,
	}).language;
	const structure = readSmartFile({ worktree: repoRoot, path: targetPath });
	const imports = collectImports(filePath, content, language, repoRoot);
	const exports = collectExports(content, language);
	const symbols = [
		...new Set([
			...structure.outline
				.map((entry) => String(entry.name ?? "").trim())
				.filter(Boolean),
			...exports,
		]),
	];
	const dependents = collectDependents(repoRoot, filePath, symbols);
	const dependencies = imports.filter(
		(item) => item.resolved_path || item.kind !== "external",
	);
	const referencesOut = [
		...new Set(
			imports
				.map((item) => item.resolved_path ?? item.specifier)
				.filter(Boolean),
		),
	];
	const referencesIn = dependents;
	const entrypoints = collectEntryPoints(filePath, exports);
	const editSurfaces = collectEditSurfaces(
		structure.outline,
		imports,
		dependents,
	);
	const symbolRecords = collectSymbolRecords(
		targetPath,
		structure.outline,
		imports,
		dependents,
	);
	const directLinks = collectDirectContextLinks({
		imports,
		dependents,
	});
	const recentEvents = includeHistory
		? readRecentEvents(repoRoot, targetPath)
		: [];
	const unknowns = buildContextSummary(
		language,
		structure.outline,
		imports,
		exports,
		dependents,
	);
	const targetHash = stableDigest(content);
	const currentVisited = new Set(visited);
	currentVisited.add(targetPath);
	const contextPayload = {
		target_path: targetPath,
		kind,
		language: language ?? null,
		target_hash: targetHash,
		line_count: content.split(/\r?\n/).length,
		symbols,
		imports,
		exports,
		references_out: referencesOut,
		references_in: referencesIn,
		dependencies,
		dependents,
		entrypoints,
		edit_surfaces: editSurfaces,
		symbol_records: symbolRecords,
		linked_contexts: [],
		recent_events: recentEvents,
		unknowns,
	};
	const scopeHash = stableDigest(
		`${JSON.stringify(contextPayload, null, 2)}\n`,
	);
	const artifactId = createRecordId("opencode-file-context");
	const artifact = {
		schema_version: FILE_CONTEXT_SCHEMA_VERSION,
		artifact_id: artifactId,
		created_at: new Date().toISOString(),
		target_path: targetPath,
		kind,
		scope_root: targetPath,
		scope_hash: scopeHash,
		target_hash: targetHash,
		language: language ?? null,
		file_size_bytes: Buffer.byteLength(content, "utf8"),
		line_count: content.split(/\r?\n/).length,
		symbols,
		imports,
		exports,
		references_out: referencesOut,
		references_in: referencesIn,
		dependencies,
		dependents,
		entrypoints,
		edit_surfaces: editSurfaces,
		symbol_records: symbolRecords,
		linked_contexts: [],
		recent_events: recentEvents,
		unknowns,
		confidence: recentEvents.length ? 0.95 : 0.85,
		content_light: true,
	};
	artifact.linked_contexts = buildLinkedContexts({
		repoRoot,
		links: directLinks,
		depth,
		visited: currentVisited,
	});
	artifact.scope_hash = stableDigest(
		`${JSON.stringify(
			{
				...contextPayload,
				linked_contexts: artifact.linked_contexts,
			},
			null,
			2,
		)}\n`,
	);
	const artifactPath = contextArtifactPath(repoRoot, artifactId);
	artifact.artifact_path = artifactPath;
	if (writeArtifact) {
		writeJson(artifactPath, artifact);
	}

	return {
		filePath,
		artifactPath,
		artifact,
		content: includeContent ? content : null,
		preview: structure.output,
		recentEvents,
		ledgerPath: contextLedgerPath(repoRoot, targetPath),
	};
}

export function buildFileChangeEvent({
	repoRoot,
	path,
	operation,
	beforeContent,
	afterContent,
	summary,
	searchText,
	replaceText,
	replaceAll = true,
	reason = "",
	contextArtifactPathValue = "",
	contextArtifactId = "",
}) {
	const filePath = resolveSmartToolPath(repoRoot, path);
	const targetPath = repoRelative(repoRoot, filePath);
	const beforeText = String(beforeContent ?? "");
	const afterText = String(afterContent ?? "");
	return {
		schema_version: FILE_CHANGE_EVENT_SCHEMA_VERSION,
		event_id: createRecordId("opencode-file-change"),
		created_at: new Date().toISOString(),
		target_path: targetPath,
		operation,
		summary: String(summary ?? "").trim(),
		reason: String(reason ?? "").trim(),
		before_sha256: stableDigest(beforeText),
		after_sha256: stableDigest(afterText),
		before_line_count: beforeText ? beforeText.split(/\r?\n/).length : 0,
		after_line_count: afterText ? afterText.split(/\r?\n/).length : 0,
		before_byte_count: Buffer.byteLength(beforeText, "utf8"),
		after_byte_count: Buffer.byteLength(afterText, "utf8"),
		search_text: searchText ?? null,
		replace_text: replaceText ?? null,
		replace_all: Boolean(replaceAll),
		context_artifact_path: contextArtifactPathValue || null,
		context_artifact_id: contextArtifactId || null,
		content_light: true,
	};
}

export function recordFileChangeEvent(repoRoot, targetPath, event) {
	return appendRecentEvent(repoRoot, targetPath, event);
}

export function writeFileWithContext({
	repoRoot,
	path,
	content,
	operation = "write_file",
	summary = "Updated file",
	reason = "",
	searchText = null,
	replaceText = null,
	replaceAll = true,
	expectedBeforeSha256 = null,
	allowOverwriteProtected = false,
	preflightOnly = false,
}) {
	ensureContextDirs(repoRoot);
	const filePath = resolveSmartToolPath(repoRoot, path);
	const targetPath = repoRelative(repoRoot, filePath);
	const exists = existsSync(filePath);
	const beforeContent = exists ? readFileSync(filePath, "utf8") : "";
	const beforeHash = beforeContent ? stableDigest(beforeContent) : null;

	if (exists && !allowOverwriteProtected) {
		if (!expectedBeforeSha256) {
			throw new Error(
				`Expected before hash required for existing file: ${targetPath}`,
			);
		}
		if (beforeHash !== expectedBeforeSha256) {
			throw new Error(`Expected before hash mismatch for ${targetPath}`);
		}
	}

	const currentContext = exists
		? readFileContext({
				repoRoot,
				path: targetPath,
				includeContent: true,
				includeHistory: true,
				depth: 2,
				writeArtifact: false,
			})
		: null;
	const preflight = buildMutationPreflight({
		repoRoot,
		operation,
		targetPath,
		currentArtifact: currentContext?.artifact ?? null,
		searchText,
		replaceText,
		replacementText: String(content ?? ""),
	});

	if (preflightOnly) {
		return {
			filePath,
			beforeContent,
			beforeHash,
			preflight,
			ledgerPath: contextLedgerPath(repoRoot, targetPath),
			context: currentContext ?? {
				artifactPath: null,
				artifact: null,
				content: null,
				preview: "",
			},
			mutated: false,
		};
	}

	mkdirSync(dirname(filePath), { recursive: true });
	writeFileSync(filePath, String(content ?? ""), "utf8");
	const afterContent = readFileSync(filePath, "utf8");
	const context = readFileContext({
		repoRoot,
		path: targetPath,
		includeContent: true,
		includeHistory: true,
	});
	const event = buildFileChangeEvent({
		repoRoot,
		path: targetPath,
		operation,
		beforeContent,
		afterContent,
		summary,
		searchText,
		replaceText,
		replaceAll,
		reason,
		contextArtifactPathValue: context.artifactPath,
		contextArtifactId: context.artifact.artifact_id,
	});
	const { ledgerPath, recentEvents } = recordFileChangeEvent(
		repoRoot,
		targetPath,
		event,
	);
	const refreshedContext = readFileContext({
		repoRoot,
		path: targetPath,
		includeContent: true,
		includeHistory: true,
	});
	return {
		filePath,
		beforeContent,
		afterContent,
		beforeHash,
		afterHash: stableDigest(afterContent),
		preflight,
		event,
		ledgerPath,
		recentEvents,
		context: refreshedContext,
		mutated: true,
	};
}

export function searchReplaceFileWithContext({
	repoRoot,
	path,
	search,
	replace,
	all = true,
	reason = "",
	expectedBeforeSha256 = null,
	allowOverwriteProtected = false,
	preflightOnly = false,
}) {
	const filePath = resolveSmartToolPath(repoRoot, path);
	const beforeContent = readFileSync(filePath, "utf8");
	const beforeHash = stableDigest(beforeContent);
	if (existsSync(filePath) && !allowOverwriteProtected) {
		if (!expectedBeforeSha256) {
			throw new Error(
				`Expected before hash required for existing file: ${repoRelative(repoRoot, filePath)}`,
			);
		}
		if (beforeHash !== expectedBeforeSha256) {
			throw new Error(
				`Expected before hash mismatch for ${repoRelative(repoRoot, filePath)}`,
			);
		}
	}

	const searchText = String(search ?? "");
	if (!searchText) {
		throw new Error("search_replace requires a non-empty search string");
	}
	const replaceText = String(replace ?? "");
	const replacementCount = beforeContent.split(searchText).length - 1;
	if (!replacementCount) {
		throw new Error(
			`Search text not found in ${repoRelative(repoRoot, filePath)}`,
		);
	}
	const afterContent = all
		? beforeContent.split(searchText).join(replaceText)
		: beforeContent.replace(searchText, replaceText);
	return writeFileWithContext({
		repoRoot,
		path,
		content: afterContent,
		operation: "search_replace",
		summary: `Replaced ${replacementCount} occurrence(s)`,
		reason,
		searchText,
		replaceText,
		replaceAll: all,
		expectedBeforeSha256,
		allowOverwriteProtected,
		preflightOnly,
	});
}

export function editFileWithContext({
	repoRoot,
	path,
	content = null,
	search = null,
	replace = null,
	all = true,
	instruction = "",
	reason = "",
	expectedBeforeSha256 = null,
	allowOverwriteProtected = false,
	preflightOnly = false,
}) {
	if (content !== null && content !== undefined) {
		return writeFileWithContext({
			repoRoot,
			path,
			content,
			operation: "edit",
			summary: instruction || "Applied guided edit",
			reason,
			expectedBeforeSha256,
			allowOverwriteProtected,
			preflightOnly,
		});
	}

	if (search !== null && replace !== null) {
		return searchReplaceFileWithContext({
			repoRoot,
			path,
			search,
			replace,
			all,
			reason: reason || instruction,
			expectedBeforeSha256,
			allowOverwriteProtected,
			preflightOnly,
		});
	}

	throw new Error("edit requires either content or search/replace arguments");
}
