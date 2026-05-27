import SwiftUI

// ── Main Content Shell (S0: Native WebKit Host Boot Boundary) ──

struct ContentView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        ZStack {
            // Primary: WebKit-hosted Gridline frontend (bundled, local file)
            if let fileURL = appState.resolvedFrontendFileURL(),
               let readAccessURL = appState.frontendReadAccessURL() {
                WebKitWebView(
                    fileURL: fileURL,
                    readAccessURL: readAccessURL,
                    messageBridge: appState.messageBridge,
                    onLoadStateChange: { newState in
                        appState.hostState = newState
                    },
                    onWebViewCreated: { webView in
                        appState.webView = webView
                    },
                    allowedBaseURL: readAccessURL
                )
                .opacity(appState.hostState == .frontendReady ? 1 : 0)
            } else {
                // No viable frontend resource — show status overlay
                Color.clear
            }

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
        .onAppear {
            if appState.hostState == .uninitialized {
                appState.boot()
            }
        }
    }
}
