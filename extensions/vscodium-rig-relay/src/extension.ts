import * as vscode from 'vscode';
import { RigControlProvider } from './panel';

export function activate(context: vscode.ExtensionContext) {
    console.log('Rig Relay MVP Hardened Extension Activated');

    const provider = new RigControlProvider(context);

    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(RigControlProvider.viewType, provider)
    );

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
        vscode.commands.registerCommand('rig-relay.clearToken', async () => {
            await context.secrets.delete('rig-relay.daemon.token');
            vscode.window.showInformationMessage('Rig Daemon Token cleared.');
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('rig-relay.reconnect', () => {
            provider.reconnect();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('rig-relay.showStatus', () => {
            provider.showStatus();
        })
    );
}

export function deactivate() {}
