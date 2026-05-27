import SwiftUI

@main
struct RigRelayApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
        }
        .windowStyle(.titleBar)
        .windowResizability(.contentMinSize)
        .defaultSize(width: 1200, height: 800)
        .commands {
            CommandGroup(replacing: .newItem) {}

            CommandMenu("View") {
                Button("Reload Frontend") {
                    appState.retryLoading()
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])
            }

            CommandMenu("Debug") {
                Button("Show Extension Contract") {
                    appState.showExtensionStatus.toggle()
                }
            }

            CommandGroup(replacing: .help) {
                Button("Rig Relay Help") {
                    if let url = URL(string: "https://github.com/juliantorr-es/rig-relay") {
                        NSWorkspace.shared.open(url)
                    }
                }
            }
        }
    }
}
