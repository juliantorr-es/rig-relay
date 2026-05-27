import Foundation

// MARK: - Safari Extension Native Messaging Contract (N1 — Q0 consumption boundary)

struct SafariExtensionMessageEnvelope: Codable, Sendable {
    let schemaVersion: String
    let messageId: String
    let kind: SafariExtensionMessageKind
    let payload: [String: String]?
    let traceId: String?
    let sentAt: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case messageId = "message_id"
        case kind
        case payload
        case traceId = "trace_id"
        case sentAt = "sent_at"
    }

    static var currentVersion: String { "rig.relay.safari_extension_message.v1" }
}

enum SafariExtensionMessageKind: String, Codable, Sendable {
    case openRigRelay
    case sendPageContext
    case requestConnectionState
    case handoffRepoURL
}

struct SafariExtensionHandoffRefusal: Codable, Sendable {
    let refusedKind: String
    let reason: String
    let allowedKinds: [String]

    enum CodingKeys: String, CodingKey {
        case refusedKind = "refused_kind"
        case reason
        case allowedKinds = "allowed_kinds"
    }
}

// MARK: - Supported Intents Vocabulary

enum SafariExtensionSupportedIntent: String, CaseIterable, Sendable {
    case openRigRelay = "open_rig_relay"
    case sendGitHubPageContext = "send_github_page_context"
    case requestAppConnectionState = "request_app_connection_state"
    case handoffRepositoryURL = "handoff_repository_url"

    var description: String {
        switch self {
        case .openRigRelay:
            "Open or bring to front the Rig Relay macOS application"
        case .sendGitHubPageContext:
            "Send the current GitHub page URL and metadata for Rig Relay context"
        case .requestAppConnectionState:
            "Query whether Rig Relay is currently connected to a Carte Blanche installation"
        case .handoffRepositoryURL:
            "Hand off a repository URL from Safari to Rig Relay for import"
        }
    }
}

// MARK: - Extension Origin Validator

struct SafariExtensionOriginValidator: Sendable {
    let allowedExtensionBundleId: String

    init(allowedExtensionBundleId: String) {
        self.allowedExtensionBundleId = allowedExtensionBundleId
    }

    func validateOrigin(bundleId: String) -> Bool {
        bundleId == allowedExtensionBundleId
    }

    func refuseMessage(kind: String, bundleId: String) -> SafariExtensionHandoffRefusal {
        SafariExtensionHandoffRefusal(
            refusedKind: kind,
            reason: "Untrusted extension origin: \(bundleId). Allowed: \(allowedExtensionBundleId)",
            allowedKinds: SafariExtensionSupportedIntent.allCases.map(\.rawValue)
        )
    }
}

// MARK: - Q0 Contract Summary (for documentation)

struct SafariExtensionContractSummary: Codable, Sendable {
    let n1ContractVersion: String
    let messageEnvelopeSchema: String
    let supportedIntents: [String]
    let originValidationRequired: Bool
    let requiresNativeMessagingPermission: Bool
    let manifestPermissionRequired: String
    let deferredToQ0: [String]
    let notes: [String]

    static func v1() -> SafariExtensionContractSummary {
        SafariExtensionContractSummary(
            n1ContractVersion: "rig.relay.safari_extension_message.v1",
            messageEnvelopeSchema: "SafariExtensionMessageEnvelope — schema_version, message_id, kind, payload, trace_id, sent_at",
            supportedIntents: SafariExtensionSupportedIntent.allCases.map(\.rawValue),
            originValidationRequired: true,
            requiresNativeMessagingPermission: true,
            manifestPermissionRequired: "nativeMessaging",
            deferredToQ0: [
                "Safari Web Extension implementation (background script, content scripts, popup, manifest.json)",
                "Xcode project target for .appex extension bundle",
                "SFSafariExtensionHandler subclass with beginRequest(with:) implementation",
                "App Group shared container setup",
                "Live Safari extension registration and App Store submission",
                "Extension entitlements (com.apple.security.application-groups)"
            ],
            notes: [
                "The extension's JS calls browser.runtime.sendNativeMessage('application.id', message, callback) — application.id is ignored by Safari; message always routes to the containing app's extension",
                "The native host receives messages in beginRequest(with:) via context.inputItems[0].userInfo[SFExtensionMessageKey]",
                "The native host sends messages via SFSafariApplication.dispatchMessage(withName:toExtensionWithIdentifier:userInfo:completionHandler:)",
                "SPM alone cannot create .appex bundles — Q0 must add an Xcode project target for the extension",
                "Both app and extension must share the same App Group ID in entitlements",
                "Content scripts cannot use native messaging — only background scripts and extension pages"
            ]
        )
    }
}
