"use client";

import { useState, useCallback } from "react";
import { useCallWebSocket } from "@/hooks/useCallWebSocket";
import CallPanel from "@/components/CallPanel";
import TranscriptPanel from "@/components/Transcript";
import LeadPanel from "@/components/LeadPanel";
import AgentStatus from "@/components/AgentStatus";
import Nav from "@/components/Nav";
import { CallSession, TranscriptEntry, LeadData, AgentState, WsEvent } from "@/types";

export default function Dashboard() {
  const [session, setSession] = useState<CallSession | null>(null);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [lead, setLead] = useState<Partial<LeadData>>({});
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [isConnected, setIsConnected] = useState(false);
  const [isHot, setIsHot] = useState(false);
  const [notification, setNotification] = useState("");

  const showNotification = (msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(""), 4000);
  };

  // Single source of truth for returning the UI to a brand-new-call state.
  // Used by both the call_ended event and the manual End button so no stale
  // transcript/lead/state can leak into the next call.
  const resetCallState = useCallback(() => {
    setSession(null);
    setTranscript([]);
    setLead({});
    setIsHot(false);
    setIsConnected(false);
    setAgentState("idle");
  }, []);

  const handleEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case "call_connected":
        setIsConnected(true);
        setSession((s) => s ? { ...s, status: "connected" } : s);
        break;

      case "transcript":
        setTranscript((prev) => {
          // Replace last interim entry if this is also interim for same role
          if (!event.is_final) {
            const last = prev[prev.length - 1];
            if (last && last.role === event.role && !last.is_final) {
              return [
                ...prev.slice(0, -1),
                { role: event.role, text: event.text, is_final: false, timestamp: Date.now() },
              ];
            }
            return [...prev, { role: event.role, text: event.text, is_final: false, timestamp: Date.now() }];
          }
          // Final: replace last interim or append
          const last = prev[prev.length - 1];
          if (last && last.role === event.role && !last.is_final) {
            return [
              ...prev.slice(0, -1),
              { role: event.role, text: event.text, is_final: true, timestamp: Date.now() },
            ];
          }
          return [...prev, { role: event.role, text: event.text, is_final: true, timestamp: Date.now() }];
        });
        break;

      case "lead_update":
        setLead((prev) => ({ ...prev, ...event.data }));
        break;

      case "agent_state":
        setAgentState(event.state);
        break;

      case "hot_lead_flagged":
        setIsHot(true);
        showNotification(`🔥 Hot Lead! ${event.reason}`);
        break;

      case "call_transferred":
        showNotification(`📲 Call transferred: ${event.reason}`);
        break;

      case "call_ended":
        showNotification(`Call ended (${event.duration_seconds}s) — saved to history`);
        resetCallState();
        break;
    }
  }, [resetCallState]);

  useCallWebSocket(session?.callId ?? null, handleEvent);

  const handleCallStarted = (s: CallSession) => {
    setSession(s);
    setTranscript([]);
    setLead({});
    setIsHot(false);
    setIsConnected(false);
    setAgentState("idle");
  };

  const handleCallEnded = () => {
    resetCallState();
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 to-blue-50">
      {/* Header */}
      <Nav>
        <span
          className={`text-xs px-2 py-1 rounded-full font-medium ${
            isConnected
              ? "bg-green-100 text-green-700"
              : session
              ? "bg-yellow-100 text-yellow-700"
              : "bg-gray-100 text-gray-500"
          }`}
        >
          {isConnected ? "● Live" : session ? "● Connecting" : "● Idle"}
        </span>
      </Nav>

      {/* Notification banner */}
      {notification && (
        <div className="bg-blue-600 text-white text-sm text-center py-2 px-4 animate-fade-in">
          {notification}
        </div>
      )}

      {/* Main layout */}
      <main className="max-w-7xl mx-auto px-6 py-6">
        <div className="grid grid-cols-12 gap-4 h-[calc(100vh-140px)]">
          {/* Left column */}
          <div className="col-span-3 flex flex-col gap-4">
            <AgentStatus state={agentState} isConnected={isConnected} />
            <CallPanel
              key={session?.callId ?? "idle"}
              session={session}
              onCallStarted={handleCallStarted}
              onCallEnded={handleCallEnded}
            />
            <LeadPanel lead={lead} isHot={isHot} />
          </div>

          {/* Right column — transcript */}
          <div className="col-span-9">
            <TranscriptPanel entries={transcript} callId={session?.callId ?? null} />
          </div>
        </div>
      </main>
    </div>
  );
}
