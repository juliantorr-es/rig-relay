import Foundation

// MARK: - Gridline Projection Fixtures
// All fixture data is explicitly marked isFixture=true.
// DEVELOPMENT ONLY — not live production data.
// Fixtures mirror the shape contracts of J0/K0/L0/M0/C/E0 published boundaries.

enum GridlineFixture {

    // MARK: — Connect Fixture (J0 contract shape)

    static let connect = ConnectProjection(
        surfaceState: .ready,
        carteBlancheDescription: """
            Carte Blanche gives Rig Relay governed access to your selected repositories.
            You choose which repositories to connect — not blanket account access.
            """,
        selectedRepoAccessExplanation: """
            After connecting, you select specific repositories for Rig Relay to study.
            Each repository requires a separate import step. Private repositories
            are studied locally; only public-safe project pages are ever published.
            """,
        privateStudyExplanation: """
            Rig Relay studies your repositories locally. Source code, private files,
            and internal documentation never leave your machine during study.
            AgentLoop investigation runs in governed mode with receipt-backed evidence.
            """,
        publicPublicationExplanation: """
            After study, Rig Relay can prepare a public-safe project page for GitHub Pages.
            This page contains only deliberately publishable content: project name,
            accomplishment summaries, released boundaries, and evidence-digest references.
            No source code, secrets, or private data appear in publication projections.
            """,
        githubInstallationStatus: nil,
        grantedCapabilities: [
            "Repository metadata read",
            "Public repository content read",
            "GitHub Pages deployment (for publication)"
        ],
        missingPermissions: [
            "Private repository access (requires repository selection)"
        ],
        connectionReady: false,
        isFixture: true
    )

    static let connectAfterConnection = ConnectProjection(
        surfaceState: .authorized,
        carteBlancheDescription: connect.carteBlancheDescription,
        selectedRepoAccessExplanation: connect.selectedRepoAccessExplanation,
        privateStudyExplanation: connect.privateStudyExplanation,
        publicPublicationExplanation: connect.publicPublicationExplanation,
        githubInstallationStatus: GitHubInstallationStatus(
            installed: true,
            installationId: "fixture_install_42",
            accountName: "developer",
            scopes: ["read:user", "user:email", "repo:public"],
            rateLimitRemaining: 4950,
            connectedAt: "2026-05-26T10:00:00Z"
        ),
        grantedCapabilities: [
            "Repository metadata read",
            "Public repository content read",
            "GitHub Pages deployment (for publication)"
        ],
        missingPermissions: [],
        connectionReady: true,
        isFixture: true
    )

    // MARK: — Repository Estate Fixture (J0 contract shape)

    static let repositoryEstate = RepositoryEstateProjection(
        surfaceState: .ready,
        repositories: [
            RepositorySummary(
                id: "repo_1",
                name: "rig-relay",
                fullName: "juliantorr-es/rig-relay",
                description: "Rig Relay — a governed local server/control-plane with a desktop cockpit.",
                isPrivate: false,
                defaultBranch: "main",
                language: "Python",
                updatedAt: "2026-05-26T12:00:00Z",
                importStatus: .cloned,
                publicationClass: .publicSafe
            ),
            RepositorySummary(
                id: "repo_2",
                name: "example-project",
                fullName: "developer/example-project",
                description: "A demonstration Python project for agent study.",
                isPrivate: true,
                defaultBranch: "main",
                language: "Python",
                updatedAt: "2026-05-25T09:00:00Z",
                importStatus: .notImported,
                publicationClass: .internalOnly
            ),
            RepositorySummary(
                id: "repo_3",
                name: "private-research",
                fullName: "developer/private-research",
                description: nil,
                isPrivate: true,
                defaultBranch: "main",
                language: "Rust",
                updatedAt: "2026-05-20T15:30:00Z",
                importStatus: .unauthorized,
                publicationClass: .internalOnly
            )
        ],
        selectedRepositoryId: "repo_1",
        cloneStatus: CloneStatus(
            status: .synced,
            progress: 1.0,
            startedAt: "2026-05-26T11:00:00Z",
            completedAt: "2026-05-26T11:02:00Z",
            errorMessage: nil
        ),
        privateCount: 2,
        publicCount: 1,
        syncReadiness: true,
        refusalDiagnostics: [],
        isFixture: true
    )

    static let repositoryEstateEmpty = RepositoryEstateProjection(
        surfaceState: .empty,
        repositories: [],
        selectedRepositoryId: nil,
        cloneStatus: nil,
        privateCount: 0,
        publicCount: 0,
        syncReadiness: false,
        refusalDiagnostics: [],
        isFixture: true
    )

