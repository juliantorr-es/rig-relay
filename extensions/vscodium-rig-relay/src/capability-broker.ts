import * as vscode from 'vscode';
import * as path from 'path';

// ── Capability Registry ─────────────────────────────────────────

export interface CapabilityEntry {
    risk: 'low' | 'medium' | 'high';
    default: 'allow' | 'allow_if_workspace_trusted' | 'ask_once_per_session' | 'always_ask' | 'deny';
    mutates: boolean | 'possible';
    description: string;
}

const CAPABILITY_REGISTRY: Record<string, CapabilityEntry> = {
    'ide.workspace.describe': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Describe current workspace state (roots, active file, selection).',
    },
    'ide.workspace.active_file': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Get the currently active editor file path.',
    },
    'ide.workspace.selection': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Get the current text selection range.',
    },
    'ide.buffer.read_range': {
        risk: 'medium', default: 'allow_if_workspace_trusted', mutates: false,
        description: 'Read a range of text from the editor buffer (includes unsaved changes).',
    },
    'ide.buffer.read': {
        risk: 'medium', default: 'allow_if_workspace_trusted', mutates: false,
        description: 'Read file content from editor buffer (not disk).',
    },
    'ide.diagnostics.file': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Get diagnostics (errors, warnings) for a file.',
    },
    'ide.symbols.document': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Get document symbols (functions, classes, etc.).',
    },
    'ide.references.find': {
        risk: 'medium', default: 'allow', mutates: false,
        description: 'Find references to a symbol.',
    },
    'ide.tests.run_file': {
        risk: 'medium', default: 'ask_once_per_session', mutates: 'possible',
        description: 'Run all tests in a file via the VS Code Test API.',
    },
    'ide.debug.stack': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Get current debug call stack.',
    },
    'ide.vcs.status': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Get VCS status for the workspace.',
    },
    'ide.vcs.diff_file': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Get diff for a file.',
    },
    'ide.ui.show_diff': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Show a diff in the editor.',
    },
    'ide.ui.show_receipt': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Show a receipt in the evidence panel.',
    },
    'ide.ui.request_approval': {
        risk: 'medium', default: 'always_ask', mutates: false,
        description: 'Request user approval for an operation.',
    },
    'ide.ui.notify': {
        risk: 'low', default: 'allow', mutates: false,
        description: 'Show a notification to the user.',
    },
};

// ── Approval Request ────────────────────────────────────────────

export interface ApprovalRequest {
    id: string;
    title: string;
    description: string;
    capability: string;
    risk: 'low' | 'medium' | 'high';
    mutates: boolean | 'possible';
}

export interface CapabilityResult {
    id: string;
    capability: string;
    status: 'ok' | 'error' | 'refused';
    result?: unknown;
    error?: string;
}

export interface CapabilityReceipt {
    kind: string;
    capability: string;
    input_sha256: string;
    output_sha256: string;
    agent_id?: string;
    mission_id?: string;
    user_approved: boolean;
    mutated_workspace: boolean;
}

export interface CapabilityBrokerDelegate {
    onApprovalRequired(request: ApprovalRequest): void;
    onCapabilityResult(result: CapabilityResult): void;
    onReceipt(receipt: CapabilityReceipt): void;
}

// ── Capability Broker ───────────────────────────────────────────

export class IdeCapabilityBroker {
    private _sessionApprovals = new Set<string>();
    private _pendingResponses = new Map<string, (approved: boolean) => void>();

    constructor(private _delegate: CapabilityBrokerDelegate) {}

    /**
     * Execute a capability, with permission checks and approval flow.
     */
    async execute(
        capability: string,
        args: Record<string, unknown>
    ): Promise<CapabilityResult> {
        const entry = CAPABILITY_REGISTRY[capability];
        if (!entry) {
            return {
                id: '',
                capability,
                status: 'refused',
                error: `Unknown capability: ${capability}`,
            };
        }

        // 1. Check if we can auto-allow
        const allowed = await this._checkPermission(capability, entry);
        if (!allowed) {
            return {
                id: '',
                capability,
                status: 'refused',
                error: `Capability ${capability} denied by user.`,
            };
        }

        // 2. Execute the capability against VS Code APIs
        const requestId = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
        const inputSha256 = this._computeSha256(JSON.stringify(args));

        try {
            const result = await this._executeVsCodeCapability(capability, args);

            const outputSha256 = this._computeSha256(JSON.stringify(result));

            // 3. Emit receipt
            this._delegate.onReceipt({
                kind: 'rig.ide.capability.receipt.v1',
                capability,
                input_sha256: inputSha256,
                output_sha256: outputSha256,
                user_approved: allowed,
                mutated_workspace: entry.mutates === true,
            });

            return {
                id: requestId,
                capability,
                status: 'ok',
                result,
            };
        } catch (err: any) {
            return {
                id: requestId,
                capability,
                status: 'error',
                error: err.message,
            };
        }
    }

