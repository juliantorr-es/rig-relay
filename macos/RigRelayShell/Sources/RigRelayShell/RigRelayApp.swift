import SwiftUI

@main
struct RigRelayApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .frame(minWidth: 800, idealWidth: 1000, maxWidth: .infinity,
                       minHeight: 560, idealHeight: 700, maxHeight: .infinity)
        }
        .windowStyle(.titleBar)
        .windowResizability(.contentMinSize)
        .defaultSize(width: 1000, height: 700)
        .commands {
            CommandGroup(replacing: .newItem) {}

            CommandMenu("Navigation") {
                ForEach(GridlineTab.allCases, id: \.self) { tab in
                    Button(tab.rawValue) {
                        appState.selectedTab = tab
                    }
                    .keyboardShortcut(keyboardShortcut(for: tab))
                }
            }

            CommandMenu("Demo") {
                Button("Load Full Demo Projection") {
                    appState.loadFixtureForDemo()
                }
                .keyboardShortcut("d", modifiers: [.command, .option])

                Divider()

                Button("Simulate Connect Flow") {
                    appState.simulateConnectFlow()
                }
                Button("Simulate Repository Import") {
                    appState.simulateRepositoryImport()
                }
                Button("Simulate Investigation") {
                    appState.simulateInvestigation()
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

    func keyboardShortcut(for tab: GridlineTab) -> KeyEquivalent {
        switch tab {
        case .connect: "1"
        case .repositories: "2"
        case .projectStudio: "3"
        case .inference: "4"
        case .publish: "5"
        }
    }
}
