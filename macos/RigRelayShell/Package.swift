// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "RigRelayShell",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "RigRelayShell", targets: ["RigRelayShell"]),
    ],
    targets: [
        .executableTarget(
            name: "RigRelayShell",
            path: "Sources/RigRelayShell"
        ),
    ]
)
