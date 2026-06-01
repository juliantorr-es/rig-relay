import { tool } from "@opencode-ai/plugin"
import {
  pushCheckpoint,
  resolveRepoRoot,
} from "./opencode_checkpoint_publication_core.mjs"

export default tool({
  description:
    "Push an admitted checkpoint exactly once, verify the admitted review evidence, and record a canonical checkpoint publication artifact.",
  args: {
    checkpoint_commit_receipt_sha256: tool.schema.string(),
    candidate_packet_digest: tool.schema.string(),
    admitted_review_artifact_path: tool.schema.string(),
    admitted_review_artifact_sha256: tool.schema.string(),
    publisher_name: tool.schema.string(),
    remote_name: tool.schema.string().default("origin"),
    target_ref: tool.schema.string(),
    publication_notes: tool.schema.array(tool.schema.string()).default([]),
    files_published: tool.schema.array(tool.schema.string()).default([]),
    post_push_checks: tool.schema.array(tool.schema.string()).default([]),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const { filePath, artifact, publication_receipt_sha256 } = pushCheckpoint(repoRoot, args)

    return {
      title: `publish_checkpoint: ${artifact.artifact_id}`,
      output: JSON.stringify(
        {
          publication_artifact_path: filePath,
          publication_receipt_sha256,
          artifact,
        },
        null,
        2,
      ),
    }
  },
})
