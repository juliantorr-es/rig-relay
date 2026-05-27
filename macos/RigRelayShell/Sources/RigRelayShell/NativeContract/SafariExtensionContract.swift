import Foundation

// MARK: - Safari Extension Native Messaging Contract (N1 — Q0 consumption boundary, X4 convergence)
//
// This file is the authoritative N1 Swift contract for the Q0 Safari Web Extension
// protocol. It implements all five integration deeds identified in the S4 N1-Q0
// contract compatibility audit (n1_q0_contract_compatibility_audit.v1.json):
//
//   1. Register all 8 Q0 message kinds as enum cases
//   2. Widen payload model from [String:String]? to typed discriminants
//   3. Add explicit direction field with mutual exclusion
//   4. Implement full response emission (accepted/deferred/refused/app_unavailable)
//   5. Use `created_at` as canonical timestamp; `sent_at` available as computed alias
//
// Schema authority: docs/schemas/rig.relay.safari_extension_message.v1.schema.json
// Python authority: rig_relay/extensions/safari/models.py

// MARK: - Schema & Constants

enum SafariExtensionMessageSchema {
    static let currentVersion = "rig.relay.safari_extension_message.v1"
    static let maxMessageLength = 10_000

    static let forbiddenPayloadKeys: Set<String> = [
        "file_contents", "html", "raw_prompt", "model_output",
    ]

    static let credentialParamNames: Set<String> = [
        "access_token", "token", "client_secret", "api_key", "private_token",
        "client_id", "code", "id_token", "refresh_token",
    ]

    static let tokenPattern = try! NSRegularExpression(
        pattern: #"ghp_|ghs_|gho_|ghu_|ghr_|github_pat_"#,
        options: []
    )

    static let credentialURLParamPattern = try! NSRegularExpression(
        pattern: #"[?&](access_token|token|client_secret|api_key|private_token|client_id|id_token|refresh_token)="#,
        options: []
    )

    static let ownerRepoPattern = try! NSRegularExpression(
        pattern: #"^[a-zA-Z0-9._-]+$"#,
        options: []
    )

    static let githubURLPattern = try! NSRegularExpression(
        pattern: #"^https://github\.com/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+"#,
        options: []
    )
}

// MARK: - Message Direction

enum SafariExtensionMessageDirection: String, Codable, Sendable, CaseIterable {
    case extensionToApp = "extension_to_app"
    case appToExtension = "app_to_extension"

    var validExtensionKinds: Set<SafariExtensionMessageKind> {
        [
            .handoffGitHubRepository,
            .handoffGitHubPullRequest,
            .handoffGitHubIssue,
            .ping,
        ]
    }

    var validAppKinds: Set<SafariExtensionMessageKind> {
        [
            .responseAccepted,
            .responseDeferred,
            .responseRefused,
            .responseAppUnavailable,
        ]
    }
}

// MARK: - Message Kinds (8 kinds per Q0 protocol)

enum SafariExtensionMessageKind: String, Codable, Sendable, CaseIterable {
    // Extension-to-app (handoff + ping)
    case handoffGitHubRepository = "handoff.github_repository"
    case handoffGitHubPullRequest = "handoff.github_pull_request"
    case handoffGitHubIssue = "handoff.github_issue"
    case ping = "ping"

    // App-to-extension (response)
    case responseAccepted = "response.accepted"
    case responseDeferred = "response.deferred"
    case responseRefused = "response.refused"
    case responseAppUnavailable = "response.app_unavailable"

    var direction: SafariExtensionMessageDirection? {
        switch self {
        case .handoffGitHubRepository, .handoffGitHubPullRequest,
             .handoffGitHubIssue, .ping:
            return .extensionToApp
        case .responseAccepted, .responseDeferred,
             .responseRefused, .responseAppUnavailable:
            return .appToExtension
        }
    }

    var isHandoff: Bool {
        switch self {
        case .handoffGitHubRepository, .handoffGitHubPullRequest, .handoffGitHubIssue:
            return true
        default:
            return false
        }
    }

    var isResponse: Bool {
        switch self {
        case .responseAccepted, .responseDeferred,
             .responseRefused, .responseAppUnavailable:
            return true
        default:
            return false
        }
    }
}

