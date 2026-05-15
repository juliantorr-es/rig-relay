import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import { RigControlProvider } from './panel';
import { IdeCapabilityBroker, CapabilityBrokerDelegate } from './capability-broker';

let sidecarProcess: cp.ChildProcess | null = null;
let capabilityBroker: IdeCapabilityBroker | null = null;

function findSidecarScript(): string {
    // Look for the sidecar relative to the workspace or globally
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath;
    if (workspaceRoot) {
        const localPath = path.join(workspaceRoot, 'rig_relay', 'cli', 'ide_sidecar.py');
        if (require('fs').existsSync(localPath)) {
            return localPath;
        }
    }
    // Fallback: assume `uv run rig-relay-ide-sidecar` is on PATH
    return 'rig-relay-ide-sidecar';
}

function spawnSidecar(): cp.ChildProcess {
    const scriptPath = findSidecarScript();
    const isDirectScript = scriptPath.endsWith('.py');

    const proc = isDirectScript
        ? cp.spawn('uv', ['run', 'python', scriptPath, '--stdio'], {
              stdio: ['pipe', 'pipe', 'pipe'],
              shell: false,
          })
        : cp.spawn(scriptPath, ['--stdio'], {
              stdio: ['pipe', 'pipe', 'pipe'],
              shell: false,
          });

    let buffer = '';
    proc.stdout?.on('data', (data: Buffer) => {
        buffer += data.toString();
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // keep incomplete line
        for (const line of lines) {
            if (line.trim()) {
                try {
                    const msg = JSON.parse(line);
                    handleSidecarMessage(msg);
                } catch {
                    // Non-JSON output from ACP agent (e.g., logs) — ignore or forward
                    console.log('[rig-sidecar]', line);
                }
            }
        }
    });

    proc.stderr?.on('data', (data: Buffer) => {
        console.error('[rig-sidecar:err]', data.toString().trim());
    });

    proc.on('close', (code) => {
        console.log(`[rig-sidecar] exited with code ${code}`);
        sidecarProcess = null;
    });

    proc.on('error', (err) => {
        console.error('[rig-sidecar] spawn error:', err.message);
        sidecarProcess = null;
    });

    return proc;
}

function sendToSidecar(message: object) {
    if (sidecarProcess?.stdin?.writable) {
        sidecarProcess.stdin.write(JSON.stringify(message) + '\n');
    }
}

function handleSidecarMessage(msg: any) {
    switch (msg.type) {
        case 'ack':
            // Sidecar confirmed connection — send workspace snapshot
            sendWorkspaceSnapshot();
            break;

        case 'capability_response':
            // Forward to the broker
            capabilityBroker?.handleCapabilityResponse(msg);
            break;

        case 'approval_request':
            // Show approval dialog in VS Code
            showApprovalDialog(msg);
            break;

        case 'error':
            vscode.window.showErrorMessage(`Rig Sidecar: ${msg.message}`);
            break;

        default:
            // Forward to the active webview panel
            vscode.commands.executeCommand('rig-relay.forwardMessage', msg);
    }
}

async function sendWorkspaceSnapshot() {
    const editor = vscode.window.activeTextEditor;
    const workspaceFolders = vscode.workspace.workspaceFolders;

    let activeFile: string | null = null;
    let selection: any = null;
    let editorState: any = null;

    if (editor) {
        activeFile = editor.document.uri.fsPath;
        const sel = editor.selection;
        selection = {
            file: activeFile,
            startLine: sel.start.line,
            startCol: sel.start.character,
            endLine: sel.end.line,
            endCol: sel.end.character,
        };
        editorState = {
            language: editor.document.languageId,
            lineCount: editor.document.lineCount,
            eol: editor.document.eol === vscode.EndOfLine.LF ? 'LF' : 'CRLF',
            isUntitled: editor.document.isUntitled,
            isDirty: editor.document.isDirty,
        };
    }

    sendToSidecar({
        type: 'workspace_snapshot',
        roots: workspaceFolders?.map(f => f.uri.fsPath) || [],
        active_file: activeFile,
        open_tabs: vscode.window.tabGroups.all
            .flatMap(g => g.tabs)
            .filter(t => t.input instanceof vscode.TabInputText)
            .map(t => (t.input as vscode.TabInputText).uri.fsPath),
        selection,
        editor_state: editorState,
    });
}

async function showApprovalDialog(msg: any) {
    const title = msg.title || 'Rig Relay Permission Request';
    const description = msg.description || '';
    const risk = msg.risk || 'medium';

    const result = await vscode.window.showWarningMessage(
        `${title}\n\n${description}`,
        { modal: true, detail: `Risk: ${risk.toUpperCase()}` },
        'Allow',
        'Deny'
    );

    sendToSidecar({
        type: 'approval_response',
        id: msg.id,
        approved: result === 'Allow',
    });
}

export function activate(context: vscode.ExtensionContext) {
    console.log('Rig Relay IDE Extension Activated');

    // ── Spawn sidecar ────────────────────────────────────────────
    sidecarProcess = spawnSidecar();

    // ── Capability Broker ────────────────────────────────────────
    capabilityBroker = new IdeCapabilityBroker({
        onApprovalRequired(request) {
            showApprovalDialog(request);
        },
        onCapabilityResult(result) {
            vscode.commands.executeCommand('rig-relay.forwardCapabilityResult', result);
        },
        onReceipt(receipt) {
            vscode.commands.executeCommand('rig-relay.forwardReceipt', receipt);
        },
    });

    // ── Register Webview Panel ───────────────────────────────────
    const provider = new RigControlProvider(context);

    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(RigControlProvider.viewType, provider)
    );

    // ── Commands ─────────────────────────────────────────────────
    context.subscriptions.push(
        vscode.commands.registerCommand('rig-relay.setToken', async () => {
            const token = await vscode.window.showInputBox({
                prompt: 'Enter Rig Daemon Token',
                password: true,
                placeHolder: 'Paste token from daemon logs...'
            });
            if (token) {
                await context.secrets.store('rig-relay.daemon.token', token);
                vscode.window.showInformationMessage('Rig Daemon Token stored securely.');
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('rig-relay.reconnect', () => {
            if (sidecarProcess) {
                sidecarProcess.kill();
            }
            sidecarProcess = spawnSidecar();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('rig-relay.forwardMessage', (msg: any) => {
            provider.postMessage(msg);
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('rig-relay.forwardCapabilityResult', (result: any) => {
            provider.postMessage({ type: 'capability_result', ...result });
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('rig-relay.forwardReceipt', (receipt: any) => {
            provider.postMessage({ type: 'receipt', ...receipt });
        })
    );

    // ── Listen for editor changes ────────────────────────────────
    context.subscriptions.push(
        vscode.window.onDidChangeActiveTextEditor(() => {
            if (sidecarProcess) {
                sendWorkspaceSnapshot();
            }
        })
    );

    context.subscriptions.push(
        vscode.window.onDidChangeTextEditorSelection(() => {
            if (sidecarProcess) {
                sendWorkspaceSnapshot();
            }
        })
    );

    // Send initial workspace snapshot
    setTimeout(sendWorkspaceSnapshot, 1000);
}

export function deactivate() {
    if (sidecarProcess) {
        sidecarProcess.kill();
        sidecarProcess = null;
    }
}
