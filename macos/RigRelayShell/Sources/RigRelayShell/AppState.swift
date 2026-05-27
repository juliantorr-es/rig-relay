import SwiftUI
import WebKit

// MARK: - Host State

enum HostState: Sendable, Equatable {
    case uninitialized
    case booting
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
        case .uninitialized, .booting: "arrow.triangle.2.circlepath"
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
        case .frontendLoadFailed, .bridgeUnavailable, .unsupportedOrigin, .error: true
        default: false
        }
    }
}

// MARK: - App State

@MainActor
final class AppState: ObservableObject {
    @Published var hostState: HostState = .uninitialized
    @Published var bridgeURL: URL?
    @Published var showExtensionStatus = false

    private let sessionId = "webkit_host_\(UUID().uuidString.prefix(8))"
    let messageBridge = NativeMessageBridge()

    init() {
        // Bridge URL — default to the production bridge server address
        bridgeURL = URL(string: "https://127.0.0.1:9876/index.html")
    }

    // MARK: — Message Dispatch

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

        case "open_file_dialog":
            // Native file dialog — future capability
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

    // MARK: — Frontend URL Resolution

    func resolvedBridgeURL() -> URL {
        if let url = bridgeURL {
            return url
        }
        return URL(string: "https://127.0.0.1:9876/index.html")!
    }

    // MARK: — Retry

    func retryLoading() {
        hostState = .loadingFrontend
    }
}
