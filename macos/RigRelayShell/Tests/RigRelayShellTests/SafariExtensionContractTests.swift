import Foundation
import Testing
@testable import RigRelayShell

// MARK: - Safari Extension Contract Swift Tests (X4 convergence)
//
// Tests validate:
//   1. All 8 Q0 message kinds encode/decode correctly
//   2. Typed payloads (including integer pr_number/issue_number)
//   3. Direction field mutual exclusion
//   4. Response emission for all 4 response kinds
//   5. created_at canonical timestamp with sent_at alias
//   6. Content-light validation rejects token patterns
//   7. Refusal paths work

@Suite("SafariExtensionMessageKind")
struct SafariExtensionMessageKindTests {

    @Test("All 8 Q0 message kinds are defined")
    func allEightKindsExist() {
        #expect(SafariExtensionMessageKind.allCases.count == 8)
    }

    @Test("Handoff kinds have correct direction")
    func handoffKindsAreExtensionToApp() {
        #expect(SafariExtensionMessageKind.handoffGitHubRepository.direction == .extensionToApp)
        #expect(SafariExtensionMessageKind.handoffGitHubPullRequest.direction == .extensionToApp)
        #expect(SafariExtensionMessageKind.handoffGitHubIssue.direction == .extensionToApp)
        #expect(SafariExtensionMessageKind.ping.direction == .extensionToApp)
    }

    @Test("Response kinds have correct direction")
    func responseKindsAreAppToExtension() {
        #expect(SafariExtensionMessageKind.responseAccepted.direction == .appToExtension)
        #expect(SafariExtensionMessageKind.responseDeferred.direction == .appToExtension)
        #expect(SafariExtensionMessageKind.responseRefused.direction == .appToExtension)
        #expect(SafariExtensionMessageKind.responseAppUnavailable.direction == .appToExtension)
    }

    @Test("isHandoff identifies handoff kinds")
    func isHandoff() {
        #expect(SafariExtensionMessageKind.handoffGitHubRepository.isHandoff)
        #expect(SafariExtensionMessageKind.handoffGitHubPullRequest.isHandoff)
        #expect(SafariExtensionMessageKind.handoffGitHubIssue.isHandoff)
        #expect(!SafariExtensionMessageKind.ping.isHandoff)
        #expect(!SafariExtensionMessageKind.responseAccepted.isHandoff)
    }
}

@Suite("Typed Payload Codability")
struct TypedPayloadTests {

    @Test("Repository handoff payload encodes and decodes")
    func repositoryHandoffRoundtrip() throws {
        let original = GitHubRepositoryHandoffPayload(
            url: "https://github.com/owner/repo",
            owner: "owner",
            repo: "repo",
            pageKind: .repositoryMain,
            triggeredBy: .popupAction
        )
        let json = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(GitHubRepositoryHandoffPayload.self, from: json)

        #expect(decoded.url == original.url)
        #expect(decoded.owner == original.owner)
        #expect(decoded.repo == original.repo)
        #expect(decoded.pageKind == original.pageKind)
    }

    @Test("PR handoff payload encodes integer pr_number") 
    func prHandoffHasIntegerNumber() throws {
        let original = GitHubPullRequestHandoffPayload(
            url: "https://github.com/owner/repo",
            owner: "owner",
            repo: "repo",
            prNumber: 42,
            pageKind: .pullRequestConversation,
            triggeredBy: .toolbarButton
        )
        let json = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(GitHubPullRequestHandoffPayload.self, from: json)

        #expect(decoded.prNumber == 42)
    }

    @Test("Issue handoff payload encodes integer issue_number")
    func issueHandoffHasIntegerNumber() throws {
        let original = GitHubIssueHandoffPayload(
            url: "https://github.com/owner/repo",
            owner: "owner",
            repo: "repo",
            issueNumber: 99,
            triggeredBy: .contextMenu
        )
        let json = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(GitHubIssueHandoffPayload.self, from: json)

        #expect(decoded.issueNumber == 99)
    }

    @Test("Ping payload encodes correctly")
    func pingPayload() throws {
        let original = PingPayload(extensionVersion: "0.1.0", safariVersion: "18.0")
        let json = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(PingPayload.self, from: json)

        #expect(decoded.extensionVersion == "0.1.0")
        #expect(decoded.safariVersion == "18.0")
    }

    @Test("Accepted response encodes all fields")
    func acceptedResponse() throws {
        let original = AcceptedResponsePayload(
            inResponseTo: "msg-1",
            action: "handoff.github_repository",
            message: "Repository imported",
            repositoryStatus: .knownAndAvailable
        )
        let json = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(AcceptedResponsePayload.self, from: json)

        #expect(decoded.inResponseTo == "msg-1")
        #expect(decoded.repositoryStatus == .knownAndAvailable)
    }

