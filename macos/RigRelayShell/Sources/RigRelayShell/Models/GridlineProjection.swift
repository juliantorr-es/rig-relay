import Foundation

// MARK: - Privacy Classification (mirrors E0 PrivacyClass)

enum PrivacyClass: String, Codable, Sendable {
    case publicSafe = "public_safe"
    case contentLight = "content_light"
    case internalOnly = "internal_only"
}

// MARK: - Surface State (every view must handle all of these)

enum SurfaceState: String, Codable, Sendable {
    case uninitialized
    case connecting
    case loading
    case ready
    case authorized
    case empty
    case importing
    case inProgress = "in_progress"
    case draftReady = "draft_ready"
    case reviewRequired = "review_required"
    case permissionBlocked = "permission_blocked"
    case refused
    case degraded
    case unavailable
    case corrupt = "corrupt_untrusted"
    case published
    case deferred = "integration_deferred"
    case error
}

// MARK: - Evidence Status (mirrors E0 EvidenceStatus)

enum EvidenceStatus: String, Codable, Sendable {
    case proven
    case claimed
    case planned
    case narrative
    case redacted
}

// MARK: - Root Gridline Projection

struct GridlineProjection: Codable, Sendable {
    let schemaVersion: String
    let generatedAt: String
    let appVersion: String
    var connectState: ConnectProjection
    var repositoryEstate: RepositoryEstateProjection
    var projectStudio: ProjectStudioProjection
    var inferenceStudio: InferenceStudioProjection
    var publishPreview: PublishPreviewProjection
    var providerEvidence: ProviderEvidenceProjection?
    var identityState: IdentityProjection?
    let warnings: [String]
    let isFixture: Bool

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
        case appVersion = "app_version"
        case connectState = "connect_state"
        case repositoryEstate = "repository_estate"
        case projectStudio = "project_studio"
        case inferenceStudio = "inference_studio"
        case publishPreview = "publish_preview"
        case providerEvidence = "provider_evidence"
        case identityState = "identity_state"
        case warnings
        case isFixture = "is_fixture"
    }
}

// MARK: - Connect (Carte Blanche / J0)

struct ConnectProjection: Codable, Sendable {
    let surfaceState: SurfaceState
    let carteBlancheDescription: String
    let selectedRepoAccessExplanation: String
    let privateStudyExplanation: String
    let publicPublicationExplanation: String
    let githubInstallationStatus: GitHubInstallationStatus?
    let grantedCapabilities: [String]
    let missingPermissions: [String]
    let connectionReady: Bool
    let isFixture: Bool

    enum CodingKeys: String, CodingKey {
        case surfaceState = "surface_state"
        case carteBlancheDescription = "carte_blanche_description"
        case selectedRepoAccessExplanation = "selected_repo_access_explanation"
        case privateStudyExplanation = "private_study_explanation"
        case publicPublicationExplanation = "public_publication_explanation"
        case githubInstallationStatus = "github_installation_status"
        case grantedCapabilities = "granted_capabilities"
        case missingPermissions = "missing_permissions"
        case connectionReady = "connection_ready"
        case isFixture = "is_fixture"
    }
}

struct GitHubInstallationStatus: Codable, Sendable {
    let installed: Bool
    let installationId: String?
    let accountName: String?
    let scopes: [String]
    let rateLimitRemaining: Int?
    let connectedAt: String?

    enum CodingKeys: String, CodingKey {
        case installed
        case installationId = "installation_id"
        case accountName = "account_name"
        case scopes
        case rateLimitRemaining = "rate_limit_remaining"
        case connectedAt = "connected_at"
    }
}

// MARK: - Repository Estate (J0)

struct RepositoryEstateProjection: Codable, Sendable {
    let surfaceState: SurfaceState
    let repositories: [RepositorySummary]
    let selectedRepositoryId: String?
    let cloneStatus: CloneStatus?
    let privateCount: Int
    let publicCount: Int
    let syncReadiness: Bool
    let refusalDiagnostics: [String]
    let isFixture: Bool

