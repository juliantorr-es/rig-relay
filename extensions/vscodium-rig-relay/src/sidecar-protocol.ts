// Rig Relay IDE Sidecar Protocol
// Defines the IPC messages between the VS Code extension host and
// the Rig Relay sidecar process. The sidecar bridges ACP ↔ MCP for
// IDE capabilities.

export const SIDECAR_PROTOCOL_VERSION = "rig.ide.v1";

// ── Sidecar → Extension Host ────────────────────────────────────

export interface IdeCapabilityRequest {
  type: "capability_request";
  id: string;
  capability: string;
  args: Record<string, unknown>;
  mission_id?: string;
  agent_id?: string;
}

export interface IdeCapabilityResponse {
  type: "capability_response";
  id: string;
  status: "ok" | "error" | "refused";
  result?: unknown;
  error?: string;
  receipt_sha256?: string;
}

export interface IdeApprovalRequest {
  type: "approval_request";
  id: string;
  title: string;
  description: string;
  capability: string;
  risk: "low" | "medium" | "high";
  mutates: boolean;
  detail?: Record<string, unknown>;
}

export interface IdeApprovalResponse {
  type: "approval_response";
  id: string;
  approved: boolean;
  reason?: string;
}

export interface IdeStatusUpdate {
  type: "status";
  status: "ready" | "busy" | "error" | "disconnected";
  message?: string;
}

export interface IdeMissionUpdate {
  type: "mission";
  mission_id: string;
  status: "active" | "completed" | "failed" | "cancelled";
  summary?: string;
}

export interface IdeReceiptEvent {
  type: "receipt";
  kind: string;
  capability: string;
  input_sha256: string;
  output_sha256: string;
  agent_id?: string;
  mission_id?: string;
  user_approved: boolean;
  mutated_workspace: boolean;
}

export interface IdeDiffPreview {
  type: "diff_preview";
  id: string;
  file_path: string;
  old_content: string;
  new_content: string;
  patch_sha256: string;
}

// ── Extension Host → Sidecar ────────────────────────────────────

export interface IdeWorkspaceSnapshot {
  type: "workspace_snapshot";
  roots: string[];
  active_file: string | null;
  open_tabs: string[];
  selection: { file: string; startLine: number; startCol: number; endLine: number; endCol: number } | null;
  visible_ranges: { file: string; startLine: number; endLine: number }[];
  editor_state: {
    language: string;
    lineCount: number;
    eol: string;
    isUntitled: boolean;
    isDirty: boolean;
  } | null;
}

export interface IdeCapabilityResult {
  type: "capability_result";
  id: string;
  capability: string;
  status: "ok" | "error" | "refused";
  result: unknown;
}
