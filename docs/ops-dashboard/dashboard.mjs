const ROOTS = [
	"../json/opencode/",
	"../json/roadmaps/",
	"../json/evidence/",
	"../json/release_gate/",
	"../json/reports/",
	"../json/audits/",
];

const REFRESH_DEFAULT_MS = 20_000;
const MAX_ARTIFACTS = 250;

const STAGE_ORDER = [
	"planning",
	"execution",
	"validation",
	"stress",
	"publication",
	"reporting",
];

const FAMILY_LABELS = new Map([
	["opencode", "OpenCode"],
	["roadmaps", "Roadmaps"],
	["evidence", "Evidence"],
	["release_gate", "Release gate"],
	["reports", "Reports"],
	["audits", "Audits"],
]);

let activeController = null;
let refreshTimer = null;
let refreshSerial = 0;
let cachedArtifacts = [];
let editorState = null;
let editorSaveTimer = null;
let editorQuestionSelection = new Set();
let editorPublishedRoadmap = null;
let editorLatestDelta = null;
let editorLatestQuestionReport = null;
let editorConnectionStatus = "disconnected";

function $(selector) {
	return document.querySelector(selector);
}

function nowIso() {
	return new Date().toISOString();
}

function urlWithBust(url) {
	const parsed = new URL(url, window.location.href);
	parsed.searchParams.set("v", `${Date.now()}`);
	return parsed.toString();
}

function toText(value) {
	if (value === null || value === undefined) {
		return "";
	}
	return String(value).trim();
}

function parseTimestamp(value) {
	const text = toText(value);
	if (!text) {
		return null;
	}
	const ms = Date.parse(text);
	return Number.isNaN(ms) ? null : ms;
}

function inferFamily(pathname) {
	const match = pathname.match(/docs\/json\/([^/]+)/);
	return match ? match[1] : "other";
}

function inferStage(artifact) {
	const schema = toText(artifact.schema_version).toLowerCase();
	const kind = toText(artifact.kind).toLowerCase();
	const title = toText(artifact.title).toLowerCase();
	const summary = toText(artifact.summary).toLowerCase();
	const bucket = `${schema} ${kind} ${title} ${summary}`;

	if (
		schema.includes("opencode.dashboard.roadmap_delta") ||
		schema.includes("opencode.dashboard.question_report") ||
		schema.includes("opencode.dashboard.roadmap.v1")
	) {
		return schema.includes("roadmap_delta") ||
			schema.includes("question_report")
			? "reporting"
			: "planning";
	}
	if (
		bucket.includes("plan") ||
		bucket.includes("roadmap") ||
		bucket.includes("comment")
	) {
		return "planning";
	}
	if (
		schema.includes("failure_inspection") ||
		schema.includes("issue_report") ||
		schema.includes("session_report") ||
		schema.includes("published_checkpoint_report") ||
		schema.includes("report") ||
		schema.includes("audit") ||
		schema.includes("evidence")
	) {
		return "reporting";
	}
	if (
		schema.includes("validation_artifact") ||
		bucket.includes("validation") ||
		bucket.includes("test")
	) {
		return "validation";
	}
	if (
		schema.includes("stress_artifact") ||
		bucket.includes("stress") ||
		bucket.includes("red_team")
	) {
		return "stress";
	}
	if (
		schema.includes("publication_artifact") ||
		schema.includes("checkpoint_publication") ||
		bucket.includes("publication") ||
		bucket.includes("published_checkpoint")
	) {
		return "publication";
	}
	if (
		schema.includes("execution_artifact") ||
		schema.includes("checkpoint_preparation") ||
		schema.includes("checkpoint_commit") ||
		bucket.includes("execution")
	) {
		return "execution";
	}
	return "reporting";
}

function inferSeverity(artifact) {
	const status = toText(
		artifact.status || artifact.severity || artifact.state,
	).toLowerCase();
	if (!status) {
		return "neutral";
	}
	if (
		["critical", "blocked", "failed", "failure", "error", "open"].some(
			(entry) => status.includes(entry),
		)
	) {
		return "danger";
	}
	if (
		["warn", "warning", "major", "minor", "pending", "repair"].some((entry) =>
			status.includes(entry),
		)
	) {
		return "warn";
	}
	return "ok";
}

function deriveTitle(artifact, sourcePath) {
	return (
		toText(artifact.title) ||
		toText(artifact.name) ||
		toText(artifact.report_summary) ||
		toText(artifact.summary) ||
		toText(artifact.objective) ||
		sourcePath.split("/").pop()
	);
}

function deriveSummary(artifact) {
	return (
		toText(artifact.summary) ||
		toText(artifact.report_summary) ||
		toText(artifact.details) ||
		toText(artifact.description) ||
		toText(artifact.next_steps?.[0]) ||
		toText(artifact.recommended_next_step)
	);
}

function deriveStatus(artifact) {
	return (
		toText(artifact.status) ||
		toText(artifact.state) ||
		toText(artifact.phase) ||
		toText(artifact.result) ||
		toText(artifact.kind) ||
		"unknown"
	);
}

function deriveTags(artifact) {
	const tags = new Set();
	for (const value of [
		artifact.schema_version,
		artifact.kind,
		artifact.wave_id,
		artifact.plan_id,
		artifact.status,
		artifact.state,
		artifact.phase,
	]) {
		const text = toText(value);
		if (text) {
			tags.add(text);
		}
	}
	return Array.from(tags).slice(0, 4);
}

function makeDefaultDraftState() {
	const now = nowIso();
	return {
		schema_version: "opencode.dashboard.draft_state.v1",
		draft_id: "ops-dashboard",
		draft_source: "local",
		draft_notes: "",
		updated_at: now,
		roadmap: {
			title: "Operations Dashboard Roadmap",
			summary:
				"Draft roadmap and timeline for the local dashboard. Publish creates a versioned artifact and transition delta.",
			status: "draft",
			owner: "ops-dashboard",
			version_hint: 1,
			timeline: [
				{
					item_id: "roadmap-foundation",
					title: "Foundation",
					status: "active",
					due: "",
					owner: "ops-dashboard",
					details:
						"Establish the published roadmap, draft editor, question inbox, and delta artifacts.",
					impacted_contexts: [
						"docs/json/opencode/ops-dashboard/published/",
						"docs/json/opencode/ops-dashboard/deltas/",
					],
					notes:
						"Start from the current published state and keep the draft hidden until publish.",
				},
				{
					item_id: "context-delta",
					title: "Context delta loop",
					status: "planned",
					due: "",
					owner: "ops-dashboard",
					details:
						"Publish versioned roadmap changes with explicit downstream context files so sessions can adopt the new version without losing the old one.",
					impacted_contexts: [
						"docs/json/opencode/ops-dashboard/published/",
						"docs/json/opencode/ops-dashboard/deltas/",
					],
					notes:
						"Agents should see the superseded version and the transition delta together.",
				},
			],
		},
		questions: {
			pending: [],
			archived: [],
		},
	};
}

