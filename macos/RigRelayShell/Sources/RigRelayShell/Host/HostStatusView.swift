import SwiftUI

// MARK: - Host Status View (loading, failed, disconnected, extension-status)

struct HostStatusView: View {
    @ObservedObject var appState: AppState

    var body: some View {
        VStack(spacing: RowHostDesign.spacingLG) {
            Image(systemName: appState.hostState.iconName)
                .font(.system(size: 48))
                .foregroundColor(statusColor)

            Text(appState.hostState.label)
                .font(RowHostDesign.fontTitle2)
                .foregroundColor(RowHostDesign.textPrimary)

            if let detail = detailMessage {
                Text(detail)
                    .font(RowHostDesign.fontCallout)
                    .foregroundColor(RowHostDesign.textSecondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, RowHostDesign.spacing2XL)
            }

            if appState.hostState.isTerminal {
                Button("Retry") {
                    appState.retryLoading()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }

            if case .loadingFrontend = appState.hostState {
                ProgressView()
                    .scaleEffect(0.8)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(RowHostDesign.surfaceSecondary)
    }

    private var detailMessage: String? {
        switch appState.hostState {
        case .uninitialized:
            "Initializing Rig Relay native host..."
        case .booting:
            "Starting application services..."
        case .loadingFrontend:
            "Connecting to the Rig Relay bridge server. Ensure the bridge is running."
        case .frontendReady:
            nil
        case .frontendLoadFailed(let error):
            "The frontend could not be loaded: \(error)\n\nCheck that the Rig Relay bridge server is running and accessible at the configured URL."
        case .bridgeUnavailable:
            "The Rig Relay bridge server is not responding. Verify the server is running and try again."
        case .unsupportedOrigin(let url):
            "Navigation to an untrusted origin was blocked: \(url)\n\nRig Relay only loads the trusted bridge frontend from the configured local server."
        case .error(let msg):
            "An unexpected error occurred: \(msg)"
        case .extensionStatusUnknown:
            "Safari extension status is not yet available. Extension messaging contract is published for Q0 consumption."
        }
    }

    private var statusColor: Color {
        switch appState.hostState {
        case .frontendReady: RowHostDesign.statusOk
        case .loadingFrontend, .booting, .uninitialized: RowHostDesign.statusInfo
        case .frontendLoadFailed, .bridgeUnavailable, .unsupportedOrigin, .error: RowHostDesign.statusError
        case .extensionStatusUnknown: RowHostDesign.statusWarn
        }
    }
}

// MARK: - RowHost Design Tokens (minimal host-only tokens)

enum RowHostDesign {
    static let textPrimary = Color.primary
    static let textSecondary = Color.secondary
    static let surfaceSecondary = Color(nsColor: .windowBackgroundColor)
    static let statusOk = Color.green
    static let statusInfo = Color.blue
    static let statusWarn = Color.orange
    static let statusError = Color.red
    static let fontTitle2 = Font.title2.weight(.medium)
    static let fontCallout = Font.callout
    static let spacingSM: CGFloat = 8
    static let spacingMD: CGFloat = 12
    static let spacingLG: CGFloat = 16
    static let spacing2XL: CGFloat = 32
}
