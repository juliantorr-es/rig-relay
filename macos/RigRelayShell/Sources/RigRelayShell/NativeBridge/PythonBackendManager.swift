import Foundation
import OSLog

// ── Python Backend Manager (X0.2: Native Transport Bridge) ──
//
// Launches the Rig Relay Python backend as a managed subprocess,
// monitors its health, and provides the server URL, WebSocket URL,
// and auth token to the native host so the WKWebView frontend can
// connect to a real governed backend instead of falling through
// to a broken fallback.

@MainActor
final class PythonBackendManager: ObservableObject {
    @Published var state: BackendState = .stopped

    private let logger = Logger(subsystem: "com.rigrelay.RigRelayShell", category: "PythonBackend")
    private var process: Process?
    private var outputPipe: Pipe?
    private var errorPipe: Pipe?
    private var healthCheckTask: Task<Void, Never>?

    private(set) var serverHost: String = "127.0.0.1"
    private(set) var serverPort: Int = 9876
    private(set) var authToken: String = ""
    private(set) var commandPath: String

    var serverURL: String {
        "http://\(serverHost):\(serverPort)"
    }

    var wsURL: String {
        "ws://\(serverHost):\(serverPort)/ws"
    }

    // ── Init ────────────────────────────────────────────

    init(
        port: Int = 9876,
        commandPath: String = "uv",
        autoLaunch: Bool = false
    ) {
        self.serverPort = port
        self.commandPath = commandPath
        self.authToken = Self.generateAuthToken()
        if autoLaunch {
            Task { @MainActor in await launch() }
        }
    }

    // ── Public API ─────────────────────────────────────

