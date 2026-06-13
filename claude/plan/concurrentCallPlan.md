# Concurrent Outbound Calling — Implementation Plan

> **Deliverable note:** Plan mode only permits editing this plan file. The very first
> implementation step (after approval) is to copy this document verbatim to the
> repo at `claude/plan/concurrentCallPlan.md` as the user requested.

## Context

HomePro Realty Voice AI today places **one outbound call at a time**: an operator types a
single phone number, the FastAPI `POST /call/start` creates a LiveKit room, dispatches the
`RealEstateAgent` worker, the agent places the SIP call, talks, and on hangup runs lead
extraction + storage. This single-call flow works well and must not regress.

The business needs an **outbound dialing campaign** tool: load many contacts (manual list or
file), and have one AI agent work **N calls concurrently** (phase 1: `MAX_CONCURRENT_CALLS = 2`,
scalable higher later). When any call ends, the freed slot must immediately dial the next
queued contact, until the list is exhausted. Calls must be fully isolated (no cross-talk),
lead extraction must auto-save after each hangup, and the live dashboard must show one
transcript panel per active call. The live "lead extraction panel" is removed (leads still
save automatically to storage/history).

### Key architectural finding (why this is tractable)

The LiveKit `AgentServer` is created with `JobExecutorType.THREAD` (`worker.py:414`) and already
supports **multiple concurrent jobs** — every `dispatch_agent()` spawns a new job in its own
thread with **fully isolated per-call state**: `transcript`, `call_state`, `session`, and
`session.userdata` are all entrypoint locals (`worker.py:70-153`). So we do **not** rewrite the
call engine. Concurrency becomes a **queue + dispatch-throttling + UI** problem, plus locking a
couple of shared globals.

**Shared state that needs protection / signaling:**
- `ACTIVE_CALLS` dict (`call.py:11`) — mutated without a lock.
- `db.txt` append in `save_call_record` (`storage_service.py:54`) — only file write lacking a lock (`leads.json`/`calls.json` already use `asyncio.Lock`).
- Slot-free signal: the worker's `_on_shutdown` runs in a **worker thread** and must notify the queue manager living on the FastAPI loop (reuse the `broadcast_from_thread` / `run_coroutine_threadsafe` pattern from `connection_manager.py:41-47`).

### Decisions locked with the user
- **Queue durability:** JSON-file persisted (`storage/queue.json`), reusing the existing async-lock storage pattern. Survives restart.
- **Live UI:** Dynamic grid — one transcript panel per active call, auto-sizing to `MAX_CONCURRENT_CALLS`, plus a queue/progress sidebar.
- **Upload formats:** CSV + XLSX/XLS (pandas + openpyxl/xlrd). `.numbers` is **not parsed**; the UI shows a clear "export to CSV/XLSX" message.
- **Retries:** **None in phase 1.** Any non-connect outcome (busy/no-answer/voicemail/failed) is terminal; operator re-queues manually. (Status enum still records the outcome.)

---

## Data Model

### `CallJob` (new — `app/schemas/queue_schema.py`)
```
id: str                 # queue job id (uuid)
contact_id: str | None  # from upload "id" column, or None for manual
name: str | None        # contact "customer_name" — drives personalized greeting
contact_location: str   # customer's CURRENT location (NOT property preference)
phone: str              # E.164
status: Literal[pending, dialing, active, completed, failed, busy, no_answer, voicemail]
attempts: int = 0
call_id: str | None     # set when dispatched
error: str | None
created_at / started_at / ended_at: iso str | None
batch_id: str | None    # groups one upload/manual submission
```

> **CRITICAL field separation:** `CallJob.contact_location` = where the customer currently lives
> (from the file). `LeadData.location` (`lead_schema.py`) = the **preferred property location**
> discovered during conversation. These are never merged. Contact location is passed to the
> agent only as soft rapport context, explicitly labeled "current city", and is persisted in
> `calls.json` under a distinct `contact_location` key — it never writes into `lead.location`.

---

## Backend Changes

### New files