    enum CodingKeys: String, CodingKey {
        case surfaceState = "surface_state"
        case repositories
        case selectedRepositoryId = "selected_repository_id"
        case cloneStatus = "clone_status"
        case privateCount = "private_count"
        case publicCount = "public_count"
        case syncReadiness = "sync_readiness"
        case refusalDiagnostics = "refusal_diagnostics"
        case isFixture = "is_fixture"
    }
}

struct RepositorySummary: Codable, Identifiable, Sendable {
    let id: String
    let name: String
    let fullName: String
    let description: String?
    let isPrivate: Bool
    let defaultBranch: String?
    let language: String?
    let updatedAt: String?
    let importStatus: RepositoryImportStatus
    let publicationClass: PrivacyClass

    enum CodingKeys: String, CodingKey {
        case id, name
        case fullName = "full_name"
        case description
        case isPrivate = "is_private"
        case defaultBranch = "default_branch"
        case language
        case updatedAt = "updated_at"
        case importStatus = "import_status"
        case publicationClass = "publication_class"
    }
}

enum RepositoryImportStatus: String, Codable, Sendable {
    case notImported = "not_imported"
    case cloning
    case cloned
    case syncing
    case synced
    case failed
    case unauthorized
}

struct CloneStatus: Codable, Sendable {
    let status: RepositoryImportStatus
    let progress: Double?
    let startedAt: String?
    let completedAt: String?
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case status, progress
        case startedAt = "started_at"
        case completedAt = "completed_at"
        case errorMessage = "error_message"
    }
}

// MARK: - Project Studio (K0 / L0)

struct ProjectStudioProjection: Codable, Sendable {
    let surfaceState: SurfaceState
    let investigationStatus: InvestigationStatus?
    let understandingSummary: ProjectUnderstandingSummary?
    let evidenceRail: EvidenceRailProjection?
    let bootstrapProposals: [BootstrapProposal]
    let profileCandidate: ProjectProfileCandidate?
    let privateContentWithheld: [String]
    let isFixture: Bool

    enum CodingKeys: String, CodingKey {
        case surfaceState = "surface_state"
        case investigationStatus = "investigation_status"
        case understandingSummary = "understanding_summary"
        case evidenceRail = "evidence_rail"
        case bootstrapProposals = "bootstrap_proposals"
        case profileCandidate = "profile_candidate"
        case privateContentWithheld = "private_content_withheld"
        case isFixture = "is_fixture"
    }
}

struct InvestigationStatus: Codable, Sendable {
    let agentProfile: String
    let modelProvider: String
    let modelId: String
    let thinkingEnabled: Bool
    let turnCount: Int
    let toolCallsCompleted: Int
    let currentPhase: String
    let startedAt: String?
    let estimatedCompletion: String?

    enum CodingKeys: String, CodingKey {
        case agentProfile = "agent_profile"
        case modelProvider = "model_provider"
        case modelId = "model_id"
        case thinkingEnabled = "thinking_enabled"
        case turnCount = "turn_count"
        case toolCallsCompleted = "tool_calls_completed"
        case currentPhase = "current_phase"
        case startedAt = "started_at"
        case estimatedCompletion = "estimated_completion"
    }
}

struct ProjectUnderstandingSummary: Codable, Sendable {
    let projectName: String
    let primaryLanguage: String
    let frameworkEcosystem: [String]
    let architectureStyle: String
    let keyModules: [String]
    let evidenceStatus: EvidenceStatus
    let generatedAt: String?

    enum CodingKeys: String, CodingKey {
        case projectName = "project_name"
        case primaryLanguage = "primary_language"
        case frameworkEcosystem = "framework_ecosystem"
        case architectureStyle = "architecture_style"
        case keyModules = "key_modules"
        case evidenceStatus = "evidence_status"
        case generatedAt = "generated_at"
    }
}

struct EvidenceRailProjection: Codable, Sendable {
    let toolReceiptCount: Int
    let checkpointCount: Int
    let findingsCount: Int
    let corruptEvidenceCount: Int
    let refusalCount: Int
    let integrityVerified: Bool
    let lastVerifiedAt: String?

