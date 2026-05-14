import * as assert from 'assert';
import { RigDaemonClient, ClientDelegate } from '../../client';
import { RigBaseMessage, ServerDeltaMessage } from '../../protocol';

class MockDelegate implements ClientDelegate {
    public status: string = '';
    public snapshots: any[] = [];
    public deltas: ServerDeltaMessage[] = [];
    public warnings: string[] = [];

    onStatusChange(status: string, details?: string) {
        this.status = status;
        if (status === 'warning') this.warnings.push(details || '');
    }
    onMessage(msg: RigBaseMessage) {
        if (msg.schema === 'rig.ws.server.warning.v1') {
            this.warnings.push((msg as any).message);
        }
    }
    onSnapshot(data: any) { this.snapshots.push(data); }
    onDelta(delta: ServerDeltaMessage) { this.deltas.push(delta); }
}

describe('RigDaemonClient Protocol Logic', () => {
    let delegate: MockDelegate;
    let client: any;

    beforeEach(() => {
        delegate = new MockDelegate();
        client = new RigDaemonClient('ws://localhost', 'token', delegate);
    });

    it('should ignore stale seq', () => {
        const msg1 = { schema: 'rig.ws.server.delta.v1', seq: 10, event_id: 'e1', op: 'append', path: '/transcript', value: {} };
        const msg2 = { schema: 'rig.ws.server.delta.v1', seq: 5, event_id: 'e2', op: 'append', path: '/transcript', value: {} };
        
        (client as any).handleMessage(JSON.stringify(msg1));
        (client as any).handleMessage(JSON.stringify(msg2));

        assert.strictEqual(delegate.deltas.length, 1);
        assert.strictEqual(delegate.deltas[0].seq, 10);
    });

    it('should ignore duplicate event_id', () => {
        const msg1 = { schema: 'rig.ws.server.delta.v1', seq: 10, event_id: 'e1', op: 'append', path: '/transcript', value: {} };
        const msg2 = { schema: 'rig.ws.server.delta.v1', seq: 11, event_id: 'e1', op: 'append', path: '/transcript', value: {} };
        
        (client as any).handleMessage(JSON.stringify(msg1));
        (client as any).handleMessage(JSON.stringify(msg2));

        assert.strictEqual(delegate.deltas.length, 1);
    });

    it('should reset seen event IDs on snapshot', () => {
        const msg1 = { schema: 'rig.ws.server.delta.v1', seq: 10, event_id: 'e1', op: 'append', path: '/transcript', value: {} };
        const snap = { schema: 'rig.ws.server.snapshot.v1', seq: 11, data: {} };
        const msg2 = { schema: 'rig.ws.server.delta.v1', seq: 12, event_id: 'e1', op: 'append', path: '/transcript', value: {} };
        
        (client as any).handleMessage(JSON.stringify(msg1));
        (client as any).handleMessage(JSON.stringify(snap));
        (client as any).handleMessage(JSON.stringify(msg2));

        assert.strictEqual(delegate.deltas.length, 2);
    });

    it('should handle malformed JSON as warning', () => {
        (client as any).handleMessage('not json');
        assert.strictEqual(delegate.status, 'warning');
        assert.strictEqual(delegate.warnings[0], 'Malformed message received from daemon');
    });
});