**`app/services/queue_manager.py`** — `CallQueueManager` singleton (the core).
- Holds `pending: deque[CallJob]`, `jobs: dict[str, CallJob]` (all jobs by id), `active: dict[call_id -> job_id]`, an `asyncio.Lock`, and a stored event loop (`set_loop`, mirroring `CONNECTION_MANAGER`).
- `async enqueue(jobs: list[CallJob])` → append to pending, persist, call `_pump()`.
- `async _pump()` → while `len(active) < SETTINGS.MAX_CONCURRENT_CALLS` and pending non-empty: pop a job, set `dialing`, generate `call_id`, `await create_room(...)` + `await dispatch_agent(...)` (passing name/contact_location/contact_id), register in `ACTIVE_CALLS` and `active`, set `active`, persist, broadcast queue update. On dispatch exception → mark `failed` (no retry) and continue.
- `notify_call_ended_from_thread(call_id, outcome, error=None)` → thread-safe entry used by the worker; schedules `_on_call_ended(...)` on the stored loop via `run_coroutine_threadsafe`.
- `async _on_call_ended(...)` → set job terminal status, remove from `active`, persist, `_pump()` (dials next), broadcast queue update.
- `async recover_from_disk()` → on startup, load `queue.json`; any job left in `dialing`/`active` (interrupted by a crash) is reset to `pending`; then `_pump()`.
- `snapshot()` → serializable queue state for the API/WS.
- Persistence via a new `_queue_lock` + `save_queue`/`load_queue` (either here or in `storage_service.py`).

