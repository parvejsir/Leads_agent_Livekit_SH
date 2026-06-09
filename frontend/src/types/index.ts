export interface LeadData {
  name?: string;
  location?: string;
  budget_min?: number;
  budget_max?: number;
  property_type?: "apartment" | "villa" | "plot" | "commercial";
  bhk?: number;
  ready_to_move?: boolean;
  purpose?: "self_use" | "investment" | "rental";
  interest_level?: "cold" | "warm" | "hot";
  is_interested?: boolean;
  notes?: string;
}

export interface TranscriptEntry {
  role: "user" | "agent";
  text: string;
  is_final: boolean;
  timestamp: number;
}

export type AgentState = "idle" | "listening" | "thinking" | "speaking";

// WebSocket event types sent by the backend
export type WsEvent =
  | { type: "transcript"; role: "user" | "agent"; text: string; is_final: boolean; call_id: string }
  | { type: "lead_update"; call_id: string; data: Partial<LeadData> }
  | { type: "agent_state"; call_id: string; state: AgentState }
  | { type: "call_connected"; call_id: string }
  | { type: "hot_lead_flagged"; call_id: string; reason: string }
  | { type: "call_transferred"; call_id: string; reason: string }
  | { type: "call_ended"; call_id: string; duration_seconds: number; lead_data?: LeadData }
  | { type: "pong" };

export interface CallSession {
  callId: string;
  roomName: string;
  callSid: string;
  phone: string;
  status: "initiated" | "connected" | "ended";
  startTime: number;
}

export type CallStatus = "completed" | "no_answer" | "failed";

// Lightweight row returned by GET /calls
export interface CallSummary {
  call_id: string;
  phone: string;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number;
  status: CallStatus;
  summary: string;
  turns: number;
  lead_data: LeadData;
}

// Full record returned by GET /calls/{id}
export interface CallRecord {
  call_id: string;
  phone: string;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number;
  status: CallStatus;
  summary: string;
  transcript: { role: "user" | "agent"; text: string }[];
  lead_data: LeadData;
}
