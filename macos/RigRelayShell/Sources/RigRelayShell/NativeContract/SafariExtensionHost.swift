import Foundation

// ── Safari Extension Message Host (X4 convergence) ──
//
// Handles validated Q0-compatible messages from the Safari Web Extension.
// Designed to be used both in a native SFSafariExtensionHandler.beginRequest(with:)
// (when Xcode project exists) and in standalone native-messaging proxy mode.
//
// All messages are validated for content-light compliance before processing.
// Unsafe, malformed, or token-bearing messages are refused.

@MainActor
final class SafariExtensionHost: ObservableObject, @unchecked Sendable {

    @Published var connectionState: SafariExtensionConnectionState = .idle
    @Published var lastMessageKind: String?
    @Published var lastMessageTimestamp: String?

    private let originValidator: SafariExtensionOriginValidator
    private let contentValidator = SafariExtensionContentLightValidator()

    private var messageHistory: [SafariExtensionMessageEnvelope] = []
    private let maxHistory = 50

    var activeHandoffURL: String? {
        guard let kind = lastMessageKind,
              kind == SafariExtensionMessageKind.handoffGitHubRepository.rawValue,
              let last = messageHistory.last
        else { return nil }
        if case .repositoryHandoff(let payload) = last.payload {
            return payload.url
        }
        if case .pullRequestHandoff(let payload) = last.payload {
            return payload.url
        }
        if case .issueHandoff(let payload) = last.payload {
            return payload.url
        }
        return nil
    }

    init(allowedBundleId: String) {
        self.originValidator = SafariExtensionOriginValidator(
            allowedExtensionBundleId: allowedBundleId
        )
    }

    // ── Primary entry point ──────────────────────────

    func handleIncomingMessage(
        rawJSON: Data,
        originBundleId: String
    ) -> SafariExtensionMessageEnvelope? {

        connectionState = .processing

        guard let envelope = SafariExtensionMessageEnvelope(fromJSON: rawJSON) else {
            connectionState = .error("Failed to decode message envelope")
            return SafariExtensionResponseBuilder.refused(
                inResponseTo: "unknown",
                action: "decode",
                reason: .invalidMessage,
                message: "Failed to parse message as SafariExtensionMessageEnvelope"
            )
        }

        return handleMessage(envelope, originBundleId: originBundleId)
    }

    func handleMessage(
        _ envelope: SafariExtensionMessageEnvelope,
        originBundleId: String
    ) -> SafariExtensionMessageEnvelope? {

        if !originValidator.validate(bundleId: originBundleId) {
            connectionState = .error("Origin validation failed")
            return originValidator.refuseMessage(
                kind: envelope.kind.rawValue,
                bundleId: originBundleId
            )
        }

        if !envelope.validateDirection() {
            connectionState = .error("Direction mismatch")
            return SafariExtensionResponseBuilder.refused(
                inResponseTo: envelope.messageId,
                action: envelope.kind.rawValue,
                reason: .invalidMessage,
                message: "Kind '\(envelope.kind.rawValue)' is not valid for direction '\(envelope.direction.rawValue)'"
            )
        }

        let contentViolations = contentValidator.validateEnvelope(envelope)
        if !contentViolations.isEmpty {
            connectionState = .error("Content-light violation: \(contentViolations.joined(separator: ", "))")
            return SafariExtensionResponseBuilder.refused(
                inResponseTo: envelope.messageId,
                action: envelope.kind.rawValue,
                reason: .invalidMessage,
                message: "Content-light violation: \(contentViolations.joined(separator: ", "))"
            )
        }

        recordMessage(envelope)
        return dispatchByKind(envelope)
    }

    // ── Message dispatch ─────────────────────────────

