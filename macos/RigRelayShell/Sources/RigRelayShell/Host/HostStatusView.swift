import SwiftUI

// ── Host Status View (S0: truthful resource-load and bridge states) ──

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
                .keyboardShortcut(.defaultAction)
            }

            if case .loadingFrontend = appState.hostState {
                ProgressView()
                    .scaleEffect(0.8)
                    .padding(.top, 4)
            } else if case .resolvingResources = appState.hostState {
                ProgressView()
                    .scaleEffect(0.8)
                    .padding(.top, 4)
            } else if case .booting = appState.hostState {
                ProgressView()
                    .scaleEffect(0.8)
                    .padding(.top, 4)
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
        case .resolvingResources:
            "Locating bundled Gridline frontend resources..."
        case .resourceNotFound(let detail):
            "The bundled Gridline frontend could not be found.\n\n\(detail)\n\nEnsure the application bundle includes Resources/GridlineFrontend/index.html."
        case .resourceMalformed(let detail):
            "The bundled Gridline frontend is corrupt or unreadable.\n\n\(detail)\n\nReinstall the application to restore frontend resources."
        case .loadingFrontend:
            "Loading bundled Gridline frontend..."
        case .frontendReady:
            nil
        case .frontendLoadFailed(let error):
            "The frontend could not be loaded: \(error)"
        case .bridgeUnavailable:
            "The native-to-frontend message bridge is not available. Restart the application."
        case .unsupportedOrigin(let url):
            "Navigation to an untrusted location was blocked: \(url)\n\nRig Relay only loads its bundled Gridline frontend. External navigation is refused."
        case .error(let msg):
            "An unexpected error occurred: \(msg)"
        case .extensionStatusUnknown:
            "Safari extension status is not yet available. Extension messaging contract is published for Q0 consumption."
        }
    }

    private var statusColor: Color {
        switch appState.hostState {
        case .frontendReady: RowHostDesign.statusOk
        case .loadingFrontend, .booting, .uninitialized, .resolvingResources: RowHostDesign.statusInfo
        case .frontendLoadFailed, .bridgeUnavailable, .unsupportedOrigin, .error: RowHostDesign.statusError
        case .resourceNotFound, .resourceMalformed: RowHostDesign.statusError
        case .extensionStatusUnknown: RowHostDesign.statusWarn
        }
    }
}

// ── RowHost Design Tokens ──────────────────────────────────

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
