import Foundation
import SwiftUI

// ── Extension Status View (N1 → X4 convergence) ──
//
// ViewModel that bridges the SafariExtensionHost state to the SwiftUI layer.
// Updated from the N1 era "extension status unknown" stub to the X4 live state.

@MainActor
final class ExtensionStatusViewModel: ObservableObject {
    @Published var contractVersion: String
    @Published var supportedKinds: [String]
    @Published var connectionState: String
    @Published var connectionDetail: String?
    @Published var handoffURL: String?
    @Published var lastMessageTimestamp: String?
    @Published var convergenceComplete: Bool
    @Published var blockingRequirements: [String]
    @Published var notes: [String]

    private let extensionHost: SafariExtensionHost

    init(extensionHost: SafariExtensionHost) {
        self.extensionHost = extensionHost
        let contract = SafariExtensionContractSummary.v1()
        self.contractVersion = contract.n1ContractVersion
        self.supportedKinds = contract.supportedKinds
        self.blockingRequirements = contract.blockingRequirements
        self.notes = contract.notes
        self.connectionState = SafariExtensionConnectionState.idle.label
        self.convergenceComplete = contract.x4ConvergenceDeeds.count == 5
    }

    func refresh() {
        connectionState = extensionHost.connectionState.label
        connectionDetail = extensionHost.connectionState.detail
        handoffURL = extensionHost.activeHandoffURL
        lastMessageTimestamp = extensionHost.lastMessageTimestamp
    }
}