function normalizeTimelineItem(raw, index) {
	const item = raw && typeof raw === "object" ? raw : {};
	return {
		item_id: toText(item.item_id) || toText(item.id) || `item-${index + 1}`,
		title: toText(item.title) || "",
		status: toText(item.status) || "planned",
		due: toText(item.due),
		owner: toText(item.owner),
		details: toText(item.details || item.description),
		impacted_contexts: Array.isArray(item.impacted_contexts)
			? item.impacted_contexts.map(toText).filter(Boolean)
			: [],
		notes: toText(item.notes),
	};
}

function normalizeQuestionItem(raw, index, archived = false) {
	const item = raw && typeof raw === "object" ? raw : {};
	const timestamp = toText(item.created_at) || nowIso();
	const question = {
		question_id:
			toText(item.question_id) || toText(item.id) || `question-${index + 1}`,
		category: toText(item.category) || "general",
		question: toText(item.question),
		linked_contexts: Array.isArray(item.linked_contexts)
			? item.linked_contexts.map(toText).filter(Boolean)
			: [],
		status: archived ? "archived" : toText(item.status) || "pending",
		created_at: timestamp,
	};
	if (archived) {
		question.answer = toText(item.answer);
		question.answered_at = toText(item.answered_at) || timestamp;
		question.archived_at = toText(item.archived_at) || timestamp;
	}
	return question;
}

function normalizeDraftState(raw) {
	const draft = raw && typeof raw === "object" ? raw : {};
	const roadmap =
		draft.roadmap && typeof draft.roadmap === "object" ? draft.roadmap : {};
	const questions =
		draft.questions && typeof draft.questions === "object"
			? draft.questions
			: {};
	return {
		schema_version: "opencode.dashboard.draft_state.v1",
		draft_id: toText(draft.draft_id) || "ops-dashboard",
		draft_source: "local",
		draft_notes: toText(draft.draft_notes),
		updated_at: toText(draft.updated_at) || nowIso(),
		roadmap: {
			title: toText(roadmap.title) || "Operations Dashboard Roadmap",
			summary:
				toText(roadmap.summary) ||
				"Draft roadmap and timeline for the local dashboard.",
			status: toText(roadmap.status) || "draft",
			owner: toText(roadmap.owner) || "ops-dashboard",
			version_hint: Number(roadmap.version_hint) || 1,
			timeline: Array.isArray(roadmap.timeline)
				? roadmap.timeline.map((item, index) =>
						normalizeTimelineItem(item, index),
					)
				: [],
		},
		questions: {
			pending: Array.isArray(questions.pending)
				? questions.pending.map((item, index) =>
						normalizeQuestionItem(item, index),
					)
				: [],
			archived: Array.isArray(questions.archived)
				? questions.archived.map((item, index) =>
						normalizeQuestionItem(item, index, true),
					)
				: [],
		},
	};
}

function roadmapToPlain(roadmap) {
	return {
		title: toText(roadmap.title),
		summary: toText(roadmap.summary),
		status: toText(roadmap.status),
		owner: toText(roadmap.owner),
		version_hint: Number(roadmap.version_hint) || 1,
		timeline: Array.isArray(roadmap.timeline)
			? roadmap.timeline.map((item, index) =>
					normalizeTimelineItem(item, index),
				)
			: [],
	};
}

function buildRoadmapDiff(beforeRoadmap, afterRoadmap) {
	const before = roadmapToPlain(beforeRoadmap || {});
	const after = roadmapToPlain(afterRoadmap || {});
	const diffs = [];
	for (const key of ["title", "summary", "status", "owner"]) {
		if (before[key] !== after[key]) {
			diffs.push({
				path: key,
				before: before[key],
				after: after[key],
				changeKind: "updated",
			});
		}
	}

	const beforeTimeline = new Map(
		(before.timeline || []).map((item) => [item.item_id, item]),
	);
	const afterTimeline = new Map(
		(after.timeline || []).map((item) => [item.item_id, item]),
	);

	for (const [itemId, item] of afterTimeline.entries()) {
		if (!beforeTimeline.has(itemId)) {
			diffs.push({
				path: `timeline.${itemId}`,
				before: null,
				after: item,
				changeKind: "added",
			});
			continue;
		}
		const previous = beforeTimeline.get(itemId);
		if (JSON.stringify(previous) !== JSON.stringify(item)) {
			diffs.push({
				path: `timeline.${itemId}`,
				before: previous,
				after: item,
				changeKind: "updated",
			});
		}
	}
	for (const [itemId, item] of beforeTimeline.entries()) {
		if (!afterTimeline.has(itemId)) {
			diffs.push({
				path: `timeline.${itemId}`,
				before: item,
				after: null,
				changeKind: "removed",
			});
		}
	}

	return diffs;
}

function summarizeRoadmapDiff(diffs) {
	if (!diffs.length) {
		return "No roadmap changes were staged in the draft.";
	}
	return diffs
		.map((diff) => {
			const label =
				diff.changeKind === "added"
					? "Added"
					: diff.changeKind === "removed"
						? "Removed"
						: "Updated";
			return `${label} ${diff.path}`;
		})
		.join(" · ");
}

function selectLatestArtifact(artifacts, predicate) {
	return (
		[...artifacts]
			.filter(predicate)
			.sort(
				(left, right) => (right.createdAt ?? 0) - (left.createdAt ?? 0),
			)[0] || null
	);
}

function flattenJsonl(text) {
	const rows = [];
	for (const [index, line] of text.split(/\r?\n/).entries()) {
		const trimmed = line.trim();
		if (!trimmed) {
			continue;
		}
		try {
			const parsed = JSON.parse(trimmed);
			rows.push({ parsed, line: index + 1 });
		} catch {
			rows.push({ parsed: { raw: trimmed }, line: index + 1 });
		}
	}
	return rows;
}

