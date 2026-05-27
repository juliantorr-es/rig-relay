import Foundation

// ── N1 Native Host Bootstrap Contract ──────────────────────
// Typed, versioned, content-light messages from native host to Gridline frontend.
// No raw file contents, no secrets, no paths beyond hashed references.

struct BootstrapMessage: Codable, Sendable {
    let schemaVersion: String
    let messageId: String
    let kind: BootstrapMessageKind
    let sessionId: String
    let payload: BootstrapPayload
    let traceId: String?
    let sentAt: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case messageId = "message_id"
        case kind
        case sessionId = "session_id"
        case payload
        case traceId = "trace_id"
        case sentAt = "sent_at"
    }

    static var currentVersion: String { "rig.relay.native_bootstrap.v1" }
}

enum BootstrapMessageKind: String, Codable, Sendable {
    case hostReady = "host_ready"
    case hostResourceFailure = "host_resource_failure"
    case hostBridgeAvailable = "host_bridge_available"
    case hostBridgeUnavailable = "host_bridge_unavailable"
    case hostCapabilityRefusal = "host_capability_refusal"
    case hostRestart = "host_restart"
}

struct BootstrapPayload: Codable, Sendable {
    let resourceLoadResult: ResourceLoadResult?
    let bridgeAvailable: Bool
    let supportedCapabilityKinds: [String]
    let refusalReasons: [String]
    let appVersion: String?
    let buildCommitSHA: String?
    let transportStatus: String

    enum CodingKeys: String, CodingKey {
        case resourceLoadResult = "resource_load_result"
        case bridgeAvailable = "bridge_available"
        case supportedCapabilityKinds = "supported_capability_kinds"
        case refusalReasons = "refusal_reasons"
        case appVersion = "app_version"
        case buildCommitSHA = "build_commit_sha"
        case transportStatus = "transport_status"
    }
}

struct ResourceLoadResult: Codable, Sendable {
    let resolvedPathHash: String
    let indexHTMLFound: Bool
    let subresourceCount: Int
    let missingSubresources: [String]
    let loadError: String?

    enum CodingKeys: String, CodingKey {
        case resolvedPathHash = "resolved_path_hash"
        case indexHTMLFound = "index_html_found"
        case subresourceCount = "subresource_count"
        case missingSubresources = "missing_subresources"
        case loadError = "load_error"
    }
}

// ── Bootstrap Encoding ──────────────────────────────────────

extension BootstrapMessage {
    func asDictionary() -> [String: Any]? {
        guard let data = try? JSONEncoder().encode(self),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return dict
    }
}

// ── Refusal Message (content-light) ────────────────────────

struct BootstrapRefusal: Codable, Sendable {
    let schemaVersion: String
    let refusedKind: String
    let reason: String
    let allowedKinds: [String]
    let traceId: String?
    let sentAt: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case refusedKind = "refused_kind"
        case reason
        case allowedKinds = "allowed_kinds"
        case traceId = "trace_id"
        case sentAt = "sent_at"
    }

    static var currentVersion: String { "rig.relay.native_bootstrap_refusal.v1" }

    func asDictionary() -> [String: Any]? {
        guard let data = try? JSONEncoder().encode(self),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return dict
    }
}
