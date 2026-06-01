import { tool } from "@opencode-ai/plugin"
import {
  buildPublishedCheckpointReport,
  findPublicationArtifactByReceipt,
  resolveRepoRoot,
} from "./opencode_checkpoint_publication_core.mjs"

export default tool({
  description:
    "Synthesize the final published-checkpoint report from the publication artifact, cumulative checkpoint line, and wave artifacts.",
  args: {
    publication_artifact_sha256: tool.schema.string(),
    report_summary: tool.schema.string(),
    next_steps: tool.schema.array(tool.schema.string()).default([]),
    blocked_seams: tool.schema.array(tool.schema.string()).default([]),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const publicationArtifactEntry = findPublicationArtifactByReceipt(
      repoRoot,
      args.publication_artifact_sha256,
    )
    if (!publicationArtifactEntry) {
      throw new Error(`No checkpoint publication artifact matches receipt ${args.publication_artifact_sha256}`)
    }
    const { filePath, artifact, report_receipt_sha256 } = buildPublishedCheckpointReport({
      repoRoot,
      publicationArtifactEntry,
      reportSummary: args.report_summary,
      nextSteps: args.next_steps,
      blockedSeams: args.blocked_seams,
    })

    return {
      title: `generate_published_checkpoint_report: ${artifact.artifact_id}`,
      output: JSON.stringify(
        {
          report_path: filePath,
          report_receipt_sha256,
          report: artifact,
        },
        null,
        2,
      ),
    }
  },
})
