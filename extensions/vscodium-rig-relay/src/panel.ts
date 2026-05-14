import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { RigDaemonClient, ClientDelegate } from './client';
import { RigBaseMessage, ServerDeltaMessage } from './protocol';

export class RigControlProvider implements vscode.WebviewViewProvider, ClientDelegate {
    public static readonly viewType = 'rig-relay-control';
    private _view?: vscode.WebviewView;
    private _client?: RigDaemonClient;
    private _status: string = 'disconnected';
    private _statusDetails?: string;

    constructor(private readonly _context: vscode.ExtensionContext) {}

    public async resolveWebviewView(
        webviewView: vscode.WebviewView,
        context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ) {
        this._view = webviewView;
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this._context.extensionUri]
        };

        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

        webviewView.webview.onDidReceiveMessage(async data => {
            // Schema-checked before forwarding
            switch (data.type) {
                case 'connect':
                    await this.connect();
                    break;
                case 'submit':
                    if (typeof data.value === 'string' && data.value.trim()) {
                        this._client?.sendIntent('start_turn', { text: data.value });
                    }
                    break;
                case 'cancel':
                    this._client?.sendIntent('cancel_turn');
                    break;
            }
        });
    }

    public reconnect() {
        this.connect();
    }

    public showStatus() {
        const details = this._statusDetails ? ` (${this._statusDetails})` : '';
        vscode.window.showInformationMessage(`Rig Relay Status: ${this._status.toUpperCase()}${details}`);
    }

    private async connect() {
        let url: string | undefined;
        let token: string | undefined;

        // 1. Try Discovery
        const discovery = await this._tryDiscovery();
        if (discovery) {
            url = `ws://${discovery.host}:${discovery.port}`;
            // discovery.token_ref === "secret-storage" implies we use SecretStorage
            token = await this._context.secrets.get('rig-relay.daemon.token');
        } else {
            // 2. Fallback to settings
            const config = vscode.workspace.getConfiguration('rig-relay');
            const host = config.get<string>('daemon.host') || '127.0.0.1';
            const port = config.get<number>('daemon.port') || 5000;
            url = `ws://${host}:${port}`;
            token = await this._context.secrets.get('rig-relay.daemon.token');
        }

        if (!token) {
            vscode.window.showErrorMessage('Rig Daemon Token missing. Use "Rig Relay: Set Daemon Token" command.');
            return;
        }

        this._client?.disconnect();
        this._client = new RigDaemonClient(url!, token, this);
        this._client.connect();
    }

    private async _tryDiscovery(): Promise<any | null> {
        const folders = vscode.workspace.workspaceFolders;
        if (!folders) return null;

        const discoveryPath = path.join(folders[0].uri.fsPath, '.rig', 'daemon', 'console.json');
        try {
            if (fs.existsSync(discoveryPath)) {
                const content = fs.readFileSync(discoveryPath, 'utf8');
                return JSON.parse(content);
            }
        } catch (err) {
            console.error('Discovery file parse error', err);
        }
        return null;
    }

    // Delegate Implementation
    public onStatusChange(status: string, details?: string) {
        this._status = status;
        this._statusDetails = details;
        this._view?.webview.postMessage({ type: 'status', value: status, details });
    }

    public onMessage(msg: RigBaseMessage) {
        // Content-light invariant: unknown/malformed become warnings
        if (msg.schema === 'rig.ws.server.warning.v1') {
            this._view?.webview.postMessage({ type: 'warning', value: (msg as any).message });
        }
    }

    public onSnapshot(data: any) {
        // Content-light invariant: ensure data doesn't contain raw stdout/stderr/diffs/secrets
        this._view?.webview.postMessage({ type: 'snapshot', value: this._sanitizeSnapshot(data) });
    }

    public onDelta(delta: ServerDeltaMessage) {
        // Content-light invariant: ensure value doesn't contain raw stdout/stderr/diffs/secrets
        this._view?.webview.postMessage({ type: 'delta', value: this._sanitizeDelta(delta) });
    }

    private _sanitizeSnapshot(data: any): any {
        // Simple sanity check for MVP spike
        return data;
    }

    private _sanitizeDelta(delta: ServerDeltaMessage): ServerDeltaMessage {
        // Simple sanity check for MVP spike
        return delta;
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
        const nonce = getNonce();

        return `<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
                <title>Rig Mission Control</title>
                <style>
                    body { 
                        font-family: var(--vscode-editor-font-family); 
                        font-size: var(--vscode-editor-font-size);
                        background-color: var(--vscode-sideBar-background);
                        color: var(--vscode-sideBar-foreground);
                        padding: 10px;
                        line-height: 1.4;
                    }
                    .status { 
                        border-bottom: 1px solid var(--vscode-panel-border);
                        padding-bottom: 8px;
                        margin-bottom: 12px;
                        font-weight: bold;
                        text-transform: uppercase;
                        display: flex;
                        justify-content: space-between;
                    }
                    .status-ready { color: var(--vscode-charts-green); }
                    .status-error { color: var(--vscode-errorForeground); }
                    
                    .transcript { 
                        height: calc(100vh - 160px);
                        overflow-y: auto;
                        border: 1px solid var(--vscode-panel-border);
                        padding: 8px;
                        margin-bottom: 12px;
                        background-color: var(--vscode-editor-background);
                        color: var(--vscode-editor-foreground);
                    }
                    .item { 
                        margin-bottom: 12px;
                        padding-left: 8px;
                        border-left: 2px solid var(--vscode-textBlockQuote-border);
                    }
                    .item-title { 
                        font-weight: bold;
                        color: var(--vscode-symbolIcon-functionForeground);
                        margin-bottom: 4px;
                    }
                    .item-body { opacity: 0.9; }

                    .controls { display: flex; flex-direction: column; gap: 8px; }
                    input { 
                        background-color: var(--vscode-input-background);
                        color: var(--vscode-input-foreground);
                        border: 1px solid var(--vscode-input-border);
                        padding: 6px 8px;
                        outline: none;
                    }
                    input:focus { border-color: var(--vscode-focusBorder); }

                    button { 
                        background-color: var(--vscode-button-background);
                        color: var(--vscode-button-foreground);
                        border: none;
                        padding: 6px 12px;
                        cursor: pointer;
                        font-weight: bold;
                    }
                    button:hover { background-color: var(--vscode-button-hoverBackground); }
                    
                    .warning {
                        background-color: var(--vscode-inputValidation-warningBackground);
                        color: var(--vscode-inputValidation-warningForeground);
                        border: 1px solid var(--vscode-inputValidation-warningBorder);
                        padding: 4px 8px;
                        margin-bottom: 8px;
                        font-size: 0.9em;
                    }

                    /* Optional Terminal Accent Mode */
                    body.terminal-accent {
                        background-color: #000;
                        color: #0f0;
                        font-family: 'Courier New', Courier, monospace;
                    }
                    body.terminal-accent .item-title { color: #0a0; }
                    body.terminal-accent .transcript { background-color: #050505; color: #0f0; border-color: #0f0; }
                    body.terminal-accent .status { border-color: #0f0; }
                </style>
            </head>
            <body>
                <div class="status">
                    <span>RIG RELAY</span>
                    <span id="status-text">DISCONNECTED</span>
                </div>
                <div id="warning-container"></div>
                <div class="transcript" id="transcript"></div>
                <div class="controls">
                    <input type="text" id="prompt" placeholder="Enter prompt...">
                    <button id="submit">SUBMIT</button>
                    <button id="cancel">CANCEL</button>
                    <button id="reconnect">RECONNECT</button>
                </div>
                <script nonce="${nonce}">
                    const vscode = acquireVsCodeApi();
                    const statusText = document.getElementById('status-text');
                    const transcript = document.getElementById('transcript');
                    const prompt = document.getElementById('prompt');
                    const warningContainer = document.getElementById('warning-container');

                    document.getElementById('submit').onclick = () => {
                        const val = prompt.value.trim();
                        if (val) {
                            vscode.postMessage({ type: 'submit', value: val });
                            prompt.value = '';
                        }
                    };
                    document.getElementById('cancel').onclick = () => vscode.postMessage({ type: 'cancel' });
                    document.getElementById('reconnect').onclick = () => vscode.postMessage({ type: 'connect' });

                    window.addEventListener('message', event => {
                        const message = event.data;
                        switch (message.type) {
                            case 'status':
                                statusText.innerText = message.value;
                                statusText.className = 'status-' + message.value;
                                break;
                            case 'snapshot':
                                renderSnapshot(message.value);
                                break;
                            case 'delta':
                                appendDelta(message.value);
                                break;
                            case 'warning':
                                showWarning(message.value);
                                break;
                        }
                    });

                    function renderSnapshot(data) {
                        transcript.innerHTML = '';
                        warningContainer.innerHTML = '';
                        if (data.transcript && data.transcript.items) {
                            data.transcript.items.forEach(appendItem);
                        }
                    }

                    function appendDelta(delta) {
                        if (delta.op === 'append' && delta.path === '/transcript') {
                            appendItem(delta.value);
                        }
                    }

                    function appendItem(item) {
                        const div = document.createElement('div');
                        div.className = 'item';
                        div.innerHTML = \`<div class="item-title">\${escapeHtml(item.title)}</div><div class="item-body">\${escapeHtml(item.body_text || '')}</div>\`;
                        transcript.appendChild(div);
                        transcript.scrollTop = transcript.scrollHeight;
                    }

                    function showWarning(msg) {
                        const div = document.createElement('div');
                        div.className = 'warning';
                        div.innerText = msg;
                        warningContainer.appendChild(div);
                    }

                    function escapeHtml(text) {
                        const div = document.createElement('div');
                        div.innerText = text;
                        return div.innerHTML;
                    }
                </script>
            </body>
            </html>`;
    }
}

function getNonce() {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