    private func dispatchByKind(
        _ envelope: SafariExtensionMessageEnvelope
    ) -> SafariExtensionMessageEnvelope? {

        switch envelope.kind {

        case .handoffGitHubRepository:
            guard case .repositoryHandoff(let payload) = envelope.payload else {
                return SafariExtensionResponseBuilder.refused(
                    inResponseTo: envelope.messageId,
                    action: envelope.kind.rawValue,
                    reason: .invalidMessage
                )
            }
            connectionState = .handoffReceived("repo: \(payload.owner)/\(payload.repo)")
            return processRepositoryHandoff(envelope, payload)

        case .handoffGitHubPullRequest:
            guard case .pullRequestHandoff(let payload) = envelope.payload else {
                return SafariExtensionResponseBuilder.refused(
                    inResponseTo: envelope.messageId,
                    action: envelope.kind.rawValue,
                    reason: .invalidMessage
                )
            }
            connectionState = .handoffReceived("pr: \(payload.owner)/\(payload.repo)#\(payload.prNumber)")
            return processPullRequestHandoff(envelope, payload)

        case .handoffGitHubIssue:
            guard case .issueHandoff(let payload) = envelope.payload else {
                return SafariExtensionResponseBuilder.refused(
                    inResponseTo: envelope.messageId,
                    action: envelope.kind.rawValue,
                    reason: .invalidMessage
                )
            }
            connectionState = .handoffReceived("issue: \(payload.owner)/\(payload.repo)#\(payload.issueNumber)")
            return processIssueHandoff(envelope, payload)

        case .ping:
            guard case .ping(let payload) = envelope.payload else {
                return SafariExtensionResponseBuilder.refused(
                    inResponseTo: envelope.messageId,
                    action: envelope.kind.rawValue,
                    reason: .invalidMessage
                )
            }
            connectionState = .connected
            return processPing(envelope, payload)

        case .responseAccepted, .responseDeferred,
             .responseRefused, .responseAppUnavailable:
            connectionState = .connected
            return nil
        }
    }

    // ── Handoff processors ───────────────────────────

    private func processRepositoryHandoff(
        _ envelope: SafariExtensionMessageEnvelope,
        _ payload: GitHubRepositoryHandoffPayload
    ) -> SafariExtensionMessageEnvelope {
        SafariExtensionResponseBuilder.accepted(
            inResponseTo: envelope.messageId,
            action: "handoff.github_repository",
            repositoryStatus: .statusPending,
            message: "GitHub repository handoff received: \(payload.owner)/\(payload.repo) [\(payload.pageKind.rawValue)]"
        )
    }

    private func processPullRequestHandoff(
        _ envelope: SafariExtensionMessageEnvelope,
        _ payload: GitHubPullRequestHandoffPayload
    ) -> SafariExtensionMessageEnvelope {
        SafariExtensionResponseBuilder.accepted(
            inResponseTo: envelope.messageId,
            action: "handoff.github_pull_request",
            repositoryStatus: .statusPending,
            message: "GitHub PR handoff received: \(payload.owner)/\(payload.repo)#\(payload.prNumber) [\(payload.pageKind.rawValue)]"
        )
    }

    private func processIssueHandoff(
        _ envelope: SafariExtensionMessageEnvelope,
        _ payload: GitHubIssueHandoffPayload
    ) -> SafariExtensionMessageEnvelope {
        SafariExtensionResponseBuilder.accepted(
            inResponseTo: envelope.messageId,
            action: "handoff.github_issue",
            repositoryStatus: .statusPending,
            message: "GitHub issue handoff received: \(payload.owner)/\(payload.repo)#\(payload.issueNumber)"
        )
    }

    private func processPing(
        _ envelope: SafariExtensionMessageEnvelope,
        _ payload: PingPayload
    ) -> SafariExtensionMessageEnvelope {
        SafariExtensionResponseBuilder.accepted(
            inResponseTo: envelope.messageId,
            action: "ping",
            repositoryStatus: .statusPending,
            message: "Native app is available"
        )
    }

    // ── State ────────────────────────────────────────

    private func recordMessage(_ envelope: SafariExtensionMessageEnvelope) {
        lastMessageKind = envelope.kind.rawValue
        lastMessageTimestamp = envelope.createdAt
        messageHistory.append(envelope)
        if messageHistory.count > maxHistory {
            messageHistory.removeFirst(messageHistory.count - maxHistory)
        }
    }

    /// Generate a content-light diagnostic summary of this host.
    func diagnosticSummary() -> [String: Any] {
        [
            "schema_version": "rig.relay.safari.diagnostic_host_summary.v1",
            "connection_state": connectionState.label,
            "connection_detail": connectionState.detail ?? "",
            "last_message_kind": lastMessageKind as Any? ?? NSNull(),
            "last_message_timestamp": lastMessageTimestamp as Any? ?? NSNull(),
            "message_history_count": messageHistory.count,
            "origin_allowed_bundle_id": originValidator.allowedExtensionBundleId,
            "content_light": "enforced",
        ]
    }
}

// ── Connection State ──────────────────────────────────────

enum SafariExtensionConnectionState: Equatable, Sendable {
    case idle
    case processing
    case connected
    case handoffReceived(String)
    case error(String)

    var label: String {
        switch self {
        case .idle: "idle"
        case .processing: "processing"
        case .connected: "connected"
        case .handoffReceived: "handoff_received"
        case .error: "error"
        }
    }

    var detail: String? {
        switch self {
        case .handoffReceived(let d): d
        case .error(let d): d
        default: nil
        }
    }
}
