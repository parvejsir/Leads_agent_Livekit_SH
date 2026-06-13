"use client";

import { useState, useCallback } from "react";
import { useCallWebSocket } from "@/hooks/useCallWebSocket";
import TranscriptPanel from "./Transcript";
import { endCall } from "@/services/api";
import { AgentState, CallJob, TranscriptEntry, WsEvent } from "@/types";

// One active call. Owns its OWN WebSocket + transcript/state, so two tiles never
// share state — this is the isolation boundary for concurrent calls.
export default function CallTile({ job }: { job: CallJob }) {
  const callId = job.call_id as string;
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [isConnected, setIsConnected] = useState(job.status === "active");
  const [isHot, setIsHot] = useState(false);
  const [ending, setEnding] = useState(false);
  const [pipelineError, setPipelineError] = useState<string>("");

  const handleEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case "call_connected":
        setIsConnected(true);
        break;
      case "transcript":
        setTranscript((prev) => mergeTranscript(prev, event));
        break;
      case "agent_state":
        setAgentState(event.state);
        break;
      case "hot_lead_flagged":
        setIsHot(true);
        break;
      case "pipeline_error":
        // e.g. Gemini 429 rate-limit → agent can't reply. Make it visible.
        setPipelineError(`${event.label}: ${event.message}`.slice(0, 160));
        break;
      case "call_ended":
        setIsConnected(false);
        setAgentState("idle");
        break;
    }
  }, []);

  useCallWebSocket(callId, handleEvent);

  const handleEnd = async () => {
    setEnding(true);
    try {
      await endCall(callId);
    } catch {
      /* idempotent on the backend; ignore */
    }
    setEnding(false);
  };

  const dot = isConnected
    ? "bg-green-500 animate-pulse"
    : "bg-yellow-400 animate-pulse";

  return (
    <div className="bg-white rounded-2xl shadow-lg flex flex-col h-full overflow-hidden">
      {/* Tile header */}
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`inline-block w-2 h-2 rounded-full ${dot}`} />
            <span className="text-sm font-bold text-gray-800 truncate">
              {job.name || "Unknown"}
            </span>
            {isHot && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-100 text-red-600 font-semibold">
                🔥 HOT
              </span>
            )}
          </div>
          <div className="text-xs text-gray-400 truncate">
            {job.phone}
            {job.contact_location ? ` · ${job.contact_location}` : ""}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs font-medium text-gray-500 capitalize">
            {isConnected ? agentState : job.status}
          </span>
          <button
            onClick={handleEnd}
            disabled={ending}
            className="text-xs bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white font-semibold px-2.5 py-1 rounded-lg transition"
          >
            {ending ? "…" : "End"}
          </button>
        </div>
      </div>

      {/* Pipeline error banner (e.g. LLM rate-limit → silent agent) */}
      {pipelineError && (
        <div className="bg-red-50 text-red-700 text-[11px] px-3 py-1.5 border-b border-red-100">
          ⚠ Agent error — {pipelineError}
        </div>
      )}

      {/* Transcript fills the rest */}
      <div className="flex-1 min-h-0">
        <TranscriptPanel entries={transcript} callId={callId} />
      </div>
    </div>
  );
}

// Replace the trailing interim bubble for the same role; otherwise append.
// Dedups exact-duplicate events so React StrictMode's double socket delivery
// (dev) can't print each turn twice.
function mergeTranscript(
  prev: TranscriptEntry[],
  event: Extract<WsEvent, { type: "transcript" }>,
): TranscriptEntry[] {
  const last = prev[prev.length - 1];
  // Same event delivered twice (e.g. duplicate socket) → ignore.
  if (
    last &&
    last.role === event.role &&
    last.text === event.text &&
    last.is_final === event.is_final
  ) {
    return prev;
  }
  const entry: TranscriptEntry = {
    role: event.role,
    text: event.text,
    is_final: event.is_final,
    timestamp: Date.now(),
  };
  // A streaming update (interim, or a growing final for the same role) replaces
  // the trailing not-yet-committed bubble of that role.
  if (last && last.role === event.role && !last.is_final) {
    return [...prev.slice(0, -1), entry];
  }
  return [...prev, entry];
}