function normalizeArtifact(raw, sourcePath, recordIndex = 0) {
	const artifact = raw && typeof raw === "object" ? raw : {};
	const createdAt = parseTimestamp(
		artifact.created_at ||
			artifact.generated_at ||
			artifact.reported_at ||
			artifact.timestamp ||
			artifact.updated_at,
	);
	const family = inferFamily(sourcePath);
	return {
		id:
			toText(artifact.artifact_id) ||
			toText(artifact.report_id) ||
			toText(artifact.plan_id) ||
			`${sourcePath}#${recordIndex}`,
		sourcePath,
		family,
		stage: inferStage(artifact),
		severity: inferSeverity(artifact),
		title: deriveTitle(artifact, sourcePath),
		summary: deriveSummary(artifact),
		status: deriveStatus(artifact),
		createdAt,
		createdAtLabel: createdAt
			? new Date(createdAt).toLocaleString()
			: "unknown time",
		schemaVersion: toText(artifact.schema_version) || "unknown",
		waveId: toText(artifact.wave_id),
		planId: toText(artifact.plan_id),
		artifactKind: toText(artifact.kind),
		tags: deriveTags(artifact),
		raw: artifact,
	};
}

async function fetchJsonText(url, signal) {
	const response = await fetch(urlWithBust(url), {
		signal,
		cache: "no-store",
	});
	if (!response.ok) {
		throw new Error(`Failed to load ${url}: ${response.status}`);
	}
	return response.text();
}

async function loadArtifactFile(url, signal) {
	const text = await fetchJsonText(url, signal);
	if (url.endsWith(".jsonl")) {
		return flattenJsonl(text).map(({ parsed, line }, index) =>
			normalizeArtifact(parsed, `${url}#L${line}`, index),
		);
	}
	try {
		return [normalizeArtifact(JSON.parse(text), url)];
	} catch {
		return [normalizeArtifact({ raw: text }, url)];
	}
}

async function walkDirectory(url, rootUrl, signal, seenDirs, collected) {
	if (signal.aborted || seenDirs.has(url)) {
		return;
	}
	seenDirs.add(url);
	const html = await fetchJsonText(url, signal);
	const parsed = new DOMParser().parseFromString(html, "text/html");
	const anchors = Array.from(parsed.querySelectorAll("a[href]"));
	for (const anchor of anchors) {
		const href = anchor.getAttribute("href");
		if (!href || href === "../" || href.startsWith("?")) {
			continue;
		}
		const nextUrl = new URL(href, url);
		if (!nextUrl.href.startsWith(rootUrl)) {
			continue;
		}
		if (href.endsWith("/")) {
			await walkDirectory(nextUrl.href, rootUrl, signal, seenDirs, collected);
			continue;
		}
		if (!/\.(json|jsonl)$/i.test(href)) {
			continue;
		}
		try {
			const artifacts = await loadArtifactFile(nextUrl.href, signal);
			for (const artifact of artifacts) {
				collected.push(artifact);
				if (collected.length >= MAX_ARTIFACTS) {
					return;
				}
			}
		} catch (error) {
			collected.push(
				normalizeArtifact(
					{
						schema_version: "dashboard.load_error",
						kind: "load_error",
						status: "warning",
						summary: error instanceof Error ? error.message : String(error),
					},
					nextUrl.href,
				),
			);
		}
	}
}

async function scanArtifacts(signal) {
	const collected = [];
	const seenDirs = new Set();
	const roots = ROOTS.map((root) => new URL(root, window.location.href).href);
	for (const root of roots) {
		try {
			await walkDirectory(root, root, signal, seenDirs, collected);
		} catch (error) {
			collected.push(
				normalizeArtifact(
					{
						schema_version: "dashboard.root_error",
						kind: "root_error",
						status: "warning",
						summary: error instanceof Error ? error.message : String(error),
					},
					root,
				),
			);
		}
		if (collected.length >= MAX_ARTIFACTS) {
			break;
		}
	}
	return collected;
}

function summarizeArtifacts(artifacts) {
	const sorted = [...artifacts].sort((a, b) => {
		const left = a.createdAt ?? -Infinity;
		const right = b.createdAt ?? -Infinity;
		return right - left;
	});
	const families = new Map();
	const stages = new Map(STAGE_ORDER.map((stage) => [stage, 0]));
	const blockers = [];
	const roadmaps = [];
	const evidence = [];
	const recent = sorted.slice(0, 18);

	for (const artifact of sorted) {
		const family = artifact.family;
		const bucket = families.get(family) || {
			count: 0,
			latest: artifact,
			ok: 0,
			warn: 0,
			danger: 0,
		};
		bucket.count += 1;
		if (
			(artifact.createdAt ?? -Infinity) > (bucket.latest.createdAt ?? -Infinity)
		) {
			bucket.latest = artifact;
		}
		bucket[artifact.severity] += 1;
		families.set(family, bucket);

		stages.set(artifact.stage, (stages.get(artifact.stage) || 0) + 1);

		if (
			artifact.severity === "danger" ||
			/fail|block|repair|open/i.test(`${artifact.status} ${artifact.summary}`)
		) {
			blockers.push(artifact);
		}
		if (family === "roadmaps" || family === "release_gate") {
			roadmaps.push(artifact);
		}
		if (family === "evidence" || family === "reports") {
			evidence.push(artifact);
		}
	}

	return {
		totalArtifacts: sorted.length,
		families,
		stages,
		blockers: blockers.slice(0, 12),
		recent,
		roadmaps: roadmaps.slice(0, 8),
		evidence: evidence.slice(0, 8),
	};
}

const DASHBOARD_DRAFT_KEY = "opencode.ops-dashboard.draft-state";
const OPS_ENDPOINTS = {
	state: "/_ops-dashboard/state",
	draft: "/_ops-dashboard/draft-state",
	publish: "/_ops-dashboard/publish-roadmap",
	answer: "/_ops-dashboard/submit-answer",
};

async function fetchDashboardJson(path, options = {}) {
	const response = await fetch(path, {
		cache: "no-store",
		...options,
		headers: {
			"Content-Type": "application/json",
			...(options.headers || {}),
		},
	});
	if (!response.ok) {
		throw new Error(`Request failed for ${path}: ${response.status}`);
	}
	return response.json();
}

function readLocalDraftFallback() {
	if (typeof window === "undefined") {
		return makeDefaultDraftState();
	}
	let raw = null;
	try {
		raw = window.localStorage?.getItem(DASHBOARD_DRAFT_KEY) || null;
	} catch {
		raw = null;
	}
	if (!raw) {
		return makeDefaultDraftState();
	}
	try {
		return normalizeDraftState(JSON.parse(raw));
	} catch {
		return makeDefaultDraftState();
	}
}

function writeLocalDraftFallback(draftState) {
	if (typeof window === "undefined") {
		return;
	}
	try {
		window.localStorage?.setItem(
			DASHBOARD_DRAFT_KEY,
			JSON.stringify(draftState),
		);
	} catch {
		/* ignore browser storage failures */
	}
}

