import WebKit

// MARK: - Native Message Bridge (Host ↔ Frontend)

@MainActor
final class NativeMessageBridge: NSObject, WKScriptMessageHandler, @unchecked Sendable {

    private weak var webView: WKWebView?
    private var pendingSendQueue: [[String: Any]] = []

    // MARK: — Configuration

    func configure(for webView: WKWebView) {
        self.webView = webView
        let controller = webView.configuration.userContentController

        controller.add(self, name: "rigHostBridge")

        // Inject bridge script at document start (runs before any frontend JS)
        let bridgeScript = WKUserScript(
            source: _bridgeScriptSource,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        controller.addUserScript(bridgeScript)
    }

    // MARK: — Frontend → Host (fire-and-forget)

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        guard message.name == "rigHostBridge" else { return }
        guard let body = message.body as? [String: Any] else { return }

        let kind = body["kind"] as? String ?? ""
        let traceId = body["trace_id"] as? String ?? ""
        _ = traceId

        // Only dispatch recognized message kinds to prevent spoofing
        switch kind {
        case "get_host_state", "open_file_dialog", "get_extension_status":
            DispatchQueue.main.async {
                NotificationCenter.default.post(
                    name: .rigFrontendMessageReceived,
                    object: nil,
                    userInfo: body
                )
            }
        default:
            // Silently ignore unrecognized message kinds
            break
        }
    }

    // MARK: — Host → Frontend

    func sendToFrontend(_ message: [String: Any]) {
        guard let webView else {
            pendingSendQueue.append(message)
            return
        }

        for pending in pendingSendQueue {
            _sendJSON(pending, to: webView)
        }
        pendingSendQueue.removeAll()
        _sendJSON(message, to: webView)
    }

    private func _sendJSON(_ message: [String: Any], to webView: WKWebView) {
        guard JSONSerialization.isValidJSONObject(message),
              let data = try? JSONSerialization.data(withJSONObject: message),
              let jsonString = String(data: data, encoding: .utf8) else {
            return
        }
        let escaped = jsonString
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "'", with: "\\'")
        let js = "window.rigHostBridge?.onMessage('\(escaped)');"
        webView.evaluateJavaScript(js, completionHandler: nil)
    }
}

// MARK: - Bridge Script (injected at document start)

private let _bridgeScriptSource = """
(function() {
    'use strict';
    var messageQueue = [];
    var onMessageHandler = null;

    window.rigHostBridge = {
        sendMessage: function(message) {
            try {
                window.webkit.messageHandlers.rigHostBridge.postMessage(message);
            } catch(e) {
                console.error('[RigHostBridge] Failed to send message:', e);
            }
        },
        onMessage: function(jsonString) {
            try {
                var message = JSON.parse(jsonString);
                if (typeof onMessageHandler === 'function') {
                    onMessageHandler(message);
                } else {
                    messageQueue.push(message);
                }
            } catch(e) {
                console.error('[RigHostBridge] Failed to parse message:', e);
            }
        },
        setMessageHandler: function(handler) {
            onMessageHandler = handler;
            while (messageQueue.length > 0) {
                handler(messageQueue.shift());
            }
        }
    };
})();
"""

// MARK: - Notification

extension Notification.Name {
    static let rigFrontendMessageReceived = Notification.Name("rigFrontendMessageReceived")
}