// MARK: - Enums (Q0 vocabulary)

enum GitHubPageKind: String, Codable, Sendable, CaseIterable {
    case repositoryMain = "repository_main"
    case repositoryCode = "repository_code"
    case repositoryIssues = "repository_issues"
    case repositoryPulls = "repository_pulls"
    case repositoryActions = "repository_actions"
    case repositoryProjects = "repository_projects"
    case repositoryWiki = "repository_wiki"
    case repositorySecurity = "repository_security"
    case repositoryInsights = "repository_insights"
    case repositorySettings = "repository_settings"
    case repositoryPages = "repository_pages"
    case organizationProfile = "organization_profile"
    case unknownGitHub = "unknown_github"
    case pullRequestConversation = "pull_request_conversation"
    case pullRequestCommits = "pull_request_commits"
    case pullRequestChecks = "pull_request_checks"
    case pullRequestFilesChanged = "pull_request_files_changed"
    case pullRequestUnknown = "pull_request_unknown"
}

enum TriggeredBy: String, Codable, Sendable, CaseIterable {
    case popupAction = "popup_action"
    case toolbarButton = "toolbar_button"
    case contextMenu = "context_menu"
}

enum RepositoryStatus: String, Codable, Sendable, CaseIterable {
    case knownAndAvailable = "known_and_available"
    case requiresImport = "requires_import"
    case requiresAuthorization = "requires_authorization"
    case statusPending = "status_pending"
}

enum DeferralReason: String, Codable, Sendable, CaseIterable {
    case appNotConnectedToCarteBlanche = "app_not_connected_to_carte_blanche"
    case repositoryNotAuthorized = "repository_not_authorized_by_installed_github_app"
    case requiresSelectionOrImport = "requires_selection_or_import_in_main_app"
    case nativeHostInitializing = "native_host_initializing"
    case integrationsIncomplete = "integrations_incomplete"
    case unsupportedPageContext = "unsupported_page_context"
    case deferredCapability = "deferred_capability"
}

enum RefusalReason: String, Codable, Sendable, CaseIterable {
    case actionNotPermitted = "action_not_permitted"
    case repositoryAccessDenied = "repository_access_denied"
    case unsupportedGitHubContext = "unsupported_github_context"
    case invalidMessage = "invalid_message"
    case rateLimited = "rate_limited"
    case extensionNotAuthorized = "extension_not_authorized"
}

enum UnavailableReason: String, Codable, Sendable, CaseIterable {
    case appNotRunning = "app_not_running"
    case appNotInstalled = "app_not_installed"
    case nativeMessagingUnavailable = "native_messaging_unavailable"
    case timeout = "timeout"
}

// MARK: - Typed Payloads (discriminated, per Q0 protocol)

struct GitHubRepositoryHandoffPayload: Codable, Sendable {
    let url: String
    let owner: String
    let repo: String
    let pageKind: GitHubPageKind
    let triggeredBy: TriggeredBy

    enum CodingKeys: String, CodingKey {
        case url, owner, repo
        case pageKind = "page_kind"
        case triggeredBy = "triggered_by"
    }
}

struct GitHubPullRequestHandoffPayload: Codable, Sendable {
    let url: String
    let owner: String
    let repo: String
    let prNumber: Int
    let pageKind: GitHubPageKind
    let triggeredBy: TriggeredBy

    enum CodingKeys: String, CodingKey {
        case url, owner, repo
        case prNumber = "pr_number"
        case pageKind = "page_kind"
        case triggeredBy = "triggered_by"
    }
}

struct GitHubIssueHandoffPayload: Codable, Sendable {
    let url: String
    let owner: String
    let repo: String
    let issueNumber: Int
    let triggeredBy: TriggeredBy

    enum CodingKeys: String, CodingKey {
        case url, owner, repo
        case issueNumber = "issue_number"
        case triggeredBy = "triggered_by"
    }
}

struct PingPayload: Codable, Sendable {
    let extensionVersion: String?
    let safariVersion: String?

    enum CodingKeys: String, CodingKey {
        case extensionVersion = "extension_version"
        case safariVersion = "safari_version"
    }
}

