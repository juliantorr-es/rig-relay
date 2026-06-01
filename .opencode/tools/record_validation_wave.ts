import { tool } from "@opencode-ai/plugin"
import {
  buildValidationArtifact,
  readPlan,
  resolveRepoRoot,
} from "./opencode_wave_core.mjs"

export default tool({
  description:
    "Record a validation wave artifact for a specific OpenCode plan version. The validator writes pass/fail status, test commands, and missing evidence into a canonical JSON artifact.",
  args: {
    plan_id: tool.schema.string(),
    wave_id: tool.schema.string(),
    validator_name: tool.schema.string(),
    commands_run: tool.schema.array(tool.schema.string()).default([]),
    pass: tool.schema.boolean(),
    tested_boundary: tool.schema.string(),
    failed_seams: tool.schema.array(tool.schema.string()).default([]),
    missing_evidence: tool.schema.array(tool.schema.string()).default([]),
    recommendations: tool.schema.array(tool.schema.string()).default([]),
  },
  async execute(args, context) {
    const repoRoot = resolveRepoRoot(context.worktree)
    const { plan } = readPlan(repoRoot, args.plan_id)
    const { filePath, artifact } = buildValidationArtifact({
      repoRoot,
      plan,
      validatorName: args.validator_name,
      waveId: args.wave_id,
      commandsRun: args.commands_run,
      pass: args.pass,
      testedBoundary: args.tested_boundary,
      failedSeams: args.failed_seams,
      missingEvidence: args.missing_evidence,
      recommendations: args.recommendations,
    })

    return {
      title: `record_validation_wave: ${artifact.artifact_id}`,
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

