import WebKit
import SwiftUI

// MARK: - WebKit WebView (NSViewRepresentable for SwiftUI)

struct WebKitWebView: NSViewRepresentable {
    let url: URL
    let messageBridge: NativeMessageBridge
    let onLoadStateChange: (HostState) -> Void
    let trustedHost: String
    let trustedPort: Int

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()

        // Non-persistent data store — no cookie/credential persistence between sessions
        config.websiteDataStore = .nonPersistent()

        // Default webpage preferences
        let prefs = WKWebpagePreferences()
        prefs.allowsContentJavaScript = true
        prefs.preferredContentMode = .desktop
        config.defaultWebpagePreferences = prefs

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        webView.allowsMagnification = false

        // Enable Safari Web Inspector in development
        #if DEBUG
        webView.isInspectable = true
        #endif

        // Configure message bridge against this web view
        messageBridge.configure(for: webView)

        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        // Only load if not already loading
        if context.coordinator.loadState == .uninitialized {
            let request = URLRequest(
                url: url,
                cachePolicy: .reloadIgnoringLocalAndRemoteCacheData,
                timeoutInterval: 30
            )
            webView.load(request)
        }
    }

    // MARK: - Coordinator (WKNavigationDelegate)

    final class Coordinator: NSObject, WKNavigationDelegate {
        let parent: WebKitWebView
        var loadState: HostState = .uninitialized

        init(parent: WebKitWebView) {
            self.parent = parent
        }

        // MARK: — Navigation Policy

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url,
                  let host = url.host else {
                decisionHandler(.cancel)
                parent.onLoadStateChange(.unsupportedOrigin("No host in URL"))
                return
            }

            // Only allow navigation to the trusted host and port
            if host == parent.trustedHost && url.port == parent.trustedPort {
                decisionHandler(.allow)
            } else {
                decisionHandler(.cancel)
                parent.onLoadStateChange(
                    .unsupportedOrigin("Blocked: \(url.absoluteString.prefix(100))")
                )
            }
        }

        // MARK: — Load Lifecycle

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
        }

        func webView(
            _ webView: WKWebView,
            didFail navigation: WKNavigation!,
            withError error: Error
        ) {
            let nsError = error as NSError
            // NSURLErrorCancelled (-999) is expected during navigation policy rejections
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
            // Provisional navigation failures indicate the bridge server is down
            loadState = .bridgeUnavailable
            parent.onLoadStateChange(.bridgeUnavailable)
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            loadState = .error("Web content process terminated")
            parent.onLoadStateChange(.error("Web content process terminated"))
        }
    }
}
