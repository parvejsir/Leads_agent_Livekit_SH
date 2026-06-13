"""
LiveKit Agent worker — Gemini LLM · Deepgram STT · Deepgram TTS

Stack:
  STT  — Deepgram nova-2-phonecall  (streaming, phone-optimised)
  LLM  — Gemini 2.5 Flash           (streaming, low first-token latency)
  TTS  — Deepgram Aura aura-orion   (streaming chunks, no buffering)
  VAD  — Silero                     (very low threshold for SIP/G.711 audio)

Call flow:
  1. Agent connects to LiveKit room
  2. Session is started (registers audio listeners)
  3. Outbound SIP call is placed — blocks until customer answers
  4. Agent greets based on persona (no hardcoded script)
  5. Real-time conversation until participant disconnects
  6. Post-call: Gemini extracts lead data → stored to disk
"""

import asyncio
import json
import time
from datetime import datetime, timezone

from livekit import api
from livekit.agents import AgentServer, AgentSession, AutoSubscribe, JobContext, JobExecutorType, RoomInputOptions
from livekit.agents import ConversationItemAddedEvent, UserInputTranscribedEvent, AgentStateChangedEvent
from livekit.agents.voice.events import ErrorEvent
from livekit.agents.llm import ChatMessage
from livekit.agents.voice.turn import TurnHandlingOptions
from livekit.plugins import deepgram, silero
from livekit.plugins import google as lk_google

from app.agents.worker_agent.agent import RealEstateAgent
from app.core.config import SETTINGS
from app.core.constants import AGENT_NAME
from app.core.logging import LOGGER
from app.services.lead_extractor import extract_lead_and_summary
from app.services.storage_service import save_call_record, save_call_history, upsert_lead
from app.websocket.connection_manager import CONNECTION_MANAGER

# SIP customer participant identity — must match create_sip_participant below.
SIP_PARTICIPANT_IDENTITY = "sip-customer"


