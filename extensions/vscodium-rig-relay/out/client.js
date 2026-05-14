"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.RigDaemonClient = void 0;
const vscode = __importStar(require("vscode"));
const ws_1 = require("ws");
const protocol_1 = require("./protocol");
class RigDaemonClient {
    url;
    token;
    delegate;
    ws = null;
    lastSeenSeq = 0;
    seenEventIds = new Set();
    constructor(url, token, delegate) {
        this.url = url;
        this.token = token;
        this.delegate = delegate;
    }
    connect() {
        this.delegate.onStatusChange('connecting');
        try {
            this.ws = new ws_1.WebSocket(this.url);
            this.ws.on('open', () => {
                this.authenticate();
            });
            this.ws.on('message', (data) => {
                this.handleMessage(data.toString());
            });
            this.ws.on('close', () => {
                this.delegate.onStatusChange('disconnected');
                this.ws = null;
            });
            this.ws.on('error', (err) => {
                this.delegate.onStatusChange('error', err.message);
                this.ws = null;
            });
        }
        catch (err) {
            this.delegate.onStatusChange('error', err.message);
        }
    }
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
    authenticate() {
        if (!this.ws)
            return;
        const auth = {
            schema: 'rig.ws.client.auth.v1',
            token: this.token,
            last_seen_seq: this.lastSeenSeq,
            client_protocol_version: protocol_1.PROTOCOL_VERSION,
            client_name: protocol_1.CLIENT_NAME
        };
        this.ws.send(JSON.stringify(auth));
    }
    sendIntent(kind, payload = {}) {
        if (!this.ws)
            return;
        const intent = {
            schema: 'rig.ws.client.intent.v1',
            intent_kind: kind,
            intent_id: Math.random().toString(36).substring(7),
            payload
        };
        this.ws.send(JSON.stringify(intent));
    }
    handleMessage(raw) {
        try {
            const msg = JSON.parse(raw);
            // Stale seq ignored
            if (msg.seq <= this.lastSeenSeq && msg.schema !== 'rig.ws.server.auth_ok.v1') {
                return;
            }
            this.lastSeenSeq = msg.seq;
            switch (msg.schema) {
                case 'rig.ws.server.auth_ok.v1':
                    const authOk = msg;
                    if (authOk.compatibility === 'incompatible') {
                        this.delegate.onStatusChange('error', `Incompatible protocol: server=${authOk.server_protocol_version}`);
                        this.disconnect();
                    }
                    else {
                        this.delegate.onStatusChange('ready');
                    }
                    break;
                case 'rig.ws.server.snapshot.v1':
                    // Snapshot resets seen event IDs
                    this.seenEventIds.clear();
                    this.delegate.onSnapshot(msg.data);
                    break;
                case 'rig.ws.server.delta.v1':
                    const delta = msg;
                    // Duplicate event_id ignored
                    if (this.seenEventIds.has(delta.event_id)) {
                        return;
                    }
                    this.seenEventIds.add(delta.event_id);
                    this.delegate.onDelta(delta);
                    break;
                case 'rig.ws.server.ack.v1':
                    const ack = msg;
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
        }
        catch (err) {
            console.error('Failed to parse Rig message', err);
            // Malformed delta becomes warning
            this.delegate.onStatusChange('warning', 'Malformed message received from daemon');
        }
    }
}
exports.RigDaemonClient = RigDaemonClient;
//# sourceMappingURL=client.js.map