import Foundation
import AppKit
import CryptoKit

struct ResourceLocator {

    private let resourceBundle: Bundle

    init(resourceBundle: Bundle? = nil) {
        self.resourceBundle = resourceBundle ?? Self.resolveResourceBundle()
    }

    private static func resolveResourceBundle() -> Bundle {
        // Bundle.module works in the main target (production).
        // In test targets, fall back to searching from executable path.
        if let gridlineURL = Bundle.module.url(
            forResource: "index",
            withExtension: "html",
            subdirectory: "GridlineFrontend"
        ), FileManager.default.fileExists(atPath: gridlineURL.path) {
            return .module
        }

        // Try main bundle (for when bundled inside a .app)
        if let resourceURL = Bundle.main.resourceURL {
            let gridlinePath = resourceURL
                .appendingPathComponent("GridlineFrontend")
                .appendingPathComponent("index.html")
                .path
            if FileManager.default.fileExists(atPath: gridlinePath) {
                return .main
            }
        }

        // Fall back to Bundle.module (will fail gracefully at call sites)
        return .module
    }

    // ── Gridline Frontend (bundled in Resources/GridlineFrontend/) ──

    var gridlineFrontendIndexURL: URL? {
        resourceBundle.url(
            forResource: "index",
            withExtension: "html",
            subdirectory: "GridlineFrontend"
        )
    }

    var gridlineFrontendRootURL: URL? {
        resourceBundle.resourceURL?
            .appendingPathComponent("GridlineFrontend")
    }

    func gridlineFrontendResourceExists() -> Bool {
        guard let url = gridlineFrontendIndexURL else { return false }
        return FileManager.default.fileExists(atPath: url.path)
    }

    func gridlineFrontendAssetCount() -> Int {
        guard let root = gridlineFrontendRootURL,
              let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)
        else { return 0 }
        return enumerator.allObjects.count
    }

    func gridlineFrontendMissingSubresources() -> [String] {
        let requiredSubdirs = ["css", "js"]
        guard let root = gridlineFrontendRootURL else { return requiredSubdirs }
        var missing: [String] = []
        for sub in requiredSubdirs {
            let path = root.appendingPathComponent(sub)
            if !FileManager.default.fileExists(atPath: path.path) {
                missing.append(sub)
            }
        }
        return missing
    }

    func gridlineFrontendIndexContentsHash() -> String? {
        guard let url = gridlineFrontendIndexURL,
              let data = try? Data(contentsOf: url) else { return nil }
        let hash = SHA256.hash(data: data)
        return "sha256:\(hash.compactMap { String(format: "%02x", $0) }.joined())"
    }
    // ── Bundle paths ──────────────────────────────────────────

    var helperPath: String {
        // Helper is at Contents/Resources/RigRelayHelper/RigRelay
        guard let resources = Bundle.main.resourceURL else {
            return ""
        }
        return resources
            .appendingPathComponent("RigRelayHelper")
            .appendingPathComponent("RigRelay")
            .path
    }

    func helperExists() -> Bool {
        let path = helperPath
        guard !path.isEmpty else { return false }
        return FileManager.default.isExecutableFile(atPath: path)
    }

    func helperExecutableURL() -> URL {
        URL(fileURLWithPath: helperPath)
    }

    // ── Application Support ───────────────────────────────────

    func applicationSupportURL() -> URL {
        let base = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first!
        return base.appendingPathComponent("Rig Relay")
    }

    func firstRunMarkerURL() -> URL {
        applicationSupportURL().appendingPathComponent(".first_run_complete")
    }

    // ── Docs ──────────────────────────────────────────────────

    func docsIndexURL() -> URL {
        applicationSupportURL()
            .appendingPathComponent("docs-site")
            .appendingPathComponent("index.html")
    }

    @MainActor
    func openDocs() {
        let url = docsIndexURL()
        if FileManager.default.fileExists(atPath: url.path) {
            NSWorkspace.shared.open(url)
        } else {
            // Try to build docs first, then open
            let alert = NSAlert()
            alert.messageText = "Docs not built"
            alert.informativeText = "Click 'Build Docs' first to generate the docs site."
            alert.runModal()
        }
    }

    // ── Logs ──────────────────────────────────────────────────

    func logsURL() -> URL {
        applicationSupportURL()
            .appendingPathComponent("logs")
            .appendingPathComponent("startup.log")
    }

    func revealLogs() {
        let logsDir = applicationSupportURL().appendingPathComponent("logs")
        if !FileManager.default.fileExists(atPath: logsDir.path) {
            try? FileManager.default.createDirectory(
                at: logsDir, withIntermediateDirectories: true
            )
        }
        NSWorkspace.shared.activateFileViewerSelecting([logsDir])
    }
}
