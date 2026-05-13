# Rig Relay Evidence

Rig Relay evidence is a read-only session record rooted at a selected evidence root.
Use it to inspect what a session wrote without mutating the session itself.

Operational guide:
- [Validation workflow](validation.md)

Current state:
- `observability.jsonl` is the canonical event stream for a session.
- `manifest.json` is a minimal per-session index for evidence files when present.
- `rig-relay doctor evidence` validates one selected session.
- The validator prefers a manifest when present and falls back to scan-based
  validation for legacy sessions.
- Root defaults have not changed; the **User Global** Relay home (`~/.rig/relay`) is the default durable home for all evidence.
- Repo-local evidence is supported for isolated tests and experiments but is not the default doctrine.

