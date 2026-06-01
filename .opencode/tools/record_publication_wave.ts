import { tool } from "@opencode-ai/plugin"
import {
  buildPublicationArtifact,
  readPlan,
  resolveRepoRoot,
} from "./opencode_wave_core.mjs"

export default tool({
  description:
    "Record a publication wave artifact for a specific OpenCode plan version. The publisher writes the target ref, pushed SHA, verification result, and publication notes into a canonical JSON artifact.",
  args: {
    plan_id: tool.schema.string(),
    wave_id: tool.schema.string(),
    publisher_name: tool.schema.string(),
    target_ref: tool.schema.string(),
    pushed_sha: tool.schema.string(),
    remote_verified: tool.schema.boolean(),
    publication_notes: tool.schema.array(tool.schema.string()).default([]),
    files_published: tool.schema.array(tool.schema.string()).default([]),
    post_push_checks: tool.schema.array(tool.schema.string()).default([]),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const { plan } = readPlan(repoRoot, args.plan_id)
    const { filePath, artifact } = buildPublicationArtifact({
      repoRoot,
      plan,
      publisherName: args.publisher_name,
      waveId: args.wave_id,
      target_ref: args.target_ref,
      pushed_sha: args.pushed_sha,
      remote_verified: args.remote_verified,
      publication_notes: args.publication_notes,
      files_published: args.files_published,
      post_push_checks: args.post_push_checks,
    })

    return {
      title: `record_publication_wave: ${artifact.artifact_id}`,
      output: JSON.stringify(
        {
          artifact_path: filePath,
          artifact,
        },
        null,
        2,
      ),
    }
  },
})

