"use client";

import { useState, useCallback, useRef } from "react";
import { useCallWebSocket } from "@/hooks/useCallWebSocket";
import ManualDial from "@/components/ManualDial";
import QueuePanel from "@/components/QueuePanel";
import CallGrid from "@/components/CallGrid";
import Nav from "@/components/Nav";
import { QueueSnapshot, WsEvent } from "@/types";

// Reserved backend channel that streams queue/progress updates.
const QUEUE_CHANNEL = "__queue__";

export default function Dashboard() {
  const [snapshot, setSnapshot] = useState<QueueSnapshot | null>(null);
  const [notification, setNotification] = useState("");
  const prevActive = useRef<Set<string>>(new Set());

  const showNotification = useCallback((msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(""), 4000);
  }, []);

  // Single queue socket drives the whole dashboard. Each active call additionally
  // opens its own socket inside its CallTile (see CallGrid).
  const handleQueueEvent = useCallback((event: WsEvent) => {
    if (event.type !== "queue_update") return;
    const snap: QueueSnapshot = {
      jobs: event.jobs,
      counts: event.counts,
      active: event.active,
      pending: event.pending,
      max_concurrent: event.max_concurrent,
    };
    setSnapshot(snap);

    // Notify when a new call goes live.
    const now = new Set(snap.active);
    for (const cid of now) {
      if (!prevActive.current.has(cid)) {
        const job = snap.jobs.find((j) => j.call_id === cid);
        showNotification(`📲 Dialing ${job?.name || job?.phone || cid}`);
      }
    }
    prevActive.current = now;
  }, [showNotification]);

  useCallWebSocket(QUEUE_CHANNEL, handleQueueEvent);

  const activeCount = snapshot?.active.length ?? 0;
  const pending = snapshot?.pending ?? 0;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 to-blue-50">
      <Nav>
        <span
          className={`text-xs px-2 py-1 rounded-full font-medium ${
            activeCount > 0
              ? "bg-green-100 text-green-700"
              : pending > 0
              ? "bg-yellow-100 text-yellow-700"
              : "bg-gray-100 text-gray-500"
          }`}
        >
          {activeCount > 0
            ? `● ${activeCount} Live`
            : pending > 0
            ? `● ${pending} Queued`
            : "● Idle"}
        </span>
      </Nav>

      {notification && (
        <div className="bg-blue-600 text-white text-sm text-center py-2 px-4 animate-fade-in">
          {notification}
        </div>
      )}

      <main className="max-w-7xl mx-auto px-6 py-6">
        <div className="grid grid-cols-12 gap-4 h-[calc(100vh-140px)]">
          {/* Left: controls + queue */}
          <div className="col-span-4 xl:col-span-3 flex flex-col gap-4 min-h-0">
            <ManualDial onQueued={showNotification} />
            <QueuePanel snapshot={snapshot} />
          </div>

          {/* Right: live concurrent calls */}
          <div className="col-span-8 xl:col-span-9 min-h-0">
            <CallGrid
              jobs={snapshot?.jobs ?? []}
              activeCallIds={snapshot?.active ?? []}
              maxConcurrent={snapshot?.max_concurrent ?? 2}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
