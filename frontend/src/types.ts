export type UserRole = "customer" | "agent" | "admin";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: UserRole;
  is_active: boolean;
}

export interface Session {
  id: string;
  user_id: string;
  title: string;
  status: string;
  last_message_at: string | null;
  created_at: string;
}

export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  event_metadata: {
    citations?: Citation[];
    approval?: Approval;
    approval_id?: string;
    approval_status?: string;
    action_type?: string;
    error?: string;
  };
  created_at: string;
}

export interface Citation {
  source: string;
  title: string;
  score: number;
  content: string;
}

export interface Approval {
  id: string;
  approval_id?: string;
  session_id: string;
  user_id: string;
  action_type: string;
  payload: Record<string, unknown>;
  status: string;
  version: number;
  requested_by: string;
  decided_by: string | null;
  decision_comment: string | null;
  error_message: string | null;
  result: Record<string, unknown>;
  notified_at: string | null;
  idempotency_key: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  filename: string;
  version: string;
  status: string;
  chunk_count: number;
  created_at: string;
}

export interface SseEvent {
  event: "session" | "token" | "tool_call" | "citation" | "approval_required" | "done" | "error";
  data: Record<string, unknown>;
}
