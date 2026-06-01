import { tool } from "@opencode-ai/plugin"
import { commitCheckpoint, repoRelative, resolveRepoRoot } from "./opencode_checkpoint_core.mjs"

export default tool({
  description:
    "Create a git commit from a previously prepared OpenCode checkpoint receipt and write the canonical checkpoint artifact.",
  args: {
    preparation_receipt_sha256: tool.schema.string(),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const result = commitCheckpoint({
      repoRoot,
      preparationReceiptSha256: args.preparation_receipt_sha256,
    })

    return {
      title: `checkpoint: ${result.artifact.artifact_id}`,
      output: JSON.stringify(
        {
          checkpoint_artifact_path: repoRelative(repoRoot, result.filePath),
          saved_to: result.filePath,
          checkpoint_receipt_sha256: result.checkpoint_receipt_sha256,
          artifact: result.artifact,
        },
        null,
        2,
      ),
    }
  },
})
