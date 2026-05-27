import SwiftUI

struct PublishPreviewView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: GridlineDesign.spacing2XL) {
                headerSection
                surfaceStateSection

                if publish.surfaceState == .empty {
                    emptyState
                } else {
                    pagesReadinessSection
                    projectPagePreviewSection
                    approvalSection
                    portfolioDeferredBanner
                }
            }
            .padding(GridlineDesign.spacing2XL)
            .frame(maxWidth: 800)
        }
    }

    var publish: PublishPreviewProjection { appState.projection.publishPreview }

    // MARK: - Header

    var headerSection: some View {
        VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
            SectionHeaderView("Publish Preview")
            Text("Public-safe project page — preview before publishing to GitHub Pages")
                .font(GridlineDesign.fontCallout)
                .foregroundColor(GridlineDesign.textSecondary)
            if appState.isFixtureMode {
                FixtureModeBannerView()
            }
            DeferredServiceBannerView("J0 Publication / L0 Profile Compilation")
        }
    }

    var surfaceStateSection: some View {
        SurfaceStateBannerView(publish.surfaceState, message: stateMessage)
    }

    var stateMessage: String? {
        switch publish.surfaceState {
        case .empty: "No project page ready for publication. Complete a project investigation in Project Studio first."
        case .reviewRequired: "A public-safe project page has been prepared. Review and approve for publication."
        case .published: "Project page published to GitHub Pages."
        case .corrupt: "Project page evidence integrity failed. Publication blocked until evidence is verified."
        default: nil
        }
    }

    // MARK: - Empty State

    var emptyState: some View {
        CardView(padding: GridlineDesign.spacing2XL) {
            VStack(spacing: GridlineDesign.spacingLG) {
                Image(systemName: "paperplane")
                    .font(.system(size: 48))
                    .foregroundColor(GridlineDesign.textTertiary)
                Text("Nothing to publish yet")
                    .font(GridlineDesign.fontTitle3)
                Text("Complete a project investigation in Project Studio to generate a public-safe project page candidate. The candidate will appear here for review before publication.")
                    .font(GridlineDesign.fontCallout)
                    .foregroundColor(GridlineDesign.textSecondary)
                    .multilineTextAlignment(.center)
                Button("Preview Publish") {
                    appState.dispatchIntent(appState.makeIntent(kind: .previewPublish))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: - Pages Readiness

    @ViewBuilder
    var pagesReadinessSection: some View {
        if let pages = publish.pagesReadiness {
            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                    HStack {
                        Image(systemName: "gearshape.2")
                            .foregroundColor(GridlineDesign.statusInfo)
                        Text("GitHub Pages Status")
                            .font(GridlineDesign.fontHeadline)
                        Spacer()
                        StatusBadgeView(
                            "Pages",
                            value: pages.pagesEnabled ? "Enabled" : "Disabled",
                            color: pages.pagesEnabled ? GridlineDesign.statusOk : GridlineDesign.statusError
                        )
                    }

                    HStack(spacing: GridlineDesign.spacingLG) {
                        StatusBadgeView(
                            "Branch",
                            value: pages.branchConfigured ? "Configured" : "Not configured",
                            color: pages.branchConfigured ? GridlineDesign.statusOk : GridlineDesign.statusWarn
                        )
                        if let path = pages.sourcePath {
                            StatusBadgeView("Source", value: path, color: GridlineDesign.textPrimary)
                        }
                        if let deployStatus = pages.deploymentStatus {
                            StatusBadgeView("Deployment", value: deployStatus, color: GridlineDesign.statusInfo)
                        }
                    }

                    if let error = pages.errorMessage {
                        HStack(spacing: GridlineDesign.spacingSM) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundColor(GridlineDesign.statusError)
                            Text(error)
                                .font(GridlineDesign.fontCallout)
                                .foregroundColor(GridlineDesign.statusError)
                        }
                        .padding(GridlineDesign.spacingSM)
                        .background(GridlineDesign.statusError.opacity(0.08), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusMD))
                    }

                    if let deployed = pages.lastDeployedAt {
                        Text("Last deployed at \(deployed)")
                            .font(GridlineDesign.fontCaption2)
                            .foregroundColor(GridlineDesign.textTertiary)
                    }
                }
            }
        }
    }

    // MARK: - Project Page Preview

    @ViewBuilder
    var projectPagePreviewSection: some View {
        if let page = publish.projectPagePreview {
            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingMD) {
                    // Header
                    HStack {
                        VStack(alignment: .leading, spacing: GridlineDesign.spacingXS) {
                            Text("Project Page Preview")
                                .font(GridlineDesign.fontHeadline)
                            Text(page.projectName)
                                .font(GridlineDesign.fontTitle2)
                            Text(page.tagline)
                                .font(GridlineDesign.fontCallout)
                                .foregroundColor(GridlineDesign.textSecondary)
                        }
                        Spacer()
                        if page.publicSafeVerified {
                            HStack(spacing: GridlineDesign.spacingXS) {
                                Image(systemName: "checkmark.seal.fill")
                                    .foregroundColor(GridlineDesign.statusOk)
                                Text("Public Safe")
                                    .font(GridlineDesign.fontCaption)
                                    .fontWeight(.medium)
                                    .foregroundColor(GridlineDesign.statusOk)
                            }
                            .padding(.horizontal, GridlineDesign.spacingSM)
                            .padding(.vertical, GridlineDesign.spacingSM)
                            .background(GridlineDesign.statusOk.opacity(0.08), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusMD))
                        } else {
                            HStack(spacing: GridlineDesign.spacingXS) {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .foregroundColor(GridlineDesign.statusError)
                                Text("NOT SAFE")
                                    .font(GridlineDesign.fontCaption)
                                    .fontWeight(.bold)
                                    .foregroundColor(GridlineDesign.statusError)
                            }
                            .padding(.horizontal, GridlineDesign.spacingSM)
                            .padding(.vertical, GridlineDesign.spacingSM)
                            .background(GridlineDesign.statusError.opacity(0.08), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusMD))
                        }
                    }

                    Divider()

                    // Status Overview
                    Text(page.statusOverview)
                        .font(GridlineDesign.fontCallout)
                        .foregroundColor(GridlineDesign.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)

                    Divider()

                    // Sections
                    Text("Page Sections")
                        .font(GridlineDesign.fontCaption)
                        .foregroundColor(GridlineDesign.textSecondary)

                    ForEach(page.sections) { section in
                        VStack(alignment: .leading, spacing: GridlineDesign.spacingXS) {
                            HStack {
                                Text(section.title)
                                    .font(GridlineDesign.fontCallout)
                                    .fontWeight(.medium)
                                Spacer()
                                PrivacyBadgeView(privacyClass: section.privacyClass)
                                EvidenceStatusIndicator(status: section.evidenceStatus, label: "")
                            }
                            Text(section.contentHash)
                                .font(GridlineDesign.fontMonospaced)
                                .foregroundColor(GridlineDesign.textTertiary)
                        }
                        .padding(GridlineDesign.spacingSM)
                        .background(GridlineDesign.surfaceSecondary, in: RoundedRectangle(cornerRadius: GridlineDesign.radiusMD))
                    }

                    // Withheld Content
                    if !page.withheldContent.isEmpty {
                        Divider()
                        HStack(spacing: GridlineDesign.spacingSM) {
                            Image(systemName: "eye.slash.fill")
                                .foregroundColor(GridlineDesign.statusWarn)
                            Text("Content Withheld from Publication")
                                .font(GridlineDesign.fontCaption)
                                .fontWeight(.medium)
                                .foregroundColor(GridlineDesign.statusWarn)
                        }
                        ForEach(page.withheldContent, id: \.self) { item in
                            HStack(spacing: GridlineDesign.spacingSM) {
                                Text("•")
                                    .foregroundColor(GridlineDesign.textTertiary)
                                Text(item)
                                    .font(GridlineDesign.fontCaption2)
                                    .foregroundColor(GridlineDesign.textSecondary)
                            }
                        }
                    }
                }
            }
        }
    }

    // MARK: - Approval

    @ViewBuilder
    var approvalSection: some View {
        if publish.approvalRequired {
            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingMD) {
                    HStack {
                        Image(systemName: "checkmark.shield")
                            .foregroundColor(GridlineDesign.statusWarn)
                        Text("Approval Required")
                            .font(GridlineDesign.fontHeadline)
                    }

                    Text("This project page requires your explicit approval before publication. Review the preview above carefully — once published, the page is publicly visible on GitHub Pages.")
                        .font(GridlineDesign.fontCallout)
                        .foregroundColor(GridlineDesign.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)

                    Text("The published page contains only deliberately publishable content: project name, accomplishment summaries, released boundaries, and evidence-digest references. No source code, secrets, or private data appear.")
                        .font(GridlineDesign.fontCaption)
                        .foregroundColor(GridlineDesign.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)

                    HStack(spacing: GridlineDesign.spacingMD) {
                        Button(action: {
                            appState.dispatchIntent(appState.makeIntent(
                                kind: .approvePublication,
                                mutationClass: .releaseAffectingMutation
                            ))
                        }) {
                            Label("Approve Publication", systemImage: "checkmark.seal")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .tint(GridlineDesign.statusOk)

                        Button(role: .destructive, action: {}) {
                            Label("Reject", systemImage: "xmark.seal")
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.large)
                    }
                }
            }
        }
    }

    // MARK: - Portfolio Deferred

    @ViewBuilder
    var portfolioDeferredBanner: some View {
        if publish.portfolioInclusionDeferred {
            CardView {
                HStack(spacing: GridlineDesign.spacingSM) {
                    Image(systemName: "clock")
                        .foregroundColor(GridlineDesign.statusDeferred)
                    VStack(alignment: .leading, spacing: GridlineDesign.spacingXS) {
                        Text("Portfolio Integration Deferred")
                            .font(GridlineDesign.fontCaption)
                            .fontWeight(.medium)
                        Text("The developer portfolio site will be available once multiple approved project profiles exist. This requires a released L0 boundary or I-level integration milestone.")
                            .font(GridlineDesign.fontCaption2)
                            .foregroundColor(GridlineDesign.textSecondary)
                    }
                }
            }
        }
    }
}
