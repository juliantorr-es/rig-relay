import * as vscode from 'vscode';

export class RigControlProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'rig-relay-control';
    private _view?: vscode.WebviewView;

    constructor(private readonly _context: vscode.ExtensionContext) {}

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ) {
        this._view = webviewView;
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this._context.extensionUri],
        };
        webviewView.webview.html = this._getHtmlForWebview();

        webviewView.webview.onDidReceiveMessage(async (data) => {
            switch (data.type) {
                case 'submit':
                    // Forward prompt to the sidecar
                    vscode.commands.executeCommand('rig-relay.forwardMessage', {
                        type: 'user_prompt',
                        text: data.value,
                    });
                    break;
                case 'cancel':
                    vscode.commands.executeCommand('rig-relay.forwardMessage', {
                        type: 'cancel',
                    });
                    break;
            }
        });
    }

    /**
     * Called by extension.ts to forward messages from the sidecar to the webview.
     */
    public postMessage(msg: any) {
        this._view?.webview.postMessage(msg);
    }

    private _getHtmlForWebview(): string {
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rig Relay</title>
    <style>
        :root {
            --bg: var(--vscode-sideBar-background, #1e1e1e);
            --text: var(--vscode-sideBar-foreground, #ccc);
            --border: var(--vscode-panel-border, #333);
            --accent: var(--vscode-focusBorder, #0078d4);
        }
        body {
            font-family: var(--vscode-editor-font-family, sans-serif);
            font-size: var(--vscode-editor-font-size, 13px);
            background: var(--bg);
            color: var(--text);
            padding: 8px;
            margin: 0;
        }
        .status {
            display: flex;
            justify-content: space-between;
            padding: 4px 0 8px 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 8px;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.85em;
        }
        .status.connected { color: #4c9a5a; }
        .status.disconnected { color: #c94a44; }

        .receipt {
            font-size: 0.85em;
            padding: 4px 6px;
            margin: 4px 0;
            border-left: 3px solid var(--accent);
            background: rgba(255,255,255,0.03);
        }
        .receipt .capability { font-weight: 600; }
        .receipt .hash { opacity: 0.6; font-family: monospace; font-size: 0.9em; }

        #transcript {
            max-height: calc(100vh - 120px);
            overflow-y: auto;
        }
        .entry {
            padding: 4px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .entry .title { font-weight: 600; }
        .entry .body { opacity: 0.85; white-space: pre-wrap; font-size: 0.95em; }
    </style>
</head>
<body>
    <div class="status disconnected" id="status-bar">
        <span>RIG RELAY</span>
        <span id="status-text">DISCONNECTED</span>
    </div>
    <div id="receipts"></div>
    <div id="transcript"></div>

    <script>
        const vscode = acquireVsCodeApi();
        const statusBar = document.getElementById('status-bar');
        const statusText = document.getElementById('status-text');
        const transcript = document.getElementById('transcript');
        const receipts = document.getElementById('receipts');

        window.addEventListener('message', event => {
            const msg = event.data;
            switch (msg.type) {
                case 'status':
                    statusText.innerText = (msg.value || 'UNKNOWN').toUpperCase();
                    statusBar.className = 'status ' + (msg.value || 'disconnected');
                    break;

                case 'receipt':
                    addReceipt(msg);
                    break;

                case 'capability_result':
                    addTranscript('capability', msg.capability + ': ' + (msg.status || 'unknown'));
                    break;

                case 'user_prompt':
                    addTranscript('user', msg.text);
                    break;

                case 'agent_response':
                    addTranscript('agent', msg.text);
                    break;

                default:
                    if (msg.text) addTranscript('system', msg.text);
            }
        });

        function addTranscript(type, text) {
            const div = document.createElement('div');
            div.className = 'entry';
            div.innerHTML = '<div class="title">' + escapeHtml(type) + '</div>' +
                '<div class="body">' + escapeHtml(text) + '</div>';
            transcript.appendChild(div);
            transcript.scrollTop = transcript.scrollHeight;
        }

        function addReceipt(r) {
            const div = document.createElement('div');
            div.className = 'receipt';
            div.innerHTML = '<div class="capability">' + escapeHtml(r.capability || r.kind || 'receipt') + '</div>' +
                '<div class="hash">' + escapeHtml((r.input_sha256 || '').slice(0, 16)) + ' &rarr; ' +
                escapeHtml((r.output_sha256 || '').slice(0, 16)) + '</div>';
            receipts.appendChild(div);
        }

        function escapeHtml(str) {
            if (typeof str !== 'string') return String(str);
            return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }
    </script>
</body>
</html>`;
    }
}
