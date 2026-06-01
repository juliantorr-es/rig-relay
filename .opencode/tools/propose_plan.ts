import { tool } from "@opencode-ai/plugin"
import {
  buildPlanRecord,
  createPlanId,
  resolveRepoRoot,
  writePlanRecord,
} from "./opencode_plan_core.mjs"

const waveSchema = tool.schema.object({
  wave_id: tool.schema.string(),
  name: tool.schema.string(),
  purpose: tool.schema.string(),
  parallelism: tool.schema.enum(["serial", "parallel"]),
  target_agents: tool.schema.array(tool.schema.string()).default([]),
  exit_criteria: tool.schema.array(tool.schema.string()).default([]),
  notes: tool.schema.string().default(""),
})

const riskSchema = tool.schema.object({
  risk: tool.schema.string(),
  impact: tool.schema.string(),
  mitigation: tool.schema.string(),
})

const planInputSchema = {
  title: tool.schema.string(),
  objective: tool.schema.string(),
  summary: tool.schema.string(),
  assumptions: tool.schema.array(tool.schema.string()).default([]),
  constraints: tool.schema.array(tool.schema.string()).default([]),
  execution_waves: tool.schema.array(waveSchema).default([]),
  acceptance_criteria: tool.schema.array(tool.schema.string()).default([]),
  risks: tool.schema.array(riskSchema).default([]),
  open_questions: tool.schema.array(tool.schema.string()).default([]),
  revision_notes: tool.schema.array(tool.schema.string()).default([]),
}

export default tool({
  description:
    "Write a canonical OpenCode plan artifact under docs/json/opencode/plans and return the saved plan plus its comment ledger path.",
  args: planInputSchema,
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const planId = createPlanId({ title: args.title, revision: 1 })
    const planRecord = buildPlanRecord({
      repoRoot,
      planId,
      revision: 1,
      title: args.title,
      objective: args.objective,
      summary: args.summary,
      assumptions: args.assumptions,
      constraints: args.constraints,
      executionWaves: args.execution_waves,
      acceptanceCriteria: args.acceptance_criteria,
      risks: args.risks,
      openQuestions: args.open_questions,
      revisionNotes: args.revision_notes,
      parentPlanId: null,
      parentPlanPath: null,
    })
    const { filePath } = writePlanRecord(repoRoot, planRecord)

    return {
      title: `propose_plan: ${planRecord.plan_id}`,
      output: JSON.stringify(
        {
          plan_path: planRecord.canonical_path,
          comment_ledger_path: planRecord.comment_ledger_path,
          plan: planRecord,
          saved_to: filePath,
        },
        null,
        2,
      ),
    }
  },
})

