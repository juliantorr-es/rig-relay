import SwiftUI

// MARK: - Main Content Shell (N1: WebKit Host, not product tabs)

struct ContentView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        ZStack {
            // Primary: WebKit-hosted bridge frontend
            WebKitWebView(
                url: appState.resolvedBridgeURL(),
                messageBridge: appState.messageBridge,
                onLoadStateChange: { newState in
                    appState.hostState = newState
                },
                trustedHost: hostName,
                trustedPort: hostPort
            )
            .opacity(appState.hostState == .frontendReady ? 1 : 0)

            // Overlay: Host status during boot, loading, or failure
            if appState.hostState != .frontendReady {
                HostStatusView(appState: appState)
            }
        }
        .frame(minWidth: 800, idealWidth: 1200, maxWidth: .infinity,
               minHeight: 560, idealHeight: 800, maxHeight: .infinity)
        .onReceive(NotificationCenter.default.publisher(for: .rigFrontendMessageReceived)) { notification in
            guard let body = notification.userInfo as? [String: Any] else { return }
            appState.handleFrontendMessage(body)
        }
    }

    private var hostName: String {
        "127.0.0.1"
    }

    private var hostPort: Int {
        9876
    }
}
