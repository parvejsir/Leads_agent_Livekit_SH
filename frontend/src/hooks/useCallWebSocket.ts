"use client";

import { useEffect, useRef, useCallback } from "react";
import { WsEvent } from "@/types";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
const PING_INTERVAL = 20_000;
const RECONNECT_DELAY = 2_000;
const MAX_RECONNECT = 5;

export function useCallWebSocket(
  callId: string | null,
  onEvent: (event: WsEvent) => void
) {
  const wsRef = useRef<WebSocket | null>(null);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectCount = useRef(0);
  const activeRef = useRef(true);
  // Once a call_ended arrives for this call, never reconnect — a reconnect after
  // end could re-attach to a stale call and leak old state into the next one.
  const endedRef = useRef(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback(() => {
    if (!callId || !activeRef.current || endedRef.current) return;
    if (reconnectCount.current >= MAX_RECONNECT) return;

    const ws = new WebSocket(`${WS_URL}/ws/${callId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectCount.current = 0;
      // Heartbeat
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      }, PING_INTERVAL);
    };

    ws.onmessage = (e) => {
      try {
        const event: WsEvent = JSON.parse(e.data);
        if (event.type === "call_ended") {
          endedRef.current = true;
          activeRef.current = false;
        }
        onEventRef.current(event);
      } catch {}
    };

    ws.onclose = () => {
      if (pingRef.current) clearInterval(pingRef.current);
      if (activeRef.current && !endedRef.current && reconnectCount.current < MAX_RECONNECT) {
        reconnectCount.current++;
        setTimeout(connect, RECONNECT_DELAY);
      }
    };

    ws.onerror = () => ws.close();
  }, [callId]);

  useEffect(() => {
    activeRef.current = true;
    endedRef.current = false;
    reconnectCount.current = 0;
    connect();
    return () => {
      activeRef.current = false;
      if (pingRef.current) clearInterval(pingRef.current);
      wsRef.current?.close();
    };
  }, [connect]);
}