    static let repositoryEstateImporting = RepositoryEstateProjection(
        surfaceState: .importing,
        repositories: [
            RepositorySummary(
                id: "repo_2",
                name: "example-project",
                fullName: "developer/example-project",
                description: "A demonstration Python project for agent study.",
                isPrivate: true,
                defaultBranch: "main",
                language: "Python",
                updatedAt: "2026-05-25T09:00:00Z",
                importStatus: .cloning,
                publicationClass: .internalOnly
            )
        ],
        selectedRepositoryId: "repo_2",
        cloneStatus: CloneStatus(
            status: .cloning,
            progress: 0.45,
            startedAt: "2026-05-26T12:00:00Z",
            completedAt: nil,
            errorMessage: nil
        ),
        privateCount: 2,
        publicCount: 1,
        syncReadiness: false,
        refusalDiagnostics: [],
        isFixture: true
    )

    // MARK: — Project Studio Fixtures (K0/L0 contract shapes)

    static let projectStudioIdle = ProjectStudioProjection(
        surfaceState: .empty,
        investigationStatus: nil,
        understandingSummary: nil,
        evidenceRail: nil,
        bootstrapProposals: [],
        profileCandidate: nil,
        privateContentWithheld: [],
        isFixture: true
    )

    static let projectStudioInvestigating = ProjectStudioProjection(
        surfaceState: .inProgress,
        investigationStatus: InvestigationStatus(
            agentProfile: "explorer",
            modelProvider: "deepseek",
            modelId: "deepseek-v4-pro",
            thinkingEnabled: true,
            turnCount: 12,
            toolCallsCompleted: 34,
            currentPhase: "Symbol indexing and module topology mapping",
            startedAt: "2026-05-26T12:05:00Z",
            estimatedCompletion: "~3 minutes remaining"
        ),
        understandingSummary: nil,
        evidenceRail: EvidenceRailProjection(
            toolReceiptCount: 34,
            checkpointCount: 0,
            findingsCount: 2,
            corruptEvidenceCount: 0,
            refusalCount: 0,
            integrityVerified: true,
            lastVerifiedAt: "2026-05-26T12:08:00Z"
        ),
        bootstrapProposals: [],
        profileCandidate: nil,
        privateContentWithheld: [
            ".env files (secrets)",
            "Credentials directory"
        ],
        isFixture: true
    )

    static let projectStudioDraftReady = ProjectStudioProjection(
        surfaceState: .draftReady,
        investigationStatus: InvestigationStatus(
            agentProfile: "explorer",
            modelProvider: "deepseek",
            modelId: "deepseek-v4-pro",
            thinkingEnabled: true,
            turnCount: 28,
            toolCallsCompleted: 67,
            currentPhase: "Complete — investigation finished",
            startedAt: "2026-05-26T12:05:00Z",
            estimatedCompletion: nil
        ),
        understandingSummary: ProjectUnderstandingSummary(
            projectName: "Rig Relay",
            primaryLanguage: "Python 3.12",
            frameworkEcosystem: [
                "Pydantic v2",
                "httpx",
                "anyio",
                "DuckDB",
                "pywebview",
                "Textual (legacy TUI)"
            ],
            architectureStyle: "Hexagonal/ports-and-adapters with desktop cockpit frontend",
            keyModules: [
                "core/ — AgentLoop engine, LLM backends, tools",
                "desktop/ — Cockpit backend, WebSocket server, projections",
                "governance/ — Auth, dirty guard, findings lifecycle",
                "coordination/ — Store, leases, fleet",
                "evidence/ — Receipts, lifecycle, telemetry",
                "frontend/ — Systems atlas, surface specification"
            ],
            evidenceStatus: .claimed,
            generatedAt: "2026-05-26T12:15:00Z"
        ),
        evidenceRail: EvidenceRailProjection(
            toolReceiptCount: 67,
            checkpointCount: 0,
            findingsCount: 5,
            corruptEvidenceCount: 0,
            refusalCount: 2,
            integrityVerified: true,
            lastVerifiedAt: "2026-05-26T12:15:00Z"
        ),
        bootstrapProposals: [
            BootstrapProposal(
                id: "prop_1",
                title: "Project structure reflects hexagonal architecture",
                description: "Core domain separated from infrastructure adapters. Desktop cockpit is a peer caller, not a bypass.",
                status: .draftReady,
                affectedFiles: ["rig_relay/core/", "rig_relay/desktop/", "rig_relay/governance/"],
                evidenceDigest: "sha256:e4a7b2c1"
            ),
            BootstrapProposal(
                id: "prop_2",
                title: "Governed tools form read/write boundary",
                description: "rig.get_context and rig.report define a governed observation surface with receipt backing.",
                status: .reviewRequired,
                affectedFiles: ["rig_relay/core/tools/", "rig_relay/reports/"],
                evidenceDigest: "sha256:f8c3d1a2"
            )
        ],
        profileCandidate: ProjectProfileCandidate(
            projectName: "Rig Relay",
            tagline: "A governed local server/control-plane with a desktop cockpit",
            currentMilestone: "Alpha v0.1.0a1 — Release Candidate Gate",
            implementedCount: 8,
            plannedCount: 3,
            overallStatus: "active_development",
            releasedBoundaries: [
                "Lane C — Provider evidence authority (published, hardened)",
                "Lane E0 — Frontend systems atlas (published)",
                "Lane D — Constrained execution corridor (published)"
            ],
            timelineEntries: [
                TimelineEntry(id: "c6.2", title: "Provider evidence read-side integrity hardening", status: .proven, completedAt: "2026-05-24"),
                TimelineEntry(id: "e0", title: "Frontend systems atlas and dual static-site surface architecture", status: .proven, completedAt: "2026-05-26"),
                TimelineEntry(id: "d2.1", title: "Constrained execution corridor — json_schema enforcement", status: .proven, completedAt: "2026-05-23"),
                TimelineEntry(id: "n0", title: "Gridline Developer Studio — native SwiftUI macOS shell", status: .planned, completedAt: nil)
            ],
            isPublicSafe: true,
            withheldFields: [
                "Private repository names",
                "Internal module paths",
                "Personal identity information"
            ]
        ),
        privateContentWithheld: [
            ".env files (secrets)",
            "Credentials directory",
            "Private repository references"
        ],
        isFixture: true
    )

