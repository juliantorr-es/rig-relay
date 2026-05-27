import SwiftUI
import Combine

// MARK: - Navigation Tab

enum GridlineTab: String, CaseIterable, Sendable {
    case connect = "Connect"
    case repositories = "Repositories"
    case projectStudio = "Project Studio"
    case inference = "Inference"
    case publish = "Publish"

    var iconName: String {
        switch self {
        case .connect: "link"
        case .repositories: "folder"
        case .projectStudio: "text.magnifyingglass"
        case .inference: "cpu"
        case .publish: "paperplane"
        }
    }

    var description: String {
        switch self {
        case .connect: "Carte Blanche connection and permissions"
        case .repositories: "Repository estate — import, study, classify"
        case .projectStudio: "AgentLoop investigation and project understanding"
        case .inference: "Local inference capability and admission"
        case .publish: "Public-safe project page preview and approval"
        }
    }
}

// MARK: - App State

@MainActor
final class AppState: ObservableObject {
    @Published var selectedTab: GridlineTab = .connect
    @Published var projection: GridlineProjection
    @Published var isFixtureMode: Bool = true
    @Published var statusMessage: String = ""
    @Published var intentLog: [IntentLogEntry] = []

    private let sessionId = "gridline_session_\(UUID().uuidString.prefix(8))"

    init() {
        projection = GridlineFixture.fullProjection
        isFixtureMode = projection.isFixture
        statusMessage = "DEVELOPMENT — Fixture mode. No live backend connected."
    }

    // MARK: — Projection Loading

    func loadProjection(_ newProjection: GridlineProjection) {
        withAnimation(.easeInOut(duration: 0.2)) {
            projection = newProjection
            isFixtureMode = newProjection.isFixture
        }
    }

    func loadFixtureForDemo() {
        loadProjection(GridlineFixture.fullProjection)
        statusMessage = "Demo projection loaded (fixture mode)."
    }

    func simulateConnectFlow() {
        var p = projection
        p.connectState = GridlineFixture.connectAfterConnection
        p.repositoryEstate = GridlineFixture.repositoryEstate
        p.identityState = GridlineFixture.identity
        loadProjection(p)
        statusMessage = "Carte Blanche connected (fixture simulation)."
    }

    func simulateRepositoryImport() {
        loadProjection(GridlineFixture.projectionForState(
            connectState: GridlineFixture.connectAfterConnection,
            estate: GridlineFixture.repositoryEstateImporting,
            studio: GridlineFixture.projectStudioIdle,
            inference: GridlineFixture.inferenceStudioUnavailable,
            publish: GridlineFixture.publishPreviewEmpty
        ))
        statusMessage = "Repository import in progress (fixture simulation)."
        Task {
            try? await Task.sleep(for: .seconds(2))
            loadProjection(GridlineFixture.projectionForState(
                connectState: GridlineFixture.connectAfterConnection,
                estate: GridlineFixture.repositoryEstate,
                studio: GridlineFixture.projectStudioIdle,
                inference: GridlineFixture.inferenceStudioUnavailable,
                publish: GridlineFixture.publishPreviewEmpty
            ))
            statusMessage = "Repository import complete (fixture simulation)."
        }
    }

    func simulateInvestigation() {
        var p = projection
        p.projectStudio = GridlineFixture.projectStudioInvestigating
        loadProjection(p)
        statusMessage = "AgentLoop investigation started (fixture simulation)."
        Task {
            try? await Task.sleep(for: .seconds(3))
            var completed = projection
            completed.projectStudio = GridlineFixture.projectStudioDraftReady
            completed.inferenceStudio = GridlineFixture.inferenceStudioDegraded
            completed.publishPreview = GridlineFixture.publishPreviewReady
            loadProjection(completed)
            statusMessage = "Investigation complete — draft ready for review (fixture simulation)."
        }
    }

    // MARK: — Intent Dispatch (simulated — no backend authority)

    func dispatchIntent(_ intent: GridlineIntent) {
        let entry = IntentLogEntry(
            timestamp: Date(),
            intentKind: intent.intentKind.rawValue,
            traceId: intent.traceId,
            mutationClass: intent.mutationClass.rawValue
        )
        intentLog.append(entry)

        statusMessage = "Intent dispatched: \(intent.intentKind.rawValue) [FIXTURE — no backend]"

        switch intent.intentKind {
        case .connectGitHub:
            simulateConnectFlow()
        case .importRepository:
            simulateRepositoryImport()
        case .startInvestigation:
            simulateInvestigation()
        case .previewPublish:
            var p = projection
            p.publishPreview = GridlineFixture.publishPreviewReady
            loadProjection(p)
        default:
            break
        }
    }

    func makeTraceId() -> String {
        "trace_\(UUID().uuidString.prefix(12))"
    }

    func makeIntent(kind: IntentKind, mutationClass: MutationClass = .safeLocalMutation) -> GridlineIntent {
        GridlineIntent(
            traceId: makeTraceId(),
            frontendSessionId: sessionId,
            intentKind: kind,
            mutationClass: mutationClass,
            capabilityRequired: nil,
            intentPayloadHash: nil,
            redactionStatus: "content_light"
        )
    }
}

struct IntentLogEntry: Identifiable, Sendable {
    let id = UUID()
    let timestamp: Date
    let intentKind: String
    let traceId: String
    let mutationClass: String
}
