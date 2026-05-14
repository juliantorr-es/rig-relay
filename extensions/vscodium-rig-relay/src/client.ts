import * as vscode from 'vscode';
import { WebSocket } from 'ws';
import {
    ClientAuthMessage,
    ClientIntentMessage,
    RigBaseMessage,
    PROTOCOL_VERSION,
    CLIENT_NAME,
    ServerAckMessage,
    ServerDeltaMessage,
    ServerSnapshotMessage,
    ServerAuthOkMessage
} from './protocol';

export interface ClientDelegate {
    onStatusChange(status: string, details?: string): void;
    onMessage(msg: RigBaseMessage): void;
    onSnapshot(data: any): void;
    onDelta(delta: ServerDeltaMessage): void;
}

export class RigDaemonClient {
    private ws: WebSocket | null = null;
    private lastSeenSeq: number = 0;
    private seenEventIds: Set<string> = new Set();

    constructor(
        private readonly url: string,
        private readonly token: string,
        private readonly delegate: ClientDelegate
    ) {}

    public connect() {
        this.delegate.onStatusChange('connecting');
        try {
            this.ws = new WebSocket(this.url);

            this.ws.on('open', () => {
                this.authenticate();
            });

            this.ws.on('message', (data: any) => {
                this.handleMessage(data.toString());
            });

            this.ws.on('close', () => {
                this.delegate.onStatusChange('disconnected');
                this.ws = null;
            });

            this.ws.on('error', (err: any) => {
                this.delegate.onStatusChange('error', err.message);
                this.ws = null;
            });
        } catch (err: any) {
            this.delegate.onStatusChange('error', err.message);
        }
    }

    public disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    private authenticate() {
        if (!this.ws) return;
        const auth: ClientAuthMessage = {
            schema: 'rig.ws.client.auth.v1',
            token: this.token,
            last_seen_seq: this.lastSeenSeq,
            client_protocol_version: PROTOCOL_VERSION,
            client_name: CLIENT_NAME
        };
        this.ws.send(JSON.stringify(auth));
    }

    public sendIntent(kind: "start_turn" | "cancel_turn" | "get_snapshot", payload: any = {}) {
        if (!this.ws) return;
        const intent: ClientIntentMessage = {
            schema: 'rig.ws.client.intent.v1',
            intent_kind: kind,
            intent_id: Math.random().toString(36).substring(7),
            payload
        };
        this.ws.send(JSON.stringify(intent));
    }

    private handleMessage(raw: string) {
        try {
            const msg = JSON.parse(raw) as RigBaseMessage;
            
            // Stale seq ignored
            if (msg.seq <= this.lastSeenSeq && msg.schema !== 'rig.ws.server.auth_ok.v1') {
                return;
            }
            this.lastSeenSeq = msg.seq;

            switch (msg.schema) {
                case 'rig.ws.server.auth_ok.v1':
                    const authOk = msg as ServerAuthOkMessage;
                    if (authOk.compatibility === 'incompatible') {
                        this.delegate.onStatusChange('error', `Incompatible protocol: server=${authOk.server_protocol_version}`);
                        this.disconnect();
                    } else {
                        this.delegate.onStatusChange('ready');
                    }
                    break;

                case 'rig.ws.server.snapshot.v1':
                    // Snapshot resets seen event IDs
                    this.seenEventIds.clear();
                    this.delegate.onSnapshot((msg as ServerSnapshotMessage).data);
                    break;

                case 'rig.ws.server.delta.v1':
                    const delta = msg as ServerDeltaMessage;
                    // Duplicate event_id ignored
                    if (this.seenEventIds.has(delta.event_id)) {
                        return;
                    }
                    this.seenEventIds.add(delta.event_id);
                    this.delegate.onDelta(delta);
                    break;

                case 'rig.ws.server.ack.v1':
                    const ack = msg as ServerAckMessage;
                    if (ack.status === 'refused') {
                        vscode.window.showWarningMessage(`Rig Intent Refused: ${ack.reason}`);
                    }
                    break;

                case 'rig.ws.server.warning.v1':
                    this.delegate.onMessage(msg);
                    break;

                default:
                    // Unknown or malformed delta becomes warning (implicit in default case for spike)
                    this.delegate.onMessage(msg);
            }
        } catch (err) {
            console.error('Failed to parse Rig message', err);
            // Malformed delta becomes warning
            this.delegate.onStatusChange('warning', 'Malformed message received from daemon');
        }
    }
}