**`app/services/contact_parser.py`** — file → contacts.
- `parse_contacts(filename, raw_bytes) -> list[ContactRow]`.
- Dispatch by extension: `.csv` → `pandas.read_csv`; `.xlsx` → `read_excel(engine="openpyxl")`; `.xls` → `read_excel(engine="xlrd")`; `.numbers` → raise `UnsupportedFormatError` with the export-to-CSV message.
- Normalize/validate columns `id, customer_name, location, phoneNo` (case-insensitive, tolerant of header variants). Validate phone (E.164-ish, reuse the frontend's regex logic server-side), drop+report invalid rows, de-dupe by phone.
- Returns parsed rows + a per-row reject report (surfaced in the API response).

**`app/api/contacts.py`** — router (`prefix="/contacts"`).
- `POST /contacts/import` (`UploadFile`) → parse → build `CallJob`s → `queue_manager.enqueue` → return `{accepted, rejected[], batch_id}`.
- `POST /contacts/enqueue` (JSON `{numbers: ["+91...","+91..."], names?: {...}}`) → split comma list, validate, build jobs (name unknown ⇒ generic greeting), enqueue.
- `GET /contacts/queue` → `queue_manager.snapshot()` (polling fallback for the UI).

### Modified files

**`app/core/config.py`** — add `MAX_CONCURRENT_CALLS: int = 2` to `Settings`.

**`app/services/livekit_service.py`** — `create_room()` and `dispatch_agent()` gain optional
`name`, `contact_location`, `contact_id` params and embed them in the room/dispatch metadata
JSON (alongside the existing `call_id`, `phone`). Use `json.dumps` in `dispatch_agent` instead
of the hand-built f-string (`livekit_service.py:42`) so names with quotes don't break.

**`app/agents/worker.py`**
- `entrypoint`: read `name`, `contact_location`, `contact_id` from `metadata` into `userdata` (`worker.py:57-64`, `144-152`).
- Personalized greeting: in the greeting `generate_reply` (`worker.py:383-388`), branch on `name` — if present, instruct "Greet the customer by name, e.g. 'Hi {name}, this is Arjun from HomePro Realty…'"; otherwise keep the current generic warm greeting. Optionally append a one-line context note to the agent about the customer's current city, clearly marked as *not* a property preference.
- `_on_shutdown` (`worker.py:252-323`): after the existing post-call processing, call
  `queue_manager.notify_call_ended_from_thread(call_id, outcome, error)` so the freed slot dials
  the next contact. `outcome` derives from `call_state`: `answered` ⇒ `completed`; SIP failure
  path (`worker.py:373-377`) ⇒ `failed` (best-effort map of busy/no-answer from the SIP
  exception text where available — purely informational, no retry). Import the queue manager
  lazily (as `ACTIVE_CALLS` is imported, `worker.py:266`) to avoid a circular import.

**`app/services/storage_service.py`**
- Add `_db_lock = asyncio.Lock()` and wrap the `save_call_record` write (`storage_service.py:28-57`) so concurrent calls don't interleave in `db.txt`.
- Add `contact_location` and `name` passthrough into `save_call_history` records (these come from the worker's `userdata`).
- Optionally house `save_queue`/`load_queue` (`storage/queue.json`, atomic temp-replace like `save_call_history`).

**`app/api/call.py`**
- Add an `asyncio.Lock` (or route everything through the queue manager) guarding `ACTIVE_CALLS` mutations in `/start`, `/end`, `/active`.
- **Back-compat:** keep `POST /call/start` working. Reimplement it as a thin wrapper that builds a single `CallJob` and calls `queue_manager.enqueue([job])` (queue of size 1 ⇒ identical single-call behavior), or leave the direct path and just register the call with the queue manager's `active` map. Either way the existing single-number flow and `POST /call/end/{id}` keep working unchanged.

**`app/main.py`**
- Register the contacts router; set the queue manager's loop in `lifespan` (next to `CONNECTION_MANAGER.set_loop`, `main.py:31`); call `await queue_manager.recover_from_disk()` on startup.
- Add a queue WebSocket channel: broadcast queue updates through `CONNECTION_MANAGER` on a reserved key (e.g. `"__queue__"`) so the frontend can subscribe at `/ws/__queue__` and receive `{type:"queue_update", jobs:[...], active:[...]}` in real time (reuses existing infra; no new socket plumbing).

**`backend/requirements.txt`** — add `pandas`, `openpyxl`, `xlrd` (xlrd only needed for legacy `.xls`).

---

## Frontend Changes (`frontend/src`)

### Concept
Replace the single-`session` dashboard with: a **control sidebar** (manual dial + file upload +
queue/progress) and a **dynamic grid** of active-call tiles, each tile owning its own WebSocket
and transcript state. The live `LeadPanel` is removed from this screen.

### New files
- **`components/ManualDial.tsx`** — comma-separated numbers textarea + a file `<input>` (accept `.csv,.xlsx,.xls,.numbers`). Posts to `/contacts/enqueue` or `/contacts/import`. Shows the accepted/rejected report; if a `.numbers` file is chosen, shows the "export to CSV/XLSX" guidance returned by the backend.
- **`components/QueuePanel.tsx`** — campaign progress: counts per status (pending/dialing/active/completed/failed/…) and a scrollable job list. Fed by `/ws/__queue__` (with `/contacts/queue` polling fallback).
- **`components/CallTile.tsx`** — encapsulates **one active call**: takes a `callId`, runs its own `useCallWebSocket(callId, …)`, holds its own `transcript`/`agentState`/`isHot` state, and renders an `AgentStatus` + `TranscriptPanel` for that call. This is the key isolation unit — N tiles ⇒ N independent sockets and states.
- **`components/CallGrid.tsx`** — maps the active call list to `CallTile`s in a responsive grid whose column count tracks `MAX_CONCURRENT_CALLS`.

### Modified files
- **`app/page.tsx`** — drop the single `session`/`transcript`/`lead` model and the `<LeadPanel>` (`page.tsx:7,145`). New layout: left = `<ManualDial>` + `<QueuePanel>`; right = `<CallGrid activeCallIds={…}>`. Active call ids come from the `/ws/__queue__` feed.
- **`hooks/useCallWebSocket.ts`** — already per-`callId` and reusable as-is inside `CallTile` (no change needed; confirmed multi-instance safe).
- **`types/index.ts`** — add `CallJob`, `QueueStatus`, and a `queue_update` WS event variant; the existing per-call `WsEvent` types are reused by each tile.
- **`components/LeadPanel.tsx`** — no longer rendered on the live screen (keep the file; it can still be used on a history/detail view).

---

## Data Flow (concurrent campaign)

```
Upload file / paste numbers
   → POST /contacts/import|enqueue
      → contact_parser → [CallJob,…]
         → CallQueueManager.enqueue() → persist queue.json → _pump()
            → while active < MAX: create_room + dispatch_agent(name,contact_location)
               → worker entrypoint (isolated thread): SIP call → greet-by-name → converse
                  → live transcript/state via CONNECTION_MANAGER.broadcast_from_thread(call_id)
                  → hangup → _on_shutdown: extract lead → save (leads.json/calls.json/db.txt)
                     → notify_call_ended_from_thread(call_id, outcome)
                        → mark job terminal → _pump() dials next pending contact
Queue + active-call set streamed to UI via /ws/__queue__; each active call streamed via /ws/{call_id}
```

---

## Testing Strategy

> Use a **mock/stub dispatch** so tests don't place real Twilio calls: add an env flag (e.g.
> `QUEUE_DRY_RUN=1`) that makes `dispatch_agent` a no-op and lets tests drive
> `notify_call_ended_from_thread` directly to simulate hangups. Real end-to-end is verified
> separately with 2–3 live numbers.

| Area | Exact test case | Expected outcome |
|---|---|---|
| **Concurrency** | Enqueue 5 jobs, `MAX=2` | Exactly 2 `active` at all times; never 3+; all 5 eventually `completed`. |
| **Slot refill** | With 2 active, signal call A ended | Within one `_pump()` cycle a 3rd contact moves `pending→dialing→active`; B untouched. |
| **Race / locking** | Fire 20 `enqueue` + 20 `notify_call_ended` concurrently (`asyncio.gather`) | No lost/duplicated jobs; `len(active) ≤ MAX` invariant holds; `queue.json` not corrupted. |
| **Call isolation** | Run 2 live calls, speak different info into each | Each `/ws/{call_id}` shows only its own transcript; `leads.json` has 2 distinct records; no field bleed. |
| **Current-vs-preferred location** | Contact `location=Delhi`; customer says "looking in Gurgaon" | `calls.json.contact_location=Delhi`; `lead.location=Gurgaon`. Never equal-by-accident. |
| **Personalized greeting** | Job with `name=Rahul` vs job with no name | First greeting includes "Rahul"; second is generic "Sir/Ma'am". |
| **Lead extraction auto-save** | Hang up each call | `_on_shutdown` writes leads.json + calls.json + db.txt with no operator action; UI lead panel absent but data persisted. |
| **Hangup (both directions)** | (a) customer hangs up; (b) `transfer_call` tool fires | Both reach `_on_shutdown`, mark terminal, free the slot, dial next. |
| **No-retry policy** | Force a SIP failure (invalid number) | Job → `failed` once, **not** re-queued; next pending still dials. |
| **Bulk upload** | Valid CSV (2 rows), valid XLSX, malformed CSV, `.numbers` | CSV/XLSX enqueue; malformed rows rejected with reasons; `.numbers` returns export-to-CSV message, 0 enqueued. |
| **Persistence/recovery** | Enqueue 6, kill backend with 2 active, restart | `recover_from_disk` resets interrupted jobs to `pending`; pending campaign resumes; no duplicate dials of `completed` jobs. |
| **Stress** | Enqueue 50 (dry-run), `MAX=2` then `MAX=5` | Throughput scales with `MAX`; invariant `active ≤ MAX` always holds; memory/threads bounded. |

**Verification checklist**
- [ ] `active` count never exceeds `MAX_CONCURRENT_CALLS` under load.
- [ ] Every enqueued job reaches a terminal status exactly once.
- [ ] Two concurrent live calls produce two isolated transcripts + two lead records.
- [ ] `contact_location` and `lead.location` are stored separately.
- [ ] Greeting uses the name when known.
- [ ] Queue survives a backend restart mid-campaign.
- [ ] Existing single-number `/call/start` + `/call/end` flow still works unchanged.
- [ ] `db.txt` has no interleaved lines after concurrent calls.

---

## How to verify end-to-end (manual)
1. `cd backend && source VENV/bin/activate && uvicorn app.main:APP --reload --port 8000`; `cd frontend && npm run dev`.
2. Single-call regression: dial one number the old way → confirm transcript, hangup, saved lead.
3. Manual multi-dial: paste 3 numbers with `MAX_CONCURRENT_CALLS=2` → confirm 2 tiles go live, 3rd dials when one ends.
4. File upload: upload a 4-row CSV (with `id,customer_name,location,phoneNo`) → confirm greeting-by-name and that all 4 process 2-at-a-time.
5. Inspect `storage/leads.json`, `storage/calls.json`, `storage/queue.json` for correct, isolated, separated data.

---

## Scaling beyond 2 (noted, not built now)
- `MAX_CONCURRENT_CALLS` is the only knob for phase 1; raising it just lets `_pump()` dispatch more jobs. Watch: LiveKit account concurrent-session limits, Twilio channel limits, Deepgram/Gemini rate limits, and in-process thread count (worker runs in-process via `lifespan`). Beyond ~tens of concurrent calls, move the LiveKit worker to its own process/host — the queue manager design (dispatch + thread-safe done signal) already supports that split.
