import Testing
import Foundation
@testable import RigRelayShell

// ── BootstrapMessage Contract Tests ────────────────────────

struct BootstrapMessageTests {

    @Test func bootstrapMessageEncodesToValidJSON() {
        let payload = BootstrapPayload(
            resourceLoadResult: ResourceLoadResult(
                resolvedPathHash: "sha256:abcdef",
                indexHTMLFound: true,
                subresourceCount: 42,
                missingSubresources: [],
                loadError: nil
            ),
            bridgeAvailable: true,
            supportedCapabilityKinds: ["host_state_query"],
            refusalReasons: [],
            appVersion: "0.2.0-dev",
            buildCommitSHA: nil,
            transportStatus: "local_file"
        )

        let message = BootstrapMessage(
            schemaVersion: BootstrapMessage.currentVersion,
            messageId: "bootstrap_test",
            kind: .hostReady,
            sessionId: "test_session",
            payload: payload,
            traceId: nil,
            sentAt: "2026-05-26T00:00:00Z"
        )

        let dict = message.asDictionary()
        #expect(dict != nil)
        #expect(dict?["schema_version"] as? String == "rig.relay.native_bootstrap.v1")
        #expect(dict?["kind"] as? String == "host_ready")
        #expect(dict?["session_id"] as? String == "test_session")
    }

    @Test func bootstrapMessageResourceFailureEncodes() {
        let payload = BootstrapPayload(
            resourceLoadResult: ResourceLoadResult(
                resolvedPathHash: "sha256:unavailable",
                indexHTMLFound: false,
                subresourceCount: 0,
                missingSubresources: ["css", "js"],
                loadError: "Gridline frontend index.html not found in bundle"
            ),
            bridgeAvailable: true,
            supportedCapabilityKinds: [],
            refusalReasons: ["frontend_resources_missing"],
            appVersion: nil,
            buildCommitSHA: nil,
            transportStatus: "local_file"
        )

        let message = BootstrapMessage(
            schemaVersion: BootstrapMessage.currentVersion,
            messageId: "bootstrap_fail",
            kind: .hostResourceFailure,
            sessionId: "fail_session",
            payload: payload,
            traceId: "trace_123",
            sentAt: "2026-05-26T00:00:00Z"
        )

        let dict = message.asDictionary()
        #expect(dict != nil)
        #expect(dict?["kind"] as? String == "host_resource_failure")
        #expect(dict?["trace_id"] as? String == "trace_123")

        let payloadDict = dict?["payload"] as? [String: Any]
        let resourceResult = payloadDict?["resource_load_result"] as? [String: Any]
        #expect(resourceResult?["index_html_found"] as? Bool == false)
    }

    @Test func bootstrapRefusalEncodes() {
        let refusal = BootstrapRefusal(
            schemaVersion: BootstrapRefusal.currentVersion,
            refusedKind: "unsupported_capability",
            reason: "not_implemented_in_host_shell",
            allowedKinds: ["host_state_query", "extension_status_query"],
            traceId: "trace_refuse_1",
            sentAt: "2026-05-26T00:00:00Z"
        )

        let dict = refusal.asDictionary()
        #expect(dict != nil)
        #expect(dict?["schema_version"] as? String == "rig.relay.native_bootstrap_refusal.v1")
        #expect(dict?["refused_kind"] as? String == "unsupported_capability")
        #expect((dict?["allowed_kinds"] as? [String])?.count == 2)
    }

    @Test func bootstrapMessageIsContentLight() {
        let payload = BootstrapPayload(
            resourceLoadResult: ResourceLoadResult(
                resolvedPathHash: "sha256:abcdef",
                indexHTMLFound: true,
                subresourceCount: 1,
                missingSubresources: [],
                loadError: nil
            ),
            bridgeAvailable: true,
            supportedCapabilityKinds: [],
            refusalReasons: [],
            appVersion: nil,
            buildCommitSHA: nil,
            transportStatus: "local_file"
        )

        let message = BootstrapMessage(
            schemaVersion: BootstrapMessage.currentVersion,
            messageId: "test",
            kind: .hostReady,
            sessionId: "s",
            payload: payload,
            traceId: nil,
            sentAt: ""
        )

        let dict = message.asDictionary() ?? [:]
        let jsonString = String(data: try! JSONSerialization.data(withJSONObject: dict), encoding: .utf8) ?? ""

        // Content-light guarantee: no raw file contents, no secrets
        #expect(!jsonString.contains("raw_file_contents"))
        #expect(!jsonString.contains("api_key"))
        #expect(!jsonString.contains("private_key"))
        #expect(!jsonString.contains("password"))
        #expect(!jsonString.contains("<html"))
        #expect(!jsonString.contains("function("))
    }
}

// ── Resource Locator Tests (integration: requires bundled resources) ──

struct ResourceLocatorTests {

