import { tool } from "@opencode-ai/plugin"
import { prepareCheckpoint, repoRelative, resolveRepoRoot } from "./opencode_checkpoint_core.mjs"

const changeItemSchema = tool.schema.object({
  path: tool.schema.string(),
  change_kind: tool.schema.string(),
  why: tool.schema.string(),
  current_sha256: tool.schema.string().default(""),
})

export default tool({
  description:
    "Stage an executor slice in git and write a canonical OpenCode checkpoint preparation artifact that records what changed and why.",
  args: {
    task_id: tool.schema.string(),
    executor_name: tool.schema.string(),
    checkpoint_summary: tool.schema.string(),
    plan_id: tool.schema.string().default(""),
    wave_id: tool.schema.string().default(""),
    change_items: tool.schema.array(changeItemSchema).default([]),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const result = prepareCheckpoint({
      repoRoot,
      taskId: args.task_id,
      executorName: args.executor_name,
      checkpointSummary: args.checkpoint_summary,
      planId: args.plan_id || null,
      waveId: args.wave_id || null,
      changeItems: args.change_items,
    })

    return {
      title: `prepare_checkpoint: ${result.artifact.artifact_id}`,
      output: JSON.stringify(
        {
          preparation_artifact_path: repoRelative(repoRoot, result.filePath),
          saved_to: result.filePath,
          preparation_receipt_sha256: result.preparation_receipt_sha256,
          artifact: result.artifact,
        },
        null,
        2,
      ),
    }
  },
})
