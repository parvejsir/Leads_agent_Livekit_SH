# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HomePro Realty Voice AI — an outbound real estate sales agent that calls phone numbers via Twilio, uses LiveKit to stream audio to an AI agent (Arjun), and displays live transcripts in a Next.js dashboard.

## Architecture

**Call initiation flow** (`POST /call/start`):
1. FastAPI creates a LiveKit room
2. Dispatches the `RealEstateAgent` worker to that room via LiveKit's agent dispatch API
3. Agent entrypoint calls `ctx.api.sip.create_sip_participant()` with `wait_until_answered=True` — this places the outbound call via the LiveKit SIP trunk (backed by Twilio) and blocks until the customer answers
4. Once answered, `session.start()` runs — agent auto-greets based on system prompt

LiveKit handles all SIP↔WebRTC audio bridging natively. No custom codec bridge is needed.

**LiveKit agent worker** (`backend/app/agents/worker.py`):
- Runs as an `asyncio.Task` inside the FastAPI process (not a separate process), using `JobExecutorType.THREAD`
- Uses Deepgram nova-2-phonecall STT, Gemini 2.5 Flash LLM, ElevenLabs turbo TTS, Silero VAD
- On shutdown, calls Gemini to extract structured lead data from the transcript, then persists it

**Real-time events** (`backend/app/websocket/connection_manager.py`):
- `CONNECTION_MANAGER` is a singleton shared between FastAPI and the LiveKit worker thread
- Worker calls `broadcast_from_thread()` which uses `asyncio.run_coroutine_threadsafe()` to cross the thread boundary
- Frontend connects via `GET /ws/{call_id}` and receives typed events: `transcript`, `agent_state`, `lead_update`, `hot_lead_flagged`, `call_transferred`, `call_ended`

**Storage** (`backend/storage/`):
- `db.txt` — append-only human-readable call log
- `leads.json` — JSON array of structured lead records, upserted by `call_id`

**Frontend** (`frontend/`):
- Next.js 14 app router, Tailwind CSS
- `useCallWebSocket` hook manages reconnection and heartbeat ping
- `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` configured in `.env.local`

## One-Time SIP Setup (required before first call)

**1. Twilio Elastic SIP Trunk:**
- Twilio Console → Elastic SIP Trunks → Create trunk
- Origination URI: `sip:<your-livekit-sip-endpoint>` (find in LiveKit Cloud dashboard under SIP)
- Associate your Twilio phone number to the trunk

**2. LiveKit outbound SIP trunk** (run once with the `lk` CLI):
```bash
lk sip outbound create '{"name":"Twilio Outbound","address":"<twilio-sip-termination-uri>","numbers":["+1xxx"],"auth_username":"<user>","auth_password":"<pass>"}'
```
Copy the returned trunk ID (e.g. `ST_xxxx`) into `backend/.env` as `SIP_OUTBOUND_TRUNK_ID`.

## Running the Backend

```bash
cd backend
source VENV/bin/activate
uvicorn app.main:APP --reload --host 0.0.0.0 --port 8000
```

Required `.env` keys at `backend/.env`:
```
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
DEEPGRAM_API_KEY=...
ELEVEN_API_KEY=...
GEMINI_API_KEY=...
OPENAI_API_KEY=...
SIP_OUTBOUND_TRUNK_ID=ST_xxxx
TRANSFER_PHONE_NUMBER=        # optional
```

## Running the Frontend

```bash
cd frontend
npm install
npm run dev
```

## Key Design Constraints

- **`ACTIVE_CALLS` is in-memory only** — restarting the server loses active call tracking.
- **Worker runs in `JobExecutorType.THREAD`** — the LiveKit agent runs on a thread, not a subprocess, so it shares memory with FastAPI but requires `broadcast_from_thread` for WebSocket calls.
- **No ngrok required for audio** — LiveKit's SIP infrastructure handles the Twilio call directly. ngrok is only needed if you want to receive Twilio status callbacks (which are now removed).

## Agent Tools

The LLM can call three function tools during a conversation:
- `update_lead_fields` — silently updates in-memory lead state as customer reveals info
- `flag_hot_lead` — marks interest level as hot, broadcasts `hot_lead_flagged` event
- `transfer_call` — broadcasts `call_transferred` event to frontend (alerts sales team)