    @Test("Refused response encodes refusal reason")
    func refusedResponse() throws {
        let original = RefusedResponsePayload(
            inResponseTo: "msg-1",
            action: "handoff",
            message: "Invalid token",
            refusalReason: .invalidMessage
        )
        let json = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(RefusedResponsePayload.self, from: json)

        #expect(decoded.refusalReason == .invalidMessage)
    }

    @Test("App unavailable response encodes correctly")
    func appUnavailableResponse() throws {
        let original = AppUnavailableResponsePayload(
            message: "App not running",
            reason: .appNotRunning
        )
        let json = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(AppUnavailableResponsePayload.self, from: json)

        #expect(decoded.reason == .appNotRunning)
    }
}

@Suite("Message Envelope")
struct MessageEnvelopeTests {

    @Test("Envelope uses created_at as canonical timestamp")
    func envelopeUsesCreatedAt() throws {
        let envelope = SafariExtensionResponseBuilder.accepted(
            inResponseTo: "test-1",
            action: "ping",
            repositoryStatus: .statusPending
        )

        #expect(!envelope.createdAt.isEmpty)
        #expect(envelope.sentAt == envelope.createdAt)
        #expect(envelope.sentAtAlias == envelope.createdAt)
    }

    @Test("Envelope validates direction")
    func envelopeValidatesDirection() throws {
        let envelope = SafariExtensionResponseBuilder.accepted(
            inResponseTo: "test-1",
            action: "ping",
            repositoryStatus: .statusPending
        )
        #expect(envelope.validateDirection())
    }

    @Test("Envelope refuses wrong direction kind")
    func envelopeRejectsWrongDirection() {
        let envelope = SafariExtensionResponseBuilder.accepted(
            inResponseTo: "wrong",
            action: "test",
            repositoryStatus: .statusPending
        )
        // Create envelope with mismatched direction
        let bad = SafariExtensionMessageEnvelope(
            schemaVersion: envelope.schemaVersion,
            messageId: envelope.messageId,
            direction: .extensionToApp,
            kind: envelope.kind,
            payload: envelope.payload,
            createdAt: envelope.createdAt
        )
        #expect(!bad.validateDirection())
    }

    @Test("toDictionary and fromJSON roundtrip")
    func dictionaryRoundtrip() throws {
        let envelope = SafariExtensionResponseBuilder.refused(
            inResponseTo: "msg-42",
            action: "handoff.github_repository",
            reason: .unsupportedGitHubContext,
            message: "Not a GitHub URL"
        )
        guard let dict = envelope.toDictionary(),
              let jsonData = try? JSONSerialization.data(withJSONObject: dict),
              let decoded = SafariExtensionMessageEnvelope(fromJSON: jsonData) else {
            #expect(Bool(false), "Roundtrip failed")
            return
        }
        #expect(decoded.kind == .responseRefused)
        #expect(decoded.direction == .appToExtension)
    }
}

@Suite("Content-Light Validation")
struct ContentLightValidationTests {

    @Test("Validator rejects token patterns")
    func rejectsTokenPatterns() {
        let validator = SafariExtensionContentLightValidator()
        let violations = validator.validateJSON([
            "message": "ghp_1234567890abcdef1234567890abcdef12345678"
        ])
        #expect(!violations.isEmpty)
        #expect(violations.contains { $0.contains("token") })
    }

    @Test("Validator rejects forbidden keys")
    func rejectsForbiddenKeys() {
        let validator = SafariExtensionContentLightValidator()
        let violations = validator.validateJSON([
            "file_contents": "some code",
            "url": "https://example.com"
        ])
        #expect(violations.contains { $0.contains("file_contents") })
    }

    @Test("Validator accepts clean messages")
    func acceptsCleanMessage() {
        let validator = SafariExtensionContentLightValidator()
        let violations = validator.validateJSON([
            "url": "https://github.com/owner/repo",
            "owner": "owner",
            "repo": "my-repo"
        ])
        #expect(violations.isEmpty)
    }

    @Test("Envelope-level validation works")
    func envelopeLevelValidation() {
        let envelope = SafariExtensionResponseBuilder.accepted(
            inResponseTo: "test",
            action: "ping",
            repositoryStatus: .statusPending
        )
        let validator = SafariExtensionContentLightValidator()
        let violations = validator.validateEnvelope(envelope)
        #expect(violations.isEmpty)
    }

