import SwiftUI

@main
struct RigRelayApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .frame(minWidth: 520, idealWidth: 560, maxWidth: 640,
                       minHeight: 480, idealHeight: 520, maxHeight: 600)
        }
        .windowStyle(.titleBar)
        .windowResizability(.contentSize)
        .defaultSize(width: 560, height: 520)
    }
}
