"use client";

import { clearFinishedQueue } from "@/services/api";
import { CallJob, JobStatus, QueueSnapshot } from "@/types";

const FINISHED: JobStatus[] = ["completed", "failed", "busy", "no_answer", "voicemail"];

const STATUS_STYLE: Record<JobStatus, string> = {
  pending: "bg-gray-100 text-gray-600",
  dialing: "bg-yellow-100 text-yellow-700",
  active: "bg-green-100 text-green-700",
  completed: "bg-blue-100 text-blue-700",
  failed: "bg-red-100 text-red-700",
  busy: "bg-orange-100 text-orange-700",
  no_answer: "bg-amber-100 text-amber-700",
  voicemail: "bg-purple-100 text-purple-700",
};

const ORDER: JobStatus[] = [
  "active", "dialing", "pending", "completed", "failed", "busy", "no_answer", "voicemail",
];

export default function QueuePanel({ snapshot }: { snapshot: QueueSnapshot | null }) {
  const jobs = snapshot?.jobs ?? [];
  const counts = snapshot?.counts ?? {};
  const total = jobs.length;
  const done = jobs.filter((j) => FINISHED.includes(j.status)).length;

  // Newest-relevant first: active/dialing on top, then pending, then finished.
  const sorted = [...jobs].sort(
    (a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status),
  );

  return (
    <div className="bg-white rounded-2xl shadow-lg p-5 flex flex-col min-h-0 flex-1">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-bold text-gray-800">📋 Call Queue</h2>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">
            {done}/{total} done · {snapshot?.max_concurrent ?? "-"} at a time
          </span>
          {done > 0 && (
            <button
              onClick={() => clearFinishedQueue().catch(() => {})}
              className="text-[11px] text-gray-500 hover:text-red-600 underline"
            >
              Clear finished
            </button>
          )}
        </div>
      </div>

      {/* Status count chips */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {ORDER.filter((s) => counts[s]).map((s) => (
          <span
            key={s}
            className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${STATUS_STYLE[s]}`}
          >
            {s.replace("_", " ")}: {counts[s]}
          </span>
        ))}
        {total === 0 && (
          <span className="text-xs text-gray-400">Queue is empty.</span>
        )}
      </div>

      {/* Job list */}
      <div className="flex-1 overflow-y-auto min-h-0 divide-y divide-gray-50">
        {sorted.map((job) => (
          <JobRow key={job.id} job={job} />
        ))}
      </div>
    </div>
  );
}

function JobRow({ job }: { job: CallJob }) {
  return (
    <div className="py-2 flex items-center justify-between gap-2">
      <div className="min-w-0">
        <div className="text-sm text-gray-700 truncate">
          {job.name || job.phone}
        </div>
        {job.name && <div className="text-[11px] text-gray-400 truncate">{job.phone}</div>}
      </div>
      <span
        className={`text-[11px] px-2 py-0.5 rounded-full font-medium shrink-0 ${STATUS_STYLE[job.status]}`}
      >
        {job.status.replace("_", " ")}
      </span>
    </div>
  );
}
