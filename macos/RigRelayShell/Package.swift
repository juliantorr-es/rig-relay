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
            path: "Sources/RigRelayShell",
            resources: [.copy("Resources/GridlineFrontend")]
        ),
        .testTarget(
            name: "RigRelayShellTests",
            dependencies: ["RigRelayShell"],
            path: "Tests/RigRelayShellTests"
        ),
    ]
)
