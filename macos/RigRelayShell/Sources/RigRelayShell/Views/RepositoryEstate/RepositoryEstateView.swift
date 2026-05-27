import SwiftUI

struct RepositoryEstateView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: GridlineDesign.spacing2XL) {
                headerSection
                surfaceStateSection
                if estate.surfaceState == .empty {
                    emptyState
                } else {
                    summaryCards
                    repositoryList
                    importStatusSection
                }
            }
            .padding(GridlineDesign.spacing2XL)
            .frame(maxWidth: 800)
        }
    }

    var estate: RepositoryEstateProjection { appState.projection.repositoryEstate }

    // MARK: - Header

    var headerSection: some View {
        VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
            SectionHeaderView("Repository Estate")
            Text("Your accessible repositories — import, study, and classify")
                .font(GridlineDesign.fontCallout)
                .foregroundColor(GridlineDesign.textSecondary)
            if appState.isFixtureMode {
                FixtureModeBannerView()
            }
            DeferredServiceBannerView("J0 GitHub Workspace / Repository Intake")
        }
    }

    var surfaceStateSection: some View {
        SurfaceStateBannerView(estate.surfaceState, message: stateMessage)
    }

    var stateMessage: String? {
        switch estate.surfaceState {
        case .ready: "\(estate.repositories.count) repositories available."
        case .empty: "No repositories found. Connect Carte Blanche and select repositories to study."
        case .importing: "Repository import in progress..."
        case .error: "Repository access error. Check GitHub connection."
        default: nil
        }
    }

    // MARK: - Empty State

    var emptyState: some View {
        CardView(padding: GridlineDesign.spacing2XL) {
            VStack(spacing: GridlineDesign.spacingLG) {
                Image(systemName: "folder.badge.questionmark")
                    .font(.system(size: 48))
                    .foregroundColor(GridlineDesign.textTertiary)
                Text("No repositories connected")
                    .font(GridlineDesign.fontTitle3)
                Text("Go to Connect → Carte Blanche to authorize GitHub access and select repositories for study.")
                    .font(GridlineDesign.fontCallout)
                    .foregroundColor(GridlineDesign.textSecondary)
                    .multilineTextAlignment(.center)
                Button("Go to Connect") {
                    appState.selectedTab = .connect
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: - Summary Cards

    var summaryCards: some View {
        HStack(spacing: GridlineDesign.spacingMD) {
            summaryCard(
                title: "Public",
                count: estate.publicCount,
                icon: "globe",
                color: GridlineDesign.statusOk
            )
            summaryCard(
                title: "Private",
                count: estate.privateCount,
                icon: "lock",
                color: GridlineDesign.statusWarn
            )
            summaryCard(
                title: "Ready",
                count: estate.syncReadiness ? 1 : 0,
                icon: "checkmark.circle",
                color: estate.syncReadiness ? GridlineDesign.statusOk : GridlineDesign.statusInactive
            )
        }
    }

    func summaryCard(title: String, count: Int, icon: String, color: Color) -> some View {
        CardView(padding: GridlineDesign.spacingMD) {
            VStack(alignment: .leading, spacing: GridlineDesign.spacingXS) {
                HStack {
                    Image(systemName: icon)
                        .foregroundColor(color)
                    Text(title)
                        .font(GridlineDesign.fontCaption)
                        .foregroundColor(GridlineDesign.textSecondary)
                }
                Text("\(count)")
                    .font(GridlineDesign.fontLargeTitle)
                    .foregroundColor(GridlineDesign.textPrimary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // MARK: - Repository List

    var repositoryList: some View {
        VStack(alignment: .leading, spacing: GridlineDesign.spacingMD) {
            SectionHeaderView("Repositories")

            ForEach(estate.repositories) { repo in
                repositoryRow(repo)
            }
        }
    }

    func repositoryRow(_ repo: RepositorySummary) -> some View {
        CardView {
            VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: GridlineDesign.spacingXS) {
                        HStack(spacing: GridlineDesign.spacingSM) {
                            Text(repo.name)
                                .font(GridlineDesign.fontHeadline)
                                .foregroundColor(GridlineDesign.textPrimary)
                            if repo.isPrivate {
                                PrivacyBadgeView(privacyClass: .internalOnly)
                            } else {
                                PrivacyBadgeView(privacyClass: .publicSafe)
                            }
                        }
                        Text(repo.fullName)
                            .font(GridlineDesign.fontCaption)
                            .foregroundColor(GridlineDesign.textTertiary)
                        if let desc = repo.description {
                            Text(desc)
                                .font(GridlineDesign.fontCallout)
                                .foregroundColor(GridlineDesign.textSecondary)
                                .lineLimit(2)
                        }
                    }

                    Spacer()

                    importStatusView(repo.importStatus)
                }

                HStack(spacing: GridlineDesign.spacingLG) {
                    if let lang = repo.language {
                        StatusBadgeView("Language", value: lang, color: GridlineDesign.statusInfo)
                    }
                    if let branch = repo.defaultBranch {
                        StatusBadgeView("Branch", value: branch, color: GridlineDesign.textSecondary)
                    }
                    PublicationStatusBadge(class: repo.publicationClass)

                    Spacer()

                    if repo.id == estate.selectedRepositoryId {
                        Text("Selected")
                            .font(GridlineDesign.fontCaption)
                            .foregroundColor(GridlineDesign.accent)
                            .padding(.horizontal, GridlineDesign.spacingSM)
                            .padding(.vertical, 2)
                            .background(GridlineDesign.accentMuted, in: RoundedRectangle(cornerRadius: GridlineDesign.radiusSM))
                    }
                }
            }
        }
    }

    func importStatusView(_ status: RepositoryImportStatus) -> some View {
        HStack(spacing: GridlineDesign.spacingXS) {
            Image(systemName: importIcon(status))
                .font(.system(size: 12))
            Text(importLabel(status))
                .font(GridlineDesign.fontCaption2)
                .fontWeight(.medium)
        }
        .foregroundColor(importColor(status))
        .padding(.horizontal, GridlineDesign.spacingSM)
        .padding(.vertical, GridlineDesign.spacingXS)
        .background(importColor(status).opacity(0.1), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusSM))
    }

    func importIcon(_ status: RepositoryImportStatus) -> String {
        switch status {
        case .notImported: "arrow.down.circle"
        case .cloning: "arrow.down.circle.dotted"
        case .cloned: "checkmark.circle"
        case .syncing: "arrow.triangle.2.circlepath"
        case .synced: "checkmark.circle.fill"
        case .failed: "xmark.circle"
        case .unauthorized: "lock.circle"
        }
    }

    func importLabel(_ status: RepositoryImportStatus) -> String {
        switch status {
        case .notImported: "Not imported"
        case .cloning: "Cloning..."
        case .cloned: "Cloned"
        case .syncing: "Syncing..."
        case .synced: "Synced"
        case .failed: "Failed"
        case .unauthorized: "Unauthorized"
        }
    }

    func importColor(_ status: RepositoryImportStatus) -> Color {
        switch status {
        case .synced, .cloned: GridlineDesign.statusOk
        case .cloning, .syncing: GridlineDesign.statusInfo
        case .notImported: GridlineDesign.textTertiary
        case .failed, .unauthorized: GridlineDesign.statusError
        }
    }

    // MARK: - Import Status (detail)

    @ViewBuilder
    var importStatusSection: some View {
        if let clone = estate.cloneStatus {
            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                    HStack {
                        Image(systemName: "arrow.down.doc")
                        Text("Import Status")
                            .font(GridlineDesign.fontHeadline)
                    }

                    HStack {
                        StatusBadgeView("Status", value: importLabel(clone.status), color: importColor(clone.status))
                        if let progress = clone.progress, clone.status == .cloning {
                            StatusBadgeView("Progress", value: "\(Int(progress * 100))%", color: GridlineDesign.statusInfo)
                        }
                    }

                    if let error = clone.errorMessage {
                        HStack(spacing: GridlineDesign.spacingSM) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundColor(GridlineDesign.statusError)
                            Text(error)
                                .font(GridlineDesign.fontCallout)
                                .foregroundColor(GridlineDesign.statusError)
                        }
                    }

                    if clone.status == .cloning, let progress = clone.progress {
                        ProgressView(value: progress)
                            .tint(GridlineDesign.statusInfo)
                    }

                    if let started = clone.startedAt {
                        Text("Started at \(started)")
                            .font(GridlineDesign.fontCaption2)
                            .foregroundColor(GridlineDesign.textTertiary)
                    }
                }
            }
        }
    }
}

// MARK: - Publication Status Badge

struct PublicationStatusBadge: View {
    let publicationClass: PrivacyClass

    init(class: PrivacyClass) {
        self.publicationClass = `class`
    }

    var body: some View {
        HStack(spacing: GridlineDesign.spacingXS) {
            Circle()
                .fill(color)
                .frame(width: 4, height: 4)
            Text(label)
                .font(GridlineDesign.fontCaption2)
                .foregroundColor(color)
        }
    }

    var label: String {
        switch publicationClass {
        case .publicSafe: "Can publish"
        case .contentLight: "Content-light"
        case .internalOnly: "Private only"
        }
    }

    var color: Color {
        switch publicationClass {
        case .publicSafe: GridlineDesign.statusOk
        case .contentLight: GridlineDesign.statusInfo
        case .internalOnly: GridlineDesign.statusError
        }
    }
}
