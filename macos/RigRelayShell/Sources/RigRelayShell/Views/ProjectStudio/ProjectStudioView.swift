import SwiftUI

struct ProjectStudioView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: GridlineDesign.spacing2XL) {
                headerSection
                surfaceStateSection

                if studio.surfaceState == .empty {
                    emptyState
                } else {
                    investigationSection
                    understandingSection
                    evidenceRailSection
                    proposalsSection
                    profilePreviewSection
                }
            }
            .padding(GridlineDesign.spacing2XL)
            .frame(maxWidth: 800)
        }
    }

    var studio: ProjectStudioProjection { appState.projection.projectStudio }

    // MARK: - Header

    var headerSection: some View {
        VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
            SectionHeaderView("Project Studio")
            Text("AgentLoop investigation — project understanding, evidence, and public-safe profile preview")
                .font(GridlineDesign.fontCallout)
                .foregroundColor(GridlineDesign.textSecondary)
            if appState.isFixtureMode {
                FixtureModeBannerView()
            }
            DeferredServiceBannerView("K0 AgentLoop / L0 Context Assembly")
        }
    }

    var surfaceStateSection: some View {
        SurfaceStateBannerView(studio.surfaceState, message: stateMessage)
    }

    var stateMessage: String? {
        switch studio.surfaceState {
        case .empty: "Select a repository and start an investigation."
        case .inProgress: "AgentLoop is investigating the repository structure and behavior."
        case .draftReady: "Investigation complete. Review findings and preview project profile."
        case .reviewRequired: "Bootstrap proposals and profile candidate require review before acceptance."
        case .corrupt: "Corrupt evidence detected in investigation receipts. Integrity verification failed."
        default: nil
        }
    }

    // MARK: - Empty State

    var emptyState: some View {
        CardView(padding: GridlineDesign.spacing2XL) {
            VStack(spacing: GridlineDesign.spacingLG) {
                Image(systemName: "text.magnifyingglass")
                    .font(.system(size: 48))
                    .foregroundColor(GridlineDesign.textTertiary)
                Text("No investigation in progress")
                    .font(GridlineDesign.fontTitle3)
                Text("Import a repository in Repository Estate, then start an investigation to discover the project structure, produce understanding artifacts, and generate a public-safe profile candidate.")
                    .font(GridlineDesign.fontCallout)
                    .foregroundColor(GridlineDesign.textSecondary)
                    .multilineTextAlignment(.center)
                Button("Start Investigation") {
                    appState.dispatchIntent(appState.makeIntent(kind: .startInvestigation))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: - Investigation Status

    @ViewBuilder
    var investigationSection: some View {
        if let inv = studio.investigationStatus {
            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                    HStack {
                        Image(systemName: "gearshape.2")
                            .foregroundColor(GridlineDesign.statusInfo)
                        Text("Investigation Status")
                            .font(GridlineDesign.fontHeadline)
                    }

                    HStack(spacing: GridlineDesign.spacingMD) {
                        statusRow("Agent", inv.agentProfile)
                        statusRow("Model", "\(inv.modelProvider)/\(inv.modelId)")
                        statusRow("Thinking", inv.thinkingEnabled ? "Enabled" : "Disabled")
                    }

                    HStack(spacing: GridlineDesign.spacingMD) {
                        statusRow("Turns", "\(inv.turnCount)")
                        statusRow("Tool Calls", "\(inv.toolCallsCompleted)")
                        statusRow("Phase", inv.currentPhase)
                    }

                    if studio.surfaceState == .inProgress {
                        ProgressView()
                            .tint(GridlineDesign.statusInfo)
                            .padding(.top, GridlineDesign.spacingXS)

                        if let started = inv.startedAt {
                            Text("Started at \(started)")
                                .font(GridlineDesign.fontCaption2)
                                .foregroundColor(GridlineDesign.textTertiary)
                        }
                        if let estimate = inv.estimatedCompletion {
                            Text(estimate)
                                .font(GridlineDesign.fontCaption2)
                                .foregroundColor(GridlineDesign.textSecondary)
                        }
                    }
                }
            }
        }
    }

    func statusRow(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(GridlineDesign.fontCaption2)
                .foregroundColor(GridlineDesign.textSecondary)
            Text(value)
                .font(GridlineDesign.fontCallout)
                .foregroundColor(GridlineDesign.textPrimary)
        }
    }

    // MARK: - Understanding Summary

    @ViewBuilder
    var understandingSection: some View {
        if let summary = studio.understandingSummary {
            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                    HStack {
                        Image(systemName: "brain.head.profile")
                            .foregroundColor(GridlineDesign.accent)
                        Text("Project Understanding")
                            .font(GridlineDesign.fontHeadline)
                        Spacer()
                        EvidenceStatusIndicator(
                            status: summary.evidenceStatus,
                            label: "Evidence:"
                        )
                    }

                    VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                        labeledRow("Project", summary.projectName)
                        labeledRow("Language", summary.primaryLanguage)
                        labeledRow("Architecture", summary.architectureStyle)

                        Text("Framework Ecosystem")
                            .font(GridlineDesign.fontCaption)
                            .foregroundColor(GridlineDesign.textSecondary)
                        FlowLayout(spacing: GridlineDesign.spacingXS) {
                            ForEach(summary.frameworkEcosystem, id: \.self) { framework in
                                Text(framework)
                                    .font(GridlineDesign.fontCaption2)
                                    .foregroundColor(GridlineDesign.textPrimary)
                                    .padding(.horizontal, GridlineDesign.spacingSM)
                                    .padding(.vertical, GridlineDesign.spacingXS)
                                    .background(GridlineDesign.accentMuted, in: RoundedRectangle(cornerRadius: GridlineDesign.radiusSM))
                            }
                        }

                        Text("Key Modules")
                            .font(GridlineDesign.fontCaption)
                            .foregroundColor(GridlineDesign.textSecondary)
                            .padding(.top, GridlineDesign.spacingXS)

                        ForEach(summary.keyModules, id: \.self) { module in
                            HStack(spacing: GridlineDesign.spacingSM) {
                                Image(systemName: "cube")
                                    .font(.system(size: 10))
                                    .foregroundColor(GridlineDesign.textTertiary)
                                Text(module)
                                    .font(GridlineDesign.fontCaption)
                                    .foregroundColor(GridlineDesign.textPrimary)
                            }
                        }
                    }
                }
            }
        }
    }

    func labeledRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
                .font(GridlineDesign.fontCaption)
                .foregroundColor(GridlineDesign.textSecondary)
                .frame(width: 100, alignment: .leading)
            Text(value)
                .font(GridlineDesign.fontCallout)
                .foregroundColor(GridlineDesign.textPrimary)
        }
    }

    // MARK: - Evidence Rail

    @ViewBuilder
    var evidenceRailSection: some View {
        if let rail = studio.evidenceRail {
            CardView {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                    HStack {
                        Image(systemName: "shield.checkered")
                            .foregroundColor(rail.integrityVerified ? GridlineDesign.statusOk : GridlineDesign.statusError)
                        Text("Evidence Rail")
                            .font(GridlineDesign.fontHeadline)
                    }

                    HStack(spacing: GridlineDesign.spacingMD) {
                        evidenceBadge("Tool Receipts", "\(rail.toolReceiptCount)", GridlineDesign.statusInfo)
                        evidenceBadge("Checkpoints", "\(rail.checkpointCount)", GridlineDesign.textSecondary)
                        evidenceBadge("Findings", "\(rail.findingsCount)", GridlineDesign.statusWarn)
                        evidenceBadge("Refusals", "\(rail.refusalCount)", rail.refusalCount > 0 ? GridlineDesign.statusError : GridlineDesign.textSecondary)
                    }

                    HStack(spacing: GridlineDesign.spacingMD) {
                        evidenceBadge("Corrupt", "\(rail.corruptEvidenceCount)", rail.corruptEvidenceCount > 0 ? GridlineDesign.statusError : GridlineDesign.statusOk)
                        StatusBadgeView(
                            "Integrity",
                            value: rail.integrityVerified ? "Verified" : "FAILED",
                            color: rail.integrityVerified ? GridlineDesign.statusOk : GridlineDesign.statusError
                        )
                    }

                    if let verified = rail.lastVerifiedAt {
                        Text("Last verified at \(verified)")
                            .font(GridlineDesign.fontCaption2)
                            .foregroundColor(GridlineDesign.textTertiary)
                    }

                    if rail.corruptEvidenceCount > 0 {
                        HStack(spacing: GridlineDesign.spacingSM) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundColor(GridlineDesign.statusError)
                            Text("Corrupt evidence detected — investigation results may be unreliable")
                                .font(GridlineDesign.fontCallout)
                                .foregroundColor(GridlineDesign.statusError)
                        }
                        .padding(GridlineDesign.spacingSM)
                        .background(GridlineDesign.statusError.opacity(0.08), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusMD))
                    }
                }
            }
        }
    }

    func evidenceBadge(_ label: String, _ value: String, _ color: Color) -> some View {
        StatusBadgeView(label, value: value, color: color)
    }

    // MARK: - Proposals

    @ViewBuilder
    var proposalsSection: some View {
        if !studio.bootstrapProposals.isEmpty {
            VStack(alignment: .leading, spacing: GridlineDesign.spacingMD) {
                SectionHeaderView("Bootstrap Proposals")

                ForEach(studio.bootstrapProposals) { proposal in
                    CardView {
                        VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                            HStack {
                                VStack(alignment: .leading, spacing: GridlineDesign.spacingXS) {
                                    Text(proposal.title)
                                        .font(GridlineDesign.fontHeadline)
                                    Text(proposal.description)
                                        .font(GridlineDesign.fontCallout)
                                        .foregroundColor(GridlineDesign.textSecondary)
                                        .lineLimit(3)
                                }
                                Spacer()
                                SurfaceStateBannerView(proposal.status)
                                    .frame(width: 120)
                            }

                            if let digest = proposal.evidenceDigest {
                                Text(digest)
                                    .font(GridlineDesign.fontMonospaced)
                                    .foregroundColor(GridlineDesign.textTertiary)
                            }

                            if proposal.status == .reviewRequired {
                                Button("Review Proposal") {
                                    appState.dispatchIntent(appState.makeIntent(kind: .approveProposal))
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.small)
                            }
                        }
                    }
                }
            }
        }
    }

    // MARK: - Profile Preview

    @ViewBuilder
    var profilePreviewSection: some View {
        if let profile = studio.profileCandidate {
            VStack(alignment: .leading, spacing: GridlineDesign.spacingMD) {
                SectionHeaderView("Project Profile Candidate")

                CardView {
                    VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                        HStack {
                            VStack(alignment: .leading, spacing: GridlineDesign.spacingXS) {
                                Text(profile.projectName)
                                    .font(GridlineDesign.fontTitle2)
                                Text(profile.tagline)
                                    .font(GridlineDesign.fontCallout)
                                    .foregroundColor(GridlineDesign.textSecondary)
                            }
                            Spacer()
                            if profile.isPublicSafe {
                                HStack(spacing: GridlineDesign.spacingXS) {
                                    Image(systemName: "checkmark.seal.fill")
                                        .foregroundColor(GridlineDesign.statusOk)
                                    Text("Public Safe")
                                        .font(GridlineDesign.fontCaption)
                                        .foregroundColor(GridlineDesign.statusOk)
                                }
                                .padding(.horizontal, GridlineDesign.spacingSM)
                                .padding(.vertical, GridlineDesign.spacingXS)
                                .background(GridlineDesign.statusOk.opacity(0.1), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusMD))
                            }
                        }

                        Divider()

                        HStack(spacing: GridlineDesign.spacingLG) {
                            VStack(alignment: .leading) {
                                Text("Milestone")
                                    .font(GridlineDesign.fontCaption)
                                    .foregroundColor(GridlineDesign.textSecondary)
                                Text(profile.currentMilestone)
                                    .font(GridlineDesign.fontCallout)
                            }
                            VStack(alignment: .leading) {
                                Text("Status")
                                    .font(GridlineDesign.fontCaption)
                                    .foregroundColor(GridlineDesign.textSecondary)
                                Text(profile.overallStatus)
                                    .font(GridlineDesign.fontCallout)
                            }
                            VStack(alignment: .leading) {
                                Text("Boundaries")
                                    .font(GridlineDesign.fontCaption)
                                    .foregroundColor(GridlineDesign.textSecondary)
                                Text("\(profile.releasedBoundaries.count) released / \(profile.implementedCount) implemented")
                                    .font(GridlineDesign.fontCallout)
                            }
                        }

                        if !profile.releasedBoundaries.isEmpty {
                            Divider()
                            Text("Released Boundaries")
                                .font(GridlineDesign.fontCaption)
                                .foregroundColor(GridlineDesign.textSecondary)
                            ForEach(profile.releasedBoundaries, id: \.self) { boundary in
                                HStack(spacing: GridlineDesign.spacingSM) {
                                    Image(systemName: "checkmark.seal.fill")
                                        .foregroundColor(GridlineDesign.statusOk)
                                        .font(.system(size: 10))
                                    Text(boundary)
                                        .font(GridlineDesign.fontCaption)
                                }
                            }
                        }

                        if !profile.timelineEntries.isEmpty {
                            Divider()
                            Text("Mission Timeline")
                                .font(GridlineDesign.fontCaption)
                                .foregroundColor(GridlineDesign.textSecondary)
                            ForEach(profile.timelineEntries) { entry in
                                HStack {
                                    EvidenceStatusIndicator(status: entry.status, label: entry.title)
                                    Spacer()
                                    if let completed = entry.completedAt {
                                        Text(completed)
                                            .font(GridlineDesign.fontCaption2)
                                            .foregroundColor(GridlineDesign.textTertiary)
                                    }
                                }
                            }
                        }

                        if !profile.withheldFields.isEmpty {
                            Divider()
                            HStack(spacing: GridlineDesign.spacingSM) {
                                Image(systemName: "eye.slash")
                                    .foregroundColor(GridlineDesign.statusWarn)
                                Text("\(profile.withheldFields.count) fields withheld from public view")
                                    .font(GridlineDesign.fontCaption)
                                    .foregroundColor(GridlineDesign.statusWarn)
                            }
                        }

                        if !studio.privateContentWithheld.isEmpty {
                            HStack(spacing: GridlineDesign.spacingSM) {
                                Image(systemName: "lock.shield")
                                    .foregroundColor(GridlineDesign.statusError)
                                Text("Private content withheld during investigation")
                                    .font(GridlineDesign.fontCaption)
                                    .foregroundColor(GridlineDesign.textSecondary)
                            }
                            ForEach(studio.privateContentWithheld, id: \.self) { item in
                                Text("  • \(item)")
                                    .font(GridlineDesign.fontCaption2)
                                    .foregroundColor(GridlineDesign.textTertiary)
                            }
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Flow Layout (for tags)

struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(proposal: proposal, subviews: subviews)
        let rowWidths: [CGFloat] = rows.map { row in
            let itemWidths = row.map { $0.sizeThatFits(.unspecified).width }
            let totalItemWidth = itemWidths.reduce(0, +)
            let gaps = CGFloat(max(0, row.count - 1)) * spacing
            return totalItemWidth + gaps
        }
        let width = rowWidths.max() ?? 0
        let rowHeights: [CGFloat] = rows.map { row in
            row.map { $0.sizeThatFits(.unspecified).height }.max() ?? 0
        }
        let totalHeight = rowHeights.reduce(0, +)
        let heightGaps = CGFloat(max(0, rows.count - 1)) * spacing
        return CGSize(width: width, height: totalHeight + heightGaps)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let rows = arrange(proposal: proposal, subviews: subviews)
        var y = bounds.minY
        for row in rows {
            var x = bounds.minX
            for view in row {
                view.place(at: CGPoint(x: x, y: y), proposal: .unspecified)
                x += view.sizeThatFits(.unspecified).width + spacing
            }
            y += row.map { $0.sizeThatFits(.unspecified).height }.max() ?? 0 + spacing
        }
    }

    func arrange(proposal: ProposedViewSize, subviews: Subviews) -> [[Subviews.Element]] {
        let maxWidth = proposal.width ?? .infinity
        var rows: [[Subviews.Element]] = [[]]
        var currentWidth: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if !rows[rows.count - 1].isEmpty && currentWidth + size.width > maxWidth {
                rows.append([view])
                currentWidth = size.width
            } else {
                rows[rows.count - 1].append(view)
                currentWidth += size.width + spacing
            }
        }
        return rows
    }
}