async def prewarm(proc) -> None:
    silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    # IMPORTANT: auto_subscribe expects an AutoSubscribe enum, NOT a bool.
    # Passing `True` makes `True == AutoSubscribe.SUBSCRIBE_ALL` evaluate False,
    # which silently DISABLES track subscription — the agent then never receives
    # the customer's audio, so STT produces nothing. This was the root cause of
    # "agent never responds to user speech". SUBSCRIBE_ALL subscribes the SIP
    # audio track so STT actually gets frames.
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)

    metadata: dict = {}
    try:
        metadata = json.loads(ctx.job.metadata or ctx.room.metadata or "{}")
    except Exception:
        pass

    call_id: str = metadata.get("call_id", ctx.room.name)
    phone: str   = metadata.get("phone", "unknown")
    # Contact context from the queue. `name` personalizes the greeting.
    # `contact_location` is the customer's CURRENT location (from the uploaded
    # file) — NOT their preferred property location, which is discovered during
    # the call and stored in LeadData.location. Never conflate the two.
    name: str | None             = metadata.get("name") or None
    contact_location: str | None = metadata.get("contact_location") or None
    contact_id: str | None       = metadata.get("contact_id") or None
    start_time   = time.time()
    start_iso    = datetime.now(timezone.utc).isoformat()

    LOGGER.info(
        f"[{call_id}] Agent entrypoint — room: {ctx.room.name}, phone: {phone}, "
        f"name: {name or '-'}"
    )

    transcript: list[dict] = []
    # Mutable end-state captured by the shutdown handler. "completed" once the
    # customer actually answered; stays "failed"/"no_answer" otherwise.
    call_state = {"status": "no_answer", "answered": False}

    # ── Audio input diagnostics ─────────────────────────────────────────────────
    # The #1 historical bug was customer audio never reaching STT. Log every track
    # subscription and participant join so a single live call is conclusive.
    @ctx.room.on("track_subscribed")
    def _on_track_subscribed(track, publication, participant) -> None:  # noqa: ANN001
        # source must be SOURCE_MICROPHONE for RoomIO to feed it to STT.
        try:
            from livekit import rtc
            source = rtc.TrackSource.Name(publication.source)
        except Exception:
            source = str(getattr(publication, "source", "?"))
        LOGGER.info(
            f"[{call_id}] track_subscribed — kind={track.kind} source={source} "
            f"identity={participant.identity} sid={getattr(publication, 'sid', '?')}"
        )

    @ctx.room.on("participant_connected")
    def _on_participant_connected(participant) -> None:  # noqa: ANN001
        LOGGER.info(
            f"[{call_id}] participant_connected — identity={participant.identity} "
            f"kind={participant.kind}"
        )

    # ── Session ────────────────────────────────────────────────────────────────
    session = AgentSession(
        vad=silero.VAD.load(
            # SIP/G.711 audio has codec noise. Thresholds of 0.05/0.04 treated
            # all noise as speech, so END_OF_SPEECH never fired and STT got no
            # complete utterances. Use sane thresholds with clear hysteresis.
            activation_threshold=0.35,
            deactivation_threshold=0.25,
            min_silence_duration=0.4,
            min_speech_duration=0.05,
            prefix_padding_duration=0.3,
        ),
        stt=deepgram.STT(
            api_key=SETTINGS.DEEPGRAM_API_KEY,
            model="nova-2-phonecall",
            smart_format=True,
            no_delay=True,
            language="en-US",
            endpointing_ms=300,   # 300ms: natural pause time for Indian-accented phone calls
            interim_results=True,
            punctuate=True,       # improves turn detector accuracy
            filler_words=True,    # captures "um"/"uh" and Hinglish fillers
            vad_events=True,      # ensures SpeechStarted events fire
        ),
        llm=lk_google.LLM(
            api_key=SETTINGS.GEMINI_API_KEY,
            # flash-lite has the highest free-tier budget (15 RPM / 1,000 req-day
            # vs flash's 10 RPM / 250 req-day) and lower latency. The per-turn
            # conversation LLM is the heaviest Gemini consumer, so it gets the
            # roomier quota. Post-call extraction stays on full `flash` (a
            # separate per-model quota bucket) — see lead_extractor.py.
            model="gemini-2.5-flash-lite",
        ),
        tts=deepgram.TTS(
            api_key=SETTINGS.DEEPGRAM_API_KEY,
            # Streams chunks as soon as they arrive — no full-synthesis wait
            model="aura-orion-en",
        ),
        turn_handling=TurnHandlingOptions(
            # Agent starts responding 100ms after speech ends
            endpointing={"mode": "fixed", "min_delay": 0.1, "max_delay": 1.0},
            # Allow user to interrupt agent mid-sentence naturally
            interruption={"enabled": True, "mode": "vad", "min_duration": 0.2},
        ),
        aec_warmup_duration=0.0,  # No acoustic echo on phone calls
        user_away_timeout=45.0,
        userdata={
            "call_id": call_id,
            "phone":   phone,
            "name":    name,
            "contact_location": contact_location,
            "contact_id": contact_id,
            "lead_data": {},
            # Set True by the transfer_call tool. Once the agent finishes speaking
            # its closing line (state → listening), the call is hung up. See the
            # hangup logic in on_state_changed below.
            "pending_hangup": False,
        },
    )

    LOGGER.info(
        f"[{call_id}] Session config — "
        f"STT: nova-2-phonecall endpointing=300ms, "
        f"VAD: activation=0.35 deactivation=0.25 min_silence=0.4s"
    )

    # ── Event hooks ────────────────────────────────────────────────────────────

    @session.on("user_input_transcribed")
    def on_user_transcript(event: UserInputTranscribedEvent) -> None:
        # Logged at INFO (not debug) so the very first event proves STT is
        # receiving customer audio. Empty/interim events are logged too.
        LOGGER.info(
            f"[{call_id}] STT event — final={event.is_final}, "
            f"len={len(event.transcript or '')}"
        )
        text = (event.transcript or "").strip()
        if not text:
            return
        LOGGER.info(f"[{call_id}] STT {'FINAL' if event.is_final else 'interim'}: {text!r}")
        if event.is_final:
            transcript.append({"role": "user", "text": text})
        CONNECTION_MANAGER.broadcast_from_thread(call_id, {
            "type":     "transcript",
            "role":     "user",
            "text":     text,
            "is_final": event.is_final,
            "call_id":  call_id,
        })

    @session.on("conversation_item_added")
    def on_conversation_item(event: ConversationItemAddedEvent) -> None:
        if not isinstance(event.item, ChatMessage) or event.item.role != "assistant":
            return
        text = ""
        for block in (event.item.content or []):
            if isinstance(block, str):
                text += block
            elif hasattr(block, "text") and isinstance(getattr(block, "text"), str):
                text += block.text
        text = text.strip()
        if not text:
            return
        LOGGER.info(f"[{call_id}] AGENT: {text[:120]!r}")
        # Store the final agent turn for lead extraction. The LIVE broadcast (incl.
        # streaming) is handled by RealEstateAgent.transcription_node — broadcasting
        # here too would print the agent turn twice on the UI.
        transcript.append({"role": "agent", "text": text})

    # ── Pipeline errors (LLM/STT/TTS) ──────────────────────────────────────────
    # These were previously swallowed — a Gemini 429 (rate limit) would leave the
    # agent silent with no clue why. Log loudly and surface to the UI so a silent
    # agent is diagnosable. The component (e.g. "google.LLM") and message tell you
    # exactly which provider failed and whether it's a quota/rate-limit error.
    @session.on("error")
    def on_error(event: ErrorEvent) -> None:
        err = event.error
        label = getattr(err, "label", None) or type(err).__name__
        message = str(getattr(err, "error", err))
        recoverable = getattr(err, "recoverable", None)
        LOGGER.error(
            f"[{call_id}] PIPELINE ERROR — {label} (recoverable={recoverable}): {message}"
        )
        CONNECTION_MANAGER.broadcast_from_thread(call_id, {
            "type":    "pipeline_error",
            "call_id": call_id,
            "label":   str(label),
            "message": message,
        })

    # Guards a single hangup so a flapping "listening" state can't fire it twice.
    hangup_started = {"v": False}

    async def _hangup_call() -> None:
        # Let the final TTS audio drain before tearing the room down, otherwise
        # the customer hears the closing line get clipped.
        await asyncio.sleep(1.2)
        try:
            await ctx.api.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
            LOGGER.info(f"[{call_id}] Room deleted — call hung up after transfer")
        except Exception as e:
            LOGGER.error(f"[{call_id}] Hangup failed: {e}")

    @session.on("agent_state_changed")
    def on_state_changed(event: AgentStateChangedEvent) -> None:
        state_str = str(event.new_state).lower()
        LOGGER.info(f"[{call_id}] State → {state_str}")
        ui_state = {"thinking": "thinking", "speaking": "speaking",
                    "listening": "listening", "idle": "idle",
                    "initializing": "idle"}.get(state_str, "idle")
        CONNECTION_MANAGER.broadcast_from_thread(call_id, {
            "type":    "agent_state",
            "call_id": call_id,
            "state":   ui_state,
        })

        # ── Transfer hangup ────────────────────────────────────────────────────
        # transfer_call set pending_hangup and returned a closing line. The agent
        # speaks it (state: thinking → speaking → listening); the first time it
        # settles back to listening, the closing line has played, so we hang up.
        # (Placeholder for a real SIP transfer later — for now the call just ends,
        # which triggers _on_shutdown → lead extraction is saved regardless of
        # whether the customer was interested.)
        if (
            ui_state == "listening"
            and session.userdata.get("pending_hangup")
            and not hangup_started["v"]
        ):
            hangup_started["v"] = True
            LOGGER.info(f"[{call_id}] Transfer closing line spoken — hanging up")
            asyncio.create_task(_hangup_call())

    # ── Shutdown / post-call cleanup ───────────────────────────────────────────

    async def _on_shutdown() -> None:
        duration_s = int(time.time() - start_time)
        end_iso = datetime.now(timezone.utc).isoformat()
        status = "completed" if call_state["answered"] else call_state["status"]
        LOGGER.info(f"[{call_id}] Shutdown — {duration_s}s, {len(transcript)} turns, status={status}")

        # ── Notify the frontend IMMEDIATELY ────────────────────────────────────
        # The moment the SIP leg drops (customer hangs up), reset the UI right
        # away. Lead extraction + summary below are slow Gemini calls (retries +
        # backoff, several seconds) — they must NOT block the call_ended event,
        # otherwise the dashboard appears frozen until they finish. The lead panel
        # already has live data from lead_update events, so call_ended doesn't
        # need lead_data here.
        try:
            from app.api.call import unregister_active_call
            unregister_active_call(call_id)
        except Exception:
            pass
        CONNECTION_MANAGER.broadcast_from_thread(call_id, {
            "type":             "call_ended",
            "call_id":          call_id,
            "duration_seconds": duration_s,
            "lead_data":        {},
        })

        # Free the queue slot → auto-dials the next pending contact. Outcome:
        # answered ⇒ completed; SIP failure ⇒ failed; otherwise no_answer.
        outcome = "completed" if call_state["answered"] else call_state["status"]
        try:
            from app.services.queue_manager import QUEUE_MANAGER
            QUEUE_MANAGER.notify_call_ended_from_thread(
                call_id, outcome, error=None if call_state["answered"] else call_state.get("error"),
            )
        except Exception:
            pass

        # ── Post-call processing (runs AFTER the UI has already reset) ──────────
        lead = None
        summary = ""
        lead_dict: dict = {}
        try:
            # Single Gemini call returns BOTH the structured lead and the summary
            # (previously two separate calls — see extract_lead_and_summary).
            lead, summary = await extract_lead_and_summary(transcript)
            tool_data = session.userdata.get("lead_data", {})
            for k, v in tool_data.items():
                if v is not None and getattr(lead, k, None) is None:
                    try:
                        setattr(lead, k, v)
                    except Exception:
                        pass
            lead_dict = lead.model_dump(exclude_none=True)

            await save_call_record(call_id, phone, transcript, duration_s, lead)
            await upsert_lead(call_id, phone, lead, duration_s)
            await save_call_history({
                "call_id":          call_id,
                "phone":            phone,
                "name":             name,
                "contact_location": contact_location,
                "contact_id":       contact_id,
                "start_time":       start_iso,
                "end_time":         end_iso,
                "duration_seconds": duration_s,
                "status":           status,
                "transcript":       transcript,
                "summary":          summary,
                "lead_data":        lead_dict,
            })
        except Exception as e:
            LOGGER.error(f"[{call_id}] Post-call error: {e}")
            # Best-effort history persistence even if lead extraction/summary failed.
            try:
                await save_call_history({
                    "call_id":          call_id,
                    "phone":            phone,
                    "start_time":       start_iso,
                    "end_time":         end_iso,
                    "duration_seconds": duration_s,
                    "status":           status,
                    "transcript":       transcript,
                    "summary":          summary,
                    "lead_data":        lead_dict,
                })
            except Exception as e2:
                LOGGER.error(f"[{call_id}] History persist failed: {e2}")

    ctx.add_shutdown_callback(_on_shutdown)

    # ── Start session BEFORE placing call ──────────────────────────────────────
    # session.start() registers the participant_connected listener. It must run
    # before the SIP participant joins so audio subscription is set up in time.
    LOGGER.info(f"[{call_id}] Starting session")
    session_task = asyncio.create_task(
        session.start(
            agent=RealEstateAgent(),
            room=ctx.room,
            room_input_options=RoomInputOptions(
                audio_enabled=True,
                # Pin the input to the SIP customer leg so the agent always reads
                # the right participant's audio (no ambiguity / wrong-track bugs).
                participant_identity=SIP_PARTICIPANT_IDENTITY,
                # Telephony has no browser client to send a pre-connect audio
                # buffer; leaving this on makes RoomIO wait pointlessly. Off = audio
                # from the live SIP track flows immediately.
                pre_connect_audio=False,
                # 8 kHz G.711 narrowband — BVC/noise-cancellation can drop it.
                noise_cancellation=None,
                # A hangup / SIP disconnect closes the session → drives call_ended.
                close_on_disconnect=True,
            ),
        )
    )

    # ── Place outbound SIP call ────────────────────────────────────────────────
    LOGGER.info(f"[{call_id}] Placing SIP call to {phone}")
    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=SETTINGS.SIP_OUTBOUND_TRUNK_ID,
                sip_call_to=phone,
                participant_identity=SIP_PARTICIPANT_IDENTITY,
                participant_name="Customer",
                wait_until_answered=True,
            )
        )
        LOGGER.info(f"[{call_id}] Customer answered")
        call_state["answered"] = True
        call_state["status"] = "completed"
        # Tell the frontend the call is live → flips the badge to "● Live".
        CONNECTION_MANAGER.broadcast_from_thread(call_id, {
            "type":    "call_connected",
            "call_id": call_id,
        })
        # Move the queue job dialing → active.
        try:
            from app.services.queue_manager import QUEUE_MANAGER
            QUEUE_MANAGER.notify_call_connected_from_thread(call_id)
        except Exception:
            pass
    except Exception as e:
        LOGGER.error(f"[{call_id}] SIP call failed: {e}")
        call_state["status"] = "failed"
        call_state["error"] = str(e)
        session_task.cancel()
        return

    await session_task

    # ── Opening greeting (persona-driven, not hardcoded) ───────────────────────
    LOGGER.info(f"[{call_id}] Triggering greeting")
    if name:
        # Known contact → greet by name. contact_location is their current city,
        # given only as soft rapport context — do NOT assume it's where they want
        # to buy property.
        greet_instructions = (
            f"The call just connected. Greet the customer by name — say something like "
            f"'Hi {name}, this is Arjun from HomePro Realty'. Be warm, natural and "
            f"conversational — no scripts, no bullet points."
        )
    else:
        greet_instructions = (
            "The call just connected. Greet the customer warmly as Arjun from HomePro Realty. "
            "Be natural and conversational — no scripts, no bullet points."
        )
    greeting_handle = session.generate_reply(instructions=greet_instructions)

    # ── Silence fallback — starts AFTER greeting finishes, not when call connects
    # Counting from call connect left only ~5s after a ~7s greeting. Now the user
    # gets a full 18s to respond once they've finished hearing the greeting.
    def _on_greeting_done(_) -> None:
        LOGGER.info(f"[{call_id}] Greeting done — starting 18s silence watch")

        async def _silence_fallback() -> None:
            await asyncio.sleep(18)
            if not any(t.get("role") == "user" for t in transcript):
                LOGGER.warning(f"[{call_id}] No user speech 18s after greeting — nudging")
                session.generate_reply(
                    instructions="Gently ask if the customer can hear you. One sentence only."
                )

        asyncio.create_task(_silence_fallback())

    greeting_handle.add_done_callback(_on_greeting_done)


def create_agent_server() -> AgentServer:
    server = AgentServer(
        ws_url=SETTINGS.LIVEKIT_URL,
        api_key=SETTINGS.LIVEKIT_API_KEY,
        api_secret=SETTINGS.LIVEKIT_API_SECRET,
        job_executor_type=JobExecutorType.THREAD,
        num_idle_processes=0,
    )

    @server.rtc_session(agent_name=AGENT_NAME)
    async def _entrypoint(ctx: JobContext) -> None:
        await entrypoint(ctx)

    return server


if __name__ == "__main__":
    from livekit.agents import cli, WorkerOptions

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            ws_url=SETTINGS.LIVEKIT_URL,
            api_key=SETTINGS.LIVEKIT_API_KEY,
            api_secret=SETTINGS.LIVEKIT_API_SECRET,
            agent_name=AGENT_NAME,
        )
    )
