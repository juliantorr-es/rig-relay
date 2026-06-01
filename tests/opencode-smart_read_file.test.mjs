import test from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  buildPatternPlan,
  inferLanguage,
  readSmartFile,
} from "../.opencode/tools/smart_read_file_core.mjs"

test("smart read planner infers typescript and includes structural outline patterns", () => {
  assert.equal(inferLanguage("src/app.ts"), "typescript")

  const plan = buildPatternPlan("typescript")
  assert.deepEqual(
    plan.map((entry) => entry.label),
    ["functions", "classes", "constants"]
  )
  assert.equal(plan[0].patterns[0], "function $NAME($$$) { $$$ }")
  assert.equal(plan[1].patterns[0], "class $NAME { $$$ }")
  assert.equal(plan[2].patterns[0], "const $NAME = ($$$) => { $$$ }")
})

test("smart read output dedupes ast matches and shows focused excerpts", () => {
  const dir = mkdtempSync(join(tmpdir(), "smart-read-"))
  const filePath = join(dir, "sample.ts")

  try {
    writeFileSync(
      filePath,
      [
        "export function alpha(x: number) {",
        "  return x + 1",
        "}",
        "",
        "export class Beta {",
        "  method() {",
        "    return alpha(2)",
        "  }",
        "}",
        "",
      ].join("\n")
    )

    const result = readSmartFile({ worktree: dir, path: "sample.ts" })

    assert.equal(result.mode, "ast-outline")
    assert.deepEqual(
      result.outline.map((entry) => `${entry.label}:${entry.name}`),
      ["functions:alpha", "classes:Beta"]
    )
    assert.match(result.output, /outline:\n1\. functions alpha \[1-3\]\n2\. classes Beta \[5-9\]/)
    assert.match(result.output, /selected excerpts:/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