async function loadDraftState() {
	try {
		const remote = await fetchDashboardJson(OPS_ENDPOINTS.draft);
		editorConnectionStatus = "connected";
		return normalizeDraftState(remote);
	} catch {
		editorConnectionStatus = "local";
		return readLocalDraftFallback();
	}
}

async function saveDraftState(draftState) {
	const normalized = normalizeDraftState(draftState);
	writeLocalDraftFallback(normalized);
	try {
		const remote = await fetchDashboardJson(OPS_ENDPOINTS.draft, {
			method: "PUT",
			body: JSON.stringify(normalized),
		});
		editorConnectionStatus = "connected";
		return normalizeDraftState(remote.draft_state || normalized);
	} catch {
		editorConnectionStatus = "local";
		return normalized;
	}
}

async function publishRoadmapArtifact() {
	const draftState = normalizeDraftState(
		editorState || (await loadDraftState()),
	);
	const remote = await fetchDashboardJson(OPS_ENDPOINTS.publish, {
		method: "POST",
		body: JSON.stringify({ draft_state: draftState }),
	});
	editorConnectionStatus = "connected";
	return remote;
}

async function submitQuestionAnswer(answer) {
	const draftState = normalizeDraftState(
		editorState || (await loadDraftState()),
	);
	const selectedIds = Array.from(editorQuestionSelection);
	const remote = await fetchDashboardJson(OPS_ENDPOINTS.answer, {
		method: "POST",
		body: JSON.stringify({
			question_ids: selectedIds,
			answer,
			draft_state: draftState,
		}),
	});
	editorConnectionStatus = "connected";
	editorQuestionSelection.clear();
	return remote;
}

function clear(node) {
	while (node.firstChild) {
		node.removeChild(node.firstChild);
	}
}

function makeBadge(label, kind = "neutral") {
	const span = document.createElement("span");
	span.className = `badge ${kind}`;
	span.textContent = label;
	return span;
}

function renderKpis(summary) {
	const nodes = [
		{
			label: "Artifacts scanned",
			value: summary.totalArtifacts,
			hint: "Local JSON + JSONL files discovered in the watched trees.",
		},
		{
			label: "Roadmap families",
			value: summary.families.size,
			hint: "Roadmaps, evidence, reports, release gates, and audits.",
		},
		{
			label: "Blockers",
			value: summary.blockers.length,
			hint: "Failures, open issues, or anything with repair wording.",
		},
		{
			label: "Recent artifacts",
			value: summary.recent.length,
			hint: "Latest material surfaced by the live scan.",
		},
		{
			label: "Polling",
			value: `${Math.round(currentIntervalMs / 1000)}s`,
			hint: autoRefreshEnabled
				? "Auto-refresh enabled."
				: "Auto-refresh paused.",
		},
	];

	const grid = $("#kpi-grid");
	clear(grid);
	for (const node of nodes) {
		const card = document.createElement("article");
		card.className = "kpi";
		const label = document.createElement("div");
		label.className = "label";
		label.textContent = node.label;
		const value = document.createElement("div");
		value.className = "value";
		value.textContent = String(node.value);
		const hint = document.createElement("div");
		hint.className = "hint";
		hint.textContent = node.hint;
		card.append(label, value, hint);
		grid.appendChild(card);
	}
}

function renderStages(summary) {
	const track = $("#stage-track");
	clear(track);
	const maximum = Math.max(...Array.from(summary.stages.values()), 1);
	for (const stage of STAGE_ORDER) {
		const count = summary.stages.get(stage) || 0;
		const row = document.createElement("div");
		row.className = "stage-row";

		const name = document.createElement("div");
		name.className = "stage-name";
		name.textContent = stage;

		const bar = document.createElement("div");
		bar.className = "stage-bar";
		const fill = document.createElement("div");
		fill.className = "stage-fill";
		fill.style.width = `${Math.max(4, Math.round((count / maximum) * 100))}%`;
		bar.appendChild(fill);

		const meta = document.createElement("div");
		meta.className = "stage-meta";
		meta.textContent = `${count} artifact${count === 1 ? "" : "s"}`;

		row.append(name, bar, meta);
		track.appendChild(row);
	}
}

function renderArtifactList(node, artifacts, emptyLabel) {
	clear(node);
	if (!artifacts.length) {
		const empty = document.createElement("div");
		empty.className = "empty-state";
		empty.textContent = emptyLabel;
		node.appendChild(empty);
		return;
	}

	for (const artifact of artifacts) {
		const card = document.createElement("article");
		card.className = "artifact";

		const head = document.createElement("div");
		head.className = "artifact-head";

		const titleWrap = document.createElement("div");
		const title = document.createElement("div");
		title.className = "artifact-title";
		title.textContent = artifact.title;
		const subtitle = document.createElement("div");
		subtitle.className = "artifact-subtitle";
		subtitle.textContent = artifact.summary || "No summary available.";
		titleWrap.append(title, subtitle);

		const meta = document.createElement("div");
		meta.className = "artifact-meta";
		meta.appendChild(makeBadge(artifact.family, artifact.severity));
		meta.appendChild(makeBadge(artifact.stage, artifact.severity));
		meta.appendChild(makeBadge(artifact.status));

		head.append(titleWrap, meta);

		const foot = document.createElement("div");
		foot.className = "artifact-foot";
		foot.appendChild(makeBadge(artifact.schemaVersion, "neutral"));
		foot.appendChild(makeBadge(artifact.createdAtLabel, "neutral"));
		if (artifact.waveId) {
			foot.appendChild(makeBadge(`wave:${artifact.waveId}`, "neutral"));
		}
		if (artifact.planId) {
			foot.appendChild(makeBadge(`plan:${artifact.planId}`, "neutral"));
		}
		if (artifact.artifactKind) {
			foot.appendChild(makeBadge(artifact.artifactKind, "neutral"));
		}

		card.append(head, foot);
		node.appendChild(card);
	}
}

function renderFamilies(summary) {
	const grid = $("#family-grid");
	clear(grid);
	for (const [family, bucket] of summary.families.entries()) {
		const row = document.createElement("section");
		row.className = "family-row";

		const name = document.createElement("div");
		name.className = "name";
		const label = document.createElement("span");
		label.textContent = FAMILY_LABELS.get(family) || family;
		const count = document.createElement("span");
		count.className = "badge";
		count.textContent = `${bucket.count}`;
		name.append(label, count);

		const counts = document.createElement("div");
		counts.className = "counts";
		counts.append(
			makeBadge(`${bucket.ok} ok`, "ok"),
			makeBadge(`${bucket.warn} warn`, "warn"),
			makeBadge(`${bucket.danger} danger`, "danger"),
			makeBadge(`latest: ${bucket.latest.title}`),
		);

		row.append(name, counts);
		grid.appendChild(row);
	}
	if (!summary.families.size) {
		const empty = document.createElement("div");
		empty.className = "empty-state";
		empty.textContent = "No artifact families discovered yet.";
		grid.appendChild(empty);
	}
}