    // MARK: — Inference Studio Fixtures (M0/D contract shapes)

    static let inferenceStudioUnavailable = InferenceStudioProjection(
        surfaceState: .unavailable,
        localRuntimeAvailable: false,
        localRuntimeDetails: nil,
        capabilityAdmissions: [],
        draftSuggestions: [],
        degradedReasons: [
            "No local inference runtime detected (Ollama not running)",
            "No cloud provider configured for inference"
        ],
        unavailableServices: [
            "Local LLM execution",
            "Capability admission gating (D3.1 awaiting promotion)"
        ],
        isFixture: true
    )

    static let inferenceStudioDegraded = InferenceStudioProjection(
        surfaceState: .degraded,
        localRuntimeAvailable: true,
        localRuntimeDetails: LocalRuntimeDetails(
            provider: "ollama",
            modelId: "llama3.2:3b",
            vramMb: 8192,
            quantization: "Q4_K_M",
            tokensPerSecond: 34.5,
            capabilitySuite: ["code_completion", "tool_calling", "reasoning"]
        ),
        capabilityAdmissions: [
            CapabilityAdmission(
                id: "cap_1",
                capabilityName: "Tool intent recovery",
                admissionStatus: .admitted,
                constraintClass: "proposal_only",
                requiresApproval: false,
                evidenceDigest: "sha256:a1b2c3d4"
            ),
            CapabilityAdmission(
                id: "cap_2",
                capabilityName: "Constrained execution",
                admissionStatus: .admitted,
                constraintClass: "sandboxed_only",
                requiresApproval: false,
                evidenceDigest: "sha256:e5f6a7b8"
            ),
            CapabilityAdmission(
                id: "cap_3",
                capabilityName: "Live file mutation",
                admissionStatus: .refused,
                constraintClass: nil,
                requiresApproval: true,
                evidenceDigest: nil
            ),
            CapabilityAdmission(
                id: "cap_4",
                capabilityName: "GitHub Pages publication",
                admissionStatus: .reviewRequired,
                constraintClass: "public_safe_only",
                requiresApproval: true,
                evidenceDigest: nil
            )
        ],
        draftSuggestions: [
            DraftSuggestion(
                id: "draft_1",
                title: "Run local code analysis pass",
                description: "Use the admitted constrained execution corridor to run a read-only code analysis on the selected repository.",
                capabilityRequired: "Constrained execution",
                requiresApproval: false,
                status: .ready
            ),
            DraftSuggestion(
                id: "draft_2",
                title: "Generate public project page",
                description: "Prepare a public-safe project page from the investigation findings. Requires publication approval.",
                capabilityRequired: "GitHub Pages publication",
                requiresApproval: true,
                status: .reviewRequired
            )
        ],
        degradedReasons: [
            "Live file mutation refused — requires capability admission review",
            "Publication requires developer approval"
        ],
        unavailableServices: [],
        isFixture: true
    )

    // MARK: — Publish Preview Fixtures (J0/L0 contract shapes)

    static let publishPreviewEmpty = PublishPreviewProjection(
        surfaceState: .empty,
        projectPagePreview: nil,
        pagesReadiness: nil,
        approvalRequired: false,
        approvalAction: nil,
        portfolioInclusionDeferred: true,
        isFixture: true
    )

