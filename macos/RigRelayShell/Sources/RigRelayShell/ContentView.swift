import SwiftUI

// MARK: - Main Content Shell

struct ContentView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        NavigationSplitView {
            sidebar
                .navigationSplitViewColumnWidth(min: 200, ideal: 220, max: 260)
        } detail: {
            detailContent
        }
        .frame(minWidth: 720, minHeight: 520)
    }

    // MARK: - Sidebar

    var sidebar: some View {
        VStack(spacing: 0) {
            // App header
            VStack(spacing: GridlineDesign.spacingXS) {
                HStack(spacing: GridlineDesign.spacingSM) {
                    Image(systemName: "shield.lefthalf.filled")
                        .font(.system(size: 24))
                        .foregroundColor(GridlineDesign.accent)
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Rig Relay")
                            .font(GridlineDesign.fontHeadline)
                        Text("Gridline Developer Studio")
                            .font(GridlineDesign.fontCaption2)
                            .foregroundColor(GridlineDesign.textTertiary)
                    }
                }
            }
            .padding(.horizontal, GridlineDesign.spacingMD)
            .padding(.vertical, GridlineDesign.spacingLG)

            Divider()

            // Navigation tabs
            List(selection: $appState.selectedTab) {
                ForEach(GridlineTab.allCases, id: \.self) { tab in
                    NavigationLink(value: tab) {
                        Label {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(tab.rawValue)
                                    .font(GridlineDesign.fontBody)
                                Text(tab.description)
                                    .font(GridlineDesign.fontCaption2)
                                    .foregroundColor(GridlineDesign.textTertiary)
                                    .lineLimit(1)
                            }
                        } icon: {
                            Image(systemName: tab.iconName)
                                .foregroundColor(tab == appState.selectedTab ? GridlineDesign.accent : GridlineDesign.textSecondary)
                        }
                    }
                }
            }
            .listStyle(.sidebar)

            Divider()

            // Provider evidence mini-section (C lane — published)
            providerEvidenceMini

            Divider()

            // Footer
            footerView
        }
    }

    // MARK: - Provider Evidence Mini (Lane C)

    @ViewBuilder
    var providerEvidenceMini: some View {
        if let providers = appState.projection.providerEvidence {
            VStack(alignment: .leading, spacing: GridlineDesign.spacingXS) {
                HStack {
                    Image(systemName: providers.integrityVerified ? "checkmark.shield" : "xmark.shield")
                        .font(.system(size: 10))
                        .foregroundColor(providers.integrityVerified ? GridlineDesign.statusOk : GridlineDesign.statusError)
                    Text("Provider Evidence")
                        .font(GridlineDesign.fontCaption2)
                        .foregroundColor(GridlineDesign.textSecondary)
                }

                ForEach(providers.providers.prefix(3)) { provider in
                    HStack(spacing: GridlineDesign.spacingXS) {
                        Circle()
                            .fill(provider.degraded ? GridlineDesign.statusWarn : GridlineDesign.statusOk)
                            .frame(width: 4, height: 4)
                        Text(provider.name)
                            .font(GridlineDesign.fontCaption2)
                            .foregroundColor(GridlineDesign.textPrimary)
                        Spacer()
                        Text("\(provider.modelsAvailable) models")
                            .font(.system(size: 9))
                            .foregroundColor(GridlineDesign.textTertiary)
                    }
                }

                if providers.corruptEvents > 0 {
                    HStack(spacing: GridlineDesign.spacingXS) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundColor(GridlineDesign.statusError)
                            .font(.system(size: 9))
                        Text("\(providers.corruptEvents) corrupt events")
                            .font(.system(size: 9))
                            .foregroundColor(GridlineDesign.statusError)
                    }
                }
            }
            .padding(.horizontal, GridlineDesign.spacingMD)
            .padding(.vertical, GridlineDesign.spacingSM)
        }
    }

    // MARK: - Footer

    var footerView: some View {
        VStack(alignment: .leading, spacing: GridlineDesign.spacingXS) {
            if appState.isFixtureMode {
                HStack(spacing: GridlineDesign.spacingXS) {
                    Image(systemName: "square.dotted")
                        .font(.system(size: 8))
                        .foregroundColor(.purple)
                    Text("Fixture mode")
                        .font(.system(size: 9))
                        .foregroundColor(.purple)
                }
            }

            HStack {
                Text("v0.2.0-dev")
                    .font(.system(size: 9))
                    .foregroundColor(GridlineDesign.textTertiary)

                Spacer()

                Button("Quit") {
                    NSApplication.shared.terminate(nil)
                }
                .buttonStyle(.borderless)
                .font(.system(size: 9))
            }

            if !appState.statusMessage.isEmpty {
                Text(appState.statusMessage)
                    .font(.system(size: 8))
                    .foregroundColor(GridlineDesign.textTertiary)
                    .lineLimit(2)
            }
        }
        .padding(.horizontal, GridlineDesign.spacingMD)
        .padding(.vertical, GridlineDesign.spacingSM)
    }

    // MARK: - Detail Content

    @ViewBuilder
    var detailContent: some View {
        switch appState.selectedTab {
        case .connect:
            ConnectView()
        case .repositories:
            RepositoryEstateView()
        case .projectStudio:
            ProjectStudioView()
        case .inference:
            InferenceStudioView()
        case .publish:
            PublishPreviewView()
        }
    }
}
