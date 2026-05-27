// Inference Studio surface fixture
// Matches M0 LocalProjectInferenceService assistance projection
// Fixture-backed until O0 publishes

window.__P0_FIXTURES__ = window.__P0_FIXTURES__ || {};

window.__P0_FIXTURES__.inference_studio = {
  _fixture_backed: true,
  _fixture_disclaimer: "Fixture data — not live bridge projection. Replace when O0 publishes.",

  local_runtime: {
    available: true,
    configured: true,
    endpoint_sha256: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    runtime_kind: "ollama",
    platform_class: "macOS"
  },

  task_suitability: [
    { task_kind: "PROJECT_SUMMARY", suitable: true, refusal_reason: null, enforcement_class_required: "JSON_OBJECT_FORMATTING_ONLY" },
    { task_kind: "PAGE_SECTION_ORDERING", suitable: true, refusal_reason: null, enforcement_class_required: "JSON_OBJECT_FORMATTING_ONLY" },
    { task_kind: "CAPABILITY_CLASSIFICATION", suitable: false, refusal_reason: "Insufficient model capability for classification tasks", enforcement_class_required: "CLASSIFICATION_REQUIRED" },
    { task_kind: "MISSING_MATERIAL_CHECKLIST", suitable: true, refusal_reason: null, enforcement_class_required: "JSON_OBJECT_FORMATTING_ONLY" }
  ],

  assistance_results: {
    total_results: 5,
    total_executed: 3,
    total_refused: 2,
    drafts_awaiting_review: 3
  },

  drafts: [
    {
      result_id: "result_001",
      task_id: "task_project_summary",
      task_kind: "PROJECT_SUMMARY",
      draft_sha256: "sha256:dddd1111111111111111111111111111111111111111111111111111111111",
      draft_byte_count: 1420,
      output_disposition: "review_required",     // "approval_needed" | "review_required" | "refused"
      requires_approval: true
    },
    {
      result_id: "result_002",
      task_id: "task_section_ordering",
      task_kind: "PAGE_SECTION_ORDERING",
      draft_sha256: "sha256:dddd2222222222222222222222222222222222222222222222222222222222",
      draft_byte_count: 890,
      output_disposition: "review_required",
      requires_approval: true
    },
    {
      result_id: "result_003",
      task_id: "task_missing_material",
      task_kind: "MISSING_MATERIAL_CHECKLIST",
      draft_sha256: "sha256:dddd3333333333333333333333333333333333333333333333333333333333",
      draft_byte_count: 1100,
      output_disposition: "review_required",
      requires_approval: true
    }
  ],

  refusal_explanations: [
    {
      result_id: "result_004",
      task_id: "task_capability_classification_1",
      task_kind: "CAPABILITY_CLASSIFICATION",
      status: "refused",
      refusal_reason: "Insufficient model capability",
      refusal_code: "UNSUPPORTED_CAPABILITY"
    },
    {
      result_id: "result_005",
      task_id: "task_capability_classification_2",
      task_kind: "CAPABILITY_CLASSIFICATION",
      status: "refused",
      refusal_reason: "Insufficient model capability",
      refusal_code: "UNSUPPORTED_CAPABILITY"
    }
  ],

  approval_needed: true,
  next_actions: ["Review 3 draft narratives", "Approve or reject each draft", "Re-run with approved context for final output"],
  content_light: true,
  raw_drafts_exposed: false
};
