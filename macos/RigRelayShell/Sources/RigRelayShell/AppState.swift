import SwiftUI
import WebKit

// ── Host State ──────────────────────────────────────────────

enum HostState: Sendable, Equatable {
    case uninitialized
    case booting
    case launchingBackend
    case backendHealthy
    case backendFailed(String)
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
        case .launchingBackend: "Launching Backend..."
        case .backendHealthy: "Backend Running"
        case .backendFailed(let msg): "Backend Failed: \(msg)"
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
        case .uninitialized, .booting, .launchingBackend, .resolvingResources: "arrow.triangle.2.circlepath"
        case .backendHealthy: "checkmark.shield"
        case .backendFailed: "xmark.shield"
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
        case .backendFailed, .resourceNotFound, .resourceMalformed, .frontendLoadFailed,
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
    let safariExtensionHost = SafariExtensionHost(
        allowedBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
    )
    let extensionStatusVM: ExtensionStatusViewModel
    let backendManager = PythonBackendManager(
        port: 9876,
        commandPath: "uv",
        autoLaunch: false
    )

    var resourceLocator: ResourceLocator { ResourceLocator() }

    // Weak ref to the WebView for JS injection
    weak var webView: WKWebView?

    init() {
        self.extensionStatusVM = ExtensionStatusViewModel(
            extensionHost: safariExtensionHost
        )
    }

    // ── Boot Sequence ───────────────────────────────────

    func boot() {
        guard hostState == .uninitialized else { return }
        hostState = .booting
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
            guard let self else { return }
            self.hostState = .launchingBackend
            Task { @MainActor in await self.launchBackend() }
        }
    }

    private func launchBackend() async {
        if case .launchingBackend = hostState {
            // OK
        } else {
            return
        }

        await backendManager.launch()

        // Wait for backend to become healthy or fail
        // The health state is published; we observe it
        // For now, poll briefly
        for _ in 0..<60 { // 30 second timeout
            if backendManager.state == .healthy {
                hostState = .backendHealthy
                injectRuntimeConfig()
                // Proceed to resource resolution
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                    self?.hostState = .resolvingResources
                }
                return
            }
            if case .failed = backendManager.state {
                let reason: String
                if case .failed(let msg) = backendManager.state { reason = msg }
                else { reason = "Unknown failure" }
                hostState = .backendFailed(reason)
                return
            }
            if case .crashed = backendManager.state {
                let code: Int32
                if case .crashed(let c) = backendManager.state { code = c }
                else { code = -1 }
                hostState = .backendFailed("Backend crashed with exit code \(code)")
                return
            }
            try? await Task.sleep(nanoseconds: 500_000_000) // 500ms
        }
        hostState = .backendFailed("Backend health timeout")
    }

    private func injectRuntimeConfig() {
        guard let webView else { return }
        let configJSON = backendManager.runtimeConfigJSON
        let escapedConfig = configJSON
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "'", with: "\\'")
        let js = """
        window.__RIG_RELAY_RUNTIME_CONFIG__ = \(configJSON);
        """
        webView.evaluateJavaScript(js) { _, error in
            if let error {
                NSLog("[AppState] Runtime config injection failed: \(error.localizedDescription)")
            } else {
                NSLog("[AppState] Runtime config injected successfully")
            }
        }
    }

    // ── Frontend URL Resolution (bundled resources only) ──

    func resolvedFrontendFileURL() -> URL? {
        let loc = resourceLocator

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

        let transportKind: String
        if backendManager.state.isHealthy {
            transportKind = "native_loopback_bridge"
        } else if backendManager.state == .launching {
            transportKind = "backend_launching"
        } else {
            transportKind = "local_file"
        }

        let payload = BootstrapPayload(
            resourceLoadResult: resourceResult,
            bridgeAvailable: true,
            supportedCapabilityKinds: [
                "host_state_query",
                "extension_status_query",
                "websocket_transport",
            ],
            refusalReasons: resourceResult.indexHTMLFound ? [] : ["frontend_resources_missing"],
            appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String,
            buildCommitSHA: nil,
            transportStatus: transportKind
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
            extensionStatusVM.refresh()
            sendToFrontend([
                "kind": "extension_status",
                "status": extensionStatusVM.connectionState,
                "contract_version": extensionStatusVM.contractVersion,
                "supported_kinds": extensionStatusVM.supportedKinds,
                "convergence_complete": extensionStatusVM.convergenceComplete,
                "handoff_url": extensionStatusVM.handoffURL as Any? ?? NSNull(),
                "last_message": extensionStatusVM.lastMessageTimestamp as Any? ?? NSNull(),
                "blocking": extensionStatusVM.blockingRequirements,
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
        // Stop backend and reset — never silently restore server assumption
        backendManager.stop()
        hostState = .booting
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in
            self?.hostState = .launchingBackend
        }
    }
}