struct AcceptedResponsePayload: Codable, Sendable {
    let inResponseTo: String
    let action: String
    let message: String?
    let repositoryStatus: RepositoryStatus

    enum CodingKeys: String, CodingKey {
        case inResponseTo = "in_response_to"
        case action
        case message
        case repositoryStatus = "repository_status"
    }
}

struct DeferredResponsePayload: Codable, Sendable {
    let inResponseTo: String
    let action: String
    let message: String?
    let deferralReason: DeferralReason

    enum CodingKeys: String, CodingKey {
        case inResponseTo = "in_response_to"
        case action
        case message
        case deferralReason = "deferral_reason"
    }
}

struct RefusedResponsePayload: Codable, Sendable {
    let inResponseTo: String
    let action: String
    let message: String?
    let refusalReason: RefusalReason

    enum CodingKeys: String, CodingKey {
        case inResponseTo = "in_response_to"
        case action
        case message
        case refusalReason = "refusal_reason"
    }
}

struct AppUnavailableResponsePayload: Codable, Sendable {
    let message: String
    let reason: UnavailableReason?
}

// MARK: - Encoded Payload wrapper (injects kind discriminator)

private struct EncodedPayload<T: Codable>: Codable {
    let kind: String
    let body: T

    func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(kind, forKey: .kind)
        try body.encode(to: encoder)
    }

    init(kind: String, body: T) {
        self.kind = kind
        self.body = body
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.kind = try container.decode(String.self, forKey: .kind)
        self.body = try T(from: decoder)
    }

    enum CodingKeys: String, CodingKey {
        case kind
    }
}

// MARK: - Any Payload (dynamic dispatch for JSON roundtrip)

enum SafariExtensionPayload: Sendable {
    case repositoryHandoff(GitHubRepositoryHandoffPayload)
    case pullRequestHandoff(GitHubPullRequestHandoffPayload)
    case issueHandoff(GitHubIssueHandoffPayload)
    case ping(PingPayload)
    case accepted(AcceptedResponsePayload)
    case deferred(DeferredResponsePayload)
    case refused(RefusedResponsePayload)
    case appUnavailable(AppUnavailableResponsePayload)

    var kind: SafariExtensionMessageKind {
        switch self {
        case .repositoryHandoff: return .handoffGitHubRepository
        case .pullRequestHandoff: return .handoffGitHubPullRequest
        case .issueHandoff: return .handoffGitHubIssue
        case .ping: return .ping
        case .accepted: return .responseAccepted
        case .deferred: return .responseDeferred
        case .refused: return .responseRefused
        case .appUnavailable: return .responseAppUnavailable
        }
    }
}

// MARK: - Custom decoder for payload (kind discriminator)

extension SafariExtensionPayload: Codable {
    private enum CodingKeys: String, CodingKey {
        case kind
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let kindStr = try container.decode(String.self, forKey: .kind)

        guard let kind = SafariExtensionMessageKind(rawValue: kindStr) else {
            throw DecodingError.dataCorruptedError(
                forKey: .kind, in: container,
                debugDescription: "Unrecognized message kind: \(kindStr)"
            )
        }

        switch kind {
        case .handoffGitHubRepository:
            self = .repositoryHandoff(try GitHubRepositoryHandoffPayload(from: decoder))
        case .handoffGitHubPullRequest:
            self = .pullRequestHandoff(try GitHubPullRequestHandoffPayload(from: decoder))
        case .handoffGitHubIssue:
            self = .issueHandoff(try GitHubIssueHandoffPayload(from: decoder))
        case .ping:
            self = .ping(try PingPayload(from: decoder))
        case .responseAccepted:
            self = .accepted(try AcceptedResponsePayload(from: decoder))
        case .responseDeferred:
            self = .deferred(try DeferredResponsePayload(from: decoder))
        case .responseRefused:
            self = .refused(try RefusedResponsePayload(from: decoder))
        case .responseAppUnavailable:
            self = .appUnavailable(try AppUnavailableResponsePayload(from: decoder))
        }
    }