function renderPublishedRoadmapPanel(artifact, history = []) {
	const panel = $("#published-roadmap");
	const version = $("#published-version");
	const historyNode = $("#published-history");
	clear(panel);
	clear(historyNode);

	if (!artifact) {
		version.textContent = "No published roadmap yet.";
		panel.appendChild(
			Object.assign(document.createElement("div"), {
				className: "empty-state",
				textContent:
					"Publish a draft roadmap to create the first Opencode roadmap artifact.",
			}),
		);
		return;
	}

	version.textContent = `v${String(artifact.raw.version).padStart(3, "0")} • ${artifact.raw.publication_state}`;

	const snapshot = document.createElement("section");
	snapshot.className = "roadmap-block";

	const title = document.createElement("div");
	title.className = "roadmap-title";
	title.textContent = artifact.raw.title;

	const summary = document.createElement("div");
	summary.className = "roadmap-summary";
	summary.textContent = artifact.raw.summary;

	const meta = document.createElement("div");
	meta.className = "line-chips";
	meta.append(
		makeBadge(`version ${artifact.raw.version}`),
		makeBadge(artifact.raw.status),
		makeBadge(`owner:${artifact.raw.owner || "ops-dashboard"}`),
		makeBadge(`published:${artifact.createdAtLabel}`),
	);

	const timeline = document.createElement("div");
	timeline.className = "roadmap-summary";
	timeline.textContent = `${artifact.raw.timeline?.length || 0} timeline item${(artifact.raw.timeline?.length || 0) === 1 ? "" : "s"}`;

	snapshot.append(title, summary, meta, timeline);
	panel.appendChild(snapshot);

	if (!history.length) {
		const empty = document.createElement("div");
		empty.className = "empty-state";
		empty.textContent =
			"Published history will appear here after the next publish.";
		historyNode.appendChild(empty);
		return;
	}

	for (const entry of history.slice().reverse()) {
		const row = document.createElement("div");
		row.className = "history-card";
		const head = document.createElement("div");
		head.className = "history-title";
		head.textContent = `v${String(entry.version).padStart(3, "0")} • ${entry.path}`;
		const body = document.createElement("div");
		body.className = "history-body";
		body.textContent = entry.path;
		row.append(head, body);
		historyNode.appendChild(row);
	}
}

function renderDraftTimelineItem(item, _index) {
	const card = document.createElement("section");
	card.className = "timeline-item";
	card.dataset.itemId = item.item_id;

	const head = document.createElement("div");
	head.className = "timeline-head";

	const title = document.createElement("div");
	title.className = "timeline-title";
	title.contentEditable = "true";
	title.spellcheck = false;
	title.textContent = item.title;
	title.addEventListener("input", () => {
		item.title = title.textContent.trim();
		queueDraftAutosave();
	});

	const removeButton = document.createElement("button");
	removeButton.type = "button";
	removeButton.className = "timeline-pill";
	removeButton.textContent = "Remove";
	removeButton.addEventListener("click", () => {
		editorState.roadmap.timeline = editorState.roadmap.timeline.filter(
			(entry) => entry.item_id !== item.item_id,
		);
		renderDraftEditorPanel();
		queueDraftAutosave();
	});

	head.append(title, removeButton);

	const metaGrid = document.createElement("div");
	metaGrid.className = "timeline-meta-grid";

	const statusField = document.createElement("label");
	statusField.className = "draft-field";
	const statusLabel = document.createElement("span");
	statusLabel.textContent = "Status";
	const statusInput = document.createElement("input");
	statusInput.value = item.status;
	statusInput.addEventListener("input", () => {
		item.status = statusInput.value.trim();
		queueDraftAutosave();
	});
	statusField.append(statusLabel, statusInput);

	const ownerField = document.createElement("label");
	ownerField.className = "draft-field";
	const ownerLabel = document.createElement("span");
	ownerLabel.textContent = "Owner";
	const ownerInput = document.createElement("input");
	ownerInput.value = item.owner;
	ownerInput.addEventListener("input", () => {
		item.owner = ownerInput.value.trim();
		queueDraftAutosave();
	});
	ownerField.append(ownerLabel, ownerInput);

	const dueField = document.createElement("label");
	dueField.className = "draft-field";
	const dueLabel = document.createElement("span");
	dueLabel.textContent = "Due";
	const dueInput = document.createElement("input");
	dueInput.value = item.due;
	dueInput.addEventListener("input", () => {
		item.due = dueInput.value.trim();
		queueDraftAutosave();
	});
	dueField.append(dueLabel, dueInput);

	metaGrid.append(statusField, ownerField, dueField);

	const detailsField = document.createElement("label");
	detailsField.className = "draft-field";
	const detailsLabel = document.createElement("span");
	detailsLabel.textContent = "Details";
	const detailsInput = document.createElement("div");
	detailsInput.contentEditable = "true";
	detailsInput.spellcheck = false;
	detailsInput.textContent = item.details;
	detailsInput.addEventListener("input", () => {
		item.details = detailsInput.textContent.trim();
		queueDraftAutosave();
	});
	detailsField.append(detailsLabel, detailsInput);

	const contextsField = document.createElement("label");
	contextsField.className = "draft-field";
	const contextsLabel = document.createElement("span");
	contextsLabel.textContent = "Impacted contexts";
	const contextsInput = document.createElement("textarea");
	contextsInput.rows = 2;
	contextsInput.value = item.impacted_contexts.join(", ");
	contextsInput.addEventListener("input", () => {
		item.impacted_contexts = contextsInput.value
			.split(",")
			.map((entry) => entry.trim())
			.filter(Boolean);
		queueDraftAutosave();
	});
	contextsField.append(contextsLabel, contextsInput);

	const notesField = document.createElement("label");
	notesField.className = "draft-field";
	const notesLabel = document.createElement("span");
	notesLabel.textContent = "Notes";
	const notesInput = document.createElement("textarea");
	notesInput.rows = 2;
	notesInput.value = item.notes;
	notesInput.addEventListener("input", () => {
		item.notes = notesInput.value.trim();
		queueDraftAutosave();
	});
	notesField.append(notesLabel, notesInput);

	card.append(head, metaGrid, detailsField, contextsField, notesField);
	return card;
}