    private var resolvedBundle: Bundle? {
        let loc = ResourceLocator()
        if loc.gridlineFrontendResourceExists() {
            // Already resolved correctly
            return nil // use default
        }
        // Try main bundle (for Xcode/SPM test runner)
        if let mainResource = Bundle.main.resourceURL {
            let indexPath = mainResource
                .appendingPathComponent("GridlineFrontend")
                .appendingPathComponent("index.html")
            if FileManager.default.fileExists(atPath: indexPath.path) {
                return .main
            }
        }
        // Try the main module bundle path via executable parent
        if let execURL = Bundle.main.executableURL {
            let buildDir = execURL.deletingLastPathComponent()
            let resourcePath = buildDir
                .appendingPathComponent("RigRelayShell_RigRelayShell.bundle")
                .appendingPathComponent("Contents")
                .appendingPathComponent("Resources")
            let indexPath = resourcePath.appendingPathComponent("GridlineFrontend").appendingPathComponent("index.html")
            if FileManager.default.fileExists(atPath: indexPath.path) {
                return Bundle(path: resourcePath.path)
            }
        }
        return nil
    }

    private var resourceLocator: ResourceLocator? {
        if let bundle = resolvedBundle {
            return ResourceLocator(resourceBundle: bundle)
        }
        let loc = ResourceLocator()
        return loc.gridlineFrontendResourceExists() ? loc : nil
    }

    @Test func frontendResourcesBundledAtBuildTime() {
        let loc = ResourceLocator()
        let url = loc.gridlineFrontendIndexURL
        #expect(url != nil, "Bundle must contain GridlineFrontend/index.html. Bug: resource bundle not found.")
    }

    @Test func indexHTMLIsRegularFile() {
        guard let loc = resourceLocator else {
            Issue.record("Skipping: bundled resources not found in test context")
            return
        }
        #expect(loc.gridlineFrontendResourceExists(), "index.html must exist as a regular file")
    }

    @Test func assetCountExceedsMinimum() {
        guard let loc = resourceLocator else {
            Issue.record("Skipping: bundled resources not found in test context")
            return
        }
        let count = loc.gridlineFrontendAssetCount()
        #expect(count >= 10, "Expected 10+ bundled frontend files, got \(count)")
    }

    @Test func contentHashIsSHA256() {
        guard let loc = resourceLocator else {
            Issue.record("Skipping: bundled resources not found in test context")
            return
        }
        let hash = loc.gridlineFrontendIndexContentsHash()
        #expect(hash != nil, "Must produce a SHA256 hash of index.html")
        #expect(hash!.hasPrefix("sha256:"), "Hash must use sha256: prefix, got: \(hash!)")
    }

    @Test func indexURLIsFileURLNotRemote() {
        guard let loc = resourceLocator,
              let url = loc.gridlineFrontendIndexURL else {
            Issue.record("Skipping: bundled resources not found in test context")
            return
        }
        #expect(url.isFileURL, "Frontend URL must be a file:// URL, not a remote URL. Got: \(url)")
    }

    @Test func rootDirectoryExists() {
        guard let loc = resourceLocator,
              let root = loc.gridlineFrontendRootURL else {
            Issue.record("Skipping: bundled resources not found in test context")
            return
        }
        var isDir: ObjCBool = false
        let exists = FileManager.default.fileExists(atPath: root.path, isDirectory: &isDir)
        #expect(exists, "Frontend root directory must exist at \(root.path)")
        #expect(isDir.boolValue, "Frontend root must be a directory")
    }

    @Test func noRequiredSubdirectoriesMissing() {
        guard let loc = resourceLocator else {
            Issue.record("Skipping: bundled resources not found in test context")
            return
        }
        let missing = loc.gridlineFrontendMissingSubresources()
        #expect(missing.isEmpty, "Required subdirectories (css, js) must exist, missing: \(missing)")
    }
}

// ── HostState Exhaustiveness Tests ─────────────────────────

struct HostStateTests {

    @Test func resourceNotFoundState() {
        let state = HostState.resourceNotFound("test detail")
        #expect(state.label == "Resources Not Found")
        #expect(state.isTerminal)
    }

    @Test func resourceMalformedState() {
        let state = HostState.resourceMalformed("test detail")
        #expect(state.label == "Resources Corrupt")
        #expect(state.isTerminal)
    }

    @Test func resolvingResourcesIsTransient() {
        #expect(!HostState.resolvingResources.isTerminal)
    }

    @Test func frontendReadyIsStable() {
        #expect(!HostState.frontendReady.isTerminal)
    }

    @Test func unsupportedOriginIsTerminal() {
        #expect(HostState.unsupportedOrigin("blocked").isTerminal)
    }

    @Test func allHostStatesHaveLabels() {
        let states: [HostState] = [
            .uninitialized, .booting, .resolvingResources,
            .resourceNotFound(""), .resourceMalformed(""),
            .loadingFrontend, .frontendReady,
            .frontendLoadFailed(""), .bridgeUnavailable,
            .unsupportedOrigin(""), .error(""),
            .extensionStatusUnknown
        ]
        for state in states {
            #expect(!state.label.isEmpty, "\(state) must have a non-empty label")
        }
    }
}