    func launch() async {
        guard state == .stopped else {
            logger.warning("launch() called but backend is already \(self.state.label)")
            return
        }

        state = .launching
        logger.info("Launching Python backend on port \(self.serverPort)...")

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = [
            commandPath,
            "run", "rig-relay",
            "--server-only",
            "--ws-port", "\(serverPort)",
            "--auth-token", authToken,
            "--allow-null-origin",
        ]
        process.currentDirectoryURL = resolveWorkingDirectory()

        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe
        self.outputPipe = outPipe
        self.errorPipe = errPipe

        // Monitor stdout for health signal
        healthCheckTask = Task { [weak self] in
            await self?.monitorHealth(outputPipe: outPipe)
        }

        process.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                self?.handleTermination(exitCode: proc.terminationStatus, reason: proc.terminationReason)
            }
        }

        do {
            try process.run()
            self.process = process
            logger.info("Python backend process started (PID \(process.processIdentifier))")
        } catch {
            logger.error("Failed to launch Python backend: \(error.localizedDescription)")
            state = .failed("Launch failed: \(error.localizedDescription)")
            healthCheckTask?.cancel()
            healthCheckTask = nil
        }
    }

    func stop() {
        healthCheckTask?.cancel()
        healthCheckTask = nil

        guard let process else {
            state = .stopped
            return
        }

        logger.info("Stopping Python backend (PID \(process.processIdentifier))")

        if process.isRunning {
            process.terminate()
            // Give it a moment to shut down gracefully
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
                guard let self, let proc = self.process, proc.isRunning else { return }
                self.logger.warning("Backend didn't exit — force killing")
                proc.interrupt()
            }
        }

        self.process = nil
        outputPipe = nil
        errorPipe = nil
        state = .stopped
    }

    func restart() async {
        stop()
        // Brief pause to let the old process release its port
        try? await Task.sleep(nanoseconds: 500_000_000) // 500ms
        await launch()
    }

    // ── Health Monitoring ──────────────────────────────

    private func monitorHealth(outputPipe: Pipe) async {
        let handle = outputPipe.fileHandleForReading
        var buffer = Data()

        // Timeout: if backend doesn't signal healthy within 30 seconds, mark failed
        let start = Date()
        let timeout: TimeInterval = 30.0

        while !Task.isCancelled {
            // Check timeout
            if Date().timeIntervalSince(start) > timeout {
                logger.error("Backend health timeout after \(timeout) seconds")
                await MainActor.run { [weak self] in
                    guard let self, self.state == .launching else { return }
                    self.state = .failed("Health timeout: no startup signal within \(Int(timeout))s")
                }
                return
            }

            let avail = handle.availableData
            if avail.isEmpty {
                // Process may have exited — check and break
                if process?.isRunning == false {
                    break
                }
                try? await Task.sleep(nanoseconds: 100_000_000) // 100ms
                continue
            }

            buffer.append(avail)
            guard let text = String(data: buffer, encoding: .utf8) else { continue }

            // Look for health markers
            if text.contains("WebSocket projection stream on")
                || text.contains("Server-only mode. Bridge is running.") {
                logger.info("Backend healthy — WebSocket server started on port \(self.serverPort)")
                await MainActor.run { [weak self] in
                    guard let self, self.state == .launching else { return }
                    self.state = .healthy
                }
                // Keep reading output for logging but don't block
                readRemaining(outputPipe: outputPipe)
                return
            }

            // Check for fatal errors in output
            if text.contains("Failed to start bridge server")
                || text.contains("Falling back to dry-run") {
                let reason = extractErrorMessage(from: text) ?? "Bridge startup failed"
                logger.error("Backend startup failed: \(reason)")
                await MainActor.run { [weak self] in
                    guard let self, self.state == .launching else { return }
                    self.state = .failed(reason)
                }
                return
            }

            buffer = Data()
        }
    }

    private func readRemaining(outputPipe: Pipe) {
        Task.detached { [logger] in
            let handle = outputPipe.fileHandleForReading
            while true {
                let data = handle.availableData
                if data.isEmpty { break }
                if let text = String(data: data, encoding: .utf8) {
                    logger.debug("Backend stdout: \(text.trimmingCharacters(in: .whitespacesAndNewlines))")
                }
            }
        }
    }

    private func handleTermination(exitCode: Int32, reason: Process.TerminationReason) {
        logger.warning("Backend process terminated (exit \(exitCode), reason \(reason.rawValue))")

        if state == .healthy {
            state = .crashed(exitCode)
        } else if state == .launching {
            // Read any remaining error output
            if let errData = errorPipe?.fileHandleForReading.readDataToEndOfFile(),
               let errText = String(data: errData, encoding: .utf8) {
                logger.error("Backend stderr during launch: \(errText.trimmingCharacters(in: .whitespacesAndNewlines))")
            }
            state = .failed("Process exited with code \(exitCode) during launch")
        }

        healthCheckTask?.cancel()
        healthCheckTask = nil
        process = nil
    }

    // ── Helpers ────────────────────────────────────────

    private func resolveWorkingDirectory() -> URL? {
        // Navigate from the .app bundle to the source root.
        // In dev: the app runs from DerivedData; we search upward for pyproject.toml.
        // In prod: the app is at RigRelayShell.app, and the working directory
        // is set at launch by the shell wrapper.

        let marker = "pyproject.toml"
        var url = Bundle.main.bundleURL
            .deletingLastPathComponent()  // MacOS/
            .deletingLastPathComponent()  // Contents/
            .deletingLastPathComponent()  // .app/

        for _ in 0..<8 {
            let candidate = url.appendingPathComponent(marker)
            if FileManager.default.fileExists(atPath: candidate.path) {
                return url
            }
            url = url.deletingLastPathComponent()
        }

        // Fallback: use the directory two levels up from the executable
        return Bundle.main.executableURL?
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            ?? URL(fileURLWithPath: NSHomeDirectory())
    }

    private func extractErrorMessage(from text: String) -> String? {
        let patterns = [
            "Failed to start bridge server:",
            "Falling back to dry-run mode...",
        ]
        for pattern in patterns {
            if let range = text.range(of: pattern) {
                let after = String(text[range.upperBound...])
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                if !after.isEmpty {
                    return String(after.prefix(200))
                }
            }
        }
        return nil
    }

    private static func generateAuthToken() -> String {
        let bytes = (0..<32).map { _ in UInt8.random(in: 0...255) }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    // ── Runtime Config (for JS injection) ─────────────

    var runtimeConfigJSON: String {
        let config: [String: Any] = [
            "ws_url": wsURL,
            "token": authToken,
            "auth_token": authToken,
            "bridge_origin": serverURL,
            "bridge_host": serverHost,
            "bridge_port": serverPort,
            "tls_enabled": false,
            "tls_mode": "insecure",
            "transport_label": "Native Loopback Bridge",
            "local_mode": true,
            "auth_required": true,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: config),
              let json = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return json
    }
}

// ── Backend State ────────────────────────────────────

enum BackendState: Sendable, Equatable {
    case stopped
    case launching
    case healthy
    case failed(String)
    case crashed(Int32)

    var label: String {
        switch self {
        case .stopped: "Stopped"
        case .launching: "Launching Python Backend..."
        case .healthy: "Backend Running"
        case .failed(let msg): "Backend Failed: \(msg)"
        case .crashed(let code): "Backend Crashed (exit \(code))"
        }
    }

    var isHealthy: Bool {
        if case .healthy = self { return true }
        return false
    }

    var isStopped: Bool {
        if case .stopped = self { return true }
        return false
    }
}
