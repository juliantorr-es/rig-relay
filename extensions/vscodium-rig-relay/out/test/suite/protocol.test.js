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
const assert = __importStar(require("assert"));
const client_1 = require("../../client");
class MockDelegate {
    status = '';
    snapshots = [];
    deltas = [];
    warnings = [];
    onStatusChange(status, details) {
        this.status = status;
        if (status === 'warning')
            this.warnings.push(details || '');
    }
    onMessage(msg) {
        if (msg.schema === 'rig.ws.server.warning.v1') {
            this.warnings.push(msg.message);
        }
    }
    onSnapshot(data) { this.snapshots.push(data); }
    onDelta(delta) { this.deltas.push(delta); }
}
describe('RigDaemonClient Protocol Logic', () => {
    let delegate;
    let client;
    beforeEach(() => {
        delegate = new MockDelegate();
        client = new client_1.RigDaemonClient('ws://localhost', 'token', delegate);
    });
    it('should ignore stale seq', () => {
        const msg1 = { schema: 'rig.ws.server.delta.v1', seq: 10, event_id: 'e1', op: 'append', path: '/transcript', value: {} };
        const msg2 = { schema: 'rig.ws.server.delta.v1', seq: 5, event_id: 'e2', op: 'append', path: '/transcript', value: {} };
        client.handleMessage(JSON.stringify(msg1));
        client.handleMessage(JSON.stringify(msg2));
        assert.strictEqual(delegate.deltas.length, 1);
        assert.strictEqual(delegate.deltas[0].seq, 10);
    });
    it('should ignore duplicate event_id', () => {
        const msg1 = { schema: 'rig.ws.server.delta.v1', seq: 10, event_id: 'e1', op: 'append', path: '/transcript', value: {} };
        const msg2 = { schema: 'rig.ws.server.delta.v1', seq: 11, event_id: 'e1', op: 'append', path: '/transcript', value: {} };
        client.handleMessage(JSON.stringify(msg1));
        client.handleMessage(JSON.stringify(msg2));
        assert.strictEqual(delegate.deltas.length, 1);
    });
    it('should reset seen event IDs on snapshot', () => {
        const msg1 = { schema: 'rig.ws.server.delta.v1', seq: 10, event_id: 'e1', op: 'append', path: '/transcript', value: {} };
        const snap = { schema: 'rig.ws.server.snapshot.v1', seq: 11, data: {} };
        const msg2 = { schema: 'rig.ws.server.delta.v1', seq: 12, event_id: 'e1', op: 'append', path: '/transcript', value: {} };
        client.handleMessage(JSON.stringify(msg1));
        client.handleMessage(JSON.stringify(snap));
        client.handleMessage(JSON.stringify(msg2));
        assert.strictEqual(delegate.deltas.length, 2);
    });
    it('should handle malformed JSON as warning', () => {
        client.handleMessage('not json');
        assert.strictEqual(delegate.status, 'warning');
        assert.strictEqual(delegate.warnings[0], 'Malformed message received from daemon');
    });
});
//# sourceMappingURL=protocol.test.js.map