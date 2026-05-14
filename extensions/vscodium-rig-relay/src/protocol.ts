/**
 * Rig Relay WebSocket Protocol Types (v1)
 */

export const PROTOCOL_VERSION = "rig.ws.v1";
export const CLIENT_NAME = "vscodium-rig-relay";

export type RigSchema =
    | "rig.ws.client.auth.v1"
    | "rig.ws.client.ping.v1"
    | "rig.ws.client.intent.v1"
    | "rig.ws.server.auth_ok.v1"
    | "rig.ws.server.auth_error.v1"
    | "rig.ws.server.snapshot.v1"
    | "rig.ws.server.delta.v1"
    | "rig.ws.server.ack.v1"
    | "rig.ws.server.pong.v1"
    | "rig.ws.server.warning.v1";

export interface RigBaseMessage {
    schema: RigSchema;
    seq: number;
    session_id: string;
    created_at: string;
}

export interface ClientAuthMessage {
    schema: "rig.ws.client.auth.v1";
    token: string;
    last_seen_seq: number;
    client_protocol_version: string;
    client_name: string;
}

export interface ClientIntentMessage {
    schema: "rig.ws.client.intent.v1";
    intent_kind: "start_turn" | "cancel_turn" | "get_snapshot";
    intent_id: string;
    payload: any;
}

export interface ServerAuthOkMessage extends RigBaseMessage {
    schema: "rig.ws.server.auth_ok.v1";
    last_seen_seq: number;
    server_protocol_version: string;
    compatibility: "full" | "partial" | "incompatible";
}

export interface ServerSnapshotMessage extends RigBaseMessage {
    schema: "rig.ws.server.snapshot.v1";
    data: any;
}

export interface ServerDeltaMessage extends RigBaseMessage {
    schema: "rig.ws.server.delta.v1";
    op: "append" | "replace" | "patch";
    path: string;
    value: any;
    turn_id: string;
    event_id: string;
}

export interface ServerAckMessage extends RigBaseMessage {
    schema: "rig.ws.server.ack.v1";
    intent_id: string;
    status: "accepted" | "refused";
    reason?: string;
    turn_id?: string;
}

export interface ServerWarningMessage extends RigBaseMessage {
    schema: "rig.ws.server.warning.v1";
    message: string;
    code?: string;
}
