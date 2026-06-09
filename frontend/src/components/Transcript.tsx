"use client";

import { useEffect, useRef } from "react";
import { TranscriptEntry } from "@/types";

interface Props {
  entries: TranscriptEntry[];
  callId: string | null;
}

export default function TranscriptPanel({ entries, callId }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  return (
    <div className="bg-white rounded-2xl shadow-lg flex flex-col h-full">
      <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-sm font-bold text-gray-700">💬 Live Transcript</h2>
        {callId && (
          <span className="text-xs text-gray-400 font-mono">
            #{callId}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-0">
        {entries.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-300 text-sm">
            Transcript will appear here when the call connects…
          </div>
        ) : (
          entries.map((entry, i) => (
            <TranscriptBubble key={i} entry={entry} />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function TranscriptBubble({ entry }: { entry: TranscriptEntry }) {
  const isAgent = entry.role === "agent";
  return (
    <div className={`flex ${isAgent ? "justify-start" : "justify-end"}`}>
      <div
        className={`max-w-[80%] px-4 py-2 rounded-2xl text-sm leading-relaxed ${
          isAgent
            ? "bg-blue-50 text-blue-900 rounded-tl-sm"
            : "bg-gray-100 text-gray-800 rounded-tr-sm"
        } ${!entry.is_final ? "opacity-60 italic" : ""}`}
      >
        <div className="text-[10px] font-semibold mb-0.5 uppercase tracking-wide opacity-50">
          {isAgent ? "Arjun (Agent)" : "Customer"}
        </div>
        {entry.text}
      </div>
    </div>
  );
}
