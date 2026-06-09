"use client";

import { useEffect, useState, useCallback } from "react";
import Nav from "@/components/Nav";
import { listCalls, getCall } from "@/services/api";
import { CallSummary, CallRecord, CallStatus } from "@/types";

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDuration(s: number): string {
  if (!s) return "0s";
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

const STATUS_STYLES: Record<CallStatus, string> = {
  completed: "bg-green-100 text-green-700",
  no_answer: "bg-gray-100 text-gray-600",
  failed: "bg-red-100 text-red-700",
};

function StatusBadge({ status }: { status: CallStatus }) {
  const label = status.replace("_", " ");
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize ${STATUS_STYLES[status] ?? STATUS_STYLES.completed}`}>
      {label}
    </span>
  );
}

export default function HistoryPage() {
  const [calls, setCalls] = useState<CallSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<CallRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setCalls(await listCalls());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load call history");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openDetail = async (callId: string) => {
    setDetailLoading(true);
    setSelected(null);
    try {
      setSelected(await getCall(callId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load call");
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 to-blue-50">
      <Nav>
        <button
          onClick={load}
          className="text-xs px-3 py-1.5 rounded-lg font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
        >
          ↻ Refresh
        </button>
      </Nav>

      <main className="max-w-7xl mx-auto px-6 py-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-gray-800">Call History</h2>
          <span className="text-sm text-gray-400">{calls.length} call{calls.length === 1 ? "" : "s"}</span>
        </div>

        {error && (
          <div className="bg-red-50 text-red-700 text-sm rounded-lg px-4 py-3 mb-4">{error}</div>
        )}

        {loading ? (
          <div className="text-center text-gray-400 py-20 text-sm">Loading call history…</div>
        ) : calls.length === 0 ? (
          <div className="bg-white rounded-2xl shadow-lg text-center text-gray-400 py-20 text-sm">
            No calls yet. Completed calls will appear here.
          </div>
        ) : (
          <div className="bg-white rounded-2xl shadow-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-400 text-xs uppercase tracking-wide border-b border-gray-100">
                  <th className="px-5 py-3 font-semibold">Phone</th>
                  <th className="px-5 py-3 font-semibold">Started</th>
                  <th className="px-5 py-3 font-semibold">Duration</th>
                  <th className="px-5 py-3 font-semibold">Status</th>
                  <th className="px-5 py-3 font-semibold">Summary</th>
                  <th className="px-5 py-3 font-semibold text-right">Turns</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((c) => (
                  <tr
                    key={c.call_id}
                    onClick={() => openDetail(c.call_id)}
                    className="border-b border-gray-50 last:border-0 hover:bg-blue-50/40 cursor-pointer transition-colors"
                  >
                    <td className="px-5 py-3 font-medium text-gray-800 whitespace-nowrap">{c.phone}</td>
                    <td className="px-5 py-3 text-gray-500 whitespace-nowrap">{fmtTime(c.start_time)}</td>
                    <td className="px-5 py-3 text-gray-500 whitespace-nowrap">{fmtDuration(c.duration_seconds)}</td>
                    <td className="px-5 py-3"><StatusBadge status={c.status} /></td>
                    <td className="px-5 py-3 text-gray-600 max-w-md truncate">{c.summary || <span className="text-gray-300">—</span>}</td>
                    <td className="px-5 py-3 text-gray-500 text-right">{c.turns}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {(selected || detailLoading) && (
        <CallDetailModal
          record={selected}
          loading={detailLoading}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

function CallDetailModal({
  record,
  loading,
  onClose,
}: {
  record: CallRecord | null;
  loading: boolean;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-gray-800">
              {record ? record.phone : "Loading…"}
            </h3>
            {record && (
              <p className="text-xs text-gray-400 font-mono">#{record.call_id}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-xl leading-none px-2"
          >
            ×
          </button>
        </div>

        {loading || !record ? (
          <div className="py-20 text-center text-gray-400 text-sm">Loading…</div>
        ) : (
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5 min-h-0">
            {/* Metadata */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
              <Meta label="Started" value={fmtTime(record.start_time)} />
              <Meta label="Ended" value={fmtTime(record.end_time)} />
              <Meta label="Duration" value={fmtDuration(record.duration_seconds)} />
              <Meta label="Status" value={record.status.replace("_", " ")} />
            </div>

            {record.summary && (
              <div>
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Summary</h4>
                <p className="text-sm text-gray-700 bg-gray-50 rounded-lg px-3 py-2">{record.summary}</p>
              </div>
            )}

            {record.lead_data && Object.keys(record.lead_data).length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Lead Data</h4>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(record.lead_data).map(([k, v]) => (
                    <span key={k} className="text-xs bg-blue-50 text-blue-700 rounded-full px-3 py-1">
                      <span className="font-semibold">{k}:</span> {String(v)}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Transcript */}
            <div>
              <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                Transcript ({record.transcript?.length ?? 0})
              </h4>
              {!record.transcript || record.transcript.length === 0 ? (
                <p className="text-sm text-gray-300">No transcript recorded.</p>
              ) : (
                <div className="space-y-3">
                  {record.transcript.map((t, i) => {
                    const isAgent = t.role === "agent";
                    return (
                      <div key={i} className={`flex ${isAgent ? "justify-start" : "justify-end"}`}>
                        <div
                          className={`max-w-[80%] px-4 py-2 rounded-2xl text-sm leading-relaxed ${
                            isAgent
                              ? "bg-blue-50 text-blue-900 rounded-tl-sm"
                              : "bg-gray-100 text-gray-800 rounded-tr-sm"
                          }`}
                        >
                          <div className="text-[10px] font-semibold mb-0.5 uppercase tracking-wide opacity-50">
                            {isAgent ? "Arjun (Agent)" : "Customer"}
                          </div>
                          {t.text}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-gray-400">{label}</div>
      <div className="text-gray-800 font-medium capitalize">{value}</div>
    </div>
  );
}
