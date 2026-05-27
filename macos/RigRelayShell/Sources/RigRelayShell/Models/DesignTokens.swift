import SwiftUI

// MARK: - Design Tokens (E0 shared: all three surfaces)

enum GridlineDesign {
    // MARK: Colors — Liquid Glass sensibility

    static let accent = Color.accentColor
    static let accentMuted = Color.accentColor.opacity(0.12)

    static let surfacePrimary = Color(nsColor: .controlBackgroundColor)
    static let surfaceSecondary = Color(nsColor: .windowBackgroundColor)
    static let surfaceTertiary = Color(nsColor: .underPageBackgroundColor)

    static let textPrimary = Color.primary
    static let textSecondary = Color.secondary
    static let textTertiary = Color(nsColor: .tertiaryLabelColor)

    static let borderSubtle = Color(nsColor: .separatorColor)
    static let borderEmphasis = Color.primary.opacity(0.12)

    // Semantic
    static let statusOk = Color.green
    static let statusWarn = Color.orange
    static let statusError = Color.red
    static let statusInfo = Color.blue
    static let statusDeferred = Color.purple
    static let statusInactive = Color.gray

    // MARK: — Typography

    static let fontLargeTitle = Font.largeTitle.weight(.semibold)
    static let fontTitle = Font.title.weight(.semibold)
    static let fontTitle2 = Font.title2.weight(.medium)
    static let fontTitle3 = Font.title3.weight(.medium)
    static let fontHeadline = Font.headline
    static let fontBody = Font.body
    static let fontCallout = Font.callout
    static let fontCaption = Font.caption
    static let fontCaption2 = Font.caption2
    static let fontMonospaced = Font.system(.caption, design: .monospaced)

    // MARK: — Spacing (progressive disclosure rhythm)

    static let spacingXS: CGFloat = 4
    static let spacingSM: CGFloat = 8
    static let spacingMD: CGFloat = 12
    static let spacingLG: CGFloat = 16
    static let spacingXL: CGFloat = 24
    static let spacing2XL: CGFloat = 32

    // MARK: — Radii

    static let radiusSM: CGFloat = 4
    static let radiusMD: CGFloat = 6
    static let radiusLG: CGFloat = 8
    static let radiusXL: CGFloat = 12
}

// MARK: - Surface State Color Mapping

extension SurfaceState {
    var color: Color {
        switch self {
        case .uninitialized, .empty, .deferred:
            GridlineDesign.statusInactive
        case .connecting, .loading, .importing, .inProgress:
            GridlineDesign.statusInfo
        case .ready, .authorized:
            GridlineDesign.statusOk
        case .draftReady, .reviewRequired:
            GridlineDesign.statusWarn
        case .permissionBlocked, .refused, .degraded:
            GridlineDesign.statusWarn
        case .unavailable, .error, .corrupt:
            GridlineDesign.statusError
        case .published:
            GridlineDesign.statusOk
        }
    }

    var iconName: String {
        switch self {
        case .uninitialized: "circle.dotted"
        case .connecting: "arrow.triangle.2.circlepath"
        case .loading: "arrow.triangle.2.circlepath"
        case .ready: "checkmark.circle"
        case .authorized: "checkmark.shield"
        case .empty: "tray"
        case .importing: "arrow.down.circle"
        case .inProgress: "gearshape.2"
        case .draftReady: "doc.text.magnifyingglass"
        case .reviewRequired: "eye"
        case .permissionBlocked: "lock.shield"
        case .refused: "hand.raised"
        case .degraded: "exclamationmark.triangle"
        case .unavailable: "xmark.circle"
        case .corrupt: "xmark.shield"
        case .published: "checkmark.seal"
        case .deferred: "clock"
        case .error: "exclamationmark.octagon"
        }
    }

    var label: String {
        switch self {
        case .uninitialized: "Not started"
        case .connecting: "Connecting…"
        case .loading: "Loading…"
        case .ready: "Ready"
        case .authorized: "Authorized"
        case .empty: "No data"
        case .importing: "Importing…"
        case .inProgress: "In progress"
        case .draftReady: "Draft ready"
        case .reviewRequired: "Review required"
        case .permissionBlocked: "Permission blocked"
        case .refused: "Refused"
        case .degraded: "Degraded"
        case .unavailable: "Unavailable"
        case .corrupt: "Evidence corrupt"
        case .published: "Published"
        case .deferred: "Deferred"
        case .error: "Error"
        }
    }
}

extension EvidenceStatus {
    var color: Color {
        switch self {
        case .proven: GridlineDesign.statusOk
        case .claimed: GridlineDesign.statusInfo
        case .planned: GridlineDesign.statusInactive
        case .narrative: GridlineDesign.statusWarn
        case .redacted: GridlineDesign.statusDeferred
        }
    }

    var label: String {
        switch self {
        case .proven: "Proven"
        case .claimed: "Claimed"
        case .planned: "Planned"
        case .narrative: "Narrative"
        case .redacted: "Redacted"
        }
    }
}

extension CapabilityAdmissionStatus {
    var color: Color {
        switch self {
        case .admitted: GridlineDesign.statusOk
        case .refused: GridlineDesign.statusError
        case .degraded: GridlineDesign.statusWarn
        case .reviewRequired: GridlineDesign.statusInfo
        case .unavailable: GridlineDesign.statusInactive
        case .pendingEvaluation: GridlineDesign.statusDeferred
        }
    }

    var label: String {
        switch self {
        case .admitted: "Admitted"
        case .refused: "Refused"
        case .degraded: "Degraded"
        case .reviewRequired: "Review required"
        case .unavailable: "Unavailable"
        case .pendingEvaluation: "Pending"
        }
    }
}
