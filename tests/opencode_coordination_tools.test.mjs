import test from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  appendCoordinationMessage,
  buildCoordinationMessage,
  readCoordinationMessages,
} from "../.opencode/tools/opencode_coordination_core.mjs"

test("coordination messages append and filter by session and group", () => {
  const repo = mkdtempSync(join(tmpdir(), "opencode-coord-"))

  try {
    const first = buildCoordinationMessage({
      senderSessionId: "session-a",
      senderRole: "executor",
      recipients: ["session:session-b"],
      messageKind: "handoff",
      subject: "handoff",
      body: "Executor A finished the slice.",
      conversationId: "run-1",
      artifactRefs: [
        {
          artifact_kind: "execution_artifact",
          artifact_id: "exec-1",
          path: "docs/json/opencode/waves/plan-a/execution/exec-1.json",
          digest: "sha256:1",
        },
      ],
    })
    const second = buildCoordinationMessage({
      senderSessionId: "session-b",
      senderRole: "orchestrator",
      recipients: ["group:all"],
      messageKind: "status",
      subject: "status",
      body: "Fan out the validation wave.",
      conversationId: "run-1",
    })

    appendCoordinationMessage(repo, first)
    appendCoordinationMessage(repo, second)

    const forB = readCoordinationMessages({
      repoRoot: repo,
      sessionId: "session-b",
      conversationId: "run-1",
    })
    assert.equal(forB.length, 2)
    assert.equal(forB[0].message_id, first.message_id)
    assert.equal(forB[1].message_id, second.message_id)

    const deduped = readCoordinationMessages({
      repoRoot: repo,
      sessionId: "session-b",
      conversationId: "run-1",
      knownMessageIds: [first.message_id],
    })
    assert.equal(deduped.length, 1)
    assert.equal(deduped[0].message_id, second.message_id)
  } finally {
    rmSync(repo, { recursive: true, force: true })
  }
})
