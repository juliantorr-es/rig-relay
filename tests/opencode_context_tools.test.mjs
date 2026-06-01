import test from "node:test"
import assert from "node:assert/strict"
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  editFileWithContext,
  readFileContext,
  searchReplaceFileWithContext,
  writeFileWithContext,
} from "./../.opencode/tools/opencode_context_core.mjs"

test("context-aware file tools seed a bounded five-event ledger", () => {
  const repoRoot = mkdtempSync(join(tmpdir(), "opencode-context-"))

  try {
    mkdirSync(join(repoRoot, "src"), { recursive: true })

    const first = writeFileWithContext({
      repoRoot,
      path: "src/example.ts",
      content: "export const alpha = 1\n",
      summary: "Created example",
      allowOverwriteProtected: true,
    })
    assert.equal(first.context.artifact.kind, "file")
    assert.equal(first.context.artifact.target_path, "src/example.ts")
    assert.equal(first.context.artifact.recent_events.length, 1)

    const second = searchReplaceFileWithContext({
      repoRoot,
      path: "src/example.ts",
      search: "alpha",
      replace: "beta",
      reason: "rename symbol",
      expectedBeforeSha256: first.afterHash,
      allowOverwriteProtected: false,
    })
    assert.equal(second.context.artifact.recent_events.length, 2)
    assert.equal(second.event.operation, "search_replace")

    const third = editFileWithContext({
      repoRoot,
      path: "src/example.ts",
      content: "export const gamma = 3\n",
      instruction: "apply targeted revision",
      expectedBeforeSha256: second.afterHash,
      allowOverwriteProtected: false,
    })
    assert.equal(third.context.artifact.recent_events.length, 3)
    assert.equal(third.event.operation, "edit")

    let previousHash = third.afterHash
    for (const index of [4, 5, 6]) {
      const result = writeFileWithContext({
        repoRoot,
        path: "src/example.ts",
        content: `export const value${index} = ${index}\n`,
        summary: `Mutation ${index}`,
        expectedBeforeSha256: previousHash,
        allowOverwriteProtected: false,
      })
      previousHash = result.afterHash
    }

    const reread = readFileContext({
      repoRoot,
      path: "src/example.ts",
      includeContent: true,
      includeHistory: true,
    })

    assert.equal(reread.artifact.recent_events.length, 5)
    assert.equal(readFileSync(reread.ledgerPath, "utf8").trim().split(/\r?\n/).length, 5)
    assert.match(reread.artifact.artifact_id, /^opencode-file-context-/)
    assert.ok(reread.preview.length > 0)
    assert.equal(reread.content?.startsWith("export const value6"), true)
  } finally {
    rmSync(repoRoot, { recursive: true, force: true })
  }
})