function renderDraftEditorPanel() {
	const node = $("#draft-editor");
	clear(node);
	if (!editorState) {
		const empty = document.createElement("div");
		empty.className = "empty-state";
		empty.textContent = "Load a draft to begin editing.";
		node.appendChild(empty);
		return;
	}

	const roadmap = editorState.roadmap;

	const titleGrid = document.createElement("div");
	titleGrid.className = "draft-field-grid";

	const titleField = document.createElement("label");
	titleField.className = "draft-field";
	const titleLabel = document.createElement("span");
	titleLabel.textContent = "Roadmap title";
	const titleInput = document.createElement("div");
	titleInput.contentEditable = "true";
	titleInput.spellcheck = false;
	titleInput.textContent = roadmap.title;
	titleInput.addEventListener("input", () => {
		roadmap.title = titleInput.textContent.trim();
		queueDraftAutosave();
	});
	titleField.append(titleLabel, titleInput);

	const statusField = document.createElement("label");
	statusField.className = "draft-field";
	const statusLabel = document.createElement("span");
	statusLabel.textContent = "Status";
	const statusInput = document.createElement("input");
	statusInput.value = roadmap.status;
	statusInput.addEventListener("input", () => {
		roadmap.status = statusInput.value.trim();
		queueDraftAutosave();
	});
	statusField.append(statusLabel, statusInput);

	const summaryField = document.createElement("label");
	summaryField.className = "draft-field";
	summaryField.style.gridColumn = "1 / -1";
	const summaryLabel = document.createElement("span");
	summaryLabel.textContent = "Roadmap summary";
	const summaryInput = document.createElement("div");
	summaryInput.contentEditable = "true";
	summaryInput.spellcheck = false;
	summaryInput.textContent = roadmap.summary;
	summaryInput.addEventListener("input", () => {
		roadmap.summary = summaryInput.textContent.trim();
		queueDraftAutosave();
	});
	summaryField.append(summaryLabel, summaryInput);

	titleGrid.append(titleField, statusField, summaryField);
	node.appendChild(titleGrid);

	const timelineHeading = document.createElement("div");
	timelineHeading.className = "card-heading";
	timelineHeading.style.marginTop = "0.25rem";
	const timelineHeadingCopy = document.createElement("div");
	const timelineLabel = document.createElement("p");
	timelineLabel.className = "section-label";
	timelineLabel.textContent = "Timeline";
	const timelineTitle = document.createElement("h2");
	timelineTitle.textContent = "Editable milestones and impacted contexts";
	timelineHeadingCopy.append(timelineLabel, timelineTitle);
	const timelineControls = document.createElement("div");
	timelineControls.className = "editor-actions";
	const addButton = document.createElement("button");
	addButton.type = "button";
	addButton.textContent = "Add timeline item";
	addButton.addEventListener("click", () => {
		editorState.roadmap.timeline.push({
			item_id: `item-${Date.now()}`,
			title: "New timeline item",
			status: "planned",
			due: "",
			owner: "ops-dashboard",
			details: "",
			impacted_contexts: [],
			notes: "",
		});
		renderDraftEditorPanel();
		queueDraftAutosave();
	});
	timelineControls.append(addButton);
	timelineHeading.append(timelineHeadingCopy, timelineControls);
	node.appendChild(timelineHeading);

	const timelineList = document.createElement("div");
	timelineList.className = "timeline-list";
	for (const [index, item] of roadmap.timeline.entries()) {
		timelineList.appendChild(renderDraftTimelineItem(item, index));
	}
	node.appendChild(timelineList);
}

function renderRoadmapDiffPanel() {
	const before = editorPublishedRoadmap ? editorPublishedRoadmap.raw : null;
	const after = editorState ? editorState.roadmap : null;
	const diffs = buildRoadmapDiff(
		before
			? {
					title: before.title,
					summary: before.summary,
					status: before.status,
					owner: before.owner,
					version_hint: before.version,
					timeline: before.timeline || [],
				}
			: makeDefaultDraftState().roadmap,
		after || makeDefaultDraftState().roadmap,
	);
	const node = $("#roadmap-diff");
	const summary = $("#delta-summary");
	const version = $("#delta-version");
	clear(node);
	if (!diffs.length) {
		node.appendChild(
			Object.assign(document.createElement("div"), {
				className: "empty-state",
				textContent: "The draft matches the latest published roadmap.",
			}),
		);
	} else {
		for (const diff of diffs) {
			const card = document.createElement("section");
			card.className = `diff-block ${diff.changeKind}`;
			const title = document.createElement("div");
			title.className = "diff-title";
			title.textContent = `${diff.changeKind.toUpperCase()} ${diff.path}`;
			const body = document.createElement("div");
			body.className = "diff-body";
			body.textContent =
				diff.changeKind === "added"
					? "New value staged in the draft."
					: diff.changeKind === "removed"
						? "Value removed from the draft."
						: "Value changed between the published snapshot and the draft.";
			card.append(title, body);
			if (diff.after && typeof diff.after === "object") {
				const chips = document.createElement("div");
				chips.className = "line-chips";
				chips.append(
					makeBadge(`after: ${toText(diff.after.title) || diff.path}`),
					makeBadge(`status: ${toText(diff.after.status) || "n/a"}`),
				);
				card.appendChild(chips);
			}
			node.appendChild(card);
		}
	}
	summary.textContent = summarizeRoadmapDiff(diffs);
	version.textContent = editorPublishedRoadmap
		? `v${String(editorPublishedRoadmap.raw.version).padStart(3, "0")} → draft`
		: "Draft only";
	if (editorLatestDelta) {
		$("#delta-summary").textContent =
			`${summary.textContent} Latest publish: ${editorLatestDelta.raw.human_summary || editorLatestDelta.summary || "No summary."}`;
		$("#delta-version").textContent =
			`delta v${String(editorLatestDelta.raw.to_version).padStart(3, "0")}`;
	}
}

