import SwiftUI

struct InferenceStudioView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: GridlineDesign.spacing2XL) {
                headerSection
                surfaceStateSection
                runtimeStatusSection
                capabilityAdmissionSection
                draftSuggestionsSection
                degradedUnavailableSection
            }
            .padding(GridlineDesign.spacing2XL)
            .frame(maxWidth: 800)
        }
    }

    var inference: InferenceStudioProjection { appState.projection.inferenceStudio }

    // MARK: - Header

    var headerSection: some View {
        VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
            SectionHeaderView("Inference Studio")
            Text("Local inference runtime, capability admission, and AI-assisted draft suggestions")
                .font(GridlineDesign.fontCallout)
                .foregroundColor(GridlineDesign.textSecondary)
            if appState.isFixtureMode {
                FixtureModeBannerView()
            }
            DeferredServiceBannerView("M0 Inference Runtime / D3.1 Capability Admission")
        }
    }

    var surfaceStateSection: some View {
        SurfaceStateBannerView(inference.surfaceState, message: stateMessage)
    }

    var stateMessage: String? {
        switch inference.surfaceState {
        case .unavailable: "No local inference runtime detected. Connect a local provider (e.g., Ollama) to enable inference."
        case .degraded: inference.degradedReasons.joined(separator: "; ")
        case .ready: "Inference runtime available and capabilities admitted."
        case .refused: "One or more capability admissions were refused. Review admission constraints."
        default: nil
        }
    }

    // MARK: - Runtime Status

    @ViewBuilder
    var runtimeStatusSection: some View {
        CardView {
            VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                HStack {
                    Image(systemName: "cpu")
                        .foregroundColor(inference.localRuntimeAvailable ? GridlineDesign.statusOk : GridlineDesign.statusInactive)
                    Text("Local Runtime")
                        .font(GridlineDesign.fontHeadline)
                    Spacer()
                    StatusBadgeView(
                        "Status",
                        value: inference.localRuntimeAvailable ? "Available" : "Unavailable",
                        color: inference.localRuntimeAvailable ? GridlineDesign.statusOk : GridlineDesign.statusInactive
                    )
                }

                if let runtime = inference.localRuntimeDetails {
                    VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                        HStack(spacing: GridlineDesign.spacingLG) {
                            detailColumn("Provider", runtime.provider ?? "—")
                            detailColumn("Model", runtime.modelId ?? "—")
                            detailColumn("Quantization", runtime.quantization ?? "—")
                        }
                        HStack(spacing: GridlineDesign.spacingLG) {
                            if let vram = runtime.vramMb {
                                detailColumn("VRAM", "\(vram) MB")
                            }
                            if let tps = runtime.tokensPerSecond {
                                detailColumn("Speed", "\(String(format: "%.1f", tps)) tok/s")
                            }
                        }

                        if !runtime.capabilitySuite.isEmpty {
                            Divider()
                            Text("Capability Suite")
                                .font(GridlineDesign.fontCaption)
                                .foregroundColor(GridlineDesign.textSecondary)
                            FlowLayout(spacing: GridlineDesign.spacingXS) {
                                ForEach(runtime.capabilitySuite, id: \.self) { cap in
                                    Text(cap.replacingOccurrences(of: "_", with: " ")
                                        .capitalized)
                                        .font(GridlineDesign.fontCaption2)
                                        .foregroundColor(GridlineDesign.textPrimary)
                                        .padding(.horizontal, GridlineDesign.spacingSM)
                                        .padding(.vertical, GridlineDesign.spacingXS)
                                        .background(GridlineDesign.statusOk.opacity(0.1), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusSM))
                                }
                            }
                        }
                    }
                } else if !inference.localRuntimeAvailable {
                    VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                        Text("Local runtime is unavailable or not configured.")
                            .font(GridlineDesign.fontCallout)
                            .foregroundColor(GridlineDesign.textSecondary)
                        Text("Rig Relay supports local inference through providers like Ollama. Install and start the runtime, then refresh to detect available models.")
                            .font(GridlineDesign.fontCaption)
                            .foregroundColor(GridlineDesign.textTertiary)
                    }
                }

                Button(action: {
                    appState.dispatchIntent(appState.makeIntent(kind: .refreshInference, mutationClass: .readOnly))
                }) {
                    Label("Refresh Runtime Status", systemImage: "arrow.triangle.2.circlepath")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
    }

    func detailColumn(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(GridlineDesign.fontCaption2)
                .foregroundColor(GridlineDesign.textSecondary)
            Text(value)
                .font(GridlineDesign.fontCallout)
                .foregroundColor(GridlineDesign.textPrimary)
        }
    }

    // MARK: - Capability Admissions

    var capabilityAdmissionSection: some View {
        VStack(alignment: .leading, spacing: GridlineDesign.spacingMD) {
            SectionHeaderView("Capability Admissions")

            if inference.capabilityAdmissions.isEmpty {
                CardView {
                    Text("No capability admissions configured. Connect a local runtime and refresh to evaluate capabilities.")
                        .font(GridlineDesign.fontCallout)
                        .foregroundColor(GridlineDesign.textSecondary)
                }
            }

            ForEach(inference.capabilityAdmissions) { admission in
                capabilityCard(admission)
            }
        }
    }

    func capabilityCard(_ admission: CapabilityAdmission) -> some View {
        CardView {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                    HStack {
                        Text(admission.capabilityName)
                            .font(GridlineDesign.fontHeadline)
                        Spacer()
                        admissionStatusBadge(admission.admissionStatus)
                    }

                    if let constraint = admission.constraintClass {
                        HStack(spacing: GridlineDesign.spacingSM) {
                            Text("Constraint:")
                                .font(GridlineDesign.fontCaption)
                                .foregroundColor(GridlineDesign.textSecondary)
                            Text(constraint)
                                .font(GridlineDesign.fontCaption2)
                                .foregroundColor(GridlineDesign.textPrimary)
                                .padding(.horizontal, GridlineDesign.spacingSM)
                                .padding(.vertical, 2)
                                .background(GridlineDesign.borderEmphasis, in: RoundedRectangle(cornerRadius: GridlineDesign.radiusSM))
                        }
                    }

                    HStack(spacing: GridlineDesign.spacingLG) {
                        if admission.requiresApproval {
                            HStack(spacing: GridlineDesign.spacingXS) {
                                Image(systemName: "hand.raised")
                                    .foregroundColor(GridlineDesign.statusWarn)
                                    .font(.system(size: 10))
                                Text("Requires approval")
                                    .font(GridlineDesign.fontCaption2)
                                    .foregroundColor(GridlineDesign.statusWarn)
                            }
                        }

                        if let digest = admission.evidenceDigest {
                            Text(digest)
                                .font(GridlineDesign.fontMonospaced)
                                .foregroundColor(GridlineDesign.textTertiary)
                        }
                    }
                }

                if admission.admissionStatus == .reviewRequired {
                    Button("Request Review") {
                        appState.dispatchIntent(appState.makeIntent(kind: .requestCapabilityReview))
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
            }
        }
    }

    func admissionStatusBadge(_ status: CapabilityAdmissionStatus) -> some View {
        HStack(spacing: GridlineDesign.spacingXS) {
            Circle()
                .fill(status.color)
                .frame(width: 6, height: 6)
            Text(status.label)
                .font(GridlineDesign.fontCaption)
                .fontWeight(.medium)
                .foregroundColor(status.color)
        }
        .padding(.horizontal, GridlineDesign.spacingSM)
        .padding(.vertical, GridlineDesign.spacingXS)
        .background(status.color.opacity(0.1), in: RoundedRectangle(cornerRadius: GridlineDesign.radiusMD))
    }

    // MARK: - Draft Suggestions

    @ViewBuilder
    var draftSuggestionsSection: some View {
        if !inference.draftSuggestions.isEmpty {
            VStack(alignment: .leading, spacing: GridlineDesign.spacingMD) {
                SectionHeaderView("Draft Suggestions")

                ForEach(inference.draftSuggestions) { suggestion in
                    CardView {
                        VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                            HStack {
                                VStack(alignment: .leading, spacing: GridlineDesign.spacingXS) {
                                    Text(suggestion.title)
                                        .font(GridlineDesign.fontHeadline)
                                    Text(suggestion.description)
                                        .font(GridlineDesign.fontCallout)
                                        .foregroundColor(GridlineDesign.textSecondary)
                                        .lineLimit(3)
                                }
                                Spacer()
                                SurfaceStateBannerView(suggestion.status)
                                    .frame(width: 100)
                            }

                            HStack(spacing: GridlineDesign.spacingLG) {
                                StatusBadgeView("Capability", value: suggestion.capabilityRequired, color: GridlineDesign.statusInfo)
                                if suggestion.requiresApproval {
                                    StatusBadgeView("Approval", value: "Required", color: GridlineDesign.statusWarn)
                                } else {
                                    StatusBadgeView("Approval", value: "Not required", color: GridlineDesign.statusOk)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // MARK: - Degraded/Unavailable

    @ViewBuilder
    var degradedUnavailableSection: some View {
        if !inference.degradedReasons.isEmpty || !inference.unavailableServices.isEmpty {
            VStack(alignment: .leading, spacing: GridlineDesign.spacingMD) {
                SectionHeaderView("Status Details")

                if !inference.degradedReasons.isEmpty {
                    CardView {
                        VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                            HStack {
                                Image(systemName: "exclamationmark.triangle")
                                    .foregroundColor(GridlineDesign.statusWarn)
                                Text("Degraded")
                                    .font(GridlineDesign.fontHeadline)
                            }
                            ForEach(inference.degradedReasons, id: \.self) { reason in
                                HStack(spacing: GridlineDesign.spacingSM) {
                                    Text("•")
                                    Text(reason)
                                        .font(GridlineDesign.fontCallout)
                                        .foregroundColor(GridlineDesign.textSecondary)
                                }
                            }
                        }
                    }
                }

                if !inference.unavailableServices.isEmpty {
                    CardView {
                        VStack(alignment: .leading, spacing: GridlineDesign.spacingSM) {
                            HStack {
                                Image(systemName: "xmark.circle")
                                    .foregroundColor(GridlineDesign.statusInactive)
                                Text("Unavailable")
                                    .font(GridlineDesign.fontHeadline)
                            }
                            ForEach(inference.unavailableServices, id: \.self) { service in
                                HStack(spacing: GridlineDesign.spacingSM) {
                                    Text("•")
                                    Text(service)
                                        .font(GridlineDesign.fontCallout)
                                        .foregroundColor(GridlineDesign.textSecondary)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
