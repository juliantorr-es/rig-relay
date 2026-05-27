import WebKit
import SwiftUI

// ── WebKit WebView (S0: Bundled Gridline Frontend Host) ─────

struct WebKitWebView: NSViewRepresentable {
    let fileURL: URL
    let readAccessURL: URL
    let messageBridge: NativeMessageBridge
    let onLoadStateChange: (HostState) -> Void
    let allowedBaseURL: URL

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()

        // Non-persistent data store
        config.websiteDataStore = .nonPersistent()

        // Desktop-rendering preferences
        let prefs = WKWebpagePreferences()
        prefs.allowsContentJavaScript = true
        prefs.preferredContentMode = .desktop
        config.defaultWebpagePreferences = prefs

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        webView.allowsMagnification = false

        #if DEBUG
        webView.isInspectable = true
        #endif

        // Configure message bridge against this web view
        messageBridge.configure(for: webView)

        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        if context.coordinator.loadState == .uninitialized {
            // Verify local file exists before attempting load
            guard FileManager.default.fileExists(atPath: fileURL.path) else {
                onLoadStateChange(.resourceNotFound(
                    "Frontend index.html missing at \(fileURL.path)"
                ))
                return
            }

            // Verify index.html is a regular, readable file
            guard let attrs = try? FileManager.default.attributesOfItem(atPath: fileURL.path),
                  let fileType = attrs[.type] as? FileAttributeType,
                  fileType == .typeRegular else {
                onLoadStateChange(.resourceMalformed(
                    "Frontend resource is not a regular file: \(fileURL.lastPathComponent)"
                ))
                return
            }

            // Load bundled file with read access restricted to the frontend root
            webView.loadFileURL(fileURL, allowingReadAccessTo: readAccessURL)
        }
    }

    // ── Coordinator (WKNavigationDelegate) ──────────────────

    final class Coordinator: NSObject, WKNavigationDelegate {
        let parent: WebKitWebView
        var loadState: HostState = .uninitialized

        init(parent: WebKitWebView) {
            self.parent = parent
        }

        // ── Navigation Policy ──────────────────────────────

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                parent.onLoadStateChange(.unsupportedOrigin("No URL in request"))
                return
            }

            // Refuse all remote URLs
            guard url.isFileURL else {
                decisionHandler(.cancel)
                parent.onLoadStateChange(
                    .unsupportedOrigin("Blocked remote: \(url.absoluteString.prefix(100))")
                )
                return
            }

            // Allowed: file URLs within the permitted frontend resource root.
            // Use standardized URL paths to defeat sibling-prefix bypass
            // (e.g. /allowed/root -> /allowed/rootBAD/file would pass raw hasPrefix).
            let allowedPath = parent.allowedBaseURL.standardizedFileURL.path
            let candidatePath = url.standardizedFileURL.path
            if candidatePath == allowedPath
                || candidatePath.hasPrefix(allowedPath + "/") {
                decisionHandler(.allow)
                return
            }

            // Block out-of-root file URLs
            decisionHandler(.cancel)
            parent.onLoadStateChange(
                .unsupportedOrigin("Blocked out-of-root: \(url.absoluteString.prefix(100))")
            )
        }

        // ── Load Lifecycle ────────────────────────────────

        func webView(
            _ webView: WKWebView,
            didStartProvisionalNavigation navigation: WKNavigation!
        ) {
            loadState = .loadingFrontend
            parent.onLoadStateChange(.loadingFrontend)
        }

        func webView(
            _ webView: WKWebView,
            didFinish navigation: WKNavigation!
        ) {
            loadState = .frontendReady
            parent.onLoadStateChange(.frontendReady)

            // Send bootstrap message to frontend once loaded
            // (dispatched in ContentView via onLoadStateChange → appState)
        }

        func webView(
            _ webView: WKWebView,
            didFail navigation: WKNavigation!,
            withError error: Error
        ) {
            let nsError = error as NSError
            if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled {
                return
            }
            loadState = .frontendLoadFailed(error.localizedDescription)
            parent.onLoadStateChange(.frontendLoadFailed(error.localizedDescription))
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            let nsError = error as NSError
            if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled {
                return
            }
            // Provisional failure for local files means resource is corrupt or unreadable
            loadState = .resourceMalformed(
                "Failed to load frontend: \(error.localizedDescription)"
            )
            parent.onLoadStateChange(
                .resourceMalformed("Failed to load frontend: \(error.localizedDescription)")
            )
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            loadState = .error("Web content process terminated")
            parent.onLoadStateChange(.error("Web content process terminated"))
        }
    }
}