    func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .repositoryHandoff(let p):
            try container.encode(EncodedPayload(kind: self.kind.rawValue, body: p))
        case .pullRequestHandoff(let p):
            try container.encode(EncodedPayload(kind: self.kind.rawValue, body: p))
        case .issueHandoff(let p):
            try container.encode(EncodedPayload(kind: self.kind.rawValue, body: p))
        case .ping(let p):
            try container.encode(EncodedPayload(kind: self.kind.rawValue, body: p))
        case .accepted(let p):
            try container.encode(EncodedPayload(kind: self.kind.rawValue, body: p))
        case .deferred(let p):
            try container.encode(EncodedPayload(kind: self.kind.rawValue, body: p))
        case .refused(let p):
            try container.encode(EncodedPayload(kind: self.kind.rawValue, body: p))
        case .appUnavailable(let p):
            try container.encode(EncodedPayload(kind: self.kind.rawValue, body: p))
        }
    }
}

// MARK: - Message Envelope (authoritative Q0-compatible)

struct SafariExtensionMessageEnvelope: Codable, Sendable {
    let schemaVersion: String
    let messageId: String
    let direction: SafariExtensionMessageDirection
    let kind: SafariExtensionMessageKind
    let payload: SafariExtensionPayload
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case messageId = "message_id"
        case direction
        case kind
        case payload
        case createdAt = "created_at"
    }

    static var currentVersion: String { SafariExtensionMessageSchema.currentVersion }
}

extension SafariExtensionMessageEnvelope {

    var sentAt: String { createdAt }

    var sentAtAlias: String { createdAt }

    init?(fromJSON data: Data) {
        let decoder = JSONDecoder()
        do {
            self = try decoder.decode(SafariExtensionMessageEnvelope.self, from: data)
        } catch {
            return nil
        }
    }

    func toJSON(pretty: Bool = false) -> Data? {
        let encoder = JSONEncoder()
        if pretty {
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        }
        guard let data = try? encoder.encode(self) else { return nil }
        return data
    }

    func toDictionary() -> [String: Any]? {
        guard let data = toJSON(),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return dict
    }

    func validateDirection() -> Bool {
        guard let expected = kind.direction else { return false }
        return direction == expected
    }
}

// MARK: - Origin Validator

struct SafariExtensionOriginValidator: Sendable {
    let allowedExtensionBundleId: String

    func validate(bundleId: String) -> Bool {
        bundleId == allowedExtensionBundleId
    }

    func refuseMessage(kind: String, bundleId: String) -> SafariExtensionMessageEnvelope? {
        let refusal = RefusedResponsePayload(
            inResponseTo: "origin_validation",
            action: kind,
            message: "Untrusted extension origin: \(bundleId). Allowed: \(allowedExtensionBundleId)",
            refusalReason: .extensionNotAuthorized
        )
        return SafariExtensionMessageEnvelope(
            schemaVersion: SafariExtensionMessageSchema.currentVersion,
            messageId: UUID().uuidString,
            direction: .appToExtension,
            kind: .responseRefused,
            payload: .refused(refusal),
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
    }
}

// MARK: - Content-Light Validator

struct SafariExtensionContentLightValidator: Sendable {

    func validateJSON(_ jsonDict: [String: Any]) -> [String] {
        var violations: [String] = []

        guard let rawData = try? JSONSerialization.data(withJSONObject: jsonDict),
              let rawString = String(data: rawData, encoding: .utf8) else {
            return ["unable_to_serialize_for_validation"]
        }

        let range = NSRange(rawString.startIndex..., in: rawString)
        if SafariExtensionMessageSchema.tokenPattern.firstMatch(in: rawString, range: range) != nil {
            violations.append("message_contains_github_token_pattern")
        }

        if SafariExtensionMessageSchema.credentialURLParamPattern.firstMatch(in: rawString, range: range) != nil {
            violations.append("message_contains_credential_url_parameter")
        }

        for key in SafariExtensionMessageSchema.forbiddenPayloadKeys {
            if jsonDict[key] != nil {
                violations.append("payload_contains_forbidden_key:\(key)")
            }
        }

        if let innerDict = jsonDict["payload"] as? [String: Any] {
            violations.append(contentsOf: _scanNested(dictionary: innerDict, path: "payload"))
            if let owner = innerDict["owner"] as? String {
                violations.append(contentsOf: _scanStringField(value: owner, path: "payload.owner"))
            }
            if let repo = innerDict["repo"] as? String {
                violations.append(contentsOf: _scanStringField(value: repo, path: "payload.repo"))
            }
            if let url = innerDict["url"] as? String {
                violations.append(contentsOf: _scanStringField(value: url, path: "payload.url"))
            }
            if let message = innerDict["message"] as? String {
                violations.append(contentsOf: _scanStringField(value: message, path: "payload.message"))
            }
        }

        if rawString.count > SafariExtensionMessageSchema.maxMessageLength {
            violations.append("message_exceeds_character_length_cap:\(SafariExtensionMessageSchema.maxMessageLength)")
        }

        return violations
    }

