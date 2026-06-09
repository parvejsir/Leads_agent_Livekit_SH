"use client";

import { useState } from "react";
import { startCall, endCall } from "@/services/api";
import { CallSession } from "@/types";

interface Props {
  session: CallSession | null;
  onCallStarted: (session: CallSession) => void;
  onCallEnded: () => void;
}

// Strip spaces and normalize phone number before sending
function normalizePhone(raw: string): string {
  return raw.replace(/\s+/g, "").trim();
}

function isValidPhone(raw: string): boolean {
  const cleaned = normalizePhone(raw);
  // E.164: optional leading +, then 10-15 digits. Catches numbers typed one
  // digit short (e.g. a 9-digit Indian mobile missing its last digit).
  return /^\+?\d{10,15}$/.test(cleaned);
}

export default function CallPanel({ session, onCallStarted, onCallEnded }: Props) {
  const [phone, setPhone] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleStart = async () => {
    const cleaned = normalizePhone(phone);
    if (!cleaned) return;
    setLoading(true);
    setError("");
    try {
      const res = await startCall(cleaned);
      onCallStarted({
        callId: res.call_id,
        roomName: res.room_name,
        callSid: res.call_sid,
        phone: cleaned,
        status: "initiated",
        startTime: Date.now(),
      });
      // loading stays true until session goes non-null (button hidden anyway)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start call");
      setLoading(false);
    }
  };

  const handleEnd = async () => {
    if (!session) return;
    setLoading(true);
    try {
      await endCall(session.callId);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to end call");
    }
    setLoading(false);
    onCallEnded();
  };

  return (
    <div className="bg-white rounded-2xl shadow-lg p-6">
      <h2 className="text-lg font-bold text-gray-800 mb-4">📞 Outbound Call</h2>

      {!session ? (
        <div className="space-y-3">
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+919876543210"
            className="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            onKeyDown={(e) => e.key === "Enter" && handleStart()}
          />
          <p className="text-xs text-gray-400">
            Format: +919876543210 (no spaces needed)
          </p>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <button
            onClick={handleStart}
            disabled={loading || !isValidPhone(phone)}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-2 rounded-lg transition"
          >
            {loading ? "Initiating…" : "📲 Call Now"}
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="text-sm text-gray-500">
            <span className="font-medium text-gray-700">Call ID:</span>{" "}
            <code className="bg-gray-100 px-1 rounded text-xs">{session.callId}</code>
          </div>
          <div className="text-sm text-gray-500">
            <span className="font-medium text-gray-700">Phone:</span> {session.phone}
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                session.status === "connected"
                  ? "bg-green-500 animate-pulse"
                  : session.status === "ended"
                  ? "bg-gray-400"
                  : "bg-yellow-400 animate-pulse"
              }`}
            />
            <span className="text-sm capitalize text-gray-600">{session.status}</span>
          </div>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <button
            onClick={handleEnd}
            disabled={loading}
            className="w-full bg-red-500 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-2 rounded-lg transition"
          >
            {loading ? "Ending…" : "End Call"}
          </button>
        </div>
      )}
    </div>
  );
}