    enum CodingKeys: String, CodingKey {
        case toolReceiptCount = "tool_receipt_count"
        case checkpointCount = "checkpoint_count"
        case findingsCount = "findings_count"
        case corruptEvidenceCount = "corrupt_evidence_count"
        case refusalCount = "refusal_count"
        case integrityVerified = "integrity_verified"
        case lastVerifiedAt = "last_verified_at"
    }
}

struct BootstrapProposal: Codable, Identifiable, Sendable {
    let id: String
    let title: String
    let description: String
    let status: SurfaceState
    let affectedFiles: [String]
    let evidenceDigest: String?

    enum CodingKeys: String, CodingKey {
        case id, title, description, status
        case affectedFiles = "affected_files"
        case evidenceDigest = "evidence_digest"
    }
}

struct ProjectProfileCandidate: Codable, Sendable {
    let projectName: String
    let tagline: String
    let currentMilestone: String
    let implementedCount: Int
    let plannedCount: Int
    let overallStatus: String
    let releasedBoundaries: [String]
    let timelineEntries: [TimelineEntry]
    let isPublicSafe: Bool
    let withheldFields: [String]

    enum CodingKeys: String, CodingKey {
        case projectName = "project_name"
        case tagline
        case currentMilestone = "current_milestone"
        case implementedCount = "implemented_count"
        case plannedCount = "planned_count"
        case overallStatus = "overall_status"
        case releasedBoundaries = "released_boundaries"
        case timelineEntries = "timeline_entries"
        case isPublicSafe = "is_public_safe"
        case withheldFields = "withheld_fields"
    }
}

struct TimelineEntry: Codable, Identifiable, Sendable {
    let id: String
    let title: String
    let status: EvidenceStatus
    let completedAt: String?

    enum CodingKeys: String, CodingKey {
        case id = "mission_id"
        case title
        case status
        case completedAt = "completed_at"
    }
}

// MARK: - Inference Studio (M0 / D)

struct InferenceStudioProjection: Codable, Sendable {
    let surfaceState: SurfaceState
    let localRuntimeAvailable: Bool
    let localRuntimeDetails: LocalRuntimeDetails?
    let capabilityAdmissions: [CapabilityAdmission]
    let draftSuggestions: [DraftSuggestion]
    let degradedReasons: [String]
    let unavailableServices: [String]
    let isFixture: Bool

    enum CodingKeys: String, CodingKey {
        case surfaceState = "surface_state"
        case localRuntimeAvailable = "local_runtime_available"
        case localRuntimeDetails = "local_runtime_details"
        case capabilityAdmissions = "capability_admissions"
        case draftSuggestions = "draft_suggestions"
        case degradedReasons = "degraded_reasons"
        case unavailableServices = "unavailable_services"
        case isFixture = "is_fixture"
    }
}

struct LocalRuntimeDetails: Codable, Sendable {
    let provider: String?
    let modelId: String?
    let vramMb: Int?
    let quantization: String?
    let tokensPerSecond: Double?
    let capabilitySuite: [String]

    enum CodingKeys: String, CodingKey {
        case provider
        case modelId = "model_id"
        case vramMb = "vram_mb"
        case quantization
        case tokensPerSecond = "tokens_per_second"
        case capabilitySuite = "capability_suite"
    }
}

struct CapabilityAdmission: Codable, Identifiable, Sendable {
    let id: String
    let capabilityName: String
    let admissionStatus: CapabilityAdmissionStatus
    let constraintClass: String?
    let requiresApproval: Bool
    let evidenceDigest: String?

    enum CodingKeys: String, CodingKey {
        case id
        case capabilityName = "capability_name"
        case admissionStatus = "admission_status"
        case constraintClass = "constraint_class"
        case requiresApproval = "requires_approval"
        case evidenceDigest = "evidence_digest"
    }
}

enum CapabilityAdmissionStatus: String, Codable, Sendable {
    case admitted
    case refused
    case degraded
    case reviewRequired = "review_required"
    case unavailable
    case pendingEvaluation = "pending_evaluation"
}

