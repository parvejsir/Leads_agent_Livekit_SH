"use client";

import CallTile from "./CallTile";
import { CallJob } from "@/types";

interface Props {
  jobs: CallJob[];          // all jobs (from queue snapshot)
  activeCallIds: string[];  // call_ids currently in-flight
  maxConcurrent: number;
}

// Dynamic grid of active calls — one tile per in-flight call, columns track
// MAX_CONCURRENT_CALLS so it scales when concurrency is raised.
export default function CallGrid({ jobs, activeCallIds, maxConcurrent }: Props) {
  const byCallId = new Map(jobs.filter((j) => j.call_id).map((j) => [j.call_id as string, j]));
  const activeJobs = activeCallIds
    .map((cid) => byCallId.get(cid))
    .filter((j): j is CallJob => Boolean(j));

  if (activeJobs.length === 0) {
    return (
      <div className="bg-white/60 rounded-2xl border-2 border-dashed border-gray-200 h-full flex items-center justify-center text-gray-400 text-sm">
        No active calls. Queue numbers or upload a file to start dialing.
      </div>
    );
  }

  // Up to `maxConcurrent` columns on large screens (capped at 3 for readability).
  const cols = Math.min(Math.max(activeJobs.length, 1), Math.min(maxConcurrent, 3));

  return (
    <div
      className="grid gap-4 h-full grid-cols-1 lg:grid-cols-[var(--cols)]"
      style={{ "--cols": `repeat(${cols}, minmax(0, 1fr))` } as React.CSSProperties}
    >
      {activeJobs.map((job) => (
        <CallTile key={job.call_id} job={job} />
      ))}
    </div>
  );
}
