# Changelog

## [0.1.0a1] — Unreleased

### Initial Release Candidate

- **Governance**: Destructive Git commands blocked; dirty file preservation active.
- **Coordination**: 10 mutation methods digester-guarded; cross-process lease safety via fcntl.flock.
- **Coordination**: Stale lease auto-detection and recovery.
- **Coordination**: Event ledger with cross-process unique sequences and fsync durability.
- **Coordination**: DuckDB-backed ledger integrity verification.
- **Telemetry**: Consent gate with 5 states, 4 scopes, and expiry enforcement.
- **Telemetry**: Remote upload redaction via redact_for_remote before HTTP POST.
- **Telemetry**: Local denial events are content-light (no secrets, no raw data).
- **Runtime**: Subprocess supervisor with timeout/cancellation/stall detection.
- **Runtime**: Bash hardening (environment scrubbing, pattern detection, denial list, rerouting).
- **Runtime**: Mutation tools require lease + receipt emission + dirty guard checks.
- **Context**: Content-light context packets with canonical SHA256.
- **Tracing**: Trace contract scanner detecting subagent.*, validate.*, tool_.* prefixes.
- **Desktop**: Cockpit with WebSocket, strict CSP, zero tracking.
- **Docs**: 223 static pages rendered from canonical JSON artifacts.
- **CI**: Pre-commit hooks, test suite, release gate, PyInstaller builds.
- **DuckDB**: Read-side analytical projections. Never canonical state.