    @Test("X4.1 — Rejects forbidden key in nested payload")
    func rejectsForbiddenKeyInNestedPayload() {
        let validator = SafariExtensionContentLightValidator()
        let violations = validator.validateJSON([
            "kind": "handoff.github_repository",
            "payload": [
                "raw_prompt": "secret prompt content",
                "url": "https://github.com/a/b",
            ]
        ])
        #expect(violations.contains { $0.contains("raw_prompt") })
    }

    @Test("X4.1 — Rejects credential-bearing URL parameters")
    func rejectsCredentialURLParams() {
        let validator = SafariExtensionContentLightValidator()
        let violations = validator.validateJSON([
            "url": "https://example.com?access_token=ghp_secret"
        ])
        #expect(violations.contains { $0.contains("credential_url_parameter") })
    }

    @Test("X4.1 — Rejects token pattern in nested URL string")
    func rejectsTokenInNestedField() {
        let validator = SafariExtensionContentLightValidator()
        let violations = validator.validateJSON([
            "payload": [
                "url": "https://github.com/owner/repo",
                "message": "Use token ghp_1234567890abcdef"
            ]
        ])
        #expect(violations.contains { $0.contains("payload.message") && $0.contains("token") })
    }

    @Test("X4.1 — Enforces 10,000-char message cap")
    func enforcesMaxChars() {
        let validator = SafariExtensionContentLightValidator()
        let longString = String(repeating: "x", count: 10001)
        let violations = validator.validateJSON(["message": longString])
        #expect(violations.contains { $0.contains("character_length_cap") })
    }

    @Test("X4.1 — Passes message near but under cap")
    func passesNearCap() {
        let validator = SafariExtensionContentLightValidator()
        let bodyText = String(repeating: "x", count: 9900)
        let violations = validator.validateJSON(["message": bodyText])
        #expect(!violations.contains { $0.contains("character_length_cap") })
    }
}

@Suite("Response Builders")
struct ResponseBuilderTests {

    @Test("Accepted response has correct shape")
    func acceptedBuilder() {
        let response = SafariExtensionResponseBuilder.accepted(
            inResponseTo: "msg-1",
            action: "handoff.github_repository",
            repositoryStatus: .knownAndAvailable,
            message: "OK"
        )
        #expect(response.kind == .responseAccepted)
        #expect(response.direction == .appToExtension)
        #expect(response.schemaVersion == SafariExtensionMessageSchema.currentVersion)
    }

    @Test("Deferred response has deferral reason")
    func deferredBuilder() {
        let response = SafariExtensionResponseBuilder.deferred(
            inResponseTo: "msg-1",
            action: "handoff.github_repository",
            reason: .nativeHostInitializing
        )
        #expect(response.kind == .responseDeferred)
    }

    @Test("Refused response has refusal reason")
    func refusedBuilder() {
        let response = SafariExtensionResponseBuilder.refused(
            inResponseTo: "msg-1",
            action: "handoff.github_issue",
            reason: .extensionNotAuthorized
        )
        #expect(response.kind == .responseRefused)
    }

    @Test("App unavailable response has message")
    func appUnavailableBuilder() {
        let response = SafariExtensionResponseBuilder.appUnavailable(
            message: "App not running",
            reason: .appNotRunning
        )
        #expect(response.kind == .responseAppUnavailable)
    }
}

@Suite("SafariExtensionHost")
struct SafariExtensionHostTests {

