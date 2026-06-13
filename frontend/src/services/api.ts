import { CallSummary, CallRecord } from "@/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface StartCallResponse {
  call_id: string;
  room_name: string;
  call_sid: string;
  status: string;
}

export async function startCall(phoneNumber: string): Promise<StartCallResponse> {
  const res = await fetch(`${API_URL}/call/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone_number: phoneNumber }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function endCall(callId: string): Promise<void> {
  const res = await fetch(`${API_URL}/call/end/${callId}`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
}

export interface EnqueueResult {
  batch_id: string;
  accepted: number;
  rejected: { phone?: string; row?: number; reason: string }[];
}

// Manual dial — comma-separated numbers queued for concurrent calling.
export async function enqueueNumbers(numbers: string): Promise<EnqueueResult> {
  const res = await fetch(`${API_URL}/contacts/enqueue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ numbers }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// Bulk upload — CSV/XLSX/XLS file parsed server-side and queued.
export async function importContacts(file: File): Promise<EnqueueResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_URL}/contacts/import`, { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// Remove finished (completed/failed/…) jobs from the live queue view.
export async function clearFinishedQueue(): Promise<{ removed: number }> {
  const res = await fetch(`${API_URL}/contacts/queue/clear`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function listCalls(): Promise<CallSummary[]> {
  const res = await fetch(`${API_URL}/calls`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return data.calls as CallSummary[];
}

export async function getCall(callId: string): Promise<CallRecord> {
  const res = await fetch(`${API_URL}/calls/${callId}`, { cache: "no-store" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
