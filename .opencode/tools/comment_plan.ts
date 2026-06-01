import { tool } from "@opencode-ai/plugin"
import {
  buildCommentRecord,
  loadPlanRecord,
  resolveRepoRoot,
  appendCommentRecord,
} from "./opencode_plan_core.mjs"

export default tool({
  description:
    "Append a structured critic comment to the canonical OpenCode plan's JSONL comment ledger.",
  args: {
    plan_id: tool.schema.string(),
    critic_name: tool.schema.string(),
    severity: tool.schema.enum(["blocking", "major", "minor", "nit"]).default("minor"),
    category: tool.schema.string().default("other"),
    comment: tool.schema.string(),
    suggested_change: tool.schema.string().default(""),
    wave_id: tool.schema.string().default(""),
    references: tool.schema.array(tool.schema.string()).default([]),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const { planRecord } = loadPlanRecord(repoRoot, args.plan_id)
    const commentRecord = buildCommentRecord({
      repoRoot,
      planRecord,
      criticName: args.critic_name,
      waveId: args.wave_id || null,
      severity: args.severity,
      category: args.category,
      comment: args.comment,
      suggestedChange: args.suggested_change,
      references: args.references,
    })
    const ledgerPath = appendCommentRecord(repoRoot, planRecord, commentRecord)

    return {
      title: `comment_plan: ${planRecord.plan_id}`,
      output: JSON.stringify(
        {
          plan_path: planRecord.canonical_path,
          comment_ledger_path: planRecord.comment_ledger_path,
          appended_to: ledgerPath,
          comment: commentRecord,
        },
        null,
        2,
      ),
    }
  },
})