    @MainActor
    @Test("Host validates origin")
    func hostValidatesOrigin() {
        let host = SafariExtensionHost(
            allowedBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        let envelope = SafariExtensionResponseBuilder.accepted(
            inResponseTo: "test",
            action: "ping",
            repositoryStatus: .statusPending
        )
        let result = host.handleMessage(
            envelope,
            originBundleId: "wrong.bundle.id"
        )
        #expect(result != nil)
        #expect(result?.kind == .responseRefused)
    }

    @MainActor
    @Test("Host validates direction")
    func hostValidatesDirection() {
        let host = SafariExtensionHost(
            allowedBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        let badEnvelope = SafariExtensionMessageEnvelope(
            schemaVersion: SafariExtensionMessageSchema.currentVersion,
            messageId: UUID().uuidString,
            direction: .extensionToApp,
            kind: .responseAccepted,
            payload: .accepted(AcceptedResponsePayload(
                inResponseTo: "x", action: "x", message: nil, repositoryStatus: .statusPending
            )),
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
        let result = host.handleMessage(
            badEnvelope,
            originBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        #expect(result != nil)
        #expect(result?.kind == .responseRefused)
    }

    @MainActor
    @Test("Host processes valid repository handoff")
    func hostProcessesRepositoryHandoff() {
        let host = SafariExtensionHost(
            allowedBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        let envelope = SafariExtensionMessageEnvelope(
            schemaVersion: SafariExtensionMessageSchema.currentVersion,
            messageId: UUID().uuidString,
            direction: .extensionToApp,
            kind: .handoffGitHubRepository,
            payload: .repositoryHandoff(GitHubRepositoryHandoffPayload(
                url: "https://github.com/test/repo",
                owner: "test",
                repo: "repo",
                pageKind: .repositoryMain,
                triggeredBy: .popupAction
            )),
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
        let result = host.handleMessage(
            envelope,
            originBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        #expect(result != nil)
        #expect(result?.kind == .responseAccepted)
    }

    @MainActor
    @Test("Host processes PR handoff with integer number")
    func hostProcessesPRHandoff() {
        let host = SafariExtensionHost(
            allowedBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        let envelope = SafariExtensionMessageEnvelope(
            schemaVersion: SafariExtensionMessageSchema.currentVersion,
            messageId: UUID().uuidString,
            direction: .extensionToApp,
            kind: .handoffGitHubPullRequest,
            payload: .pullRequestHandoff(GitHubPullRequestHandoffPayload(
                url: "https://github.com/test/repo",
                owner: "test",
                repo: "repo",
                prNumber: 42,
                pageKind: .pullRequestConversation,
                triggeredBy: .popupAction
            )),
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
        let result = host.handleMessage(
            envelope,
            originBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        #expect(result != nil)
        #expect(result?.kind == .responseAccepted)
    }

    @MainActor
    @Test("Host processes ping")
    func hostProcessesPing() {
        let host = SafariExtensionHost(
            allowedBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        let envelope = SafariExtensionMessageEnvelope(
            schemaVersion: SafariExtensionMessageSchema.currentVersion,
            messageId: UUID().uuidString,
            direction: .extensionToApp,
            kind: .ping,
            payload: .ping(PingPayload(extensionVersion: "0.1.0", safariVersion: nil)),
            createdAt: ISO8601DateFormatter().string(from: Date())
        )
        let result = host.handleMessage(
            envelope,
            originBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        #expect(result != nil)
        #expect(result?.kind == .responseAccepted)
    }

    @MainActor
    @Test("Host diagnostic summary is content-light")
    func hostDiagnosticSummary() {
        let host = SafariExtensionHost(
            allowedBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        let summary = host.diagnosticSummary()
        #expect(summary["content_light"] as? String == "enforced")
        #expect(summary["schema_version"] != nil)
    }
}

@Suite("SafariExtensionContractSummary")
struct ContractSummaryTests {

    @Test("Contract summary documents X4 convergence deeds")
    func documentsConvergenceDeeds() {
        let summary = SafariExtensionContractSummary.v1()
        #expect(summary.x4ConvergenceDeeds.count == 5)
    }

    @Test("Contract summary lists blocking requirements")
    func listsBlockingRequirements() {
        let summary = SafariExtensionContractSummary.v1()
        #expect(!summary.blockingRequirements.isEmpty)
        #expect(summary.blockingRequirements.contains { $0.contains("Xcode project") })
    }

    @Test("Contract summary documents Sparkle notes")
    func documentsSparkleNotes() {
        let summary = SafariExtensionContractSummary.v1()
        #expect(summary.notes.contains { $0.contains("Sparkle") })
    }
}

@Suite("ExtensionStatusViewModel")
struct ExtensionStatusViewModelTests {

    @MainActor
    @Test("ViewModel reports convergence complete")
    func reportsConvergenceComplete() {
        let host = SafariExtensionHost(
            allowedBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        let vm = ExtensionStatusViewModel(extensionHost: host)
        #expect(vm.convergenceComplete)
    }

    @MainActor
    @Test("ViewModel supports all 8 kinds")
    func supportsAllKinds() {
        let host = SafariExtensionHost(
            allowedBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        let vm = ExtensionStatusViewModel(extensionHost: host)
        #expect(vm.supportedKinds.count == 8)
    }

    @MainActor
    @Test("ViewModel refresh updates from host")
    func refreshUpdatesFromHost() {
        let host = SafariExtensionHost(
            allowedBundleId: "com.rigrelay.RigRelayShell.SafariExtension"
        )
        let vm = ExtensionStatusViewModel(extensionHost: host)
        vm.refresh()
        #expect(vm.connectionState == "idle")
    }
}
