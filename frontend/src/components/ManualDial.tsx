"use client";

import { useRef, useState } from "react";
import { enqueueNumbers, importContacts, EnqueueResult } from "@/services/api";

interface Props {
  onQueued: (msg: string) => void;
}

// Two ways to feed the queue: paste comma-separated numbers, or upload a file.
// Both hit the same backend queue.
export default function ManualDial({ onQueued }: Props) {
  const [numbers, setNumbers] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<EnqueueResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const report = (r: EnqueueResult) => {
    setResult(r);
    onQueued(`Queued ${r.accepted} number(s)${r.rejected.length ? `, ${r.rejected.length} skipped` : ""}`);
  };

  const handleEnqueue = async () => {
    if (!numbers.trim()) return;
    setLoading(true);
    setError("");
    try {
      report(await enqueueNumbers(numbers));
      setNumbers("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to queue numbers");
    }
    setLoading(false);
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      report(await importContacts(file));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to import file");
    }
    setLoading(false);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <div className="bg-white rounded-2xl shadow-lg p-5 space-y-4">
      <h2 className="text-lg font-bold text-gray-800">📞 Dial Contacts</h2>

      {/* Manual numbers */}
      <div className="space-y-2">
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Manual — comma-separated
        </label>
        <textarea
          value={numbers}
          onChange={(e) => setNumbers(e.target.value)}
          placeholder="+919999999999, +918888888888, +917777777777"
          rows={3}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none"
        />
        <button
          onClick={handleEnqueue}
          disabled={loading || !numbers.trim()}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-2 rounded-lg transition text-sm"
        >
          {loading ? "Queuing…" : "Queue & Dial"}
        </button>
      </div>

      {/* File upload */}
      <div className="space-y-2 pt-2 border-t border-gray-100">
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Upload — CSV / XLSX / XLS
        </label>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.xlsx,.xls,.numbers"
          onChange={handleFile}
          disabled={loading}
          className="w-full text-xs text-gray-600 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-blue-50 file:text-blue-700 file:font-semibold hover:file:bg-blue-100"
        />
        <p className="text-[11px] text-gray-400">
          Columns: id, customer_name, location, phoneNo. (.numbers — export to CSV/XLSX first.)
        </p>
      </div>

      {error && <p className="text-red-500 text-xs">{error}</p>}

      {result && result.rejected.length > 0 && (
        <div className="text-[11px] text-amber-600 bg-amber-50 rounded-lg p-2 max-h-24 overflow-y-auto">
          <div className="font-semibold mb-1">{result.rejected.length} skipped:</div>
          {result.rejected.slice(0, 20).map((r, i) => (
            <div key={i}>
              {r.row ? `row ${r.row}: ` : ""}{r.phone || "—"} — {r.reason}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
