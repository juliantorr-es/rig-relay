import { tool } from "@opencode-ai/plugin"
import {
  buildExecutionArtifact,
  readPlan,
  resolveRepoRoot,
} from "./opencode_wave_core.mjs"

const proofArtifactSchema = tool.schema.object({
  label: tool.schema.string(),
  path: tool.schema.string(),
  digest: tool.schema.string(),
})

export default tool({
  description:
    "Record an execution wave artifact for a specific OpenCode plan version. The executor writes the implementation summary, changed files, commands, and proof refs into a canonical JSON artifact.",
  args: {
    plan_id: tool.schema.string(),
    wave_id: tool.schema.string(),
    executor_name: tool.schema.string(),
    task_summary: tool.schema.string(),
    files_changed: tool.schema.array(tool.schema.string()).default([]),
    implementation_notes: tool.schema.array(tool.schema.string()).default([]),
    commands_run: tool.schema.array(tool.schema.string()).default([]),
    proof_artifacts: tool.schema.array(proofArtifactSchema).default([]),
    deferred_seams: tool.schema.array(tool.schema.string()).default([]),
    open_risks: tool.schema.array(tool.schema.string()).default([]),
    boundary_claim: tool.schema.string(),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const { plan } = readPlan(repoRoot, args.plan_id)
    const { filePath, artifact } = buildExecutionArtifact({
      repoRoot,
      plan,
      executorName: args.executor_name,
      waveId: args.wave_id,
      taskSummary: args.task_summary,
      filesChanged: args.files_changed,
      implementationNotes: args.implementation_notes,
      commandsRun: args.commands_run,
      proofArtifacts: args.proof_artifacts,
      deferredSeams: args.deferred_seams,
      openRisks: args.open_risks,
      boundaryClaim: args.boundary_claim,
    })

    return {
      title: `record_execution_wave: ${artifact.artifact_id}`,
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

