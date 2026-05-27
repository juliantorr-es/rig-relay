import SwiftUI

// MARK: - Status Badge

struct StatusBadgeView: View {
    let label: String
    let value: String
    let color: Color

    init(_ label: String, value: String, color: Color) {
        self.label = label
        self.value = value
        self.color = color
    }

    var body: some View {
        HStack(spacing: GridlineDesign.spacingXS) {
            Text(label)
                .font(GridlineDesign.fontCaption2)
                .foregroundColor(GridlineDesign.textSecondary)
            Text(value)
                .font(GridlineDesign.fontCaption2)
                .fontWeight(.medium)
                .foregroundColor(color)
                .padding(.horizontal, GridlineDesign.spacingXS)
                .padding(.vertical, 2)
                .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusSM))
        }
    }
}

// MARK: - Surface State Banner

struct SurfaceStateBannerView: View {
    let state: SurfaceState
    let message: String?

    init(_ state: SurfaceState, message: String? = nil) {
        self.state = state
        self.message = message
    }

    var body: some View {
        HStack(spacing: GridlineDesign.spacingSM) {
            Image(systemName: state.iconName)
                .foregroundColor(state.color)
                .font(.system(size: 14))

            VStack(alignment: .leading, spacing: 2) {
                Text(state.label)
                    .font(GridlineDesign.fontCaption)
                    .fontWeight(.medium)
                    .foregroundColor(state.color)
                if let message {
                    Text(message)
                        .font(GridlineDesign.fontCaption2)
                        .foregroundColor(GridlineDesign.textSecondary)
                        .lineLimit(2)
                }
            }
        }
        .padding(GridlineDesign.spacingSM)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(state.color.opacity(0.06), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusMD))
    }
}

// MARK: - Fixture Mode Banner

struct FixtureModeBannerView: View {
    var body: some View {
        HStack(spacing: GridlineDesign.spacingSM) {
            Image(systemName: "square.dotted")
                .foregroundColor(.purple)
            Text("DEVELOPMENT FIXTURE")
                .font(GridlineDesign.fontCaption2)
                .fontWeight(.bold)
                .foregroundColor(.purple)
            Text("Not live production data. Backend integration deferred.")
                .font(GridlineDesign.fontCaption2)
                .foregroundColor(GridlineDesign.textSecondary)
        }
        .padding(.horizontal, GridlineDesign.spacingSM)
        .padding(.vertical, GridlineDesign.spacingXS)
        .background(Color.purple.opacity(0.08))
    }
}

// MARK: - Evidence Status Indicator

struct EvidenceStatusIndicator: View {
    let status: EvidenceStatus
    let label: String

    var body: some View {
        HStack(spacing: GridlineDesign.spacingXS) {
            Circle()
                .fill(status.color)
                .frame(width: 6, height: 6)
            Text(label)
                .font(GridlineDesign.fontCaption)
                .foregroundColor(GridlineDesign.textSecondary)
            Text(status.label)
                .font(GridlineDesign.fontCaption2)
                .foregroundColor(status.color)
                .padding(.horizontal, GridlineDesign.spacingXS)
                .padding(.vertical, 1)
                .background(status.color.opacity(0.1), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusSM))
        }
    }
}

// MARK: - Section Header

struct SectionHeaderView: View {
    let title: String

    init(_ title: String) {
        self.title = title
    }

    var body: some View {
        Text(title)
            .font(GridlineDesign.fontTitle3)
            .fontWeight(.semibold)
            .foregroundColor(GridlineDesign.textPrimary)
    }
}

// MARK: - Card Container

struct CardView<Content: View>: View {
    let content: Content
    let padding: CGFloat

    init(padding: CGFloat = GridlineDesign.spacingLG, @ViewBuilder content: () -> Content) {
        self.content = content()
        self.padding = padding
    }

    var body: some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(GridlineDesign.surfacePrimary, in: RoundedRectangle(cornerRadius: GridlineDesign.radiusLG))
            .overlay(
                RoundedRectangle(cornerRadius: GridlineDesign.radiusLG)
                    .stroke(GridlineDesign.borderSubtle, lineWidth: 0.5)
            )
    }
}

// MARK: - Privacy Badge

struct PrivacyBadgeView: View {
    let privacyClass: PrivacyClass

    var body: some View {
        Text(privacyClassLabel)
            .font(GridlineDesign.fontCaption2)
            .foregroundColor(privacyClassColor)
            .padding(.horizontal, GridlineDesign.spacingXS)
            .padding(.vertical, 2)
            .background(privacyClassColor.opacity(0.1), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusSM))
    }

    var privacyClassLabel: String {
        switch privacyClass {
        case .publicSafe: "Public Safe"
        case .contentLight: "Content Light"
        case .internalOnly: "Internal Only"
        }
    }

    var privacyClassColor: Color {
        switch privacyClass {
        case .publicSafe: GridlineDesign.statusOk
        case .contentLight: GridlineDesign.statusInfo
        case .internalOnly: GridlineDesign.statusError
        }
    }
}

// MARK: - Deferred Service Banner

struct DeferredServiceBannerView: View {
    let serviceName: String

    init(_ serviceName: String) {
        self.serviceName = serviceName
    }

    var body: some View {
        HStack(spacing: GridlineDesign.spacingSM) {
            Image(systemName: "clock")
                .foregroundColor(GridlineDesign.statusDeferred)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(serviceName) — Integration Deferred")
                    .font(GridlineDesign.fontCaption)
                    .fontWeight(.medium)
                Text("This service boundary is not yet published. Displaying fixture projection.")
                    .font(GridlineDesign.fontCaption2)
                    .foregroundColor(GridlineDesign.textSecondary)
            }
        }
        .padding(GridlineDesign.spacingSM)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(GridlineDesign.statusDeferred.opacity(0.06), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusMD))
    }
}
