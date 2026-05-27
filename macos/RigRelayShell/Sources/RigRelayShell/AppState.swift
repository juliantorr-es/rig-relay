import SwiftUI
import WebKit

// ── Host State ──────────────────────────────────────────────

enum HostState: Sendable, Equatable {
    case uninitialized
    case booting
    case resolvingResources
    case resourceNotFound(String)
    case resourceMalformed(String)
    case loadingFrontend
    case frontendReady
    case frontendLoadFailed(String)
    case bridgeUnavailable
    case unsupportedOrigin(String)
    case error(String)
    case extensionStatusUnknown

    var label: String {
        switch self {
        case .uninitialized: "Starting..."
        case .booting: "Booting..."
        case .resolvingResources: "Resolving Resources..."
        case .resourceNotFound: "Resources Not Found"
        case .resourceMalformed: "Resources Corrupt"
        case .loadingFrontend: "Loading Rig Relay..."
        case .frontendReady: "Ready"
        case .frontendLoadFailed: "Load Failed"
        case .bridgeUnavailable: "Bridge Unavailable"
        case .unsupportedOrigin: "Navigation Refused"
        case .error: "Error"
        case .extensionStatusUnknown: "Extension status unknown"
        }
    }

    var iconName: String {
        switch self {
        case .uninitialized, .booting, .resolvingResources: "arrow.triangle.2.circlepath"
        case .resourceNotFound, .resourceMalformed: "doc.questionmark"
        case .loadingFrontend: "globe"
        case .frontendReady: "checkmark.circle"
        case .frontendLoadFailed: "xmark.circle"
        case .bridgeUnavailable: "wifi.slash"
        case .unsupportedOrigin: "lock.shield"
        case .error: "exclamationmark.octagon"
        case .extensionStatusUnknown: "questionmark.circle"
        }
    }

    var isTerminal: Bool {
        switch self {
        case .resourceNotFound, .resourceMalformed, .frontendLoadFailed,
             .bridgeUnavailable, .unsupportedOrigin, .error: true
        default: false
        }
    }
}

// ── App State ───────────────────────────────────────────────

@MainActor
final class AppState: ObservableObject {
    @Published var hostState: HostState = .uninitialized
    @Published var showExtensionStatus = false

    private let sessionId = "webkit_host_\(UUID().uuidString.prefix(8))"
    let messageBridge = NativeMessageBridge()

    var resourceLocator: ResourceLocator { ResourceLocator() }

    init() {
        // No default remote URL assumption — resources resolved from bundle
    }

    // ── Frontend URL Resolution (bundled resources only) ──

    func resolvedFrontendFileURL() -> URL? {
        let loc = resourceLocator
        hostState = .resolvingResources

        guard let url = loc.gridlineFrontendIndexURL else {
            hostState = .resourceNotFound("No bundled Gridline frontend found in Resources/GridlineFrontend/")
            return nil
        }

        guard loc.gridlineFrontendResourceExists() else {
            hostState = .resourceNotFound(
                "GridlineFrontend/index.html not found at expected bundle path"
            )
            return nil
        }

        let missing = loc.gridlineFrontendMissingSubresources()
        if !missing.isEmpty {
            hostState = .resourceNotFound(
                "Missing subdirectories: \(missing.joined(separator: ", "))"
            )
            return nil
        }

        return url
    }

    func frontendReadAccessURL() -> URL? {
        resourceLocator.gridlineFrontendRootURL
    }

    // ── Bootstrap Message ───────────────────────────

    func buildBootstrapMessage() -> BootstrapMessage? {
        let loc = resourceLocator
        let resourceResult: ResourceLoadResult
        if loc.gridlineFrontendIndexURL != nil,
           loc.gridlineFrontendResourceExists() {
            resourceResult = ResourceLoadResult(
                resolvedPathHash: loc.gridlineFrontendIndexContentsHash() ?? "sha256:unavailable",
                indexHTMLFound: true,
                subresourceCount: loc.gridlineFrontendAssetCount(),
                missingSubresources: loc.gridlineFrontendMissingSubresources(),
                loadError: nil
            )
        } else {
            resourceResult = ResourceLoadResult(
                resolvedPathHash: "sha256:unavailable",
                indexHTMLFound: false,
                subresourceCount: 0,
                missingSubresources: loc.gridlineFrontendMissingSubresources(),
                loadError: "Gridline frontend index.html not found in bundle"
            )
        }

        let payload = BootstrapPayload(
            resourceLoadResult: resourceResult,
            bridgeAvailable: true,
            supportedCapabilityKinds: [
                "host_state_query",
                "extension_status_query"
            ],
            refusalReasons: resourceResult.indexHTMLFound ? [] : ["frontend_resources_missing"],
            appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String,
            buildCommitSHA: nil,
            transportStatus: "local_file"
        )

        return BootstrapMessage(
            schemaVersion: BootstrapMessage.currentVersion,
            messageId: "bootstrap_\(sessionId)",
            kind: resourceResult.indexHTMLFound ? .hostReady : .hostResourceFailure,
            sessionId: sessionId,
            payload: payload,
            traceId: nil,
            sentAt: ISO8601DateFormatter().string(from: Date())
        )
    }

    // ── Message Dispatch ─────────────────────────────

    func handleFrontendMessage(_ message: [String: Any]) {
        let kind = message["kind"] as? String ?? ""
        let traceId = message["trace_id"] as? String ?? ""

        switch kind {
        case "get_host_state":
            sendToFrontend([
                "kind": "host_state",
                "state": hostState.label,
                "session_id": sessionId,
                "trace_id": traceId
            ])

        case "get_bootstrap":
            if let bootstrap = buildBootstrapMessage(),
               let dict = bootstrap.asDictionary() {
                sendToFrontend(dict)
            } else {
                sendToFrontend([
                    "kind": "bootstrap_failure",
                    "reason": "failed_to_encode_bootstrap_message",
                    "trace_id": traceId
                ])
            }

        case "open_file_dialog":
            sendToFrontend([
                "kind": "native_capability_refused",
                "capability": "open_file_dialog",
                "reason": "not_implemented_in_host_shell",
                "trace_id": traceId
            ])

        case "get_extension_status":
            sendToFrontend([
                "kind": "extension_status",
                "status": "unknown",
                "message": "Safari extension contract published; live extension implementation deferred to Q0",
                "trace_id": traceId
            ])

        default:
            sendToFrontend([
                "kind": "unrecognized_message",
                "original_kind": kind,
                "trace_id": traceId
            ])
        }
    }

    func sendToFrontend(_ message: [String: Any]) {
        messageBridge.sendToFrontend(message)
    }

    // ── Retry ────────────────────────────────────────

    func retryLoading() {
        // Reset to booting — never silently restore server assumption
        hostState = .booting
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in
            self?.hostState = .resolvingResources
        }
    }
}
