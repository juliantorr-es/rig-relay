import SwiftUI

struct ContentView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        VStack(spacing: 0) {
            // ── Header ─────────────────────────────────────────
            headerView

            Divider()

            // ── Safety badges ──────────────────────────────────
            badgesView
                .padding(.horizontal, 24)
                .padding(.vertical, 12)

            Divider()

            // ── Buttons ────────────────────────────────────────
            buttonsView
                .padding(.horizontal, 24)
                .padding(.vertical, 16)

            Divider()

            // ── Status area ────────────────────────────────────
            statusView
                .padding(.horizontal, 24)
                .padding(.vertical, 12)

            Spacer(minLength: 0)

            // ── Footer ─────────────────────────────────────────
            footerView
        }
        .frame(minWidth: 520, minHeight: 480)
    }

    // ── Header ────────────────────────────────────────────────────

    var headerView: some View {
        HStack(spacing: 16) {
            Image(systemName: "shield.lefthalf.filled")
                .font(.system(size: 36))
                .foregroundColor(.accentColor)
                .frame(width: 48, height: 48)

            VStack(alignment: .leading, spacing: 2) {
                Text("Rig Relay")
                    .font(.title)
                    .fontWeight(.semibold)
                Text("Local governed runtime for agent work")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
            }

            Spacer()

            Text("v0.2")
                .font(.caption)
                .foregroundColor(.secondary)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 4))
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 20)
    }

    // ── Badges ────────────────────────────────────────────────────

    var badgesView: some View {
        HStack(spacing: 8) {
            BadgeView(label: "Local Demo", value: "On", color: .green)
            BadgeView(label: "Network", value: "Off", color: .secondary)
            BadgeView(label: "OAuth", value: "None", color: .secondary)
            BadgeView(label: "API Keys", value: "Not required", color: .green)
            BadgeView(label: "Merge", value: "Disabled", color: .orange)
            BadgeView(label: "Push", value: "Disabled", color: .orange)
        }
    }

    // ── Buttons ───────────────────────────────────────────────────

    var buttonsView: some View {
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                actionButton("Run Doctor", systemImage: "stethoscope") {
                    appState.runDoctor()
                }
                actionButton("Start Demo", systemImage: "play.fill") {
                    appState.startDemo()
                }
            }
            HStack(spacing: 8) {
                actionButton("Launch Cockpit", systemImage: "rectangle.inset.filled.and.person.filled") {
                    appState.launchCockpit()
                }
                .disabled(appState.cockpitRunning)

                actionButton("Build Docs", systemImage: "doc.text.fill") {
                    appState.renderDocs()
                }
            }
            HStack(spacing: 8) {
                actionButton("Open Docs", systemImage: "book.fill") {
                    appState.openDocs()
                }
                actionButton("Reveal Logs", systemImage: "folder.fill") {
                    appState.revealLogs()
                }
            }
        }
    }

    func actionButton(_ title: String, systemImage: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .controlSize(.large)
        .disabled(appState.isRunning)
    }

    // ── Status ────────────────────────────────────────────────────

    var statusView: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Circle()
                    .fill(appState.helperFound ? Color.green : Color.red)
                    .frame(width: 8, height: 8)
                Text("Helper: \(appState.helperFound ? "Found" : "Missing")")
                    .font(.caption)
                    .foregroundColor(.secondary)

                Spacer()

                if appState.isRunning {
                    ProgressView()
                        .scaleEffect(0.7)
                        .frame(width: 16, height: 16)
                }
            }

            if !appState.statusOutput.isEmpty {
                Text(appState.statusOutput)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(3)
            }

            if !appState.doctorResult.isEmpty {
                ScrollView {
                    Text(appState.doctorResult)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(.secondary)
                        .textSelection(.enabled)
                }
                .frame(maxHeight: 100)
                .padding(8)
                .background(.quinary, in: RoundedRectangle(cornerRadius: 6))
            }
        }
    }

    // ── Footer ────────────────────────────────────────────────────

    var footerView: some View {
        HStack {
            Text("Runs locally. No account, API key, network, merge, or push required.")
                .font(.caption2)
                .foregroundColor(.secondary)

            Spacer()

            Button("Quit") {
                NSApplication.shared.terminate(nil)
            }
            .buttonStyle(.borderless)
            .font(.caption)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 10)
        .background(.regularMaterial)
    }
}

// ── Badge ────────────────────────────────────────────────────────

struct BadgeView: View {
    let label: String
    let value: String
    let color: Color

    var body: some View {
        HStack(spacing: 4) {
            Text(label)
                .font(.caption2)
                .foregroundColor(.secondary)
            Text(value)
                .font(.caption2)
                .fontWeight(.medium)
                .foregroundColor(color)
                .padding(.horizontal, 4)
                .padding(.vertical, 2)
                .background(color.opacity(0.15), in: RoundedRectangle(cornerRadius: 3))
        }
    }
}
