"use client";

import { AgentState } from "@/types";

interface Props {
  state: AgentState;
  isConnected: boolean;
}

const STATE_CONFIG: Record<AgentState, { label: string; color: string; dot: string }> = {
  idle: { label: "Idle", color: "text-gray-500", dot: "bg-gray-400" },
  listening: { label: "Listening…", color: "text-blue-600", dot: "bg-blue-500 animate-pulse" },
  thinking: { label: "Thinking…", color: "text-yellow-600", dot: "bg-yellow-400 animate-bounce" },
  speaking: { label: "Speaking", color: "text-green-600", dot: "bg-green-500 animate-pulse" },
};

export default function AgentStatus({ state, isConnected }: Props) {
  const cfg = STATE_CONFIG[state];

  return (
    <div className="bg-white rounded-2xl shadow-lg p-4 flex items-center gap-3">
      <div className="flex flex-col items-center">
        <div className="text-2xl">🤖</div>
        <div className="text-xs text-gray-400 mt-1">Arjun</div>
      </div>
      <div className="flex-1">
        <div className="text-sm font-semibold text-gray-700">HomePro Realty Agent</div>
        {isConnected ? (
          <div className={`flex items-center gap-1.5 mt-1 ${cfg.color}`}>
            <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
            <span className="text-xs font-medium">{cfg.label}</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 mt-1 text-gray-400">
            <span className="w-2 h-2 rounded-full bg-gray-300" />
            <span className="text-xs">Waiting for call…</span>
          </div>
        )}
      </div>
    </div>
  );
}