struct DraftSuggestion: Codable, Identifiable, Sendable {
    let id: String
    let title: String
    let description: String
    let capabilityRequired: String
    let requiresApproval: Bool
    let status: SurfaceState

    enum CodingKeys: String, CodingKey {
        case id, title, description
        case capabilityRequired = "capability_required"
        case requiresApproval = "requires_approval"
        case status
    }
}

// MARK: - Publish Preview (J0 / L0)

struct PublishPreviewProjection: Codable, Sendable {
    let surfaceState: SurfaceState
    let projectPagePreview: ProjectPagePreview?
    let pagesReadiness: PagesReadinessStatus?
    let approvalRequired: Bool
    let approvalAction: String?
    let portfolioInclusionDeferred: Bool
    let isFixture: Bool

    enum CodingKeys: String, CodingKey {
        case surfaceState = "surface_state"
        case projectPagePreview = "project_page_preview"
        case pagesReadiness = "pages_readiness"
        case approvalRequired = "approval_required"
        case approvalAction = "approval_action"
        case portfolioInclusionDeferred = "portfolio_inclusion_deferred"
        case isFixture = "is_fixture"
    }
}

struct ProjectPagePreview: Codable, Sendable {
    let projectName: String
    let tagline: String
    let statusOverview: String
    let sections: [ProjectPageSection]
    let publicSafeVerified: Bool
    let withheldContent: [String]

    enum CodingKeys: String, CodingKey {
        case projectName = "project_name"
        case tagline
        case statusOverview = "status_overview"
        case sections
        case publicSafeVerified = "public_safe_verified"
        case withheldContent = "withheld_content"
    }
}

struct ProjectPageSection: Codable, Identifiable, Sendable {
    let id: String
    let title: String
    let contentHash: String
    let privacyClass: PrivacyClass
    let evidenceStatus: EvidenceStatus

    enum CodingKeys: String, CodingKey {
        case id, title
        case contentHash = "content_hash"
        case privacyClass = "privacy_class"
        case evidenceStatus = "evidence_status"
    }
}

struct PagesReadinessStatus: Codable, Sendable {
    let pagesEnabled: Bool
    let branchConfigured: Bool
    let sourcePath: String?
    let deploymentStatus: String?
    let lastDeployedAt: String?
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case pagesEnabled = "pages_enabled"
        case branchConfigured = "branch_configured"
        case sourcePath = "source_path"
        case deploymentStatus = "deployment_status"
        case lastDeployedAt = "last_deployed_at"
        case errorMessage = "error_message"
    }
}

// MARK: - Provider Evidence (Lane C — published read-side)

struct ProviderEvidenceProjection: Codable, Sendable {
    let available: Bool
    let providers: [ProviderSummary]
    let integrityVerified: Bool
    let corruptEvents: Int
    let lastVerifiedAt: String?
    let isFixture: Bool

    enum CodingKeys: String, CodingKey {
        case available
        case providers
        case integrityVerified = "integrity_verified"
        case corruptEvents = "corrupt_events"
        case lastVerifiedAt = "last_verified_at"
        case isFixture = "is_fixture"
    }
}

struct ProviderSummary: Codable, Identifiable, Sendable {
    let id: String
    let name: String
    let apiStyle: String?
    let supportsStreaming: Bool?
    let modelsAvailable: Int
    let eventsRecorded: Int
    let degraded: Bool

    enum CodingKeys: String, CodingKey {
        case id, name
        case apiStyle = "api_style"
        case supportsStreaming = "supports_streaming"
        case modelsAvailable = "models_available"
        case eventsRecorded = "events_recorded"
        case degraded
    }
}

// MARK: - Identity (partial A / identity provider)

struct IdentityProjection: Codable, Sendable {
    let available: Bool
    let providerName: String?
    let accountIdHash: String?
    let scopes: [String]
    let signedIn: Bool
    let isFixture: Bool

    enum CodingKeys: String, CodingKey {
        case available
        case providerName = "provider_name"
        case accountIdHash = "account_id_hash"
        case scopes
        case signedIn = "signed_in"
        case isFixture = "is_fixture"
    }
}
