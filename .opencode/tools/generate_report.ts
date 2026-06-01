import { tool } from "@opencode-ai/plugin"
import { join } from "node:path"
import {
  collectPlanArtifacts,
  buildSessionReport,
  planRoot,
  readJsonl,
  readPlan,
  resolveRepoRoot,
  summarizeArtifacts,
} from "./opencode_wave_core.mjs"
import {
  collectCheckpointArtifacts,
} from "./opencode_checkpoint_core.mjs"
import {
  collectPublicationArtifacts as collectCheckpointPublicationArtifacts,
} from "./opencode_checkpoint_publication_core.mjs"

function mapArtifacts(entries) {
  return entries.map((entry) => ({
    artifact_id: entry.artifact.artifact_id,
    path: entry.path,
    digest: entry.digest,
  }))
}

export default tool({
  description:
    "Generate a canonical OpenCode session report from the plan, its critic comments, checkpoint receipts, and all wave artifacts. The orchestrator uses the report to tell a coherent story from the underlying artifacts.",
  args: {
    plan_id: tool.schema.string(),
    report_summary: tool.schema.string(),
    next_steps: tool.schema.array(tool.schema.string()).default([]),
    blocked_seams: tool.schema.array(tool.schema.string()).default([]),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const { plan } = readPlan(repoRoot, args.plan_id)
    const planComments = readJsonl(join(planRoot(repoRoot), `${plan.plan_id}.comments.jsonl`))
    const executionArtifacts = collectPlanArtifacts(repoRoot, plan.plan_id, "/execution/")
    const validationArtifacts = collectPlanArtifacts(repoRoot, plan.plan_id, "/validation/")
    const stressArtifacts = collectPlanArtifacts(repoRoot, plan.plan_id, "/stress/")
    const checkpointPreparations = collectCheckpointArtifacts(repoRoot, "preparations", plan.plan_id)
    const checkpointCommits = collectCheckpointArtifacts(repoRoot, "commits", plan.plan_id)
    const checkpointPublicationArtifacts = collectCheckpointPublicationArtifacts(repoRoot)
      .filter((entry) => String(entry.artifact.plan_id ?? "").trim() === String(plan.plan_id ?? "").trim())
    const publicationArtifacts = [
      ...collectPlanArtifacts(repoRoot, plan.plan_id, "/publication/"),
      ...checkpointPublicationArtifacts,
    ]
    const { filePath, artifact } = buildSessionReport({
      repoRoot,
      plan,
      executionArtifacts: mapArtifacts(executionArtifacts),
      validationArtifacts: mapArtifacts(validationArtifacts),
      stressArtifacts: mapArtifacts(stressArtifacts),
      checkpointPreparations: mapArtifacts(checkpointPreparations),
      checkpointCommits: mapArtifacts(checkpointCommits),
      publicationArtifacts: mapArtifacts(publicationArtifacts),
      planComments,
      reportSummary: args.report_summary,
      next_steps: args.next_steps,
      blocked_seams: args.blocked_seams,
    })

    return {
      title: `generate_report: ${artifact.artifact_id}`,
      output: JSON.stringify(
        {
          report_path: filePath,
          report: artifact,
          execution_artifacts: summarizeArtifacts(executionArtifacts),
          validation_artifacts: summarizeArtifacts(validationArtifacts),
          stress_artifacts: summarizeArtifacts(stressArtifacts),
          checkpoint_preparations: summarizeArtifacts(checkpointPreparations),
          checkpoint_commits: summarizeArtifacts(checkpointCommits),
          publication_artifacts: summarizeArtifacts(publicationArtifacts),
          checkpoint_publication_artifacts: summarizeArtifacts(checkpointPublicationArtifacts),
        },
        null,
        2,
      ),
    }
  },
})
