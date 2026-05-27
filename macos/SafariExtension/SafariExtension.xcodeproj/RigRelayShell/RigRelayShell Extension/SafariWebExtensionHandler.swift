//
//  SafariWebExtensionHandler.swift
//  RigRelayShell Extension (X4.2 — real Safari transport)
//
//  This is the Apple-routable native extension handler that receives
//  messages from the Safari Web Extension via the standard
//  `browser.runtime.sendNativeMessage` → `SFSafariExtensionHandler.beginRequest(with:)`
//  mechanism.
//
//  It decodes Q0/S4-compatible message envelopes, validates content-light
//  safety, and returns typed response messages (accepted/deferred/refused/
//  app_unavailable).
//

import SafariServices
import Foundation

private let schemaVersion = "rig.relay.safari_extension_message.v1"
private let maxMessageLength = 10_000

private let tokenPattern = try! NSRegularExpression(
    pattern: #"ghp_|ghs_|gho_|ghu_|ghr_|github_pat_"#,
    options: []
)

private let credentialURLParamPattern = try! NSRegularExpression(
    pattern: #"[?&](access_token|token|client_secret|api_key|private_token|client_id|id_token|refresh_token)="#,
    options: []
)

private let forbiddenKeys: Set<String> = [
    "file_contents", "html", "raw_prompt", "model_output",
]

private let validHandoffKinds: Set<String> = [
    "handoff.github_repository",
    "handoff.github_pull_request",
    "handoff.github_issue",
    "ping",
]

class SafariWebExtensionHandler: NSObject, NSExtensionRequestHandling {

    func beginRequest(with context: NSExtensionContext) {
        guard let item = context.inputItems.first as? NSExtensionItem,
              let userInfo = item.userInfo as? [String: Any] else {
            context.completeRequest(returningItems: nil, completionHandler: nil)
            return
        }

        let rawMessage: Any?
        if #available(macOS 11.0, *) {
            rawMessage = userInfo[SFExtensionMessageKey]
        } else {
            rawMessage = userInfo["message"]
        }

        let response = handleIncomingMessage(rawMessage)

        let responseItem = NSExtensionItem()
        if #available(macOS 11.0, *) {
            responseItem.userInfo = [SFExtensionMessageKey: response]
        } else {
            responseItem.userInfo = ["message": response]
        }

        context.completeRequest(returningItems: [responseItem], completionHandler: nil)
    }

    // ── Message handler ──────────────────────────────────────────────

    private func handleIncomingMessage(_ raw: Any?) -> [String: Any] {
        guard let rawDict = raw as? [String: Any] else {
            return refusedResponse(
                inResponseTo: "unknown",
                action: "decode",
                reason: "invalid_message",
                message: "Message is not a valid JSON dictionary"
            )
        }

        guard let kind = rawDict["kind"] as? String else {
            return refusedResponse(
                inResponseTo: rawDict["message_id"] as? String ?? "unknown",
                action: "decode",
                reason: "invalid_message",
                message: "Missing required 'kind' field"
            )
        }

        guard let rawData = try? JSONSerialization.data(withJSONObject: rawDict),
              let rawString = String(data: rawData, encoding: .utf8) else {
            return refusedResponse(
                inResponseTo: rawDict["message_id"] as? String ?? "unknown",
                action: kind,
                reason: "invalid_message",
                message: "Unable to serialize message for validation"
            )
        }

        let range = NSRange(rawString.startIndex..., in: rawString)

        if tokenPattern.firstMatch(in: rawString, range: range) != nil {
            return refusedResponse(
                inResponseTo: rawDict["message_id"] as? String ?? "unknown",
                action: kind,
                reason: "invalid_message",
                message: "Message contains GitHub token pattern"
            )
        }

        if credentialURLParamPattern.firstMatch(in: rawString, range: range) != nil {
            return refusedResponse(
                inResponseTo: rawDict["message_id"] as? String ?? "unknown",
                action: kind,
                reason: "invalid_message",
                message: "Message contains credential-bearing URL parameter"
            )
        }

        for key in forbiddenKeys {
            if keyPresentInDict(rawDict, key: key) {
                return refusedResponse(
                    inResponseTo: rawDict["message_id"] as? String ?? "unknown",
                    action: kind,
                    reason: "invalid_message",
                    message: "Message contains forbidden key: \(key)"
                )
            }
        }

        if rawString.count > maxMessageLength {
            return refusedResponse(
                inResponseTo: rawDict["message_id"] as? String ?? "unknown",
                action: kind,
                reason: "invalid_message",
                message: "Message exceeds 10,000 character limit"
            )
        }

        guard let direction = rawDict["direction"] as? String else {
            return refusedResponse(
                inResponseTo: rawDict["message_id"] as? String ?? "unknown",
                action: kind,
                reason: "invalid_message",
                message: "Missing 'direction' field"
            )
        }

        if direction != "extension_to_app" {
            return refusedResponse(
                inResponseTo: rawDict["message_id"] as? String ?? "unknown",
                action: kind,
                reason: "invalid_message",
                message: "Invalid direction: expected 'extension_to_app'"
            )
        }

        guard validHandoffKinds.contains(kind) else {
            return refusedResponse(
                inResponseTo: rawDict["message_id"] as? String ?? "unknown",
                action: kind,
                reason: "unsupported_github_context",
                message: "Unsupported message kind: \(kind)"
            )
        }

        let messageId = rawDict["message_id"] as? String ?? UUID().uuidString

        return acceptedResponse(
            inResponseTo: messageId,
            action: kind,
            message: "Handoff received by native macOS app"
        )
    }

    // ── Helpers ──────────────────────────────────────────────────────

    private func keyPresentInDict(_ dict: [String: Any], key: String) -> Bool {
        if dict[key] != nil {
            return true
        }
        for (_, value) in dict {
            if let nested = value as? [String: Any] {
                if keyPresentInDict(nested, key: key) {
                    return true
                }
            }
        }
        return false
    }

    private func refusedResponse(
        inResponseTo: String,
        action: String,
        reason: String,
        message: String
    ) -> [String: Any] {
        [
            "schema_version": schemaVersion,
            "message_id": UUID().uuidString,
            "direction": "app_to_extension",
            "kind": "response.refused",
            "payload": [
                "in_response_to": inResponseTo,
                "action": action,
                "message": message,
                "refusal_reason": reason,
            ],
            "created_at": ISO8601DateFormatter().string(from: Date()),
        ]
    }

    private func acceptedResponse(
        inResponseTo: String,
        action: String,
        message: String
    ) -> [String: Any] {
        [
            "schema_version": schemaVersion,
            "message_id": UUID().uuidString,
            "direction": "app_to_extension",
            "kind": "response.accepted",
            "payload": [
                "in_response_to": inResponseTo,
                "action": action,
                "message": message,
                "repository_status": "status_pending",
            ],
            "created_at": ISO8601DateFormatter().string(from: Date()),
        ]
    }
}
