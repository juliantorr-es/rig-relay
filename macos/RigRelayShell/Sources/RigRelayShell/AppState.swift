import Foundation
import Combine

@MainActor
final class AppState: ObservableObject {
    @Published var stage: String = "ready"
    @Published var statusOutput: String = ""
    @Published var doctorResult: String = ""
    @Published var isRunning: Bool = false
    @Published var helperFound: Bool = false
    @Published var demoSeeded: Bool = false
    @Published var docsBuilt: Bool = false
    @Published var cockpitRunning: Bool = false

    private let resourceLocator = ResourceLocator()

    init() {
        checkHelper()
        checkFirstRun()
        // Auto-seed demo data on first launch
        if helperFound && !demoSeeded {
            startDemo()
        }
    }

    func checkHelper() {
        helperFound = resourceLocator.helperExists()
        if !helperFound {
            statusOutput = "Helper not found at \(resourceLocator.helperPath)"
        }
    }

    func checkFirstRun() {
        let marker = resourceLocator.firstRunMarkerURL()
        demoSeeded = marker.isFileURL && FileManager.default.fileExists(atPath: marker.path)
    }

    // ── Commands ──────────────────────────────────────────────────

    func runDoctor() {
        stage = "doctor"
        isRunning = true
        statusOutput = "Running doctor..."
        runHelper(arg: "--demo-doctor") { [weak self] result in
            DispatchQueue.main.async {
                self?.isRunning = false
                self?.doctorResult = result.output
                self?.statusOutput = result.success ? "Doctor: all checks passed ✅" : "Doctor: issues found"
                self?.stage = "ready"
            }
        }
    }

    func startDemo() {
        stage = "seed"
        isRunning = true
        statusOutput = "Seeding demo data..."
        runHelper(arg: "--demo-seed") { [weak self] result in
            DispatchQueue.main.async {
                self?.isRunning = false
                self?.demoSeeded = result.success
                self?.statusOutput = result.success ? "Demo data seeded ✅" : "Seed failed: \(result.output)"
                self?.stage = "ready"
            }
        }
    }

    func renderDocs() {
        stage = "docs"
        isRunning = true
        statusOutput = "Building docs site..."
        runHelper(arg: "--demo-render-docs") { [weak self] result in
            DispatchQueue.main.async {
                self?.isRunning = false
                self?.docsBuilt = result.success
                self?.statusOutput = result.success ? "Docs built ✅" : "Docs build failed"
                self?.stage = "ready"
            }
        }
    }

    func launchCockpit() {
        guard !cockpitRunning else {
            statusOutput = "Cockpit already running"
            return
        }
        stage = "cockpit"
        isRunning = true
        cockpitRunning = true
        statusOutput = "Launching cockpit..."

        let helperURL = resourceLocator.helperExecutableURL()
        let process = Process()
        process.executableURL = helperURL
        process.arguments = ["--launch-cockpit"]
        process.environment = [
            "RIG_RELAY_PACKAGED_APP": "1",
            "RIG_RELAY_APP_SUPPORT": resourceLocator.applicationSupportURL().path,
        ]

        do {
            try process.run()
            DispatchQueue.main.async { [weak self] in
                self?.isRunning = false
                self?.statusOutput = "Cockpit launched"
                self?.stage = "ready"
            }
        } catch {
            DispatchQueue.main.async { [weak self] in
                self?.isRunning = false
                self?.cockpitRunning = false
                self?.statusOutput = "Launch failed: \(error.localizedDescription)"
                self?.stage = "ready"
            }
        }
    }

    func openDocs() {
        resourceLocator.openDocs()
    }

    func revealLogs() {
        resourceLocator.revealLogs()
    }

    // ── Internal ──────────────────────────────────────────────────

    private nonisolated func runHelper(arg: String, completion: @escaping (HelperResult) -> Void) {
        let helperURL = resourceLocator.helperExecutableURL()
        let process = Process()
        process.executableURL = helperURL
        process.arguments = [arg]
        process.environment = [
            "RIG_RELAY_PACKAGED_APP": "1",
            "RIG_RELAY_APP_SUPPORT": resourceLocator.applicationSupportURL().path,
        ]

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        do {
            try process.run()
            process.waitUntilExit()

            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8) ?? ""
            let success = process.terminationStatus == 0
            completion(HelperResult(success: success, output: output))
        } catch {
            completion(HelperResult(success: false, output: error.localizedDescription))
        }
    }
}

struct HelperResult {
    let success: Bool
    let output: String
}