    func validateEnvelope(_ envelope: SafariExtensionMessageEnvelope) -> [String] {
        guard let dict = envelope.toDictionary() else {
            return ["unable_to_serialize"]
        }
        return validateJSON(dict)
    }

    private func _scanNested(dictionary: [String: Any], path: String) -> [String] {
        var violations: [String] = []

        for key in SafariExtensionMessageSchema.forbiddenPayloadKeys {
            if dictionary[key] != nil {
                violations.append("nested_payload_contains_forbidden_key:\(path).\(key)")
            }
        }

        for (childKey, childValue) in dictionary {
            let childPath = "\(path).\(childKey)"
            if let nestedDict = childValue as? [String: Any] {
                violations.append(contentsOf: _scanNested(dictionary: nestedDict, path: childPath))
            } else if let nestedArray = childValue as? [Any] {
                for (index, element) in nestedArray.enumerated() {
                    if let nestedDict = element as? [String: Any] {
                        violations.append(contentsOf: _scanNested(dictionary: nestedDict, path: "\(childPath)[\(index)]"))
                    } else if let str = element as? String {
                        violations.append(contentsOf: _scanStringField(value: str, path: "\(childPath)[\(index)]"))
                    }
                }
            } else if let str = childValue as? String {
                violations.append(contentsOf: _scanStringField(value: str, path: childPath))
            }
        }

        return violations
    }

    private func _scanStringField(value: String, path: String) -> [String] {
        var violations: [String] = []
        let range = NSRange(value.startIndex..., in: value)

        if SafariExtensionMessageSchema.tokenPattern.firstMatch(in: value, range: range) != nil {
            violations.append("field_contains_token_pattern:\(path)")
        }
        if SafariExtensionMessageSchema.credentialURLParamPattern.firstMatch(in: value, range: range) != nil {
            violations.append("field_contains_credential_url_parameter:\(path)")
        }

        return violations
    }
}

// MARK: - Response Builders

enum SafariExtensionResponseBuilder {

