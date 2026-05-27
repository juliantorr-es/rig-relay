import SwiftUI

struct ConnectView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: GridlineDesign.spacing2XL) {
                headerSection
                surfaceStateSection
                explanationCards
                installationStatusSection
                actionSection
            }
            .padding(GridlineDesign.spacing2XL)
            .frame(maxWidth: 700)
        }
    }

    // MARK: - Header

    var headerSection: some View {
        VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
            SectionHeaderView("Carte Blanche")
            Text("Governed repository access for Rig Relay")
                .font(GridlineDesign.fontCallout)
                .foregroundColor(GridlineDesign.textSecondary)
            if appState.isFixtureMode {
                FixtureModeBannerView()
            }
            DeferredServiceBannerView("J0 GitHub Workspace / Carte Blanche")
        }
    }

    // MARK: - Surface State

    @ViewBuilder
    var surfaceStateSection: some View {
        let connect = appState.projection.connectState
        SurfaceStateBannerView(connect.surfaceState, message: connectStateMessage(connect))
    }

    func connectStateMessage(_ connect: ConnectProjection) -> String? {
        switch connect.surfaceState {
        case .ready: "Carte Blanche is ready to connect. Choose a GitHub installation."
        case .connecting: "Connecting to GitHub installation..."
        case .authorized: "GitHub installation authorized. \(connect.grantedCapabilities.count) capabilities granted."
        case .permissionBlocked: "Permission blocked — missing required scopes."
        case .empty: "No Carte Blanche connection established. Connect GitHub to begin."
        default: nil
        }
    }

    // MARK: - Explanation Cards

    var explanationCards: some View {
        let connect = appState.projection.connectState
        return VStack(spacing: GridlineDesign.spacingMD) {
            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                    HStack {
                        Image(systemName: "hand.raised")
                            .foregroundColor(GridlineDesign.accent)
                        Text("What Carte Blanche grants")
                            .font(GridlineDesign.fontHeadline)
                    }
                    Text(connect.carteBlancheDescription)
                        .font(GridlineDesign.fontBody)
                        .foregroundColor(GridlineDesign.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                    HStack {
                        Image(systemName: "lock.shield")
                            .foregroundColor(GridlineDesign.statusWarn)
                        Text("Private study vs. public publication")
                            .font(GridlineDesign.fontHeadline)
                    }
                    Text(connect.privateStudyExplanation)
                        .font(GridlineDesign.fontBody)
                        .foregroundColor(GridlineDesign.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Divider()
                    Text(connect.publicPublicationExplanation)
                        .font(GridlineDesign.fontBody)
                        .foregroundColor(GridlineDesign.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                    HStack {
                        Image(systemName: "checkmark.shield")
                            .foregroundColor(GridlineDesign.statusOk)
                        Text("Granted Capabilities")
                            .font(GridlineDesign.fontHeadline)
                    }
                    ForEach(connect.grantedCapabilities, id: \.self) { cap in
                        HStack(spacing: GridlineDesign.spacingSM) {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundColor(GridlineDesign.statusOk)
                                .font(.system(size: 12))
                            Text(cap)
                                .font(GridlineDesign.fontCallout)
                                .foregroundColor(GridlineDesign.textPrimary)
                        }
                    }
                    if !connect.missingPermissions.isEmpty {
                        Divider()
                        Text("Missing Permissions")
                            .font(GridlineDesign.fontCaption)
                            .fontWeight(.medium)
                            .foregroundColor(GridlineDesign.statusWarn)
                        ForEach(connect.missingPermissions, id: \.self) { perm in
                            HStack(spacing: GridlineDesign.spacingSM) {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .foregroundColor(GridlineDesign.statusWarn)
                                    .font(.system(size: 12))
                                Text(perm)
                                    .font(GridlineDesign.fontCallout)
                                    .foregroundColor(GridlineDesign.textSecondary)
                            }
                        }
                    }
                }
            }
        }
    }

    // MARK: - Installation Status

    @ViewBuilder
    var installationStatusSection: some View {
        let connect = appState.projection.connectState
        if let install = connect.githubInstallationStatus {
            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                    HStack {
                        Image(systemName: install.installed ? "checkmark.seal.fill" : "xmark.seal.fill")
                            .foregroundColor(install.installed ? GridlineDesign.statusOk : GridlineDesign.statusError)
                        Text("GitHub Installation")
                            .font(GridlineDesign.fontHeadline)
                    }
                    if install.installed {
                        HStack {
                            StatusBadgeView("Account", value: install.accountName ?? "—", color: GridlineDesign.textPrimary)
                            StatusBadgeView("Rate Limit", value: "\(install.rateLimitRemaining ?? 0)", color: GridlineDesign.statusOk)
                        }
                        HStack {
                            Text("Scopes:")
                                .font(GridlineDesign.fontCaption)
                                .foregroundColor(GridlineDesign.textSecondary)
                            ForEach(install.scopes, id: \.self) { scope in
                                Text(scope)
                                    .font(GridlineDesign.fontCaption2)
                                    .foregroundColor(GridlineDesign.textPrimary)
                                    .padding(.horizontal, GridlineDesign.spacingXS)
                                    .padding(.vertical, 1)
                                    .background(GridlineDesign.borderEmphasis, in: RoundedRectangle(cornerRadius: GridlineDesign.radiusSM))
                            }
                        }
                        if let connectedAt = install.connectedAt {
                            Text("Connected at \(connectedAt)")
                                .font(GridlineDesign.fontCaption2)
                                .foregroundColor(GridlineDesign.textTertiary)
                        }
                    } else {
                        Text("No GitHub installation detected. Connect to begin.")
                            .font(GridlineDesign.fontCallout)
                            .foregroundColor(GridlineDesign.textSecondary)
                    }
                }
            }
        }
    }

    // MARK: - Actions

    var actionSection: some View {
        let connect = appState.projection.connectState
        return HStack(spacing: GridlineDesign.spacingSM) {
            if !connect.connectionReady {
                Button(action: {
                    appState.dispatchIntent(appState.makeIntent(kind: .connectGitHub))
                }) {
                    Label("Connect GitHub", systemImage: "link")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            } else {
                Button(action: {
                    appState.selectedTab = .repositories
                }) {
                    Label("View Repositories", systemImage: "folder")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }

            Button(action: {
                appState.dispatchIntent(appState.makeIntent(kind: .refreshProjection, mutationClass: .readOnly))
            }) {
                Label("Refresh", systemImage: "arrow.triangle.2.circlepath")
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
        }
    }
}