    static let publishPreviewReady = PublishPreviewProjection(
        surfaceState: .reviewRequired,
        projectPagePreview: ProjectPagePreview(
            projectName: "Rig Relay",
            tagline: "A governed local server/control-plane with a desktop cockpit",
            statusOverview: "Alpha — active development with 3 published authority boundaries",
            sections: [
                ProjectPageSection(
                    id: "sec_identity",
                    title: "Project Identity",
                    contentHash: "sha256:abc123",
                    privacyClass: .publicSafe,
                    evidenceStatus: .claimed
                ),
                ProjectPageSection(
                    id: "sec_status",
                    title: "Status Overview",
                    contentHash: "sha256:def456",
                    privacyClass: .publicSafe,
                    evidenceStatus: .proven
                ),
                ProjectPageSection(
                    id: "sec_accomplishments",
                    title: "Accomplishments",
                    contentHash: "sha256:ghi789",
                    privacyClass: .publicSafe,
                    evidenceStatus: .proven
                ),
                ProjectPageSection(
                    id: "sec_boundaries",
                    title: "Released Boundaries",
                    contentHash: "sha256:jkl012",
                    privacyClass: .publicSafe,
                    evidenceStatus: .proven
                ),
                ProjectPageSection(
                    id: "sec_timeline",
                    title: "Mission Timeline",
                    contentHash: "sha256:mno345",
                    privacyClass: .contentLight,
                    evidenceStatus: .claimed
                )
            ],
            publicSafeVerified: true,
            withheldContent: [
                "Private repository metadata",
                "Internal module architecture details",
                "Personal developer identity"
            ]
        ),
        pagesReadiness: PagesReadinessStatus(
            pagesEnabled: true,
            branchConfigured: true,
            sourcePath: "/docs",
            deploymentStatus: "ready",
            lastDeployedAt: nil,
            errorMessage: nil
        ),
        approvalRequired: true,
        approvalAction: "approve_publication",
        portfolioInclusionDeferred: true,
        isFixture: true
    )

    // MARK: — Provider Evidence (Lane C — published read-side)

    static let providerEvidence = ProviderEvidenceProjection(
        available: true,
        providers: [
            ProviderSummary(
                id: "prov_deepseek",
                name: "DeepSeek",
                apiStyle: "openai_compatible",
                supportsStreaming: true,
                modelsAvailable: 3,
                eventsRecorded: 1450,
                degraded: false
            ),
            ProviderSummary(
                id: "prov_openai",
                name: "OpenAI",
                apiStyle: "openai",
                supportsStreaming: true,
                modelsAvailable: 5,
                eventsRecorded: 320,
                degraded: false
            ),
            ProviderSummary(
                id: "prov_anthropic",
                name: "Anthropic",
                apiStyle: "anthropic",
                supportsStreaming: true,
                modelsAvailable: 2,
                eventsRecorded: 0,
                degraded: false
            )
        ],
        integrityVerified: true,
        corruptEvents: 0,
        lastVerifiedAt: "2026-05-26T12:00:00Z",
        isFixture: true
    )

    // MARK: — Identity (partial A, fixture only)

    static let identity = IdentityProjection(
        available: true,
        providerName: "github",
        accountIdHash: "sha256:fixture_hash_identity",
        scopes: ["read:user", "user:email"],
        signedIn: true,
        isFixture: true
    )

    // MARK: — Full Composite Projection

    static let fullProjection = GridlineProjection(
        schemaVersion: "rig.relay.gridline_projection.v1",
        generatedAt: "2026-05-26T14:00:00Z",
        appVersion: "0.2.0-dev",
        connectState: connect,
        repositoryEstate: repositoryEstate,
        projectStudio: projectStudioInvestigating,
        inferenceStudio: inferenceStudioDegraded,
        publishPreview: publishPreviewEmpty,
        providerEvidence: providerEvidence,
        identityState: identity,
        warnings: [
            "DEVELOPMENT_FIXTURE: This projection is fixture data, not live production state.",
            "J0, K0, L0, M0 lanes are not yet published — all studio views use contract fixtures."
        ],
        isFixture: true
    )

    // MARK: — State Transitions (for demo)

    static func projectionForState(
        connectState: ConnectProjection = connect,
        estate: RepositoryEstateProjection = repositoryEstate,
        studio: ProjectStudioProjection = projectStudioIdle,
        inference: InferenceStudioProjection = inferenceStudioUnavailable,
        publish: PublishPreviewProjection = publishPreviewEmpty
    ) -> GridlineProjection {
        GridlineProjection(
            schemaVersion: "rig.relay.gridline_projection.v1",
            generatedAt: ISO8601DateFormatter().string(from: Date()),
            appVersion: "0.2.0-dev",
            connectState: connectState,
            repositoryEstate: estate,
            projectStudio: studio,
            inferenceStudio: inference,
            publishPreview: publish,
            providerEvidence: providerEvidence,
            identityState: identity,
            warnings: [],
            isFixture: true
        )
    }
}
