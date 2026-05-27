import Foundation

// MARK: - Intent Envelope (typed bridge intent)

struct GridlineIntent: Codable, Sendable {
    let traceId: String
    let frontendSessionId: String
    let intentKind: IntentKind
    let mutationClass: MutationClass
    let capabilityRequired: String?
    let intentPayloadHash: String?
    let redactionStatus: String

    enum CodingKeys: String, CodingKey {
        case traceId = "trace_id"
        case frontendSessionId = "frontend_session_id"
        case intentKind = "intent_kind"
        case mutationClass = "mutation_class"
        case capabilityRequired = "capability_required"
        case intentPayloadHash = "intent_payload_hash"
        case redactionStatus = "redaction_status"
    }
}

enum IntentKind: String, Codable, Sendable {
    case refreshProjection = "refresh_projection"
    case connectGitHub = "connect_github"
    case selectRepository = "select_repository"
    case importRepository = "import_repository"
    case startInvestigation = "start_investigation"
    case approveProposal = "approve_proposal"
    case refreshInference = "refresh_inference"
    case requestCapabilityReview = "request_capability_review"
    case previewPublish = "preview_publish"
    case approvePublication = "approve_publication"
    case openDocs = "open_docs"
    case revealLogs = "reveal_logs"
}

enum MutationClass: String, Codable, Sendable {
    case readOnly = "read_only"
    case safeLocalMutation = "safe_local_mutation"
    case dangerousLocalMutation = "dangerous_local_mutation"
    case externalNetworkMutation = "external_network_mutation"
    case credentialedProviderMutation = "credentialed_provider_mutation"
    case releaseAffectingMutation = "release_affecting_mutation"
}

// MARK: - Intent Result (from backend)

struct IntentResult: Codable, Sendable {
    let status: IntentResultStatus
    let outputRefs: [String]
    let projectionRefreshRecommended: Bool
    let authorizationRequired: Bool
    let warnings: [String]

    enum CodingKeys: String, CodingKey {
        case status
        case outputRefs = "output_refs"
        case projectionRefreshRecommended = "projection_refresh_recommended"
        case authorizationRequired = "authorization_required"
        case warnings
    }
}

enum IntentResultStatus: String, Codable, Sendable {
    case accepted
    case completed
    case refused
    case failed
}
