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

// Call queue job — mirrors backend app/schemas/queue_schema.py
export type JobStatus =
  | "pending"
  | "dialing"
  | "active"
  | "completed"
  | "failed"
  | "busy"
  | "no_answer"
  | "voicemail";

export interface CallJob {
  id: string;
  phone: string;
  name?: string | null;
  // Customer's CURRENT location (from upload) — NOT preferred property location.
  contact_location?: string | null;
  contact_id?: string | null;
  batch_id?: string | null;
  status: JobStatus;
  attempts: number;
  call_id?: string | null;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
}

export interface QueueSnapshot {
  jobs: CallJob[];
  counts: Partial<Record<JobStatus, number>>;
  active: string[];        // active call_ids
  pending: number;
  max_concurrent: number;
}

// WebSocket event types sent by the backend
export type WsEvent =
  | { type: "transcript"; role: "user" | "agent"; text: string; is_final: boolean; call_id: string }
  | { type: "lead_update"; call_id: string; data: Partial<LeadData> }
  | { type: "agent_state"; call_id: string; state: AgentState }
  | { type: "call_connected"; call_id: string }
  | { type: "hot_lead_flagged"; call_id: string; reason: string }
  | { type: "call_transferred"; call_id: string; reason: string }
  | { type: "call_ended"; call_id: string; duration_seconds: number; lead_data?: LeadData }
  | { type: "pipeline_error"; call_id: string; label: string; message: string }
  | ({ type: "queue_update" } & QueueSnapshot)
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