function renderQuestionPanel() {
	const node = $("#question-list");
	const archiveNode = $("#question-archive");
	const reportNode = $("#question-report");
	const countNode = $("#question-count");
	clear(node);
	clear(archiveNode);
	clear(reportNode);

	if (!editorState) {
		node.appendChild(
			Object.assign(document.createElement("div"), {
				className: "empty-state",
				textContent: "Reconnect the storage bridge to load the question inbox.",
			}),
		);
		countNode.textContent = "0 pending";
		return;
	}

	const pending = editorState.questions.pending;
	countNode.textContent = `${pending.length} pending`;

	if (!pending.length) {
		node.appendChild(
			Object.assign(document.createElement("div"), {
				className: "empty-state",
				textContent:
					"No pending questions. Add one above or wait for agents to submit.",
			}),
		);
	} else {
		for (const item of pending) {
			const card = document.createElement("section");
			card.className = "question-card";
			if (editorQuestionSelection.has(item.question_id)) {
				card.classList.add("selected");
			}

			const head = document.createElement("div");
			head.className = "question-head";

			const copy = document.createElement("div");
			const title = document.createElement("div");
			title.className = "question-title";
			title.textContent = item.question;
			const body = document.createElement("div");
			body.className = "question-body";
			body.textContent = `Category: ${item.category} • Contexts: ${item.linked_contexts.join(", ") || "none"}`;
			copy.append(title, body);

			const controls = document.createElement("label");
			controls.className = "question-controls";
			const checkbox = document.createElement("input");
			checkbox.type = "checkbox";
			checkbox.checked = editorQuestionSelection.has(item.question_id);
			checkbox.addEventListener("change", () => {
				if (checkbox.checked) {
					editorQuestionSelection.add(item.question_id);
				} else {
					editorQuestionSelection.delete(item.question_id);
				}
				renderQuestionPanel();
			});
			const label = document.createElement("span");
			label.textContent = "Select";
			controls.append(checkbox, label);

			head.append(copy, controls);
			card.append(head);
			node.appendChild(card);
		}
	}

	if (!editorState.questions.archived.length) {
		archiveNode.appendChild(
			Object.assign(document.createElement("div"), {
				className: "empty-state",
				textContent: "Answered questions will move into the archive here.",
			}),
		);
	} else {
		for (const item of editorState.questions.archived.slice(-6).reverse()) {
			const card = document.createElement("section");
			card.className = "history-card";
			const title = document.createElement("div");
			title.className = "history-title";
			title.textContent = item.question;
			const body = document.createElement("div");
			body.className = "history-body";
			body.textContent = `Answered: ${item.answer || "n/a"}`;
			card.append(title, body);
			archiveNode.appendChild(card);
		}
	}

	if (!editorLatestQuestionReport) {
		reportNode.appendChild(
			Object.assign(document.createElement("div"), {
				className: "empty-state",
				textContent: "Submitted answers will appear here as a compact report.",
			}),
		);
		return;
	}

	const report = document.createElement("section");
	report.className = "report-card";
	const title = document.createElement("div");
	title.className = "question-title";
	title.textContent = editorLatestQuestionReport.summary;
	const body = document.createElement("div");
	body.className = "report-body";
	body.textContent = editorLatestQuestionReport.selected_questions
		.map((item) => item.question)
		.join(" · ");
	report.append(title, body);
	reportNode.appendChild(report);
}

function renderSyncLog(lines) {
	const log = $("#sync-log");
	clear(log);
	for (const line of lines) {
		const row = document.createElement("div");
		row.className = "artifact";
		row.textContent = line;
		log.appendChild(row);
	}
}

