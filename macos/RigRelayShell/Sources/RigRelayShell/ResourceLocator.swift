import Foundation
import AppKit

struct ResourceLocator {
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