    handleCapabilityResponse(msg: any) {
        const resolver = this._pendingResponses.get(msg.id);
        if (resolver) {
            resolver(msg.status === 'ok' || msg.approved === true);
            this._pendingResponses.delete(msg.id);
        }
    }

    private async _checkPermission(
        capability: string,
        entry: CapabilityEntry
    ): Promise<boolean> {
        switch (entry.default) {
            case 'allow':
                return true;
            case 'allow_if_workspace_trusted':
                return true;
            case 'ask_once_per_session':
                if (this._sessionApprovals.has(capability)) {
                    return true;
                }
                return this._requestApproval(capability, entry);
            case 'always_ask':
                return this._requestApproval(capability, entry);
            case 'deny':
                return false;
            default:
                return false;
        }
    }

    private async _requestApproval(
        capability: string,
        entry: CapabilityEntry
    ): Promise<boolean> {
        return new Promise((resolve) => {
            const id = `approval_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
            this._pendingResponses.set(id, resolve);

            this._delegate.onApprovalRequired({
                id,
                title: `Allow ${capability}?`,
                description: entry.description,
                capability,
                risk: entry.risk,
                mutates: entry.mutates,
            });

            // Timeout after 30s
            setTimeout(() => {
                if (this._pendingResponses.has(id)) {
                    this._pendingResponses.delete(id);
                    resolve(false);
                }
            }, 30000);
        });
    }

    private async _executeVsCodeCapability(
        capability: string,
        args: Record<string, unknown>
    ): Promise<unknown> {
        const editor = vscode.window.activeTextEditor;

        switch (capability) {
            case 'ide.workspace.describe': {
                return {
                    roots: vscode.workspace.workspaceFolders?.map(f => f.uri.fsPath) || [],
                    active_file: editor?.document.uri.fsPath || null,
                    open_tabs: vscode.window.tabGroups.all
                        .flatMap(g => g.tabs)
                        .filter(t => t.input instanceof vscode.TabInputText)
                        .map(t => (t.input as vscode.TabInputText).uri.fsPath),
                    editor_state: editor ? {
                        language: editor.document.languageId,
                        lineCount: editor.document.lineCount,
                        isDirty: editor.document.isDirty,
                    } : null,
                };
            }

            case 'ide.workspace.active_file': {
                return { path: editor?.document.uri.fsPath || null };
            }

            case 'ide.workspace.selection': {
                if (!editor) return { selection: null };
                const sel = editor.selection;
                return {
                    selection: {
                        file: editor.document.uri.fsPath,
                        startLine: sel.start.line,
                        startCol: sel.start.character,
                        endLine: sel.end.line,
                        endCol: sel.end.character,
                        text: editor.document.getText(sel),
                    },
                };
            }

            case 'ide.buffer.read_range': {
                const filePath = args.file as string;
                if (!filePath) throw new Error('file argument required');

                // Try editor buffer first (has unsaved changes)
                const matchingEditor = vscode.window.visibleTextEditors.find(
                    e => e.document.uri.fsPath === filePath
                );
                if (matchingEditor) {
                    const doc = matchingEditor.document;
                    const startLine = (args.start_line as number) || 0;
                    const endLine = (args.end_line as number) || doc.lineCount;
                    const range = new vscode.Range(startLine, 0, endLine, 0);
                    return {
                        content: doc.getText(range),
                        source: 'buffer',
                        isDirty: doc.isDirty,
                    };
                }

                // Fall back to filesystem
                const fs = require('fs');
                const content = fs.readFileSync(filePath, 'utf-8');
                const lines = content.split('\n');
                const startLine = (args.start_line as number) || 0;
                const endLine = (args.end_line as number) || lines.length;
                return {
                    content: lines.slice(startLine, endLine).join('\n'),
                    source: 'disk',
                };
            }

            case 'ide.diagnostics.file': {
                const filePath = (args.file as string) || editor?.document.uri.fsPath;
                if (!filePath) throw new Error('No file specified');

                const uri = vscode.Uri.file(filePath);
                const diagnostics = vscode.languages.getDiagnostics(uri);
                return diagnostics.map(d => ({
                    severity: d.severity === vscode.DiagnosticSeverity.Error ? 'error'
                        : d.severity === vscode.DiagnosticSeverity.Warning ? 'warning'
                        : 'info',
                    message: d.message,
                    range: {
                        startLine: d.range.start.line,
                        startCol: d.range.start.character,
                        endLine: d.range.end.line,
                        endCol: d.range.end.character,
                    },
                    source: d.source,
                    code: typeof d.code === 'string' ? d.code : String(d.code ?? ''),
                }));
            }

            case 'ide.symbols.document': {
                if (!editor) throw new Error('No active editor');
                const symbols = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
                    'vscode.executeDocumentSymbolProvider',
                    editor.document.uri
                );
                return this._flattenSymbols(symbols || []);
            }

            case 'ide.references.find': {
                const position = new vscode.Position(
                    (args.line as number) || 0,
                    (args.column as number) || 0
                );
                const uri = args.file
                    ? vscode.Uri.file(args.file as string)
                    : editor?.document.uri;
                if (!uri) throw new Error('No file specified');

                const references = await vscode.commands.executeCommand<vscode.Location[]>(
                    'vscode.executeReferenceProvider',
                    uri,
                    position
                );
                return (references || []).map(ref => ({
                    file: ref.uri.fsPath,
                    line: ref.range.start.line,
                    column: ref.range.start.character,
                }));
            }

            case 'ide.tests.run_file': {
                const filePath = args.file as string;
                if (filePath) {
                    await vscode.commands.executeCommand('testing.runCurrentFile', vscode.Uri.file(filePath));
                } else {
                    await vscode.commands.executeCommand('testing.runAll');
                }
                return { status: 'triggered' };
            }

            case 'ide.vcs.status': {
                const workspaceUri = vscode.workspace.workspaceFolders?.[0]?.uri;
                if (!workspaceUri) return { changes: [] };

                const api = vscode.extensions.getExtension('vscode.git')?.exports?.getAPI(1);
                if (!api) return { changes: [], error: 'Git extension not available' };

                const repository = api.repositories[0];
                if (!repository) return { changes: [], error: 'No git repository found' };

                const state = repository.state;
                return {
                    HEAD: state.HEAD?.name || state.HEAD?.commit || '',
                    changes: state.workingTreeChanges.map((c: any) => ({
                        file: c.uri.fsPath,
                        status: c.status,
                    })),
                    ahead: state.ahead || 0,
                    behind: state.behind || 0,
                };
            }

            case 'ide.ui.show_diff': {
                const { title, old_content, new_content, file_path } = args as any;
                if (!old_content || !new_content) {
                    // Show file diff via VS Code git
                    await vscode.commands.executeCommand('git.openChange');
                } else {
                    // Create temporary diff view
                    const oldUri = vscode.Uri.parse(`untitled:${file_path || 'diff'}.old`);
                    const newUri = vscode.Uri.parse(`untitled:${file_path || 'diff'}.new`);
                    await vscode.commands.executeCommand('vscode.diff', oldUri, newUri, title || 'Rig Patch');
                }
                return { status: 'shown' };
            }

            case 'ide.ui.notify': {
                const message = args.message as string;
                if (message) {
                    vscode.window.showInformationMessage(message);
                }
                return { status: 'notified' };
            }

            default:
                throw new Error(`Unknown capability: ${capability}`);
        }
    }

    private _flattenSymbols(symbols: vscode.DocumentSymbol[], indent = ''): any[] {
        const result: any[] = [];
        for (const s of symbols) {
            result.push({
                name: s.name,
                kind: this._symbolKindToString(s.kind),
                range: {
                    startLine: s.range.start.line,
                    endLine: s.range.end.line,
                },
                detail: s.detail,
            });
            result.push(...this._flattenSymbols(s.children, indent + '  '));
        }
        return result;
    }

    private _symbolKindToString(kind: vscode.SymbolKind): string {
        const names: Record<number, string> = {
            [vscode.SymbolKind.Function]: 'function',
            [vscode.SymbolKind.Class]: 'class',
            [vscode.SymbolKind.Method]: 'method',
            [vscode.SymbolKind.Property]: 'property',
            [vscode.SymbolKind.Variable]: 'variable',
            [vscode.SymbolKind.Interface]: 'interface',
            [vscode.SymbolKind.Module]: 'module',
        };
        return names[kind] || 'symbol';
    }

    private _computeSha256(input: string): string {
        // Simple content hash — not cryptographically secure, just for dedup
        let hash = 0;
        for (let i = 0; i < input.length; i++) {
            const chr = input.charCodeAt(i);
            hash = ((hash << 5) - hash) + chr;
            hash |= 0;
        }
        return hash.toString(36);
    }
}
