import assert from "node:assert/strict";
import test from "node:test";

import {
	buildRoadmapDiff,
	makeDefaultDraftState,
	normalizeArtifact,
	normalizeDraftState,
	summarizeArtifacts,
	summarizeRoadmapDiff,
} from "../docs/ops-dashboard/dashboard.mjs";

test("dashboard summarizer groups families and lifecycle stages", () => {
	const artifacts = [
		normalizeArtifact(
			{
				schema_version: "opencode.plan.v1",
				artifact_id: "plan-1",
				created_at: "2026-05-28T12:00:00Z",
				title: "Roadmap plan",
				summary: "Initial plan for the ops dashboard.",
			},
			"docs/json/roadmaps/plan.json",
		),
		normalizeArtifact(
			{
				schema_version: "opencode.execution_artifact.v1",
				artifact_id: "exec-1",
				created_at: "2026-05-28T12:01:00Z",
				title: "Executor wave",
				summary: "Implemented the dashboard scaffold.",
			},
			"docs/json/evidence/execution.json",
		),
		normalizeArtifact(
			{
				schema_version: "opencode.failure_inspection.v1",
				artifact_id: "failure-1",
				created_at: "2026-05-28T12:02:00Z",
				title: "Failure inspection",
				summary: "AssertionError: boom",
				status: "failed",
			},
			"docs/json/audits/failure.json",
		),
	];

	const summary = summarizeArtifacts(artifacts);

	assert.equal(summary.totalArtifacts, 3);
	assert.equal(summary.families.size, 3);
	assert.equal(summary.stages.get("planning"), 1);
	assert.equal(summary.stages.get("execution"), 1);
	assert.equal(summary.stages.get("reporting"), 1);
	assert.equal(summary.blockers.length, 1);
	assert.equal(summary.recent[0].id, "failure-1");
	assert.equal(summary.recent[1].id, "exec-1");
	assert.equal(summary.recent[2].id, "plan-1");
});

test("dashboard draft normalizer keeps timeline and questions stable", () => {
	const draft = normalizeDraftState({
		draft_id: "draft-1",
		roadmap: {
			title: "Title",
			summary: "Summary",
			status: "draft",
			timeline: [
				{
					item_id: "one",
					title: "One",
					status: "planned",
					details: "Details",
					impacted_contexts: ["docs/json/opencode/one.json"],
				},
			],
		},
		questions: {
			pending: [
				{
					question_id: "q1",
					category: "question",
					question: "What now?",
					linked_contexts: ["docs/json/opencode/one.json"],
					created_at: "2026-05-28T12:00:00Z",
				},
			],
			archived: [],
		},
	});

	assert.equal(draft.schema_version, "opencode.dashboard.draft_state.v1");
	assert.equal(draft.roadmap.timeline[0].item_id, "one");
	assert.equal(draft.questions.pending[0].question_id, "q1");
});

test("roadmap diff summarizes changes and timeline updates", () => {
	const before = makeDefaultDraftState().roadmap;
	const after = normalizeDraftState({
		roadmap: {
			title: "Operations Dashboard Roadmap",
			summary:
				"Draft roadmap and timeline for the local dashboard with a change.",
			status: "draft",
			timeline: [
				...before.timeline,
				{
					item_id: "extra",
					title: "Extra",
					status: "planned",
					details: "Added milestone.",
					impacted_contexts: ["docs/json/opencode/extra.json"],
				},
			],
		},
	}).roadmap;

	const diffs = buildRoadmapDiff(before, after);

	assert.ok(diffs.some((entry) => entry.path === "summary"));
	assert.ok(diffs.some((entry) => entry.path === "timeline.extra"));
	assert.match(summarizeRoadmapDiff(diffs), /Updated summary/);
});
