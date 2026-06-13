"""
Call queue + concurrency manager.

One AI agent works up to MAX_CONCURRENT_CALLS outbound calls at a time. Contacts
are enqueued (manual numbers or file upload); the manager dispatches at most
MAX_CONCURRENT_CALLS jobs and, whenever a call ends, immediately dials the next
pending contact. State is persisted to storage/queue.json so a campaign survives
a backend restart.

Threading note: the LiveKit worker runs in a separate thread. It signals call
connect/end via notify_*_from_thread(), which hops back onto the FastAPI event
loop with run_coroutine_threadsafe — the same pattern as ConnectionManager.
"""

import asyncio
from collections import deque

from app.core.config import SETTINGS
from app.core.logging import LOGGER
from app.schemas.queue_schema import CallJob, TERMINAL_STATUSES
from app.services.storage_service import load_queue, save_queue
from app.utils.helpers import generate_call_id, utc_now_iso
from app.websocket.connection_manager import CONNECTION_MANAGER

# Reserved CONNECTION_MANAGER channel the frontend subscribes to (/ws/__queue__)
# for real-time queue/progress updates.
QUEUE_CHANNEL = "__queue__"


class CallQueueManager:
    """Singleton owning the pending queue, the active set, and the dispatch loop."""

    def __init__(self) -> None:
        self._jobs: dict[str, CallJob] = {}     # job_id -> job (all jobs)
        self._pending: deque[str] = deque()     # job_ids awaiting a slot
        self._active: dict[str, str] = {}        # call_id -> job_id (in-flight)
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ── Public API ────────────────────────────────────────────────────────────

    async def enqueue(self, jobs: list[CallJob]) -> None:
        async with self._lock:
            for job in jobs:
                self._jobs[job.id] = job
                self._pending.append(job.id)
            await self._persist_locked()
        LOGGER.info(f"[queue] enqueued {len(jobs)} job(s); pending={len(self._pending)}")
        await self._broadcast_snapshot()
        await self._pump()

    async def clear_finished(self) -> int:
        """Drop terminal jobs (completed/failed/…) from the live queue view."""
        async with self._lock:
            removed = [jid for jid, j in self._jobs.items() if j.status in TERMINAL_STATUSES]
            for jid in removed:
                del self._jobs[jid]
            await self._persist_locked()
        await self._broadcast_snapshot()
        return len(removed)

    def snapshot(self) -> dict:
        """Serializable queue state. Synchronous (no awaits) → atomic on the loop."""
        counts: dict[str, int] = {}
        for j in self._jobs.values():
            counts[j.status] = counts.get(j.status, 0) + 1
        return {
            "jobs": [j.model_dump() for j in self._jobs.values()],
            "counts": counts,
            "active": list(self._active.keys()),
            "pending": len(self._pending),
            "max_concurrent": SETTINGS.MAX_CONCURRENT_CALLS,
        }

    async def recover_from_disk(self) -> None:
        """Reload persisted jobs on startup; re-queue calls interrupted by a crash."""
        raw = await load_queue()
        async with self._lock:
            self._jobs.clear()
            self._pending.clear()
            self._active.clear()
            for data in raw:
                try:
                    job = CallJob(**data)
                except Exception:
                    continue
                # Finished jobs from previous sessions live in calls.json — don't
                # reload them, otherwise the queue panel fills with stale rows.
                if job.status in TERMINAL_STATUSES:
                    continue
                # A call left mid-flight by a crash can't be resumed — re-queue it.
                if job.status in ("dialing", "active"):
                    job.status = "pending"
                    job.call_id = None
                    job.started_at = None
                self._jobs[job.id] = job
                if job.status == "pending":
                    self._pending.append(job.id)
            await self._persist_locked()
        LOGGER.info(f"[queue] recovered {len(self._jobs)} job(s); pending={len(self._pending)}")
        await self._broadcast_snapshot()
        await self._pump()

    # ── Thread-safe signals from the LiveKit worker ───────────────────────────

    def notify_call_connected_from_thread(self, call_id: str) -> None:
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._on_call_connected(call_id), self._loop)

    def notify_call_ended_from_thread(
        self, call_id: str, outcome: str, error: str | None = None
    ) -> None:
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._on_call_ended(call_id, outcome, error), self._loop
            )

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _pump(self) -> None:
        """Fill free slots from the pending queue. Dispatch happens outside the lock."""
        to_dispatch: list[CallJob] = []
        async with self._lock:
            while len(self._active) < SETTINGS.MAX_CONCURRENT_CALLS and self._pending:
                job_id = self._pending.popleft()
                job = self._jobs.get(job_id)
                if not job or job.status != "pending":
                    continue
                job.call_id = generate_call_id()
                job.status = "dialing"
                job.started_at = utc_now_iso()
                job.attempts += 1
                self._active[job.call_id] = job_id
                to_dispatch.append(job)
            if to_dispatch:
                await self._persist_locked()

        for job in to_dispatch:
            await self._dispatch(job)
        if to_dispatch:
            await self._broadcast_snapshot()

    async def _dispatch(self, job: CallJob) -> None:
        """Place the outbound call for a job already moved to `dialing`/`active`."""
        if SETTINGS.QUEUE_DRY_RUN:
            async with self._lock:
                job.status = "active"
                await self._persist_locked()
            return

        # Lazy imports avoid a circular dependency (call.py ↔ queue_manager).
        from app.api.call import register_active_call
        from app.services.livekit_service import create_room, dispatch_agent

        try:
            room_name = await create_room(
                job.call_id, job.phone,
                name=job.name, contact_location=job.contact_location, contact_id=job.contact_id,
            )
            await dispatch_agent(
                room_name, job.call_id, job.phone,
                name=job.name, contact_location=job.contact_location, contact_id=job.contact_id,
            )
            register_active_call(job.call_id, room_name, job.phone)
            LOGGER.info(f"[queue] dispatched job {job.id} → call {job.call_id} ({job.phone})")
        except Exception as e:
            LOGGER.error(f"[queue] dispatch failed for job {job.id}: {e}")
            async with self._lock:
                self._active.pop(job.call_id or "", None)
                job.status = "failed"
                job.error = str(e)
                job.ended_at = utc_now_iso()
                await self._persist_locked()
            await self._broadcast_snapshot()
            await self._pump()  # free the slot, dial the next contact

    async def _on_call_connected(self, call_id: str) -> None:
        async with self._lock:
            job = self._job_for_call(call_id)
            if job and job.status == "dialing":
                job.status = "active"
                await self._persist_locked()
        await self._broadcast_snapshot()

    async def _on_call_ended(self, call_id: str, outcome: str, error: str | None) -> None:
        async with self._lock:
            job_id = self._active.pop(call_id, None)
            job = self._jobs.get(job_id) if job_id else self._job_for_call(call_id)
            if job:
                job.status = outcome if outcome in TERMINAL_STATUSES else "completed"
                job.error = error
                job.ended_at = utc_now_iso()
            await self._persist_locked()
        LOGGER.info(f"[queue] call {call_id} ended → {outcome}; active={len(self._active)}")
        await self._broadcast_snapshot()
        await self._pump()  # dial the next pending contact into the freed slot

    def _job_for_call(self, call_id: str) -> CallJob | None:
        for job in self._jobs.values():
            if job.call_id == call_id:
                return job
        return None

    async def _persist_locked(self) -> None:
        await save_queue([j.model_dump() for j in self._jobs.values()])

    async def _broadcast_snapshot(self) -> None:
        await CONNECTION_MANAGER.broadcast(
            QUEUE_CHANNEL, {"type": "queue_update", **self.snapshot()}
        )


QUEUE_MANAGER = CallQueueManager()