    static func accepted(
        inResponseTo messageId: String,
        action: String,
        repositoryStatus: RepositoryStatus,
        message: String? = nil
    ) -> SafariExtensionMessageEnvelope {
        SafariExtensionMessageEnvelope(
            schemaVersion: SafariExtensionMessageSchema.currentVersion,
            messageId: UUID().uuidString,
            direction: .appToExtension,
            kind: .responseAccepted,
            payload: .accepted(AcceptedResponsePayload(
                inResponseTo: messageId,
                action: action,
                message: message,
                repositoryStatus: repositoryStatus
            )),
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
    }

    static func deferred(
        inResponseTo messageId: String,
        action: String,
        reason: DeferralReason,
        message: String? = nil
    ) -> SafariExtensionMessageEnvelope {
        SafariExtensionMessageEnvelope(
            schemaVersion: SafariExtensionMessageSchema.currentVersion,
            messageId: UUID().uuidString,
            direction: .appToExtension,
            kind: .responseDeferred,
            payload: .deferred(DeferredResponsePayload(
                inResponseTo: messageId,
                action: action,
                message: message,
                deferralReason: reason
            )),
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
    }

    static func refused(
        inResponseTo messageId: String,
        action: String,
        reason: RefusalReason,
        message: String? = nil
    ) -> SafariExtensionMessageEnvelope {
        SafariExtensionMessageEnvelope(
            schemaVersion: SafariExtensionMessageSchema.currentVersion,
            messageId: UUID().uuidString,
            direction: .appToExtension,
            kind: .responseRefused,
            payload: .refused(RefusedResponsePayload(
                inResponseTo: messageId,
                action: action,
                message: message,
                refusalReason: reason
            )),
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
    }

    static func appUnavailable(
        message: String,
        reason: UnavailableReason? = nil
    ) -> SafariExtensionMessageEnvelope {
        SafariExtensionMessageEnvelope(
            schemaVersion: SafariExtensionMessageSchema.currentVersion,
            messageId: UUID().uuidString,
            direction: .appToExtension,
            kind: .responseAppUnavailable,
            payload: .appUnavailable(AppUnavailableResponsePayload(
                message: message,
                reason: reason
            )),
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
    }
}

// MARK: - Deferred/Blocker Documentation (N1 → N2 transition)

struct SafariExtensionContractSummary: Codable, Sendable {
    let n1ContractVersion: String
    let messageEnvelopeSchema: String
    let supportedKinds: [String]
    let directionModel: String
    let originValidationRequired: Bool
    let requiresNativeMessagingPermission: Bool
    let manifestPermissionRequired: String

    let x4ConvergenceDeeds: [String]

    let blockingRequirements: [String]
    let deferredCapabilities: [String]
    let notes: [String]

    static func v1() -> SafariExtensionContractSummary {
        SafariExtensionContractSummary(
            n1ContractVersion: "rig.relay.safari_extension_message.v1 (X4 convergence)",
            messageEnvelopeSchema: "SafariExtensionMessageEnvelope — schema_version, message_id, direction, kind, payload (discriminated union), created_at (sent_at alias)",
            supportedKinds: SafariExtensionMessageKind.allCases.map(\.rawValue).sorted(),
            directionModel: "Explicit direction field with mutual exclusion per Q0 protocol",
            originValidationRequired: true,
            requiresNativeMessagingPermission: true,
            manifestPermissionRequired: "nativeMessaging",

            x4ConvergenceDeeds: [
                "Register all 8 Q0 message kinds as enum cases (completed)",
                "Widen payload model from [String:String]? to typed discriminants (completed)",
                "Add explicit direction field with mutual exclusion (completed)",
                "Implement full response emission (accepted/deferred/refused/app_unavailable) (completed)",
                "Use created_at as canonical timestamp; sent_at available as computed alias (completed)",
            ],

            blockingRequirements: [
                "Xcode project target (.xcodeproj) required for .appex extension bundle — cannot create SFSafariExtensionHandler subclass via SPM alone",
                "Apple Developer Program membership required for code signing",
                "Developer ID Application certificate required for notarized distribution",
                "xcrun safari-web-extension-packager invocation to convert safari-web-extension/ to Xcode project",
                "App Group shared container setup between containing app and extension (com.apple.security.application-groups)",
            ],

            deferredCapabilities: [
                "Live Safari Web Extension installation and runtime integration",
                "SFSafariApplication.dispatchMessage for app-to-extension async push (macOS only)",
                "browser.runtime.connectNative persistent port support",
                "Safari 17+ SFExtensionProfileKey for multi-profile support",
                "iOS Safari extension support (not in v1 scope)",
            ],

            notes: [
                "The extension's JS calls browser.runtime.sendNativeMessage('application.id', message, callback) — application.id is ignored by Safari; message always routes to the containing app's extension via SFSafariExtensionHandler.beginRequest(with:)",
                "The native handler receives messages via context.inputItems[0].userInfo[SFExtensionMessageKey]",
                "App-to-extension messages use SFSafariApplication.dispatchMessage(withName:toExtensionWithIdentifier:userInfo:completionHandler:)",
                "SPM alone cannot create .appex bundles — an Xcode project with Safari Extension target is required for the native extension handler",
                "Both app and extension must share the same App Group ID in entitlements (com.apple.security.application-groups)",
                "Content scripts cannot use native messaging — only background scripts and extension pages",
                "Hardened Runtime required for notarization; no com.apple.security.get-task-allow for release builds",
                "Sparkle 2 SPM integration available for update delivery; requires manual framework signing for non-Xcode builds",
                "Ed25519 key pair for Sparkle update signing; private key in Keychain (CI secret); public key in Info.plist",
            ]
        )
    }
}