function renderEditorPanels({ mountDraft = false } = {}) {
	const latestPublished = editorPublishedRoadmap;
	const history = cachedArtifacts
		.filter(
			(artifact) =>
				artifact.schemaVersion === "opencode.dashboard.roadmap.v1" &&
				artifact.sourcePath.includes(
					"docs/json/opencode/ops-dashboard/published/",
				),
		)
		.map((artifact) => ({
			version: Number(artifact.raw.version) || 0,
			path: artifact.sourcePath.replace(/^https?:\/\/[^/]+\//, ""),
		}))
		.sort((left, right) => left.version - right.version);

	renderPublishedRoadmapPanel(latestPublished, history);
	renderRoadmapDiffPanel();
	renderQuestionPanel();
	$("#draft-status").textContent =
		editorConnectionStatus === "connected"
			? "Draft is connected to the OpenCode storage bridge and autosaves into hidden draft state."
			: "Draft is local only until you reconnect the storage bridge.";
	if (mountDraft) {
		renderDraftEditorPanel();
	}
}

function updateDraftStatus(message) {
	$("#draft-status").textContent = message;
}

function queueDraftAutosave() {
	if (editorSaveTimer) {
		clearTimeout(editorSaveTimer);
	}
	updateDraftStatus("Saving draft...");
	editorSaveTimer = setTimeout(async () => {
		try {
			editorState.updated_at = nowIso();
			editorState = await saveDraftState(editorState);
			updateDraftStatus(
				editorConnectionStatus === "connected"
					? `Draft saved to the OpenCode storage bridge at ${new Date().toLocaleTimeString()}.`
					: `Draft saved locally at ${new Date().toLocaleTimeString()}.`,
			);
		} catch (error) {
			updateDraftStatus(error instanceof Error ? error.message : String(error));
		}
	}, 500);
}

async function initializeEditor() {
	try {
		editorState = await loadDraftState();
		if (!editorState) {
			editorState = readLocalDraftFallback();
			writeLocalDraftFallback(editorState);
		}
		editorQuestionSelection = new Set();
		editorLatestDelta = null;
		editorLatestQuestionReport = null;
		renderEditorPanels({ mountDraft: true });
		updateDraftStatus(
			editorConnectionStatus === "connected"
				? "Draft loaded from the OpenCode storage bridge."
				: "Draft loaded from local fallback state until the storage bridge responds.",
		);
	} catch (error) {
		editorState = makeDefaultDraftState();
		writeLocalDraftFallback(editorState);
		renderEditorPanels({ mountDraft: true });
		updateDraftStatus(error instanceof Error ? error.message : String(error));
	}
}

function updateCounts(summary) {
	$("#artifact-count").textContent =
		`${summary.totalArtifacts} artifacts scanned`;
	$("#recent-count").textContent = `${summary.recent.length} recent`;
	$("#blocker-count").textContent = `${summary.blockers.length} blockers`;
	$("#family-count").textContent = `${summary.families.size} families`;
}

function render(summary, logLines) {
	renderKpis(summary);
	renderStages(summary);
	renderArtifactList(
		$("#recent-feed"),
		summary.recent,
		"No artifacts found in the watched trees.",
	);
	renderArtifactList(
		$("#blocker-feed"),
		summary.blockers,
		"No blockers or failures were detected in the latest scan.",
	);
	renderFamilies(summary);
	renderSyncLog(logLines);
	updateCounts(summary);
}

let currentIntervalMs = REFRESH_DEFAULT_MS;
let autoRefreshEnabled = true;

async function runRefresh(reason = "manual") {
	if (activeController) {
		activeController.abort();
	}
	activeController = new AbortController();
	const signal = activeController.signal;
	const serial = ++refreshSerial;
	const logLines = [
		`[${nowIso()}] ${reason} refresh started`,
		`[${nowIso()}] polling ${ROOTS.length} local artifact roots`,
	];
	const status = $("#sync-status");
	const statusCopy = $("#sync-copy");

	status.dataset.state = "syncing";
	status.textContent = "Syncing";
	statusCopy.textContent = "Scanning local JSON artifacts...";

	const started = performance.now();

	try {
		const artifacts = await scanArtifacts(signal);
		if (serial !== refreshSerial || signal.aborted) {
			return;
		}
		cachedArtifacts = artifacts;
		const summary = summarizeArtifacts(artifacts);
		editorPublishedRoadmap = selectLatestArtifact(
			artifacts,
			(artifact) =>
				artifact.schemaVersion === "opencode.dashboard.roadmap.v1" &&
				artifact.sourcePath.includes(
					"docs/json/opencode/ops-dashboard/published/",
				),
		);
		editorLatestDelta = selectLatestArtifact(
			artifacts,
			(artifact) =>
				artifact.schemaVersion === "opencode.dashboard.roadmap_delta.v1",
		);
		editorLatestQuestionReport = selectLatestArtifact(
			artifacts,
			(artifact) =>
				artifact.schemaVersion === "opencode.dashboard.question_report.v1",
		);
		render(summary, logLines);
		if (editorState) {
			renderEditorPanels();
		}
		const elapsed = Math.round(performance.now() - started);
		status.dataset.state = "ok";
		status.textContent = "Live";
		statusCopy.textContent = `Last sync ${new Date().toLocaleTimeString()} • ${elapsed} ms • ${artifacts.length} artifacts.`;
	} catch (error) {
		if (signal.aborted) {
			return;
		}
		status.dataset.state = "error";
		status.textContent = "Error";
		statusCopy.textContent =
			error instanceof Error ? error.message : String(error);
		render(summarizeArtifacts(cachedArtifacts), [
			`[${nowIso()}] refresh failed`,
			error instanceof Error ? error.message : String(error),
		]);
	}
}

function scheduleRefresh() {
	if (refreshTimer) {
		clearInterval(refreshTimer);
	}
	refreshTimer = setInterval(() => {
		if (autoRefreshEnabled) {
			runRefresh("timer");
		}
	}, currentIntervalMs);
}

function initControls() {
	$("#refresh-button").addEventListener("click", () => runRefresh("manual"));
	$("#auto-refresh-toggle").addEventListener("change", (event) => {
		autoRefreshEnabled = event.target.checked;
		const status = $("#sync-status");
		status.textContent = autoRefreshEnabled ? "Live" : "Paused";
		status.dataset.state = autoRefreshEnabled ? "ok" : "idle";
		$("#sync-copy").textContent = autoRefreshEnabled
			? "Auto-refresh resumed."
			: "Auto-refresh paused.";
	});
	$("#refresh-interval").addEventListener("change", (event) => {
		currentIntervalMs = Number(event.target.value) || REFRESH_DEFAULT_MS;
		scheduleRefresh();
		runRefresh("interval change");
	});
	$("#reconnect-storage-button").addEventListener("click", async () => {
		try {
			await initializeEditor();
			renderEditorPanels({ mountDraft: true });
			updateDraftStatus(
				"Connected to the OpenCode storage bridge and reloaded the draft state.",
			);
		} catch (error) {
			updateDraftStatus(error instanceof Error ? error.message : String(error));
		}
	});
	$("#save-draft-button").addEventListener("click", async () => {
		try {
			editorState.updated_at = nowIso();
			editorState = await saveDraftState(editorState);
			renderEditorPanels();
			updateDraftStatus("Draft saved.");
		} catch (error) {
			updateDraftStatus(error instanceof Error ? error.message : String(error));
		}
	});
	$("#publish-roadmap-button").addEventListener("click", async () => {
		try {
			const result = await publishRoadmapArtifact();
			editorLatestDelta = result.delta;
			renderEditorPanels();
			runRefresh("publish");
			updateDraftStatus(
				`Published roadmap v${String(result.nextVersion).padStart(3, "0")} and wrote the transition delta.`,
			);
		} catch (error) {
			updateDraftStatus(error instanceof Error ? error.message : String(error));
		}
	});
	$("#add-question-button").addEventListener("click", async () => {
		if (!editorState) {
			return;
		}
		const category = toText($("#question-category").value) || "question";
		const question = toText($("#question-text").value);
		if (!question) {
			updateDraftStatus("Write a question or comment before adding it.");
			return;
		}
		const linkedContexts = toText($("#question-contexts").value)
			.split(",")
			.map((entry) => entry.trim())
			.filter(Boolean);
		editorState.questions.pending.push({
			question_id: `question-${Date.now()}`,
			category,
			question,
			linked_contexts: linkedContexts,
			status: "pending",
			created_at: nowIso(),
		});
		$("#question-text").value = "";
		$("#question-contexts").value = "";
		editorQuestionSelection.clear();
		await saveDraftState(editorState);
		renderQuestionPanel();
		updateDraftStatus("Question added to the local inbox.");
	});
	$("#submit-answer-button").addEventListener("click", async () => {
		try {
			const answer = toText($("#question-answer").value);
			if (!answer) {
				updateDraftStatus("Write an answer before submitting.");
				return;
			}
			const result = await submitQuestionAnswer(answer);
			editorState = result.draftState;
			editorLatestQuestionReport = result.report;
			$("#question-answer").value = "";
			renderQuestionPanel();
			renderDraftEditorPanel();
			updateDraftStatus(
				`Submitted ${result.report.selection_count} question${result.report.selection_count === 1 ? "" : "s"} to the archive.`,
			);
			runRefresh("question submit");
		} catch (error) {
			updateDraftStatus(error instanceof Error ? error.message : String(error));
		}
	});
	$("#clear-selection-button").addEventListener("click", () => {
		editorQuestionSelection.clear();
		renderQuestionPanel();
		updateDraftStatus("Cleared question selection.");
	});
}

async function bootstrap() {
	initControls();
	await initializeEditor();
	scheduleRefresh();
	runRefresh("startup");
}

if (typeof document !== "undefined") {
	document.addEventListener("DOMContentLoaded", () => {
		void bootstrap();
	});
}

export {
	buildRoadmapDiff,
	cachedArtifacts,
	deriveSummary,
	deriveTitle,
	flattenJsonl,
	inferFamily,
	inferStage,
	makeDefaultDraftState,
	normalizeArtifact,
	normalizeDraftState,
	parseTimestamp,
	summarizeArtifacts,
	summarizeRoadmapDiff,
};
