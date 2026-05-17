# Security Policy

## Reporting a Vulnerability

Rig Relay is local-first software. Most security concerns relate to local tool execution
boundaries, credential handling, and debug packet quarantine.

Please report security vulnerabilities by opening a GitHub issue with the `security` label
at https://github.com/juliantorr-es/rig-relay/issues.

## Supported Versions

| Version | Supported |
|---|---|
| 0.1.x (alpha) | :white_check_mark: |

## Local Execution Safety

Rig Relay executes tools and subprocesses on your local machine. The following
boundaries are enforced:

- All destructive Git commands are blocked by the governance guard.
- Bash commands are scanned for dangerous patterns before execution.
- Environment variables are scrubbed before subprocess execution.
- Debug bundles are created only by explicit user action (dry-run by default).

## Credential Handling

- API keys are stored in the platform-native credential store (macOS Keychain, etc.).
- Tokens and secrets are redacted from telemetry, traces, and debug bundles.
- No credentials are transmitted without explicit user consent.

See [docs/governance/](docs/governance/) for detailed architecture documentation.
